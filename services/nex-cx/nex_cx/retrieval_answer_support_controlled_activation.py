from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitter,
    OperationalEventStore,
    build_subject_ref,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportGenerationClient,
    AnswerSupportShadowOutcomeSink,
    validate_answer_support_shadow_configuration,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    AnswerSupportProgressSink,
    BoundedSynchronousAnswerSupportRuntime,
    build_bounded_synchronous_answer_support_runtime,
    validate_synchronous_runtime_policy,
)
from nex_cx.retrieval_answer_support_provider_relocation import (
    resolve_runtime_provider_binding,
)

ACTIVATION_BUNDLE_SCHEMA_VERSION = "cx_answer_support_controlled_activation_bundle.v1"
ACTIVATION_STATE_SCHEMA_VERSION = "cx_answer_support_controlled_activation_state.v1"
ACTIVATION_MODE_ENV = "NEX_CX_ANSWER_SUPPORT_SHADOW_MODE"
ACTIVATION_BUNDLE_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_ACTIVATION_BUNDLE_PATH"
ACTIVATION_MODE_DISABLED = "DISABLED"
ACTIVATION_MODE_CONTROLLED = "CONTROLLED"
ACTIVATION_EVENT_TYPE = "cx.retrieval.answer_support_activation"
PROGRESS_EVENT_TYPE = "cx.retrieval.answer_support_progress"
ACTIVE = "ACTIVE"
ROLLED_BACK = "ROLLED_BACK"
CURRENT_POLICY = "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"
DEFAULT_ACTIVATION_BUNDLE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_controlled_activation.v1.json"
)

_BUNDLE_FIELDS = {
    "bundle_schema_version",
    "status",
    "approval_receipt",
    "readiness_manifest",
    "signal_design",
    "request_profile",
    "selected_policy",
    "source_binding",
    "rollback_policy",
    "slo_profile",
    "safety",
    "bundle_hash",
}
_SOURCE_FIELDS = {
    "approval_receipt_document_hash",
    "approval_receipt_hash",
    "operator_decision_hash",
    "operator_manifest_hash",
    "source_e2e_receipt_hash",
    "source_e2e_manifest_hash",
    "selected_policy_hash",
    "readiness_manifest_hash",
    "signal_design_hash",
    "request_profile_hash",
    "provider_binding_hash",
}
_ROLLBACK_POLICY = {
    "source_binding_drift": "IMMEDIATE_ROLLBACK",
    "provider_error": "IMMEDIATE_ROLLBACK",
    "progress_sink_failure": "IMMEDIATE_ROLLBACK",
    "feedback_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "interactive_e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "non_retryable_overload": "IMMEDIATE_ROLLBACK",
}
_SAFETY = {
    "holdout_access_permitted": False,
    "primary_decision_mutation_permitted": False,
    "production_cutover_permitted": False,
    "raw_text_persistence_permitted": False,
    "user_visible_decision_change_permitted": False,
}
_IMMEDIATE_FAILURE_CODES = {
    "cx.answer_support_shadow.provider_binding_drift": "SOURCE_BINDING_DRIFT",
    "cx.answer_support_shadow.provider_unavailable": "PROVIDER_ERROR",
    "cx.answer_support_shadow.provider_response_invalid": "PROVIDER_ERROR",
}


class RuntimeActivationStateStore(Protocol):
    def current_state(self, bundle_hash: str) -> Mapping[str, Any] | None: ...

    def record_state(self, state: Mapping[str, Any]) -> None: ...


class ControlledRuntimeActivationError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class OperationalRuntimeActivationStateStore:
    emitter: OperationalEventEmitter
    store: OperationalEventStore

    def current_state(self, bundle_hash: str) -> Mapping[str, Any] | None:
        validate_hash_ref(bundle_hash)
        active: dict[str, Any] | None = None
        for event in self.store.list_events(
            service_id="nex-cx",
            event_type=ACTIVATION_EVENT_TYPE,
            limit=100,
        ):
            details = event.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("activation_bundle_hash") == bundle_hash
            ):
                normalized = deepcopy(dict(details))
                if normalized.get("activation_state") == ROLLED_BACK:
                    return normalized
                active = normalized
        return active

    def record_state(self, state: Mapping[str, Any]) -> None:
        normalized = validate_activation_state(state)
        bundle_hash = normalized["activation_bundle_hash"]
        activation_state = normalized["activation_state"]
        self.emitter.emit(
            event_type=ACTIVATION_EVENT_TYPE,
            severity="WARNING" if activation_state == ROLLED_BACK else "INFO",
            message=(
                "CX answer-support controlled shadow runtime was rolled back."
                if activation_state == ROLLED_BACK
                else "CX answer-support controlled shadow runtime was activated."
            ),
            subject_ref=build_subject_ref("cx.answer_support_activation", bundle_hash),
            details=normalized,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"cx-answer-support-activation:{bundle_hash}:{activation_state}",
                )
            ),
        )


@dataclass(frozen=True)
class OperationalAnswerSupportProgressSink:
    emitter: OperationalEventEmitter

    def record(self, event: Mapping[str, Any]) -> None:
        request_id = _required_text(event.get("request_id"), "request_id")
        trace_id = _required_text(event.get("trace_id"), "trace_id")
        event_type = _required_text(event.get("event_type"), "event_type")
        elapsed_ms = _number(event.get("elapsed_ms"), "elapsed_ms")
        self.emitter.emit(
            event_type=PROGRESS_EVENT_TYPE,
            severity="WARNING" if event_type.endswith("FAILED") else "INFO",
            message="CX answer-support controlled shadow progress was observed.",
            request_id=request_id,
            trace_id=trace_id,
            subject_ref=build_subject_ref("cx.answer_support_request", request_id),
            details={
                "progress_event_schema_version": event.get("event_schema_version"),
                "progress_event_type": event_type,
                "elapsed_ms": elapsed_ms,
                "retryable": event.get("retryable") is True,
                "event_hash": event.get("event_hash"),
                "user_visible": False,
            },
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"cx-answer-support-progress:{event.get('event_hash')}",
                )
            ),
        )


class ControlledAnswerSupportRuntime:
    """Run the approved observer and permanently fall back on rollback signals."""

    def __init__(
        self,
        delegate: BoundedSynchronousAnswerSupportRuntime,
        *,
        bundle: Mapping[str, Any],
        state_store: RuntimeActivationStateStore,
    ) -> None:
        self.delegate = delegate
        self._bundle = validate_controlled_activation_bundle(bundle)
        self._bundle_hash = self._bundle["bundle_hash"]
        self._state_store = state_store
        self._state = ACTIVE
        self._rollback_reason: str | None = None
        self._lock = Lock()
        self._e2e_latencies_ms: list[float] = []

    def observe(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]:
        with self._lock:
            if self._state == ROLLED_BACK:
                return _rolled_back_outcome(
                    primary_package=primary_package,
                    access_context=access_context,
                    reason_code=self._rollback_reason or "PREVIOUS_ROLLBACK",
                )
        before = self.delegate.generation_client.snapshot()
        try:
            outcome = dict(
                self.delegate.observe(
                    query_text=query_text,
                    evidence_items=evidence_items,
                    primary_package=primary_package,
                    access_context=access_context,
                )
            )
        except Exception:
            self._rollback("NON_RETRYABLE_OVERLOAD")
            raise
        after = self.delegate.generation_client.snapshot()
        reason = _immediate_rollback_reason(outcome, before=before, after=after)
        if reason is None:
            reason = self._latency_rollback_reason(outcome, snapshot=after)
        if reason is not None:
            self._rollback(reason)
        return outcome

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            reason = self._rollback_reason
            e2e = list(self._e2e_latencies_ms)
        gateway = self.delegate.generation_client.snapshot()
        return {
            "activation_bundle_hash": self._bundle_hash,
            "activation_state": state,
            "rollback_reason": reason,
            "fallback_policy": CURRENT_POLICY,
            "user_visible_decision_change": False,
            "production_cutover": False,
            "e2e_sample_count": len(e2e),
            "e2e_p95_latency_ms": _p95(e2e),
            "generation_client": gateway,
        }

    def _latency_rollback_reason(
        self,
        outcome: Mapping[str, Any],
        *,
        snapshot: Mapping[str, Any],
    ) -> str | None:
        if outcome.get("provider_called") is True:
            with self._lock:
                self._e2e_latencies_ms.append(
                    _number(outcome.get("elapsed_ms"), "outcome.elapsed_ms")
                )
                e2e = list(self._e2e_latencies_ms)
        else:
            return None
        minimum = int(self._bundle["slo_profile"]["minimum_sample_count"])
        if len(e2e) < minimum:
            return None
        slo = self._bundle["slo_profile"]
        feedback = snapshot.get("feedback_latencies_ms")
        provider = snapshot.get("provider_latencies_ms")
        if _p95(_numbers(feedback)) > slo["feedback_p95_latency_ms"]:
            return "FEEDBACK_P95_SLO_BREACH"
        if _p95(_numbers(provider)) > slo["provider_p95_latency_ms"]:
            return "PROVIDER_P95_SLO_BREACH"
        if _p95(e2e) > slo["interactive_e2e_p95_latency_ms"]:
            return "INTERACTIVE_E2E_P95_SLO_BREACH"
        return None

    def _rollback(self, reason_code: str) -> None:
        with self._lock:
            if self._state == ROLLED_BACK:
                return
            self._state = ROLLED_BACK
            self._rollback_reason = reason_code
        self._state_store.record_state(
            build_activation_state(
                bundle_hash=self._bundle_hash,
                activation_state=ROLLED_BACK,
                reason_code=reason_code,
            )
        )


def build_installed_controlled_answer_support_runtime(
    *,
    environ: Mapping[str, str],
    generation_client: AnswerSupportGenerationClient,
    progress_sink: AnswerSupportProgressSink,
    outcome_sink: AnswerSupportShadowOutcomeSink,
    state_store: RuntimeActivationStateStore,
) -> ControlledAnswerSupportRuntime | None:
    mode = (
        str(environ.get(ACTIVATION_MODE_ENV, ACTIVATION_MODE_DISABLED)).strip().upper()
    )
    if mode == ACTIVATION_MODE_DISABLED:
        return None
    if mode != ACTIVATION_MODE_CONTROLLED:
        raise _invalid("activation_mode")
    path = Path(
        str(environ.get(ACTIVATION_BUNDLE_PATH_ENV, DEFAULT_ACTIVATION_BUNDLE_PATH))
    )
    bundle = load_controlled_activation_bundle(path)
    runtime_provider_binding = resolve_runtime_provider_binding(
        environ,
        activation_bundle=bundle,
    )
    previous = state_store.current_state(bundle["bundle_hash"])
    if previous is not None:
        previous = validate_activation_state(previous)
        if previous["activation_state"] == ROLLED_BACK:
            return None
    delegate = build_bounded_synchronous_answer_support_runtime(
        policy=bundle["selected_policy"],
        readiness_manifest=bundle["readiness_manifest"],
        signal_design=bundle["signal_design"],
        request_profile=bundle["request_profile"],
        generation_client=generation_client,
        progress_sink=progress_sink,
        outcome_sink=outcome_sink,
        runtime_provider_binding=runtime_provider_binding,
    )
    runtime = ControlledAnswerSupportRuntime(
        delegate,
        bundle=bundle,
        state_store=state_store,
    )
    if previous is None:
        state_store.record_state(
            build_activation_state(
                bundle_hash=bundle["bundle_hash"],
                activation_state=ACTIVE,
                reason_code="OPERATOR_APPROVED_CONTROLLED_ACTIVATION",
            )
        )
    return runtime


def load_controlled_activation_bundle(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlledRuntimeActivationError(
            "CX_ANSWER_SUPPORT_ACTIVATION_BUNDLE_UNAVAILABLE",
            "The controlled activation bundle is unavailable.",
        ) from exc
    return validate_controlled_activation_bundle(value)


def validate_controlled_activation_bundle(bundle: object) -> dict[str, Any]:
    normalized = dict(_mapping(bundle, "activation_bundle"))
    if set(normalized) != _BUNDLE_FIELDS:
        raise _invalid("activation_bundle_fields")
    supplied_hash = _hash_ref(normalized.pop("bundle_hash", None), "bundle_hash")
    if semantic_sha256_hash_ref(normalized) != supplied_hash:
        raise _integrity("activation_bundle")
    if (
        normalized.get("bundle_schema_version") != ACTIVATION_BUNDLE_SCHEMA_VERSION
        or normalized.get("status") != "APPROVED_FOR_CONTROLLED_ACTIVATION"
    ):
        raise _invalid("activation_bundle_identity")
    source = _exact(normalized.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    source = {key: _hash_ref(source.get(key), key) for key in sorted(_SOURCE_FIELDS)}
    approval = _validate_approval_receipt(
        normalized.get("approval_receipt"), source=source
    )
    readiness = dict(
        _mapping(normalized.get("readiness_manifest"), "readiness_manifest")
    )
    signal = dict(_mapping(normalized.get("signal_design"), "signal_design"))
    request_profile = dict(
        _mapping(normalized.get("request_profile"), "request_profile")
    )
    configuration = validate_answer_support_shadow_configuration(
        readiness,
        signal_design=signal,
        request_profile=request_profile,
    )
    policy = validate_synchronous_runtime_policy(
        _mapping(normalized.get("selected_policy"), "selected_policy")
    )
    provider_binding = configuration["candidate_profile"]["provider_binding"]
    if (
        readiness.get("manifest_hash") != source["readiness_manifest_hash"]
        or configuration["signal_design"]["design_hash"] != source["signal_design_hash"]
        or configuration["request_profile"]["profile_hash"]
        != source["request_profile_hash"]
        or policy["policy_hash"] != source["selected_policy_hash"]
        or semantic_sha256_hash_ref(provider_binding) != source["provider_binding_hash"]
        or dict(_mapping(normalized.get("rollback_policy"), "rollback_policy"))
        != _ROLLBACK_POLICY
        or dict(_mapping(normalized.get("safety"), "safety")) != _SAFETY
    ):
        raise _integrity("activation_sources")
    slo = _validate_slo_profile(normalized.get("slo_profile"), policy=policy)
    normalized.update(
        {
            "approval_receipt": approval,
            "readiness_manifest": readiness,
            "signal_design": signal,
            "request_profile": request_profile,
            "selected_policy": policy,
            "source_binding": source,
            "slo_profile": slo,
            "bundle_hash": supplied_hash,
        }
    )
    return normalized


def build_activation_state(
    *, bundle_hash: str, activation_state: str, reason_code: str
) -> dict[str, Any]:
    state = {
        "state_schema_version": ACTIVATION_STATE_SCHEMA_VERSION,
        "activation_bundle_hash": _hash_ref(bundle_hash, "activation_bundle_hash"),
        "activation_state": activation_state,
        "reason_code": _required_text(reason_code, "reason_code"),
        "fallback_policy": CURRENT_POLICY,
        "user_visible": False,
        "production_cutover": False,
    }
    state["state_hash"] = semantic_sha256_hash_ref(state)
    return validate_activation_state(state)


def validate_activation_state(state: object) -> dict[str, Any]:
    normalized = dict(_mapping(state, "activation_state"))
    supplied_hash = _hash_ref(normalized.pop("state_hash", None), "state_hash")
    if (
        set(normalized)
        != {
            "state_schema_version",
            "activation_bundle_hash",
            "activation_state",
            "reason_code",
            "fallback_policy",
            "user_visible",
            "production_cutover",
        }
        or semantic_sha256_hash_ref(normalized) != supplied_hash
        or normalized.get("state_schema_version") != ACTIVATION_STATE_SCHEMA_VERSION
        or normalized.get("activation_state") not in {ACTIVE, ROLLED_BACK}
        or normalized.get("fallback_policy") != CURRENT_POLICY
        or normalized.get("user_visible") is not False
        or normalized.get("production_cutover") is not False
    ):
        raise _invalid("activation_state")
    _hash_ref(normalized.get("activation_bundle_hash"), "activation_bundle_hash")
    _required_text(normalized.get("reason_code"), "reason_code")
    normalized["state_hash"] = supplied_hash
    return normalized


def _validate_approval_receipt(
    receipt: object, *, source: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = dict(_mapping(receipt, "approval_receipt"))
    receipt_hash = _hash_ref(normalized.pop("receipt_hash", None), "receipt_hash")
    if (
        semantic_sha256_hash_ref(normalized) != receipt_hash
        or receipt_hash != source["approval_receipt_hash"]
    ):
        raise _integrity("approval_receipt")
    normalized["receipt_hash"] = receipt_hash
    if (
        semantic_sha256_hash_ref(normalized) != source["approval_receipt_document_hash"]
        or normalized.get("status") != "PASS"
        or normalized.get("decision")
        != "CONTROLLED_SYNCHRONOUS_SHADOW_ACTIVATION_APPROVED"
        or normalized.get("activation_status") != "APPROVED_NOT_ACTIVATED"
        or normalized.get("approved_activation_scope")
        != "BOUNDED_SYNCHRONOUS_ANSWER_SUPPORT_SHADOW_OBSERVER"
        or normalized.get("runtime_activation_approved") is not True
        or normalized.get("runtime_activated") is not False
        or normalized.get("production_cutover_approved") is not False
        or normalized.get("user_visible_decision_change_permitted") is not False
        or normalized.get("operator_decision_hash") != source["operator_decision_hash"]
        or normalized.get("manifest_hash") != source["operator_manifest_hash"]
        or normalized.get("source_e2e_receipt_hash")
        != source["source_e2e_receipt_hash"]
        or normalized.get("source_e2e_manifest_hash")
        != source["source_e2e_manifest_hash"]
        or normalized.get("selected_policy_hash") != source["selected_policy_hash"]
    ):
        raise _integrity("approval_semantics")
    return normalized


def _validate_slo_profile(
    value: object, *, policy: Mapping[str, Any]
) -> dict[str, Any]:
    slo = dict(_mapping(value, "slo_profile"))
    if set(slo) != {
        "minimum_sample_count",
        "feedback_p95_latency_ms",
        "provider_p95_latency_ms",
        "interactive_e2e_p95_latency_ms",
    }:
        raise _invalid("slo_profile_fields")
    expected = policy["slo_profile"]
    if (
        slo.get("minimum_sample_count") != 4
        or slo.get("feedback_p95_latency_ms")
        != expected["prompt_acceptance_feedback_p95_latency_ms"]
        or slo.get("provider_p95_latency_ms")
        != expected["generation_provider_p95_latency_ms"]
        or slo.get("interactive_e2e_p95_latency_ms")
        != expected["interactive_final_response_e2e_p95_latency_ms"]
    ):
        raise _invalid("slo_profile")
    return slo


def _immediate_rollback_reason(
    outcome: Mapping[str, Any],
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> str | None:
    if int(after.get("progress_failure_count", 0)) > int(
        before.get("progress_failure_count", 0)
    ):
        return "PROGRESS_SINK_FAILURE"
    if outcome.get("status") == "FAILED":
        return _IMMEDIATE_FAILURE_CODES.get(
            str(outcome.get("error_code")), "PROVIDER_ERROR"
        )
    return None


def _rolled_back_outcome(
    *,
    primary_package: Mapping[str, Any],
    access_context: CxAccessContext,
    reason_code: str,
) -> dict[str, Any]:
    outcome = {
        "outcome_schema_version": "cx_answer_support_controlled_activation_outcome.v1",
        "mode": "SHADOW",
        "status": "SKIPPED",
        "shadow_decision": "NOT_EVALUATED",
        "skip_reason": "RUNTIME_ROLLED_BACK",
        "rollback_reason": reason_code,
        "retrieval_package_id": primary_package.get("retrieval_package_id"),
        "request_id": access_context.request_id,
        "trace_id": access_context.trace_id,
        "provider_called": False,
        "user_visible": False,
        "primary_decision_mutated": False,
        "production_cutover_permitted": False,
    }
    outcome["outcome_hash"] = semantic_sha256_hash_ref(outcome)
    return outcome


def _numbers(value: object) -> list[float]:
    if not isinstance(value, list):
        raise _invalid("latency_samples")
    return [_number(item, "latency_sample") for item in value]


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return round(float(ordered[index]), 6)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise _invalid(name)
    return float(value)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise _invalid(name)
    return value.strip()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != expected:
        raise _invalid(f"{name}_fields")
    return normalized


def _hash_ref(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(name)
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(name) from exc


def _invalid(detail: str) -> ControlledRuntimeActivationError:
    return ControlledRuntimeActivationError(
        "CX_ANSWER_SUPPORT_CONTROLLED_ACTIVATION_INVALID", detail
    )


def _integrity(detail: str) -> ControlledRuntimeActivationError:
    return ControlledRuntimeActivationError(
        "CX_ANSWER_SUPPORT_CONTROLLED_ACTIVATION_INTEGRITY", detail
    )
