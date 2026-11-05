from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import OperationalEventStore, problem_response
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.authorization import authorize_cx_operations_request
from nex_cx.retrieval_answer_support_controlled_activation import (
    ACTIVATION_EVENT_TYPE,
    ACTIVE,
    CURRENT_POLICY,
    PROGRESS_EVENT_TYPE,
    ROLLED_BACK,
    ControlledAnswerSupportRuntime,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    SHADOW_ELIGIBLE_PURPOSES,
    AnswerSupportShadowOutcomeSink,
)
from nex_cx.retrieval_observability import CX_ANSWER_SUPPORT_SHADOW_EVENT

POLICY_SCHEMA_VERSION = "cx_answer_support_limited_operations_policy.v1"
OPERATIONS_SCHEMA_VERSION = "cx_answer_support_limited_operations.v1"
LIMITED_OPERATIONS_MODE_ENV = "NEX_CX_ANSWER_SUPPORT_LIMITED_OPERATIONS_MODE"
LIMITED_OPERATIONS_POLICY_PATH_ENV = (
    "NEX_CX_ANSWER_SUPPORT_LIMITED_OPERATIONS_POLICY_PATH"
)
LIMITED_OPERATIONS_DISABLED = "DISABLED"
LIMITED_OPERATIONS_ENABLED = "ENABLED"
OPERATIONS_PATH = "/internal/v1/retrieval/answer-support/shadow-operations"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_limited_operations.v1.json"
)

_POLICY_FIELDS = {
    "policy_schema_version",
    "policy_id",
    "status",
    "activation_bundle_hash",
    "window_id",
    "minimum_operator_review_samples",
    "maximum_provider_samples",
    "maximum_event_scan",
    "safety",
    "policy_hash",
}
_SAFETY = {
    "holdout_access_permitted": False,
    "primary_decision_mutation_permitted": False,
    "production_cutover_permitted": False,
    "raw_text_projection_permitted": False,
    "user_visible_decision_change_permitted": False,
}


class LimitedShadowOperationsError(ValueError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int = 422,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class OperationalLimitedShadowSource:
    store: OperationalEventStore
    policy: Mapping[str, Any]
    runtime_snapshot: Callable[[], Mapping[str, Any] | None]

    def provider_sample_count(self) -> int:
        return int(self.snapshot()["window"]["provider_sample_count"])

    def snapshot(self, *, generated_at: datetime | None = None) -> dict[str, Any]:
        observed_at = generated_at or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise LimitedShadowOperationsError(
                "CX_LIMITED_SHADOW_CLOCK_INVALID",
                "Limited shadow operations clock must be timezone-aware.",
            )
        policy = validate_limited_operations_policy(self.policy)
        events = self._events(policy)
        activation = _activation_projection(events["activation"], policy)
        progress = _progress_projection(events["progress"], activation)
        outcomes = _outcome_projection(events["outcomes"], activation)
        provider_samples = progress["completed_count"] + progress["failed_count"]
        maximum = policy["maximum_provider_samples"]
        runtime = self.runtime_snapshot()
        activation_state = activation["activation_state"]
        if activation_state == ROLLED_BACK:
            operations_status = "ROLLED_BACK"
            health_status = "DEGRADED"
        elif provider_samples >= maximum:
            operations_status = "REVIEW_REQUIRED"
            health_status = "READY"
        elif activation_state == ACTIVE and runtime is not None:
            operations_status = "OBSERVING"
            health_status = "READY"
        else:
            operations_status = "DISABLED"
            health_status = "UNAVAILABLE"
        snapshot = {
            "operations_schema_version": OPERATIONS_SCHEMA_VERSION,
            "operations_status": operations_status,
            "health_status": health_status,
            "generated_at": _timestamp(observed_at),
            "activation": activation,
            "window": {
                "window_id": policy["window_id"],
                "policy_hash": policy["policy_hash"],
                "minimum_operator_review_samples": policy[
                    "minimum_operator_review_samples"
                ],
                "maximum_provider_samples": maximum,
                "provider_sample_count": provider_samples,
                "remaining_provider_samples": max(0, maximum - provider_samples),
                "sample_cap_reached": provider_samples >= maximum,
            },
            "progress": progress,
            "outcomes": outcomes,
            "runtime": _safe_runtime_projection(runtime),
            "safety": {
                **_SAFETY,
                "authoritative_policy": CURRENT_POLICY,
            },
            "source": {
                "store": "service_operational_events",
                "maximum_event_scan": policy["maximum_event_scan"],
                "raw_text_included": False,
            },
        }
        snapshot["snapshot_hash"] = semantic_sha256_hash_ref(snapshot)
        return snapshot

    def _events(self, policy: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        limit = int(policy["maximum_event_scan"])
        try:
            return {
                "activation": self.store.list_events(
                    service_id="nex-cx",
                    event_type=ACTIVATION_EVENT_TYPE,
                    limit=limit,
                ),
                "progress": self.store.list_events(
                    service_id="nex-cx",
                    event_type=PROGRESS_EVENT_TYPE,
                    limit=limit,
                ),
                "outcomes": self.store.list_events(
                    service_id="nex-cx",
                    event_type=CX_ANSWER_SUPPORT_SHADOW_EVENT,
                    limit=limit,
                ),
            }
        except Exception as exc:
            raise LimitedShadowOperationsError(
                "CX_LIMITED_SHADOW_SOURCE_UNAVAILABLE",
                "Limited shadow operational events are unavailable.",
                status_code=503,
                retryable=True,
            ) from exc


class LimitedShadowOperationsRuntime:
    """Cap the approved shadow observer at a restart-safe provider sample count."""

    def __init__(
        self,
        delegate: ControlledAnswerSupportRuntime,
        *,
        source: OperationalLimitedShadowSource,
        policy: Mapping[str, Any],
        outcome_sink: AnswerSupportShadowOutcomeSink,
    ) -> None:
        self.delegate = delegate
        self.source = source
        self.policy = validate_limited_operations_policy(policy)
        if (
            delegate.snapshot()["activation_bundle_hash"]
            != self.policy["activation_bundle_hash"]
        ):
            raise LimitedShadowOperationsError(
                "CX_LIMITED_SHADOW_ACTIVATION_BINDING_DRIFT",
                "Limited shadow policy does not match the active bundle.",
            )
        self.outcome_sink = outcome_sink
        self._lock = Lock()
        self._reservations = 0
        self._allocated_provider_samples = source.provider_sample_count()

    def observe(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]:
        if primary_package.get("purpose") not in SHADOW_ELIGIBLE_PURPOSES:
            return self.delegate.observe(
                query_text=query_text,
                evidence_items=evidence_items,
                primary_package=primary_package,
                access_context=access_context,
            )
        with self._lock:
            sample_count = self.source.provider_sample_count()
            self._allocated_provider_samples = max(
                self._allocated_provider_samples,
                sample_count,
            )
            if self._allocated_provider_samples >= self.policy[
                "maximum_provider_samples"
            ]:
                outcome = _window_complete_outcome(
                    primary_package=primary_package,
                    access_context=access_context,
                    policy=self.policy,
                )
                with suppress(Exception):  # Shadow telemetry cannot affect retrieval.
                    self.outcome_sink.record(outcome)
                return outcome
            self._allocated_provider_samples += 1
            self._reservations += 1
        provider_called = False
        try:
            outcome = self.delegate.observe(
                query_text=query_text,
                evidence_items=evidence_items,
                primary_package=primary_package,
                access_context=access_context,
            )
            provider_called = outcome.get("provider_called") is True
            return outcome
        finally:
            with self._lock:
                self._reservations -= 1
                if not provider_called:
                    self._allocated_provider_samples -= 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            reservations = self._reservations
        return {
            **self.source.snapshot(),
            "in_flight_reservations": reservations,
        }


def build_installed_limited_shadow_operations_runtime(
    *,
    environ: Mapping[str, str],
    controlled_runtime: ControlledAnswerSupportRuntime | None,
    store: OperationalEventStore,
    outcome_sink: AnswerSupportShadowOutcomeSink,
) -> LimitedShadowOperationsRuntime | None:
    mode = str(
        environ.get(LIMITED_OPERATIONS_MODE_ENV, LIMITED_OPERATIONS_DISABLED)
    ).strip().upper()
    if mode == LIMITED_OPERATIONS_DISABLED:
        return None
    if mode != LIMITED_OPERATIONS_ENABLED:
        raise LimitedShadowOperationsError(
            "CX_LIMITED_SHADOW_MODE_INVALID",
            "Limited shadow operations mode is invalid.",
        )
    if controlled_runtime is None:
        return None
    policy = load_limited_operations_policy(
        Path(str(environ.get(LIMITED_OPERATIONS_POLICY_PATH_ENV, DEFAULT_POLICY_PATH)))
    )
    source = OperationalLimitedShadowSource(
        store=store,
        policy=policy,
        runtime_snapshot=controlled_runtime.snapshot,
    )
    runtime = LimitedShadowOperationsRuntime(
        controlled_runtime,
        source=source,
        policy=policy,
        outcome_sink=outcome_sink,
    )
    return runtime


def register_limited_shadow_operations_routes(
    app: FastAPI,
    *,
    source: OperationalLimitedShadowSource,
) -> None:
    @app.get(OPERATIONS_PATH, response_model=None)
    def get_limited_shadow_operations(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_cx_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return source.snapshot()
        except LimitedShadowOperationsError as exc:
            return _problem(request, exc)


def load_limited_operations_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LimitedShadowOperationsError(
            "CX_LIMITED_SHADOW_POLICY_UNAVAILABLE",
            "Limited shadow operations policy is unavailable.",
        ) from exc
    return validate_limited_operations_policy(value)


def validate_limited_operations_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("policy")
    policy = dict(value)
    if set(policy) != _POLICY_FIELDS:
        raise _invalid("policy_fields")
    supplied_hash = _hash_ref(policy.pop("policy_hash", None), "policy_hash")
    if semantic_sha256_hash_ref(policy) != supplied_hash:
        raise LimitedShadowOperationsError(
            "CX_LIMITED_SHADOW_POLICY_INTEGRITY",
            "Limited shadow operations policy integrity failed.",
        )
    if (
        policy.get("policy_schema_version") != POLICY_SCHEMA_VERSION
        or policy.get("status") != "APPROVED_FOR_LIMITED_SHADOW_OPERATIONS"
        or policy.get("minimum_operator_review_samples") != 12
        or policy.get("maximum_provider_samples") != 12
        or policy.get("maximum_event_scan") != 500
        or policy.get("safety") != _SAFETY
        or not _text(policy.get("policy_id"))
        or not _text(policy.get("window_id"))
    ):
        raise _invalid("policy_semantics")
    _hash_ref(policy.get("activation_bundle_hash"), "activation_bundle_hash")
    policy["policy_hash"] = supplied_hash
    return policy


def _activation_projection(
    events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    active_event: Mapping[str, Any] | None = None
    rollback_event: Mapping[str, Any] | None = None
    for event in events:
        details = event.get("details")
        if not isinstance(details, Mapping) or details.get(
            "activation_bundle_hash"
        ) != policy["activation_bundle_hash"]:
            continue
        if details.get("activation_state") == ROLLED_BACK:
            rollback_event = event
        elif details.get("activation_state") == ACTIVE:
            active_event = event
    selected = rollback_event or active_event
    details = selected.get("details") if selected else {}
    return {
        "activation_bundle_hash": policy["activation_bundle_hash"],
        "activation_state": (
            details.get("activation_state") or "NOT_ACTIVATED"
            if isinstance(details, Mapping)
            else "NOT_ACTIVATED"
        ),
        "reason_code": (
            details.get("reason_code") if isinstance(details, Mapping) else None
        ),
        "activated_at": active_event.get("created_at") if active_event else None,
        "rolled_back_at": (
            rollback_event.get("created_at") if rollback_event else None
        ),
    }


def _progress_projection(
    events: Sequence[Mapping[str, Any]], activation: Mapping[str, Any]
) -> dict[str, Any]:
    filtered = _after_activation(events, activation)
    counters = {
        "admitted_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "rejected_count": 0,
    }
    feedback: list[float] = []
    provider: list[float] = []
    for event in filtered:
        details = event.get("details")
        if not isinstance(details, Mapping):
            continue
        event_type = details.get("progress_event_type")
        key = {
            "REQUEST_ADMITTED": "admitted_count",
            "REQUEST_COMPLETED": "completed_count",
            "REQUEST_FAILED": "failed_count",
            "REQUEST_REJECTED": "rejected_count",
        }.get(event_type)
        if key is None:
            continue
        counters[key] += 1
        latency = _safe_number(details.get("elapsed_ms"))
        if latency is not None:
            if event_type == "REQUEST_ADMITTED":
                feedback.append(latency)
            elif event_type in {"REQUEST_COMPLETED", "REQUEST_FAILED"}:
                provider.append(latency)
    return {
        **counters,
        "feedback_p95_latency_ms": _p95(feedback),
        "provider_p95_latency_ms": _p95(provider),
    }


def _outcome_projection(
    events: Sequence[Mapping[str, Any]], activation: Mapping[str, Any]
) -> dict[str, Any]:
    counters = {"observed_count": 0, "skipped_count": 0, "failed_count": 0}
    e2e: list[float] = []
    agreement = 0
    disagreement = 0
    for event in _after_activation(events, activation):
        details = event.get("details")
        if not isinstance(details, Mapping):
            continue
        status = details.get("shadow_status")
        key = {
            "OBSERVED": "observed_count",
            "SKIPPED": "skipped_count",
            "FAILED": "failed_count",
        }.get(status)
        if key is not None:
            counters[key] += 1
        if details.get("provider_called") is True:
            latency = _safe_number(details.get("elapsed_ms"))
            if latency is not None:
                e2e.append(latency)
        if details.get("primary_shadow_agree") is True:
            agreement += 1
        elif details.get("primary_shadow_agree") is False:
            disagreement += 1
    return {
        **counters,
        "primary_shadow_agreement_count": agreement,
        "primary_shadow_disagreement_count": disagreement,
        "e2e_p95_latency_ms": _p95(e2e),
    }


def _after_activation(
    events: Sequence[Mapping[str, Any]], activation: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    activated_at = activation.get("activated_at")
    if not isinstance(activated_at, str):
        return []
    return [
        event
        for event in events
        if isinstance(event.get("created_at"), str)
        and str(event["created_at"]) >= activated_at
    ]


def _safe_runtime_projection(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "installed": False,
            "activation_state": None,
            "in_flight": 0,
            "peak_in_flight": 0,
        }
    gateway = value.get("generation_client")
    gateway = gateway if isinstance(gateway, Mapping) else {}
    return {
        "installed": True,
        "activation_state": value.get("activation_state"),
        "in_flight": _safe_integer(gateway.get("in_flight")),
        "peak_in_flight": _safe_integer(gateway.get("peak_in_flight")),
    }


def _window_complete_outcome(
    *,
    primary_package: Mapping[str, Any],
    access_context: CxAccessContext,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    outcome = {
        "outcome_schema_version": "cx_answer_support_limited_window_outcome.v1",
        "mode": "SHADOW",
        "status": "SKIPPED",
        "shadow_decision": "NOT_EVALUATED",
        "skip_reason": "LIMITED_WINDOW_COMPLETE",
        "retrieval_package_id": primary_package.get("retrieval_package_id"),
        "request_id": access_context.request_id,
        "trace_id": access_context.trace_id,
        "window_id": policy["window_id"],
        "provider_called": False,
        "user_visible": False,
        "primary_decision_mutated": False,
        "production_cutover_permitted": False,
    }
    outcome["outcome_hash"] = semantic_sha256_hash_ref(outcome)
    return outcome


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 6)


def _safe_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def _safe_integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _hash_ref(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(name)
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc


def _invalid(detail: str) -> LimitedShadowOperationsError:
    return LimitedShadowOperationsError(
        "CX_LIMITED_SHADOW_POLICY_INVALID",
        detail,
    )


def _problem(request: Request, exc: LimitedShadowOperationsError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX limited shadow operations unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-limited-shadow-operations-unavailable"
        ),
    )
