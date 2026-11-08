from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import suppress
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
from nex_cx.retrieval_answer_support_controlled_activation import (
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    OperationalAnswerSupportProgressSink,
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_provider_relocation import (
    resolve_runtime_provider_binding,
)
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportGenerationClient,
    AnswerSupportShadowOutcomeSink,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    BoundedSynchronousAnswerSupportRuntime,
    build_bounded_synchronous_answer_support_runtime,
)

CUTOVER_MODE_ENV = "NEX_CX_ANSWER_SUPPORT_POLICY_MODE"
CUTOVER_AUTHORIZATION_PATH_ENV = "NEX_CX_ANSWER_SUPPORT_POLICY_AUTHORIZATION_PATH"
CUTOVER_MODE_DISABLED = "DISABLED"
CUTOVER_MODE_CONTROLLED = "CONTROLLED"
CUTOVER_EVENT_TYPE = "cx.retrieval.answer_support_policy_cutover"
CUTOVER_AUTHORIZATION_SCHEMA_VERSION = (
    "cx_answer_support_policy_cutover_authorization.v1"
)
CUTOVER_STATE_SCHEMA_VERSION = "cx_answer_support_policy_cutover_state.v1"
CUTOVER_DECISION_EVENT_SCHEMA_VERSION = "cx_answer_support_policy_cutover_decision.v1"
ACTIVE = "ACTIVE"
ROLLED_BACK = "ROLLED_BACK"
ROLLBACK_PENDING_REVIEW = "ROLLBACK_PENDING_REVIEW"
CURRENT_POLICY = "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY"
DEFAULT_AUTHORIZATION_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_policy_cutover_authorization.v1.json"
)

_TERMINAL_STATES = {ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
_IMMEDIATE_FAILURE_CODES = {
    "cx.answer_support_shadow.configuration_invalid": "SOURCE_BINDING_DRIFT",
    "cx.answer_support_shadow.provider_binding_drift": "SOURCE_BINDING_DRIFT",
    "cx.answer_support_shadow.provider_response_invalid": "PROVIDER_ERROR",
    "cx.answer_support_shadow.provider_unavailable": "PROVIDER_ERROR",
    "cx.answer_support_shadow.permission_drift": "SOURCE_BINDING_DRIFT",
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
    "production_cutover_permitted": False,
    "permission_scope_mutation_permitted": False,
    "candidate_order_mutation_permitted": False,
}


class CutoverStateStore(Protocol):
    def current_state(self, authorization_hash: str) -> Mapping[str, Any] | None: ...

    def record_state(self, state: Mapping[str, Any]) -> None: ...


class CutoverDecisionSink(Protocol):
    def record(self, decision: Mapping[str, Any]) -> None: ...


class AnswerSupportPolicyCutoverError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class OperationalPolicyCutoverStateStore:
    emitter: OperationalEventEmitter
    store: OperationalEventStore

    def current_state(self, authorization_hash: str) -> Mapping[str, Any] | None:
        validate_hash_ref(authorization_hash)
        active: dict[str, Any] | None = None
        for event in self.store.list_events(
            service_id="nex-cx", event_type=CUTOVER_EVENT_TYPE, limit=100
        ):
            details = event.get("details")
            if not isinstance(details, Mapping):
                continue
            if details.get("cutover_receipt_hash") != authorization_hash:
                continue
            normalized = deepcopy(dict(details))
            if normalized.get("cutover_state") in _TERMINAL_STATES:
                return normalized
            active = normalized
        return active

    def record_state(self, state: Mapping[str, Any]) -> None:
        normalized = validate_cutover_state(state)
        cutover_state = normalized["cutover_state"]
        authorization_hash = normalized["cutover_receipt_hash"]
        self.emitter.emit(
            event_type=CUTOVER_EVENT_TYPE,
            severity="INFO" if cutover_state == ACTIVE else "WARNING",
            message=(
                "CX answer-support user-visible policy cutover was activated."
                if cutover_state == ACTIVE
                else "CX answer-support user-visible policy cutover fell back."
            ),
            subject_ref=build_subject_ref(
                "cx.answer_support_policy_cutover", authorization_hash
            ),
            details=normalized,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"cx-answer-support-policy-cutover:{authorization_hash}:{cutover_state}",
                )
            ),
        )


class ControlledAnswerSupportPolicyCutover:
    def __init__(
        self,
        delegate: BoundedSynchronousAnswerSupportRuntime,
        *,
        activation_bundle: Mapping[str, Any],
        authorization: Mapping[str, Any],
        state_store: CutoverStateStore,
        decision_sink: CutoverDecisionSink | None = None,
        previous_state: Mapping[str, Any] | None = None,
    ) -> None:
        self.delegate = delegate
        self._bundle = load_and_validate_cutover_sources(
            activation_bundle=activation_bundle,
            authorization=authorization,
        )
        self._authorization = self._bundle["authorization"]
        self._state_store = state_store
        self._decision_sink = decision_sink
        self._state = ACTIVE
        self._rollback_reason: str | None = None
        if previous_state is not None:
            restored = validate_cutover_state(previous_state)
            self._state = restored["cutover_state"]
            self._rollback_reason = restored["reason_code"]
        self._lock = Lock()
        self._e2e_latencies_ms: list[float] = []

    def apply(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]:
        with self._lock:
            if self._state in _TERMINAL_STATES:
                result = deepcopy(dict(primary_package))
                self._record_decision(
                    access_context=access_context,
                    primary_package=primary_package,
                    result=result,
                    outcome=None,
                    decision_state="FALLBACK",
                    reason_code=self._rollback_reason or "PREVIOUS_ROLLBACK",
                )
                return result
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
        except Exception:  # noqa: BLE001 - cutover must fall back on any delegate fault
            self._rollback("NON_RETRYABLE_OVERLOAD", pending_review=False)
            result = deepcopy(dict(primary_package))
            self._record_decision(
                access_context=access_context,
                primary_package=primary_package,
                result=result,
                outcome=None,
                decision_state="FALLBACK",
                reason_code="NON_RETRYABLE_OVERLOAD",
            )
            return result
        after = self.delegate.generation_client.snapshot()
        reason = _immediate_rollback_reason(outcome, before=before, after=after)
        pending_review = False
        if reason is None:
            reason = self._latency_rollback_reason(outcome, snapshot=after)
            pending_review = reason is not None
        if reason is not None:
            self._rollback(reason, pending_review=pending_review)
            result = deepcopy(dict(primary_package))
            self._record_decision(
                access_context=access_context,
                primary_package=primary_package,
                result=result,
                outcome=outcome,
                decision_state="FALLBACK",
                reason_code=reason,
            )
            return result
        if outcome.get("status") != "OBSERVED":
            result = deepcopy(dict(primary_package))
            self._record_decision(
                access_context=access_context,
                primary_package=primary_package,
                result=result,
                outcome=outcome,
                decision_state="SKIPPED",
                reason_code=str(outcome.get("skip_reason") or "NOT_OBSERVED"),
            )
            return result
        result = _apply_authoritative_decision(
            primary_package,
            outcome=outcome,
            authorization=self._authorization,
            activation_bundle=self._bundle["activation_bundle"],
        )
        self._record_decision(
            access_context=access_context,
            primary_package=primary_package,
            result=result,
            outcome=outcome,
            decision_state="APPLIED",
            reason_code=None,
        )
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            reason = self._rollback_reason
            e2e = list(self._e2e_latencies_ms)
        return {
            "authorization_hash": self._authorization["authorization_hash"],
            "activation_bundle_hash": self._authorization["activation_bundle_hash"],
            "selected_policy_hash": self._authorization["selected_policy_hash"],
            "cutover_state": state,
            "rollback_reason": reason,
            "fallback_policy": CURRENT_POLICY,
            "user_visible_decision_change": state == ACTIVE,
            "production_cutover": False,
            "e2e_sample_count": len(e2e),
            "e2e_p95_latency_ms": _p95(e2e),
            "generation_client": self.delegate.generation_client.snapshot(),
        }

    def _latency_rollback_reason(
        self, outcome: Mapping[str, Any], *, snapshot: Mapping[str, Any]
    ) -> str | None:
        if outcome.get("provider_called") is not True:
            return None
        with self._lock:
            self._e2e_latencies_ms.append(_number(outcome.get("elapsed_ms")))
            e2e = list(self._e2e_latencies_ms)
        slo = self._bundle["activation_bundle"]["slo_profile"]
        if len(e2e) < int(slo["minimum_sample_count"]):
            return None
        if _p95(_numbers(snapshot.get("feedback_latencies_ms"))) > float(
            slo["feedback_p95_latency_ms"]
        ):
            return "FEEDBACK_P95_SLO_BREACH"
        if _p95(_numbers(snapshot.get("provider_latencies_ms"))) > float(
            slo["provider_p95_latency_ms"]
        ):
            return "PROVIDER_P95_SLO_BREACH"
        if _p95(e2e) > float(slo["interactive_e2e_p95_latency_ms"]):
            return "INTERACTIVE_E2E_P95_SLO_BREACH"
        return None

    def _rollback(self, reason_code: str, *, pending_review: bool) -> None:
        state = ROLLBACK_PENDING_REVIEW if pending_review else ROLLED_BACK
        with self._lock:
            if self._state in _TERMINAL_STATES:
                return
            self._state = state
            self._rollback_reason = reason_code
        self._state_store.record_state(
            build_cutover_state(
                authorization_hash=self._authorization["authorization_hash"],
                cutover_state=state,
                reason_code=reason_code,
            )
        )

    def _record_decision(
        self,
        *,
        access_context: CxAccessContext,
        primary_package: Mapping[str, Any],
        result: Mapping[str, Any],
        outcome: Mapping[str, Any] | None,
        decision_state: str,
        reason_code: str | None,
    ) -> None:
        if self._decision_sink is None:
            return
        decision = build_cutover_decision_event(
            authorization_hash=self._authorization["authorization_hash"],
            selected_policy_hash=self._authorization["selected_policy_hash"],
            request_id=access_context.request_id,
            trace_id=access_context.trace_id,
            primary_package=primary_package,
            result=result,
            outcome=outcome,
            decision_state=decision_state,
            reason_code=reason_code,
        )
        with suppress(Exception):
            self._decision_sink.record(decision)


def build_installed_answer_support_policy_cutover(
    *,
    environ: Mapping[str, str],
    generation_client: AnswerSupportGenerationClient,
    progress_sink: OperationalAnswerSupportProgressSink,
    outcome_sink: AnswerSupportShadowOutcomeSink,
    state_store: CutoverStateStore,
    decision_sink: CutoverDecisionSink | None = None,
) -> ControlledAnswerSupportPolicyCutover | None:
    mode = str(environ.get(CUTOVER_MODE_ENV, CUTOVER_MODE_DISABLED)).strip().upper()
    if mode == CUTOVER_MODE_DISABLED:
        return None
    if mode != CUTOVER_MODE_CONTROLLED:
        raise _invalid("cutover_mode")
    activation = load_controlled_activation_bundle(
        Path(
            str(
                environ.get(
                    "NEX_CX_ANSWER_SUPPORT_ACTIVATION_BUNDLE_PATH",
                    DEFAULT_ACTIVATION_BUNDLE_PATH,
                )
            )
        )
    )
    authorization = load_cutover_authorization(
        Path(
            str(environ.get(CUTOVER_AUTHORIZATION_PATH_ENV, DEFAULT_AUTHORIZATION_PATH))
        ),
        activation_bundle=activation,
    )
    runtime_provider_binding = resolve_runtime_provider_binding(
        environ,
        activation_bundle=activation,
    )
    previous = state_store.current_state(authorization["authorization_hash"])
    delegate = build_bounded_synchronous_answer_support_runtime(
        policy=activation["selected_policy"],
        readiness_manifest=activation["readiness_manifest"],
        signal_design=activation["signal_design"],
        request_profile=activation["request_profile"],
        generation_client=generation_client,
        progress_sink=progress_sink,
        outcome_sink=outcome_sink,
        runtime_provider_binding=runtime_provider_binding,
    )
    runtime = ControlledAnswerSupportPolicyCutover(
        delegate,
        activation_bundle=activation,
        authorization=authorization,
        state_store=state_store,
        decision_sink=decision_sink,
        previous_state=previous,
    )
    if previous is None:
        state_store.record_state(
            build_cutover_state(
                authorization_hash=authorization["authorization_hash"],
                cutover_state=ACTIVE,
                reason_code="OPERATOR_APPROVED_CONTROLLED_POLICY_CUTOVER",
            )
        )
    return runtime


def build_cutover_decision_event(
    *,
    authorization_hash: str,
    selected_policy_hash: str,
    request_id: str,
    trace_id: str,
    primary_package: Mapping[str, Any],
    result: Mapping[str, Any],
    outcome: Mapping[str, Any] | None,
    decision_state: str,
    reason_code: str | None,
) -> dict[str, Any]:
    normalized_outcome = outcome or {}
    decision = {
        "decision_event_schema_version": CUTOVER_DECISION_EVENT_SCHEMA_VERSION,
        "cutover_receipt_hash": _hash_ref(authorization_hash),
        "selected_policy_hash": _hash_ref(selected_policy_hash),
        "request_id": _required_text(request_id),
        "trace_id": _required_text(trace_id),
        "source_package_id": _required_text(
            primary_package.get("retrieval_package_id")
        ),
        "source_package_hash": _required_text(primary_package.get("package_hash")),
        "result_package_id": _required_text(result.get("retrieval_package_id")),
        "result_package_hash": _required_text(result.get("package_hash")),
        "decision_state": decision_state,
        "policy_decision": _required_text(result.get("status")),
        "reason_code": reason_code,
        "provider_called": normalized_outcome.get("provider_called") is True,
        "elapsed_ms": _number(normalized_outcome.get("elapsed_ms", 0.0)),
        "user_visible": decision_state == "APPLIED",
        "incumbent_fallback": decision_state != "APPLIED",
        "production_cutover": False,
    }
    decision["decision_event_hash"] = semantic_sha256_hash_ref(decision)
    return validate_cutover_decision_event(decision)


def validate_cutover_decision_event(value: object) -> dict[str, Any]:
    decision = dict(_mapping(value, "cutover_decision"))
    supplied_hash = _hash_ref(decision.pop("decision_event_hash", None))
    expected = {
        "decision_event_schema_version",
        "cutover_receipt_hash",
        "selected_policy_hash",
        "request_id",
        "trace_id",
        "source_package_id",
        "source_package_hash",
        "result_package_id",
        "result_package_hash",
        "decision_state",
        "policy_decision",
        "reason_code",
        "provider_called",
        "elapsed_ms",
        "user_visible",
        "incumbent_fallback",
        "production_cutover",
    }
    state = decision.get("decision_state")
    if (
        set(decision) != expected
        or semantic_sha256_hash_ref(decision) != supplied_hash
        or decision.get("decision_event_schema_version")
        != CUTOVER_DECISION_EVENT_SCHEMA_VERSION
        or state not in {"APPLIED", "FALLBACK", "SKIPPED"}
        or decision.get("user_visible") is not (state == "APPLIED")
        or decision.get("incumbent_fallback") is not (state != "APPLIED")
        or decision.get("production_cutover") is not False
        or not isinstance(decision.get("provider_called"), bool)
    ):
        raise _invalid("cutover_decision")
    _hash_ref(decision.get("cutover_receipt_hash"))
    _hash_ref(decision.get("selected_policy_hash"))
    for name in (
        "source_package_id",
        "source_package_hash",
        "result_package_id",
        "result_package_hash",
        "policy_decision",
    ):
        _required_text(decision.get(name))
    reason = decision.get("reason_code")
    if reason is not None:
        _required_text(reason)
    _number(decision.get("elapsed_ms"))
    decision["decision_event_hash"] = supplied_hash
    return decision


def load_cutover_authorization(
    path: Path, *, activation_bundle: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnswerSupportPolicyCutoverError(
            "CX_ANSWER_SUPPORT_POLICY_CUTOVER_UNAVAILABLE",
            "The policy cutover authorization is unavailable.",
        ) from exc
    return validate_cutover_authorization(value, activation_bundle=activation_bundle)


def validate_cutover_authorization(
    value: object, *, activation_bundle: Mapping[str, Any]
) -> dict[str, Any]:
    activation = load_and_validate_cutover_sources(
        activation_bundle=activation_bundle, authorization=value
    )
    return activation["authorization"]


def load_and_validate_cutover_sources(
    *, activation_bundle: Mapping[str, Any], authorization: object
) -> dict[str, Any]:
    bundle = load_controlled_activation_bundle_from_mapping(activation_bundle)
    normalized = dict(_mapping(authorization, "authorization"))
    supplied_hash = _hash_ref(normalized.pop("authorization_hash", None))
    expected_fields = {
        "authorization_schema_version",
        "status",
        "decision_receipt",
        "activation_bundle_hash",
        "selected_policy_hash",
        "provider_binding_hash",
        "fallback_policy",
        "rollback_policy",
        "safety",
    }
    if set(normalized) != expected_fields:
        raise _invalid("authorization_fields")
    if semantic_sha256_hash_ref(normalized) != supplied_hash:
        raise _integrity("authorization")
    receipt = dict(_mapping(normalized.get("decision_receipt"), "decision_receipt"))
    receipt_hash = _hash_ref(receipt.pop("receipt_hash", None))
    if semantic_sha256_hash_ref(receipt) != receipt_hash:
        raise _integrity("decision_receipt")
    receipt["receipt_hash"] = receipt_hash
    provider_binding = bundle["readiness_manifest"]["candidate_profile"][
        "provider_binding"
    ]
    if (
        normalized.get("authorization_schema_version")
        != CUTOVER_AUTHORIZATION_SCHEMA_VERSION
        or normalized.get("status") != "APPROVED_FOR_CONTROLLED_CUTOVER"
        or receipt.get("status") != "PASS"
        or receipt.get("decision")
        != "CONTROLLED_ANSWER_SUPPORT_POLICY_CUTOVER_APPROVED"
        or receipt.get("decision_status") != "APPROVED_NOT_EXECUTED"
        or receipt.get("approved_scope")
        != "CONTROLLED_ANSWER_SUPPORT_USER_VISIBLE_POLICY_CUTOVER"
        or receipt.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_CUTOVER_AND_ROLLBACK_ACCEPTANCE"
        or receipt.get("policy_cutover_approved") is not True
        or receipt.get("policy_cutover_executed") is not False
        or receipt.get("user_visible_policy_change_approved") is not True
        or receipt.get("user_visible_policy_change_executed") is not False
        or receipt.get("production_cutover_permitted") is not False
        or normalized.get("activation_bundle_hash") != bundle["bundle_hash"]
        or normalized.get("activation_bundle_hash")
        != receipt.get("activation_bundle_hash")
        or normalized.get("selected_policy_hash")
        != bundle["selected_policy"]["policy_hash"]
        or normalized.get("selected_policy_hash") != receipt.get("selected_policy_hash")
        or normalized.get("provider_binding_hash")
        != semantic_sha256_hash_ref(provider_binding)
        or normalized.get("fallback_policy") != CURRENT_POLICY
        or dict(_mapping(normalized.get("rollback_policy"), "rollback_policy"))
        != _ROLLBACK_POLICY
        or dict(_mapping(normalized.get("safety"), "safety")) != _SAFETY
    ):
        raise _integrity("authorization_binding")
    normalized["decision_receipt"] = receipt
    normalized["authorization_hash"] = supplied_hash
    return {"authorization": normalized, "activation_bundle": bundle}


def build_cutover_state(
    *, authorization_hash: str, cutover_state: str, reason_code: str
) -> dict[str, Any]:
    state = {
        "state_schema_version": CUTOVER_STATE_SCHEMA_VERSION,
        "cutover_receipt_hash": _hash_ref(authorization_hash),
        "cutover_state": cutover_state,
        "reason_code": _required_text(reason_code),
        "fallback_policy": CURRENT_POLICY,
        "user_visible": cutover_state == ACTIVE,
        "production_cutover": False,
    }
    state["state_hash"] = semantic_sha256_hash_ref(state)
    return validate_cutover_state(state)


def validate_cutover_state(value: object) -> dict[str, Any]:
    state = dict(_mapping(value, "cutover_state"))
    supplied_hash = _hash_ref(state.pop("state_hash", None))
    expected = {
        "state_schema_version",
        "cutover_receipt_hash",
        "cutover_state",
        "reason_code",
        "fallback_policy",
        "user_visible",
        "production_cutover",
    }
    if (
        set(state) != expected
        or semantic_sha256_hash_ref(state) != supplied_hash
        or state.get("state_schema_version") != CUTOVER_STATE_SCHEMA_VERSION
        or state.get("cutover_state")
        not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
        or state.get("fallback_policy") != CURRENT_POLICY
        or state.get("user_visible") is not (state.get("cutover_state") == ACTIVE)
        or state.get("production_cutover") is not False
    ):
        raise _invalid("cutover_state")
    _hash_ref(state.get("cutover_receipt_hash"))
    _required_text(state.get("reason_code"))
    state["state_hash"] = supplied_hash
    return state


def load_controlled_activation_bundle_from_mapping(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    from nex_cx.retrieval_answer_support_controlled_activation import (
        validate_controlled_activation_bundle,
    )

    return validate_controlled_activation_bundle(value)


def _apply_authoritative_decision(
    primary_package: Mapping[str, Any],
    *,
    outcome: Mapping[str, Any],
    authorization: Mapping[str, Any],
    activation_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(primary_package))
    decision = str(outcome["shadow_decision"])
    score = float(outcome["shadow_score"])
    threshold = float(outcome["threshold"])
    profile = activation_bundle["readiness_manifest"]["candidate_profile"]
    profile_hash = str(profile["profile_hash"]).removeprefix("sha256:")
    score_summary = dict(_mapping(result.get("score_summary"), "score_summary"))
    features = score_summary.get("confidence_features")
    if isinstance(features, Mapping):
        features = {**features, "composite_score": score}
    else:
        evidence_items = result.get("evidence_items")
        first = (
            evidence_items[0]
            if isinstance(evidence_items, list) and evidence_items
            else {}
        )
        scores = first.get("scores") if isinstance(first, Mapping) else {}
        scores = scores if isinstance(scores, Mapping) else {}
        features = {
            "feature_schema_version": "cx_retrieval_confidence_features.v1",
            "candidate_count": len(evidence_items)
            if isinstance(evidence_items, list)
            else 0,
            "reranker_score": _bounded_score(
                scores.get("rerank_score", scores.get("final_score", 0.0))
            ),
            "reranker_margin": _bounded_score(score_summary.get("score_spread", 0.0)),
            "rrf_normalized_score": _bounded_score(
                scores.get("rrf_normalized_score", 0.0)
            ),
            "channel_support": _bounded_score(scores.get("channel_support_score", 0.0)),
            "composite_score": score,
        }
    score_summary.update(
        {
            "best_score": score,
            "confidence_bucket": decision,
            "confidence_policy_id": "cx_retrieval_confidence_multisignal_v1",
            "decision_reason": (
                None if decision == "READY" else "answer_support_policy_below_threshold"
            ),
            "low_confidence_threshold": threshold,
            "confidence_feature_schema_version": (
                "cx_retrieval_confidence_features.v1"
            ),
            "confidence_features": features,
            "calibration_profile_id": profile["profile_id"],
            "calibration_profile_hash": profile_hash,
        }
    )
    retrieval_profile = dict(
        _mapping(result.get("retrieval_profile"), "retrieval_profile")
    )
    confidence_policy = dict(
        _mapping(retrieval_profile.get("confidence_policy"), "confidence_policy")
    )
    confidence_policy.update(
        {
            "policy_id": "cx_retrieval_confidence_multisignal_v1",
            "low_confidence_threshold": threshold,
            "threshold_inclusive": True,
            "no_evidence_behavior": "NO_ANSWER",
            "below_threshold_behavior": "LOW_CONFIDENCE",
            "feature_schema_version": "cx_retrieval_confidence_features.v1",
            "calibration_profile_id": profile["profile_id"],
            "calibration_profile_hash": profile_hash,
            "missing_profile_behavior": "LOW_CONFIDENCE",
        }
    )
    quality_policy = dict(
        _mapping(retrieval_profile.get("quality_policy"), "quality_policy")
    )
    quality_policy["low_confidence_threshold"] = threshold
    retrieval_profile.update(
        {"confidence_policy": confidence_policy, "quality_policy": quality_policy}
    )
    source_hash = str(result.get("package_hash"))
    cutover_hash = semantic_sha256_hash_ref(
        {
            "source_package_hash": source_hash,
            "authorization_hash": authorization["authorization_hash"],
            "outcome_hash": outcome["outcome_hash"],
            "decision": decision,
        }
    ).removeprefix("sha256:")
    result.update(
        {
            "retrieval_package_id": str(
                uuid5(NAMESPACE_URL, f"cx-hybrid-retrieval:{cutover_hash}")
            ),
            "package_hash": cutover_hash,
            "status": decision,
            "retrieval_profile": retrieval_profile,
            "score_summary": score_summary,
            "no_answer_reason": (
                None if decision == "READY" else "answer_support_policy_below_threshold"
            ),
        }
    )
    return result


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


def _numbers(value: object) -> list[float]:
    if not isinstance(value, list):
        raise _invalid("latency_samples")
    return [_number(item) for item in value]


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise _invalid("number")
    return float(value)


def _bounded_score(value: object) -> float:
    if value is None:
        return 0.0
    number = _number(value)
    return min(number, 1.0)


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(float(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]), 6)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


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


def _invalid(detail: str) -> AnswerSupportPolicyCutoverError:
    return AnswerSupportPolicyCutoverError(
        "CX_ANSWER_SUPPORT_POLICY_CUTOVER_INVALID", detail
    )


def _integrity(detail: str) -> AnswerSupportPolicyCutoverError:
    return AnswerSupportPolicyCutoverError(
        "CX_ANSWER_SUPPORT_POLICY_CUTOVER_INTEGRITY", detail
    )
