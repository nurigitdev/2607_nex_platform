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
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DECISION_EVENT_TYPE,
    _decision_projection,
    _progress_projection,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    CURRENT_POLICY,
    STEADY_STATE_EVENT_TYPE,
)
from nex_cx.retrieval_answer_support_policy_sustained_operations import (
    _cadence_projection,
    _slo_checks,
)

POLICY_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_operations_policy.v1"
)
OPERATIONS_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_operations.v1"
WINDOW_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_window.v1"
WINDOW_EVENT_TYPE = "cx.retrieval.answer_support_policy_steady_state_window"
POLICY_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_PATH"
OPERATIONS_PATH = (
    "/internal/v1/retrieval/answer-support/policy-steady-state-operations"
)
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_policy_steady_state_operations.v1.json"
)

_SOURCE_ACTIVATION = {
    "database_profile": "test",
    "decision": (
        "ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_AND_ROLLBACK_ACCEPTED"
    ),
    "evidence_hash": (
        "sha256:f03487ff10b867e0b19c60933369c1dbc8e26c9c0c90b1972d7c14dbb506bcbc"
    ),
    "evidence_schema_version": (
        "gb2_s20qpan_answer_support_policy_steady_state_activation.v1"
    ),
    "next_boundary": "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS",
    "operator_decision_receipt_hash": (
        "sha256:4d3277da3c9e6591cdc176fb3a062b1ff1c72efed40b7f3e9c3ffcb4b199b2b6"
    ),
    "operations_profile_hash": (
        "sha256:a7332978f9779253959c555bf9e4186ff59020363431d0962b9442d4712d5376"
    ),
    "rollback_reason": "PROVIDER_ERROR",
    "status": "PASS",
    "steady_state_authorization_hash": (
        "sha256:082356e051209a0819886b48be5b8dadf41ef63991572b97ce5ede059cefd008"
    ),
    "test_database_residue_rows": 0,
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
    "operator_review_required_at_cadence": True,
    "production_cutover_permitted": False,
    "raw_text_projection_permitted": False,
    "rollback_contract_preserved": True,
    "runtime_stopped_at_review_cadence": False,
}


class PolicySteadyStateOperationsError(ValueError):
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
class OperationalPolicySteadyStateSource:
    store: OperationalEventStore
    policy: Mapping[str, Any]
    runtime_snapshot: Callable[[], Mapping[str, Any] | None]

    def snapshot(self, *, generated_at: datetime | None = None) -> dict[str, Any]:
        observed_at = generated_at or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise _invalid("operations_clock")
        policy = validate_policy_steady_state_operations_policy(self.policy)
        events = self._events(policy)
        window = _window_projection(events["window"], policy)
        state = _steady_state_projection(events["state"], policy)
        decisions = _decision_projection(
            events["decisions"],
            opened_at=window["opened_at"],
            maximum_samples=policy["review_sample_interval"],
            authorization_hash=policy["cutover_authorization_hash"],
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
                "source_activation_evidence_hash": policy["source_activation"][
                    "evidence_hash"
                ],
                "steady_state_authorization_hash": policy[
                    "steady_state_authorization_hash"
                ],
                "operations_profile_hash": policy["operations_profile_hash"],
                "cutover_authorization_hash": policy[
                    "cutover_authorization_hash"
                ],
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
            "safety": dict(_SAFETY),
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
                    service_id="nex-cx",
                    event_type=STEADY_STATE_EVENT_TYPE,
                    limit=limit,
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
            raise PolicySteadyStateOperationsError(
                "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_SOURCE_UNAVAILABLE",
                "Answer-support steady-state operational events are unavailable.",
                status_code=503,
                retryable=True,
            ) from exc


def build_installed_policy_steady_state_operations_source(
    *,
    environ: Mapping[str, str],
    store: OperationalEventStore,
    emitter: OperationalEventEmitter,
    runtime_snapshot: Callable[[], Mapping[str, Any] | None],
) -> OperationalPolicySteadyStateSource:
    policy = load_policy_steady_state_operations_policy(
        Path(str(environ.get(POLICY_PATH_ENV, DEFAULT_POLICY_PATH)))
    )
    source = OperationalPolicySteadyStateSource(
        store=store,
        policy=policy,
        runtime_snapshot=runtime_snapshot,
    )
    runtime = runtime_snapshot()
    if runtime is not None:
        _require_runtime_binding(policy=policy, runtime=runtime)
        if runtime.get("steady_state_state") == ACTIVE:
            _ensure_window_open(
                emitter=emitter, store=store, policy=policy, runtime=runtime
            )
    return source


def register_policy_steady_state_operations_routes(
    app: FastAPI, *, source: OperationalPolicySteadyStateSource
) -> None:
    @app.get(OPERATIONS_PATH, response_model=None)
    def get_policy_steady_state_operations(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = authorize_cx_operations_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        try:
            return source.snapshot()
        except PolicySteadyStateOperationsError as exc:
            return _problem(request, exc)


def load_policy_steady_state_operations_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicySteadyStateOperationsError(
            "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_POLICY_UNAVAILABLE",
            "Answer-support steady-state operations policy is unavailable.",
        ) from exc
    return validate_policy_steady_state_operations_policy(value)


def validate_policy_steady_state_operations_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("policy")
    policy = dict(value)
    supplied_hash = _hash_ref(policy.pop("policy_hash", None))
    expected = {
        "policy_schema_version",
        "policy_id",
        "status",
        "source_activation",
        "steady_state_authorization_hash",
        "operations_profile_hash",
        "cutover_authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_policy_hash",
        "steady_state_window_id",
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
        or policy.get("status")
        != "APPROVED_FOR_CONTROLLED_STEADY_STATE_OPERATIONS"
        or policy.get("source_activation") != _SOURCE_ACTIVATION
        or policy.get("steady_state_authorization_hash")
        != _SOURCE_ACTIVATION["steady_state_authorization_hash"]
        or policy.get("operations_profile_hash")
        != _SOURCE_ACTIVATION["operations_profile_hash"]
        or policy.get("review_sample_interval") != 12
        or policy.get("maximum_concurrency") != 4
        or policy.get("maximum_event_scan") != 1000
        or policy.get("operational_slo") != _OPERATIONAL_SLO
        or policy.get("escalation_policy") != _ESCALATION
        or policy.get("safety") != _SAFETY
    ):
        raise _invalid("policy_semantics")
    for name in (
        "steady_state_authorization_hash",
        "operations_profile_hash",
        "cutover_authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_policy_hash",
    ):
        _hash_ref(policy.get(name))
    for name in ("policy_id", "steady_state_window_id"):
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
    if runtime.get("steady_state_state") != ACTIVE:
        raise _binding_drift()
    details = {
        "window_schema_version": WINDOW_SCHEMA_VERSION,
        "window_state": "OPEN",
        "window_id": policy["steady_state_window_id"],
        "policy_hash": policy["policy_hash"],
        "source_activation_evidence_hash": policy["source_activation"][
            "evidence_hash"
        ],
        "steady_state_receipt_hash": policy["steady_state_authorization_hash"],
        "operations_profile_hash": policy["operations_profile_hash"],
        "cutover_receipt_hash": policy["cutover_authorization_hash"],
        "selected_policy_hash": policy["selected_policy_hash"],
        "review_sample_interval": policy["review_sample_interval"],
        "maximum_concurrency": policy["maximum_concurrency"],
    }
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-answer-support-policy-steady-state-window:"
            f"{policy['steady_state_window_id']}",
        )
    )
    event = emitter.emit(
        event_type=WINDOW_EVENT_TYPE,
        severity="INFO",
        message="CX answer-support policy steady-state operations window was opened.",
        subject_ref=build_subject_ref(
            "cx.answer_support_policy_steady_state_window",
            policy["steady_state_window_id"],
        ),
        details=details,
        event_id=event_id,
    )
    if event.get("details") != details:
        raise PolicySteadyStateOperationsError(
            "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_WINDOW_DRIFT",
            "Existing steady-state operations window does not match the policy.",
        )
    persisted = store.get_event(event_id)
    if persisted is None or persisted.get("details") != details:
        raise PolicySteadyStateOperationsError(
            "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_WINDOW_UNAVAILABLE",
            "Steady-state operations window could not be recovered.",
            status_code=503,
            retryable=True,
        )
    return persisted


def _require_runtime_binding(
    *, policy: Mapping[str, Any], runtime: Mapping[str, Any]
) -> None:
    if (
        runtime.get("steady_state_authorization_hash")
        != policy["steady_state_authorization_hash"]
        or runtime.get("operations_profile_hash")
        != policy["operations_profile_hash"]
        or runtime.get("authorization_hash")
        != policy["cutover_authorization_hash"]
        or runtime.get("activation_bundle_hash")
        != policy["activation_bundle_hash"]
        or runtime.get("selected_policy_hash") != policy["selected_policy_hash"]
        or runtime.get("sustained_policy_hash") != policy["sustained_policy_hash"]
        or runtime.get("steady_state_state")
        not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
        or runtime.get("cutover_state")
        not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
    ):
        raise _binding_drift()


def _window_projection(
    events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    opened_at = None
    for event in events:
        details = event.get("details")
        if (
            isinstance(details, Mapping)
            and details.get("window_schema_version") == WINDOW_SCHEMA_VERSION
            and details.get("window_id") == policy["steady_state_window_id"]
            and details.get("policy_hash") == policy["policy_hash"]
            and details.get("steady_state_receipt_hash")
            == policy["steady_state_authorization_hash"]
            and isinstance(event.get("created_at"), str)
        ):
            opened_at = str(event["created_at"])
            break
    return {
        "window_id": policy["steady_state_window_id"],
        "policy_hash": policy["policy_hash"],
        "window_state": "OPEN" if opened_at else "NOT_OPENED",
        "opened_at": opened_at,
        "review_sample_interval": policy["review_sample_interval"],
        "maximum_concurrency": policy["maximum_concurrency"],
    }


def _steady_state_projection(
    events: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    selected: Mapping[str, Any] | None = None
    selected_rank = -1
    ranks = {ACTIVE: 0, ROLLBACK_PENDING_REVIEW: 1, ROLLED_BACK: 2}
    for event in events:
        details = event.get("details")
        if (
            not isinstance(details, Mapping)
            or details.get("steady_state_receipt_hash")
            != policy["steady_state_authorization_hash"]
            or details.get("operations_profile_hash")
            != policy["operations_profile_hash"]
        ):
            continue
        rank = ranks.get(str(details.get("steady_state_state")), -1)
        if rank > selected_rank:
            selected = event
            selected_rank = rank
    details = selected.get("details") if selected else {}
    return {
        "steady_state_state": (
            details.get("steady_state_state")
            if isinstance(details, Mapping)
            else "NOT_ACTIVATED"
        )
        or "NOT_ACTIVATED",
        "reason_code": (
            details.get("reason_code") if isinstance(details, Mapping) else None
        ),
        "observed_at": selected.get("created_at") if selected else None,
    }


def _runtime_projection(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "installed": False,
            "steady_state_state": None,
            "cutover_state": None,
            "in_flight": 0,
            "peak_in_flight": 0,
        }
    gateway = value.get("generation_client")
    gateway = gateway if isinstance(gateway, Mapping) else {}
    return {
        "installed": True,
        "steady_state_state": value.get("steady_state_state"),
        "steady_state_reason_code": value.get("steady_state_reason_code"),
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
    progress: Mapping[str, Any],
    runtime: Mapping[str, Any],
    cadence: Mapping[str, Any],
    slo_checks: Mapping[str, bool],
) -> tuple[str, str, list[str]]:
    steady_state = state.get("steady_state_state")
    if steady_state == ROLLED_BACK:
        return "ROLLED_BACK", "DEGRADED", ["ROLLBACK_STATE_DOMINANT"]
    if steady_state == ROLLBACK_PENDING_REVIEW:
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
        and steady_state == ACTIVE
        and runtime.get("installed") is True
        and runtime.get("steady_state_state") == ACTIVE
    ):
        return "MONITORING", "READY", []
    return "DISABLED", "UNAVAILABLE", []


def _safe_integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) and value >= 0 else 0


def _binding_drift() -> PolicySteadyStateOperationsError:
    return PolicySteadyStateOperationsError(
        "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_BINDING_DRIFT",
        "Installed steady-state runtime does not match the operations policy.",
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


def _invalid(detail: str) -> PolicySteadyStateOperationsError:
    return PolicySteadyStateOperationsError(
        "CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_INVALID", detail
    )


def _problem(
    request: Request, exc: PolicySteadyStateOperationsError
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX answer-support steady-state operations unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-answer-support-steady-state-operations-unavailable"
        ),
    )
