from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    OperationalEventEmitter,
    OperationalEventStore,
    build_subject_ref,
    problem_response,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.authorization import authorize_cx_operations_request
from nex_cx.retrieval_answer_support_controlled_activation import PROGRESS_EVENT_TYPE
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CURRENT_POLICY,
    CUTOVER_EVENT_TYPE,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
    validate_cutover_decision_event,
)

POLICY_SCHEMA_VERSION = "cx_answer_support_policy_cutover_operations_policy.v1"
OPERATIONS_SCHEMA_VERSION = "cx_answer_support_policy_cutover_operations.v1"
WINDOW_SCHEMA_VERSION = "cx_answer_support_policy_cutover_window.v1"
DECISION_EVENT_TYPE = "cx.retrieval.answer_support_policy_decision"
WINDOW_EVENT_TYPE = "cx.retrieval.answer_support_policy_cutover_window"
POLICY_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_POLICY_OPERATIONS_PATH"
OPERATIONS_PATH = "/internal/v1/retrieval/answer-support/policy-cutover-operations"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_policy_cutover_operations.v1.json"
)

_SOURCE_ACCEPTANCE = {
    "evidence_schema_version": (
        "gb2_s20qpag_answer_support_policy_cutover_acceptance.v1"
    ),
    "decision": "ANSWER_SUPPORT_POLICY_CUTOVER_AND_ROLLBACK_ACCEPTED",
    "next_boundary": "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS",
    "evidence_hash": (
        "sha256:c07655bcba5fc85db6506bbcba873dbb33d3ed91fd2395cd266837df18545aac"
    ),
    "report_document_hash": (
        "sha256:36b181a7800e3a3d44264c6ad6067dbd08afd823d3cc1c7329136002dc2983bd"
    ),
    "slice_document_hash": (
        "sha256:003f070aa65304f1436a6a540ddcddbacbe5c22855406dba293c980cfe9d35e2"
    ),
}
_OPERATIONAL_SLO = {
    "maximum_feedback_p95_latency_ms": 2000,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "maximum_provider_failures": 0,
}
_SAFETY = {
    "holdout_access_permitted": False,
    "raw_text_projection_permitted": False,
    "production_cutover_permitted": False,
    "runtime_stopped_at_observation_cap": False,
    "operator_review_required_at_observation_cap": True,
}


class PolicyCutoverOperationsError(ValueError):
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
class OperationalPolicyCutoverDecisionSink:
    emitter: OperationalEventEmitter

    def record(self, decision: Mapping[str, Any]) -> None:
        normalized = validate_cutover_decision_event(decision)
        state = normalized["decision_state"]
        self.emitter.emit(
            event_type=DECISION_EVENT_TYPE,
            severity="WARNING" if state == "FALLBACK" else "INFO",
            message="CX answer-support policy cutover decision was observed.",
            request_id=normalized["request_id"],
            trace_id=normalized["trace_id"],
            subject_ref=build_subject_ref(
                "cx.retrieval_package", normalized["source_package_id"]
            ),
            details=normalized,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    "cx-answer-support-policy-decision:"
                    f"{normalized['decision_event_hash']}",
                )
            ),
        )


@dataclass(frozen=True)
class OperationalPolicyCutoverSource:
    store: OperationalEventStore
    policy: Mapping[str, Any]
    runtime_snapshot: Callable[[], Mapping[str, Any] | None]

    def snapshot(self, *, generated_at: datetime | None = None) -> dict[str, Any]:
        observed_at = generated_at or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise _invalid("operations_clock")
        policy = validate_policy_cutover_operations_policy(self.policy)
        events = self._events(policy)
        window = _window_projection(events["window"], policy)
        state = _state_projection(events["state"], policy)
        decisions = _decision_projection(
            events["decisions"],
            opened_at=window["opened_at"],
            maximum_samples=policy["maximum_observation_provider_samples"],
            authorization_hash=policy["authorization_hash"],
            selected_policy_hash=policy["selected_policy_hash"],
        )
        progress = _progress_projection(
            events["progress"], opened_at=window["opened_at"]
        )
        runtime = _runtime_projection(self.runtime_snapshot())
        operations_status, health_status = _operations_status(
            window=window,
            state=state,
            decisions=decisions,
            runtime=runtime,
        )
        slo = policy["operational_slo"]
        slo_status = {
            "feedback_p95_within_limit": (
                progress["feedback_p95_latency_ms"]
                <= slo["maximum_feedback_p95_latency_ms"]
            ),
            "provider_p95_within_limit": (
                progress["provider_p95_latency_ms"]
                <= slo["maximum_provider_p95_latency_ms"]
            ),
            "e2e_p95_within_limit": (
                decisions["e2e_p95_latency_ms"] <= slo["maximum_e2e_p95_latency_ms"]
            ),
            "provider_failures_within_limit": (
                progress["failed_count"] <= slo["maximum_provider_failures"]
            ),
        }
        snapshot = {
            "operations_schema_version": OPERATIONS_SCHEMA_VERSION,
            "operations_status": operations_status,
            "health_status": health_status,
            "generated_at": _timestamp(observed_at),
            "policy": {
                "policy_id": policy["policy_id"],
                "policy_hash": policy["policy_hash"],
                "cutover_receipt_hash": policy["authorization_hash"],
                "activation_bundle_hash": policy["activation_bundle_hash"],
                "selected_policy_hash": policy["selected_policy_hash"],
            },
            "window": window,
            "state": state,
            "decisions": decisions,
            "progress": progress,
            "runtime": runtime,
            "slo": {**slo, "checks": slo_status},
            "safety": {**_SAFETY, "fallback_policy": CURRENT_POLICY},
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
                "state": self.store.list_events(
                    service_id="nex-cx", event_type=CUTOVER_EVENT_TYPE, limit=limit
                ),
                "decisions": self.store.list_events(
                    service_id="nex-cx", event_type=DECISION_EVENT_TYPE, limit=limit
                ),
                "progress": self.store.list_events(
                    service_id="nex-cx", event_type=PROGRESS_EVENT_TYPE, limit=limit
                ),
                "window": self.store.list_events(
                    service_id="nex-cx", event_type=WINDOW_EVENT_TYPE, limit=limit
                ),
            }
        except Exception as exc:
            raise PolicyCutoverOperationsError(
                "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_SOURCE_UNAVAILABLE",
                "Answer-support policy cutover operational events are unavailable.",
                status_code=503,
                retryable=True,
            ) from exc


def build_installed_policy_cutover_operations_source(
    *,
    environ: Mapping[str, str],
    store: OperationalEventStore,
    emitter: OperationalEventEmitter,
    runtime_snapshot: Callable[[], Mapping[str, Any] | None],
) -> OperationalPolicyCutoverSource:
    policy = load_policy_cutover_operations_policy(
        Path(str(environ.get(POLICY_PATH_ENV, DEFAULT_POLICY_PATH)))
    )
    source = OperationalPolicyCutoverSource(
        store=store,
        policy=policy,
        runtime_snapshot=runtime_snapshot,
    )
    runtime = runtime_snapshot()
    if runtime is not None:
        _require_runtime_binding(policy=policy, runtime=runtime)
        if runtime.get("cutover_state") == ACTIVE:
            _ensure_window_open(
                emitter=emitter, store=store, policy=policy, runtime=runtime
            )
    return source


def register_policy_cutover_operations_routes(
    app: FastAPI, *, source: OperationalPolicyCutoverSource
) -> None:
    @app.get(OPERATIONS_PATH, response_model=None)
    def get_policy_cutover_operations(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_cx_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return source.snapshot()
        except PolicyCutoverOperationsError as exc:
            return _problem(request, exc)


def load_policy_cutover_operations_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyCutoverOperationsError(
            "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_POLICY_UNAVAILABLE",
            "Answer-support policy cutover operations policy is unavailable.",
        ) from exc
    return validate_policy_cutover_operations_policy(value)


def validate_policy_cutover_operations_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("policy")
    policy = dict(value)
    supplied_hash = _hash_ref(policy.pop("policy_hash", None))
    expected = {
        "policy_schema_version",
        "policy_id",
        "status",
        "source_acceptance",
        "authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "window_id",
        "minimum_operator_review_samples",
        "maximum_observation_provider_samples",
        "maximum_concurrency",
        "maximum_event_scan",
        "operational_slo",
        "safety",
    }
    if (
        set(policy) != expected
        or semantic_sha256_hash_ref(policy) != supplied_hash
        or policy.get("policy_schema_version") != POLICY_SCHEMA_VERSION
        or policy.get("status") != "APPROVED_FOR_BOUNDED_CUTOVER_OPERATIONS"
        or policy.get("source_acceptance") != _SOURCE_ACCEPTANCE
        or policy.get("minimum_operator_review_samples") != 12
        or policy.get("maximum_observation_provider_samples") != 12
        or policy.get("maximum_concurrency") != 4
        or policy.get("maximum_event_scan") != 500
        or policy.get("operational_slo") != _OPERATIONAL_SLO
        or policy.get("safety") != _SAFETY
    ):
        raise _invalid("policy_semantics")
    for name in (
        "authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
    ):
        _hash_ref(policy.get(name))
    for name in ("policy_id", "window_id"):
        _required_text(policy.get(name))
    policy["policy_hash"] = supplied_hash
    return policy


def _ensure_window_open(
    *,
    emitter: OperationalEventEmitter,
    store: OperationalEventStore,
    policy: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    _require_runtime_binding(policy=policy, runtime=runtime)
    if runtime.get("cutover_state") != ACTIVE:
        raise PolicyCutoverOperationsError(
            "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_BINDING_DRIFT",
            "Installed cutover runtime does not match the operations policy.",
        )
    details = {
        "window_schema_version": WINDOW_SCHEMA_VERSION,
        "window_state": "OPEN",
        "window_id": policy["window_id"],
        "policy_hash": policy["policy_hash"],
        "cutover_receipt_hash": policy["authorization_hash"],
        "activation_bundle_hash": policy["activation_bundle_hash"],
        "selected_policy_hash": policy["selected_policy_hash"],
        "maximum_observation_provider_samples": policy[
            "maximum_observation_provider_samples"
        ],
        "maximum_concurrency": policy["maximum_concurrency"],
    }
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-policy-cutover-window:{policy['window_id']}",
        )
    )
    event = emitter.emit(
        event_type=WINDOW_EVENT_TYPE,
        severity="INFO",
        message="CX answer-support policy cutover operations window was opened.",
        subject_ref=build_subject_ref(
            "cx.answer_support_policy_cutover_window", policy["window_id"]
        ),
        details=details,
        event_id=event_id,
    )
    if event.get("details") != details:
        raise PolicyCutoverOperationsError(
            "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_WINDOW_DRIFT",
            "Existing cutover operations window does not match the policy.",
        )
    persisted = store.get_event(event_id)
    if persisted is None or persisted.get("details") != details:
        raise PolicyCutoverOperationsError(
            "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_WINDOW_UNAVAILABLE",
            "Cutover operations window could not be recovered.",
            status_code=503,
            retryable=True,
        )
    return persisted


def _require_runtime_binding(
    *, policy: Mapping[str, Any], runtime: Mapping[str, Any]
) -> None:
    if (
        runtime.get("authorization_hash") != policy["authorization_hash"]
        or runtime.get("activation_bundle_hash") != policy["activation_bundle_hash"]
        or runtime.get("selected_policy_hash") != policy["selected_policy_hash"]
        or runtime.get("cutover_state")
        not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
    ):
        raise PolicyCutoverOperationsError(
            "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_BINDING_DRIFT",
            "Installed cutover runtime does not match the operations policy.",
        )


def _window_projection(
    events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    opened_at = None
    for event in events:
        details = event.get("details")
        if (
            isinstance(details, Mapping)
            and details.get("window_schema_version") == WINDOW_SCHEMA_VERSION
            and details.get("window_id") == policy["window_id"]
            and details.get("policy_hash") == policy["policy_hash"]
            and details.get("cutover_receipt_hash") == policy["authorization_hash"]
            and isinstance(event.get("created_at"), str)
        ):
            opened_at = str(event["created_at"])
            break
    return {
        "window_id": policy["window_id"],
        "policy_hash": policy["policy_hash"],
        "window_state": "OPEN" if opened_at else "NOT_OPENED",
        "opened_at": opened_at,
        "minimum_operator_review_samples": policy["minimum_operator_review_samples"],
        "maximum_observation_provider_samples": policy[
            "maximum_observation_provider_samples"
        ],
        "maximum_concurrency": policy["maximum_concurrency"],
    }


def _state_projection(
    events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    selected: Mapping[str, Any] | None = None
    for event in events:
        details = event.get("details")
        if (
            not isinstance(details, Mapping)
            or details.get("cutover_receipt_hash") != policy["authorization_hash"]
        ):
            continue
        if selected is None or details.get("cutover_state") in {
            ROLLED_BACK,
            ROLLBACK_PENDING_REVIEW,
        }:
            selected = event
        if details.get("cutover_state") in {ROLLED_BACK, ROLLBACK_PENDING_REVIEW}:
            break
    details = selected.get("details") if selected else {}
    return {
        "cutover_state": (
            details.get("cutover_state")
            if isinstance(details, Mapping)
            else "NOT_ACTIVATED"
        )
        or "NOT_ACTIVATED",
        "reason_code": (
            details.get("reason_code") if isinstance(details, Mapping) else None
        ),
        "observed_at": selected.get("created_at") if selected else None,
    }


def _decision_projection(
    events: Sequence[Mapping[str, Any]],
    *,
    opened_at: str | None,
    maximum_samples: int,
    authorization_hash: str,
    selected_policy_hash: str,
) -> dict[str, Any]:
    counters = {
        "applied_count": 0,
        "fallback_count": 0,
        "skipped_count": 0,
        "ready_count": 0,
        "low_confidence_count": 0,
    }
    provider_samples = 0
    latencies: list[float] = []
    for event in _after_open(events, opened_at):
        details = event.get("details")
        if not isinstance(details, Mapping):
            continue
        if (
            details.get("cutover_receipt_hash") != authorization_hash
            or details.get("selected_policy_hash") != selected_policy_hash
        ):
            continue
        state = details.get("decision_state")
        key = {
            "APPLIED": "applied_count",
            "FALLBACK": "fallback_count",
            "SKIPPED": "skipped_count",
        }.get(state)
        if key is not None:
            counters[key] += 1
        if state == "APPLIED" and details.get("policy_decision") == "READY":
            counters["ready_count"] += 1
        elif state == "APPLIED" and details.get("policy_decision") == "LOW_CONFIDENCE":
            counters["low_confidence_count"] += 1
        if details.get("provider_called") is True:
            provider_samples += 1
            latency = _safe_number(details.get("elapsed_ms"))
            if latency is not None:
                latencies.append(latency)
    return {
        **counters,
        "total_count": sum(
            counters[name]
            for name in ("applied_count", "fallback_count", "skipped_count")
        ),
        "provider_sample_count": provider_samples,
        "remaining_review_samples": max(0, maximum_samples - provider_samples),
        "observation_cap_reached": provider_samples >= maximum_samples,
        "observation_overrun_count": max(0, provider_samples - maximum_samples),
        "e2e_p95_latency_ms": _p95(latencies),
    }


def _progress_projection(
    events: Sequence[Mapping[str, Any]], *, opened_at: str | None
) -> dict[str, Any]:
    counters = {"admitted_count": 0, "completed_count": 0, "failed_count": 0}
    feedback: list[float] = []
    provider: list[float] = []
    for event in _after_open(events, opened_at):
        details = event.get("details")
        if not isinstance(details, Mapping):
            continue
        kind = details.get("progress_event_type")
        key = {
            "REQUEST_ADMITTED": "admitted_count",
            "REQUEST_COMPLETED": "completed_count",
            "REQUEST_FAILED": "failed_count",
        }.get(kind)
        if key is None:
            continue
        counters[key] += 1
        latency = _safe_number(details.get("elapsed_ms"))
        if latency is not None:
            (feedback if kind == "REQUEST_ADMITTED" else provider).append(latency)
    return {
        **counters,
        "feedback_p95_latency_ms": _p95(feedback),
        "provider_p95_latency_ms": _p95(provider),
    }


def _runtime_projection(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "installed": False,
            "cutover_state": None,
            "in_flight": 0,
            "peak_in_flight": 0,
        }
    gateway = value.get("generation_client")
    gateway = gateway if isinstance(gateway, Mapping) else {}
    return {
        "installed": True,
        "cutover_state": value.get("cutover_state"),
        "rollback_reason": value.get("rollback_reason"),
        "in_flight": _safe_integer(gateway.get("in_flight")),
        "peak_in_flight": _safe_integer(gateway.get("peak_in_flight")),
    }


def _operations_status(
    *,
    window: Mapping[str, Any],
    state: Mapping[str, Any],
    decisions: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> tuple[str, str]:
    cutover_state = state.get("cutover_state")
    if cutover_state == ROLLED_BACK:
        return "ROLLED_BACK", "DEGRADED"
    if cutover_state == ROLLBACK_PENDING_REVIEW:
        return "ROLLBACK_PENDING_REVIEW", "DEGRADED"
    if decisions.get("observation_cap_reached") is True:
        return "REVIEW_REQUIRED", "READY"
    if (
        window.get("window_state") == "OPEN"
        and cutover_state == ACTIVE
        and runtime.get("installed") is True
    ):
        return "OBSERVING", "READY"
    return "DISABLED", "UNAVAILABLE"


def _after_open(
    events: Sequence[Mapping[str, Any]], opened_at: str | None
) -> list[Mapping[str, Any]]:
    if opened_at is None:
        return []
    return [
        event
        for event in events
        if isinstance(event.get("created_at"), str)
        and str(event["created_at"]) >= opened_at
    ]


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(float(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]), 6)


def _safe_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def _safe_integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise _invalid("text")
    return value.strip()


def _hash_ref(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("hash")
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid("hash") from exc


def _invalid(detail: str) -> PolicyCutoverOperationsError:
    return PolicyCutoverOperationsError(
        "CX_ANSWER_SUPPORT_CUTOVER_OPERATIONS_INVALID", detail
    )


def _problem(request: Request, exc: PolicyCutoverOperationsError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX answer-support policy cutover operations unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-answer-support-policy-cutover-operations-unavailable"
        ),
    )
