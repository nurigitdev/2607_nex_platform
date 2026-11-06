from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DECISION_EVENT_TYPE,
    _decision_projection,
    _progress_projection,
    _runtime_projection,
    _state_projection,
)

POLICY_SCHEMA_VERSION = "cx_answer_support_policy_sustained_operations_policy.v1"
OPERATIONS_SCHEMA_VERSION = "cx_answer_support_policy_sustained_operations.v1"
WINDOW_SCHEMA_VERSION = "cx_answer_support_policy_sustained_window.v1"
WINDOW_EVENT_TYPE = "cx.retrieval.answer_support_policy_sustained_window"
POLICY_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_PATH"
OPERATIONS_PATH = "/internal/v1/retrieval/answer-support/policy-sustained-operations"
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_policy_sustained_operations.v1.json"
)

_SOURCE_REVIEW = {
    "evidence_schema_version": (
        "gb2_s20qpai_policy_cutover_operations_operator_review.v1"
    ),
    "decision": "CONTINUE_CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_APPROVED",
    "decision_status": "APPROVED_CONTINUATION_NOT_PRODUCTION",
    "approved_scope": (
        "CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_CONTINUATION_ONLY"
    ),
    "next_boundary": "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS",
    "design_hash": (
        "sha256:e01cd96bf3dd1ab6021f4a3435697218f89bcb4704ea7d0496ffe554ec738228"
    ),
    "operator_decision_hash": (
        "sha256:5a4285d0b75fe10676ae00a43ab8c41016bcb8db61ec911e8ba947b467b87843"
    ),
    "manifest_hash": (
        "sha256:98ea9425b80c67ea213add6bbca6f161ce549779cf2e9f0af11f4b8b57affbf3"
    ),
    "decision_receipt_hash": (
        "sha256:36c97a3f3033d8963edea0931f05378799e2dfd273bb12cb65599ccaf5899ade"
    ),
    "decision_receipt_document_hash": (
        "sha256:015a141d067ccd1a7f7d479d9a8c73d41fe2d7c017954624be455cf4a08a4072"
    ),
    "review_report_document_hash": (
        "sha256:adc10e23d0d798b51243d0bca719a4da177768432b00ab2c0fc16d0f2138fbed"
    ),
    "source_evidence_hash": (
        "sha256:0c1ba91b7cf5b537db9f0b3cd24beef651372c2ef8f59aa1422a3048fac14827"
    ),
}
_OPERATIONAL_SLO = {
    "maximum_feedback_p95_latency_ms": 2000,
    "maximum_provider_p95_latency_ms": 15000,
    "maximum_e2e_p95_latency_ms": 20000,
    "maximum_provider_failures": 0,
    "maximum_fallback_count": 0,
}
_ESCALATION = {
    "cutover_terminal_state": "ROLLBACK_STATE_DOMINANT",
    "provider_failure": "IMMEDIATE_ROLLBACK_REQUIRED",
    "fallback_decision": "IMMEDIATE_ROLLBACK_REQUIRED",
    "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "review_cadence_reached": "OPERATOR_REVIEW_REQUIRED",
}
_SAFETY = {
    "holdout_access_permitted": False,
    "raw_text_projection_permitted": False,
    "production_cutover_permitted": False,
    "runtime_stopped_at_review_cadence": False,
    "rollback_contract_preserved": True,
    "operator_review_required_at_cadence": True,
}


class PolicySustainedOperationsError(ValueError):
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
class OperationalPolicySustainedSource:
    store: OperationalEventStore
    policy: Mapping[str, Any]
    runtime_snapshot: Callable[[], Mapping[str, Any] | None]

    def snapshot(self, *, generated_at: datetime | None = None) -> dict[str, Any]:
        observed_at = generated_at or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise _invalid("operations_clock")
        policy = validate_policy_sustained_operations_policy(self.policy)
        events = self._events(policy)
        window = _window_projection(events["window"], policy)
        state = _state_projection(events["state"], policy)
        decisions = _decision_projection(
            events["decisions"],
            opened_at=window["opened_at"],
            maximum_samples=policy["review_sample_interval"],
            authorization_hash=policy["authorization_hash"],
            selected_policy_hash=policy["selected_policy_hash"],
        )
        progress = _progress_projection(
            events["progress"], opened_at=window["opened_at"]
        )
        runtime = _runtime_projection(self.runtime_snapshot())
        cadence = _cadence_projection(
            decisions, review_sample_interval=policy["review_sample_interval"]
        )
        slo_checks = _slo_checks(
            decisions=decisions,
            progress=progress,
            slo=policy["operational_slo"],
        )
        operations_status, health_status, escalations = _operations_status(
            window=window,
            state=state,
            decisions=decisions,
            progress=progress,
            runtime=runtime,
            cadence=cadence,
            slo_checks=slo_checks,
        )
        snapshot = {
            "operations_schema_version": OPERATIONS_SCHEMA_VERSION,
            "operations_status": operations_status,
            "health_status": health_status,
            "generated_at": _timestamp(observed_at),
            "policy": {
                "policy_id": policy["policy_id"],
                "policy_hash": policy["policy_hash"],
                "continuation_receipt_hash": policy["source_review"][
                    "decision_receipt_hash"
                ],
                "cutover_authorization_hash": policy["authorization_hash"],
                "activation_bundle_hash": policy["activation_bundle_hash"],
                "selected_policy_hash": policy["selected_policy_hash"],
            },
            "window": window,
            "state": state,
            "decisions": decisions,
            "progress": progress,
            "runtime": runtime,
            "cadence": cadence,
            "slo": {**policy["operational_slo"], "checks": slo_checks},
            "escalations": escalations,
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
            raise PolicySustainedOperationsError(
                "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_SOURCE_UNAVAILABLE",
                "Answer-support sustained operational events are unavailable.",
                status_code=503,
                retryable=True,
            ) from exc


def build_installed_policy_sustained_operations_source(
    *,
    environ: Mapping[str, str],
    store: OperationalEventStore,
    emitter: OperationalEventEmitter,
    runtime_snapshot: Callable[[], Mapping[str, Any] | None],
) -> OperationalPolicySustainedSource:
    policy = load_policy_sustained_operations_policy(
        Path(str(environ.get(POLICY_PATH_ENV, DEFAULT_POLICY_PATH)))
    )
    source = OperationalPolicySustainedSource(
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


def register_policy_sustained_operations_routes(
    app: FastAPI, *, source: OperationalPolicySustainedSource
) -> None:
    @app.get(OPERATIONS_PATH, response_model=None)
    def get_policy_sustained_operations(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_cx_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return source.snapshot()
        except PolicySustainedOperationsError as exc:
            return _problem(request, exc)


def load_policy_sustained_operations_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicySustainedOperationsError(
            "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_POLICY_UNAVAILABLE",
            "Answer-support sustained operations policy is unavailable.",
        ) from exc
    return validate_policy_sustained_operations_policy(value)


def validate_policy_sustained_operations_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("policy")
    policy = dict(value)
    supplied_hash = _hash_ref(policy.pop("policy_hash", None))
    expected = {
        "policy_schema_version",
        "policy_id",
        "status",
        "source_review",
        "authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_window_id",
        "review_sample_interval",
        "maximum_concurrency",
        "maximum_event_scan",
        "operational_slo",
        "escalation_policy",
        "safety",
    }
    if (
        set(policy) != expected
        or semantic_sha256_hash_ref(policy) != supplied_hash
        or policy.get("policy_schema_version") != POLICY_SCHEMA_VERSION
        or policy.get("status") != "APPROVED_FOR_CONTROLLED_SUSTAINED_OPERATIONS"
        or policy.get("source_review") != _SOURCE_REVIEW
        or policy.get("review_sample_interval") != 12
        or policy.get("maximum_concurrency") != 4
        or policy.get("maximum_event_scan") != 1000
        or policy.get("operational_slo") != _OPERATIONAL_SLO
        or policy.get("escalation_policy") != _ESCALATION
        or policy.get("safety") != _SAFETY
    ):
        raise _invalid("policy_semantics")
    for name in (
        "authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
    ):
        _hash_ref(policy.get(name))
    for name in ("policy_id", "sustained_window_id"):
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
        raise _binding_drift()
    details = {
        "window_schema_version": WINDOW_SCHEMA_VERSION,
        "window_state": "OPEN",
        "window_id": policy["sustained_window_id"],
        "policy_hash": policy["policy_hash"],
        "continuation_receipt_hash": policy["source_review"][
            "decision_receipt_hash"
        ],
        "cutover_receipt_hash": policy["authorization_hash"],
        "activation_bundle_hash": policy["activation_bundle_hash"],
        "selected_policy_hash": policy["selected_policy_hash"],
        "review_sample_interval": policy["review_sample_interval"],
        "maximum_concurrency": policy["maximum_concurrency"],
    }
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-answer-support-policy-sustained-window:"
            f"{policy['sustained_window_id']}",
        )
    )
    event = emitter.emit(
        event_type=WINDOW_EVENT_TYPE,
        severity="INFO",
        message="CX answer-support policy sustained operations window was opened.",
        subject_ref=build_subject_ref(
            "cx.answer_support_policy_sustained_window",
            policy["sustained_window_id"],
        ),
        details=details,
        event_id=event_id,
    )
    if event.get("details") != details:
        raise PolicySustainedOperationsError(
            "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_WINDOW_DRIFT",
            "Existing sustained operations window does not match the policy.",
        )
    persisted = store.get_event(event_id)
    if persisted is None or persisted.get("details") != details:
        raise PolicySustainedOperationsError(
            "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_WINDOW_UNAVAILABLE",
            "Sustained operations window could not be recovered.",
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
        raise _binding_drift()


def _window_projection(
    events: list[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    opened_at = None
    for event in events:
        details = event.get("details")
        if (
            isinstance(details, Mapping)
            and details.get("window_schema_version") == WINDOW_SCHEMA_VERSION
            and details.get("window_id") == policy["sustained_window_id"]
            and details.get("policy_hash") == policy["policy_hash"]
            and details.get("continuation_receipt_hash")
            == policy["source_review"]["decision_receipt_hash"]
            and isinstance(event.get("created_at"), str)
        ):
            opened_at = str(event["created_at"])
            break
    return {
        "window_id": policy["sustained_window_id"],
        "policy_hash": policy["policy_hash"],
        "window_state": "OPEN" if opened_at else "NOT_OPENED",
        "opened_at": opened_at,
        "review_sample_interval": policy["review_sample_interval"],
        "maximum_concurrency": policy["maximum_concurrency"],
    }


def _cadence_projection(
    decisions: Mapping[str, Any], *, review_sample_interval: int
) -> dict[str, Any]:
    samples = int(decisions.get("provider_sample_count", 0))
    return {
        "review_sample_interval": review_sample_interval,
        "provider_samples_since_review": samples,
        "remaining_review_samples": max(0, review_sample_interval - samples),
        "operator_review_due": samples >= review_sample_interval,
        "observation_overrun_count": max(0, samples - review_sample_interval),
        "runtime_stopped": False,
    }


def _slo_checks(
    *,
    decisions: Mapping[str, Any],
    progress: Mapping[str, Any],
    slo: Mapping[str, Any],
) -> dict[str, bool]:
    return {
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
        "fallbacks_within_limit": (
            decisions["fallback_count"] <= slo["maximum_fallback_count"]
        ),
    }


def _operations_status(
    *,
    window: Mapping[str, Any],
    state: Mapping[str, Any],
    decisions: Mapping[str, Any],
    progress: Mapping[str, Any],
    runtime: Mapping[str, Any],
    cadence: Mapping[str, Any],
    slo_checks: Mapping[str, bool],
) -> tuple[str, str, list[str]]:
    cutover_state = state.get("cutover_state")
    if cutover_state == ROLLED_BACK:
        return "ROLLED_BACK", "DEGRADED", ["ROLLBACK_STATE_DOMINANT"]
    if cutover_state == ROLLBACK_PENDING_REVIEW:
        return (
            "ROLLBACK_PENDING_REVIEW",
            "DEGRADED",
            ["ROLLBACK_STATE_DOMINANT"],
        )
    if decisions.get("fallback_count", 0) > 0 or progress.get("failed_count", 0) > 0:
        return "ROLLBACK_REQUIRED", "DEGRADED", ["IMMEDIATE_ROLLBACK_REQUIRED"]
    latency_breaches = [
        name
        for name in ("provider_p95_within_limit", "e2e_p95_within_limit")
        if slo_checks.get(name) is not True
    ]
    if latency_breaches:
        return "ROLLBACK_PENDING_REVIEW", "DEGRADED", latency_breaches
    if cadence.get("operator_review_due") is True:
        return "OPERATOR_REVIEW_DUE", "ATTENTION", ["OPERATOR_REVIEW_REQUIRED"]
    if (
        window.get("window_state") == "OPEN"
        and cutover_state == ACTIVE
        and runtime.get("installed") is True
    ):
        return "MONITORING", "READY", []
    return "DISABLED", "UNAVAILABLE", []


def _binding_drift() -> PolicySustainedOperationsError:
    return PolicySustainedOperationsError(
        "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_BINDING_DRIFT",
        "Installed cutover runtime does not match the sustained operations policy.",
    )


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


def _invalid(detail: str) -> PolicySustainedOperationsError:
    return PolicySustainedOperationsError(
        "CX_ANSWER_SUPPORT_SUSTAINED_OPERATIONS_INVALID", detail
    )


def _problem(request: Request, exc: PolicySustainedOperationsError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX answer-support sustained operations unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-answer-support-sustained-operations-unavailable"
        ),
    )
