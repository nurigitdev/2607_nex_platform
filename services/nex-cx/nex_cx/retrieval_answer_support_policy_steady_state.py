from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import OperationalEventEmitter, OperationalEventStore, build_subject_ref
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
)

STEADY_STATE_MODE_ENV = "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_MODE"
STEADY_STATE_AUTHORIZATION_PATH_ENV = (
    "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_AUTHORIZATION_PATH"
)
STEADY_STATE_MODE_DISABLED = "DISABLED"
STEADY_STATE_MODE_CONTROLLED = "CONTROLLED"
STEADY_STATE_EVENT_TYPE = "cx.retrieval.answer_support_policy_steady_state"
AUTHORIZATION_SCHEMA_VERSION = (
    "cx_answer_support_policy_steady_state_authorization.v1"
)
STATE_SCHEMA_VERSION = "cx_answer_support_policy_steady_state_state.v1"
CURRENT_POLICY = "ANSWER_SUPPORT_POLICY_CUTOVER_ACTIVE"
CURRENT_OPERATIONS_MODE = "CONTROLLED_STEADY_STATE_OPERATIONS"
DEFAULT_AUTHORIZATION_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "answer_support_policy_steady_state_authorization.v1.json"
)

_TERMINAL_STATES = {ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
_PROFILE_FIELDS = {
    "profile_schema_version",
    "profile_id",
    "status",
    "current_policy",
    "current_operations_mode",
    "review_sample_interval",
    "maximum_concurrency",
    "maximum_event_scan",
    "operational_slo",
    "escalation_policy",
    "source_binding",
    "runtime_activation_permitted",
    "profile_hash",
}
_PROFILE_SOURCE_FIELDS = {
    "review_report_hash",
    "review_receipt_hash",
    "sustained_policy_hash",
    "selected_policy_hash",
}
_RECEIPT_FIELDS = {
    "approved_scope",
    "decided_at",
    "decision",
    "decision_status",
    "design_hash",
    "manifest_hash",
    "next_boundary",
    "operations_profile_hash",
    "operator_decision_hash",
    "production_cutover_permitted",
    "receipt_hash",
    "receipt_schema_version",
    "runtime_changed",
    "selected_policy_hash",
    "source_readiness_manifest_hash",
    "source_readiness_report_hash",
    "status",
    "steady_state_operations_activated",
    "steady_state_operations_approved",
}
_ROLLBACK_POLICY = {
    "cutover_terminal_state": "ROLLBACK_STATE_DOMINANT",
    "provider_failure": "IMMEDIATE_ROLLBACK_REQUIRED",
    "fallback_decision": "IMMEDIATE_ROLLBACK_REQUIRED",
    "provider_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "e2e_p95_slo_breach": "ROLLBACK_PENDING_OPERATOR_REVIEW",
    "review_cadence_reached": "OPERATOR_REVIEW_REQUIRED",
}
_SAFETY = {
    "holdout_access_permitted": False,
    "production_cutover_permitted": False,
    "permission_scope_mutation_permitted": False,
    "candidate_order_mutation_permitted": False,
    "runtime_algorithm_mutation_permitted": False,
    "rollback_contract_preserved": True,
}


class SteadyStatePolicyDelegate(Protocol):
    def apply(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]: ...

    def snapshot(self) -> Mapping[str, Any]: ...


class SteadyStateStateStore(Protocol):
    def current_state(self, authorization_hash: str) -> Mapping[str, Any] | None: ...

    def record_state(self, state: Mapping[str, Any]) -> None: ...


class AnswerSupportPolicySteadyStateError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class OperationalSteadyStateStateStore:
    emitter: OperationalEventEmitter
    store: OperationalEventStore

    def current_state(self, authorization_hash: str) -> Mapping[str, Any] | None:
        validate_hash_ref(authorization_hash)
        active: dict[str, Any] | None = None
        for event in self.store.list_events(
            service_id="nex-cx", event_type=STEADY_STATE_EVENT_TYPE, limit=100
        ):
            details = event.get("details")
            if not isinstance(details, Mapping):
                continue
            if details.get("steady_state_receipt_hash") != authorization_hash:
                continue
            normalized = validate_steady_state_state(details)
            if normalized["steady_state_state"] in _TERMINAL_STATES:
                return normalized
            active = normalized
        return active

    def record_state(self, state: Mapping[str, Any]) -> None:
        normalized = validate_steady_state_state(state)
        steady_state = normalized["steady_state_state"]
        authorization_hash = normalized["steady_state_receipt_hash"]
        self.emitter.emit(
            event_type=STEADY_STATE_EVENT_TYPE,
            severity="INFO" if steady_state == ACTIVE else "WARNING",
            message=(
                "CX answer-support steady-state operations were activated."
                if steady_state == ACTIVE
                else "CX answer-support steady-state operations fell back."
            ),
            subject_ref=build_subject_ref(
                "cx.answer_support_policy_steady_state", authorization_hash
            ),
            details=normalized,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    "cx-answer-support-policy-steady-state:"
                    f"{authorization_hash}:{steady_state}",
                )
            ),
        )


class ControlledAnswerSupportPolicySteadyState:
    def __init__(
        self,
        delegate: SteadyStatePolicyDelegate,
        *,
        authorization: Mapping[str, Any],
        state_store: SteadyStateStateStore,
        previous_state: Mapping[str, Any] | None = None,
    ) -> None:
        self.delegate = delegate
        self.authorization = validate_steady_state_authorization(authorization)
        self._state_store = state_store
        self._state = ACTIVE
        self._reason_code = "OPERATOR_APPROVED_STEADY_STATE_OPERATIONS"
        if previous_state is not None:
            restored = validate_steady_state_state(previous_state)
            self._require_state_binding(restored)
            self._state = restored["steady_state_state"]
            self._reason_code = restored["reason_code"]
        self._synchronize_delegate_state(persist=False)

    def apply(
        self,
        *,
        query_text: str,
        evidence_items: Sequence[Mapping[str, Any]],
        primary_package: Mapping[str, Any],
        access_context: CxAccessContext,
    ) -> Mapping[str, Any]:
        result = self.delegate.apply(
            query_text=query_text,
            evidence_items=evidence_items,
            primary_package=primary_package,
            access_context=access_context,
        )
        self._synchronize_delegate_state(persist=True)
        return result

    def snapshot(self) -> dict[str, Any]:
        delegate = self._synchronize_delegate_state(persist=True)
        return {
            **delegate,
            "steady_state_authorization_hash": self.authorization[
                "authorization_hash"
            ],
            "operations_profile_hash": self.authorization["operations_profile"][
                "profile_hash"
            ],
            "sustained_policy_hash": self.authorization["sustained_policy_hash"],
            "steady_state_state": self._state,
            "steady_state_reason_code": self._reason_code,
            "steady_state_operations_mode": CURRENT_OPERATIONS_MODE,
            "steady_state_operations_active": self._state == ACTIVE,
            "production_cutover": False,
        }

    def state(self) -> dict[str, Any]:
        return build_steady_state_state(
            authorization=self.authorization,
            steady_state_state=self._state,
            reason_code=self._reason_code,
        )

    def _synchronize_delegate_state(self, *, persist: bool) -> dict[str, Any]:
        snapshot = dict(self.delegate.snapshot())
        self._require_delegate_binding(snapshot)
        delegate_state = snapshot.get("cutover_state")
        if delegate_state not in _TERMINAL_STATES:
            return snapshot
        changed = self._state != delegate_state
        self._state = str(delegate_state)
        self._reason_code = str(snapshot.get("rollback_reason") or "CUTOVER_ROLLBACK")
        if persist and changed:
            self._state_store.record_state(self.state())
        return snapshot

    def _require_delegate_binding(self, snapshot: Mapping[str, Any]) -> None:
        if (
            snapshot.get("authorization_hash")
            != self.authorization["cutover_authorization_hash"]
            or snapshot.get("activation_bundle_hash")
            != self.authorization["activation_bundle_hash"]
            or snapshot.get("selected_policy_hash")
            != self.authorization["selected_policy_hash"]
            or snapshot.get("cutover_state")
            not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
        ):
            raise _binding_drift()

    def _require_state_binding(self, state: Mapping[str, Any]) -> None:
        if (
            state.get("steady_state_receipt_hash")
            != self.authorization["authorization_hash"]
            or state.get("operations_profile_hash")
            != self.authorization["operations_profile"]["profile_hash"]
            or state.get("cutover_receipt_hash")
            != self.authorization["cutover_authorization_hash"]
            or state.get("selected_policy_hash")
            != self.authorization["selected_policy_hash"]
        ):
            raise _binding_drift()


def build_installed_answer_support_policy_steady_state(
    *,
    environ: Mapping[str, str],
    delegate: SteadyStatePolicyDelegate | None,
    state_store: SteadyStateStateStore,
) -> ControlledAnswerSupportPolicySteadyState | None:
    mode = str(
        environ.get(STEADY_STATE_MODE_ENV, STEADY_STATE_MODE_DISABLED)
    ).strip().upper()
    if mode == STEADY_STATE_MODE_DISABLED:
        return None
    if mode != STEADY_STATE_MODE_CONTROLLED:
        raise _invalid("steady_state_mode")
    if delegate is None:
        raise _binding_drift()
    authorization = load_steady_state_authorization(
        Path(
            str(
                environ.get(
                    STEADY_STATE_AUTHORIZATION_PATH_ENV,
                    DEFAULT_AUTHORIZATION_PATH,
                )
            )
        )
    )
    previous = state_store.current_state(authorization["authorization_hash"])
    runtime = ControlledAnswerSupportPolicySteadyState(
        delegate,
        authorization=authorization,
        state_store=state_store,
        previous_state=previous,
    )
    if previous is None:
        state_store.record_state(runtime.state())
    return runtime


def load_steady_state_authorization(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnswerSupportPolicySteadyStateError(
            "CX_ANSWER_SUPPORT_STEADY_STATE_AUTHORIZATION_UNAVAILABLE",
            "The steady-state operations authorization is unavailable.",
        ) from exc
    return validate_steady_state_authorization(value)


def validate_steady_state_authorization(value: object) -> dict[str, Any]:
    authorization = dict(_mapping(value, "authorization"))
    supplied_hash = _hash_ref(authorization.pop("authorization_hash", None))
    expected = {
        "authorization_schema_version",
        "status",
        "decision_receipt",
        "operations_profile",
        "cutover_authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_policy_hash",
        "fallback_policy",
        "rollback_policy",
        "safety",
    }
    if set(authorization) != expected:
        raise _invalid("authorization_fields")
    if semantic_sha256_hash_ref(authorization) != supplied_hash:
        raise _integrity("authorization")

    receipt = dict(
        _exact(authorization.get("decision_receipt"), _RECEIPT_FIELDS, "receipt")
    )
    receipt_hash = _hash_ref(receipt.pop("receipt_hash", None))
    if semantic_sha256_hash_ref(receipt) != receipt_hash:
        raise _integrity("decision_receipt")
    receipt["receipt_hash"] = receipt_hash

    profile = dict(
        _exact(authorization.get("operations_profile"), _PROFILE_FIELDS, "profile")
    )
    profile_hash = _hash_ref(profile.pop("profile_hash", None))
    source = _exact(
        profile.get("source_binding"), _PROFILE_SOURCE_FIELDS, "profile_source"
    )
    if semantic_sha256_hash_ref(profile) != profile_hash:
        raise _integrity("operations_profile")
    profile["profile_hash"] = profile_hash

    if (
        authorization.get("authorization_schema_version")
        != AUTHORIZATION_SCHEMA_VERSION
        or authorization.get("status")
        != "APPROVED_FOR_CONTROLLED_STEADY_STATE_OPERATIONS"
        or receipt.get("receipt_schema_version")
        != "cx_answer_support_policy_steady_state_operator_decision_receipt.v1"
        or receipt.get("status") != "PASS"
        or receipt.get("decision")
        != "CONTROLLED_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_APPROVED"
        or receipt.get("decision_status") != "APPROVED_NOT_EXECUTED"
        or receipt.get("approved_scope")
        != "CONTROLLED_ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS"
        or receipt.get("next_boundary")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_"
        "ACTIVATION_AND_ROLLBACK_ACCEPTANCE"
        or receipt.get("steady_state_operations_approved") is not True
        or receipt.get("steady_state_operations_activated") is not False
        or receipt.get("runtime_changed") is not False
        or receipt.get("production_cutover_permitted") is not False
        or receipt.get("operations_profile_hash") != profile_hash
        or receipt.get("selected_policy_hash")
        != authorization.get("selected_policy_hash")
        or profile.get("profile_schema_version")
        != "cx_answer_support_policy_steady_state_operations_profile.v1"
        or profile.get("status") != "READY_FOR_OPERATOR_DECISION"
        or profile.get("current_policy") != CURRENT_POLICY
        or profile.get("current_operations_mode") != "CONTROLLED_SUSTAINED_OPERATIONS"
        or profile.get("review_sample_interval") != 12
        or profile.get("maximum_concurrency") != 4
        or profile.get("maximum_event_scan") != 1000
        or profile.get("runtime_activation_permitted") is not False
        or source.get("selected_policy_hash")
        != authorization.get("selected_policy_hash")
        or source.get("sustained_policy_hash")
        != authorization.get("sustained_policy_hash")
        or dict(_mapping(authorization.get("rollback_policy"), "rollback_policy"))
        != _ROLLBACK_POLICY
        or dict(_mapping(authorization.get("safety"), "safety")) != _SAFETY
        or authorization.get("fallback_policy")
        != "CURRENT_ANSWER_SUPPORT_POLICY_FALLBACK"
    ):
        raise _integrity("authorization_binding")
    for name in (
        "cutover_authorization_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "sustained_policy_hash",
    ):
        _hash_ref(authorization.get(name))
    authorization["decision_receipt"] = receipt
    authorization["operations_profile"] = profile
    authorization["authorization_hash"] = supplied_hash
    return authorization


def build_steady_state_state(
    *,
    authorization: Mapping[str, Any],
    steady_state_state: str,
    reason_code: str,
) -> dict[str, Any]:
    normalized = validate_steady_state_authorization(authorization)
    state = {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "steady_state_receipt_hash": normalized["authorization_hash"],
        "operations_profile_hash": normalized["operations_profile"]["profile_hash"],
        "cutover_receipt_hash": normalized["cutover_authorization_hash"],
        "activation_bundle_hash": normalized["activation_bundle_hash"],
        "selected_policy_hash": normalized["selected_policy_hash"],
        "steady_state_state": steady_state_state,
        "reason_code": _required_text(reason_code),
        "current_policy": CURRENT_POLICY,
        "current_operations_mode": CURRENT_OPERATIONS_MODE,
        "production_cutover": False,
    }
    state["state_hash"] = semantic_sha256_hash_ref(state)
    return validate_steady_state_state(state)


def validate_steady_state_state(value: object) -> dict[str, Any]:
    state = dict(_mapping(value, "steady_state_state"))
    supplied_hash = _hash_ref(state.pop("state_hash", None))
    expected = {
        "state_schema_version",
        "steady_state_receipt_hash",
        "operations_profile_hash",
        "cutover_receipt_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
        "steady_state_state",
        "reason_code",
        "current_policy",
        "current_operations_mode",
        "production_cutover",
    }
    if (
        set(state) != expected
        or semantic_sha256_hash_ref(state) != supplied_hash
        or state.get("state_schema_version") != STATE_SCHEMA_VERSION
        or state.get("steady_state_state")
        not in {ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW}
        or state.get("current_policy") != CURRENT_POLICY
        or state.get("current_operations_mode") != CURRENT_OPERATIONS_MODE
        or state.get("production_cutover") is not False
    ):
        raise _invalid("steady_state_state")
    for name in (
        "steady_state_receipt_hash",
        "operations_profile_hash",
        "cutover_receipt_hash",
        "activation_bundle_hash",
        "selected_policy_hash",
    ):
        _hash_ref(state.get(name))
    _required_text(state.get("reason_code"))
    state["state_hash"] = supplied_hash
    return state


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("text")
    return value.strip()


def _hash_ref(value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid("hash") from exc


def _binding_drift() -> AnswerSupportPolicySteadyStateError:
    return AnswerSupportPolicySteadyStateError(
        "CX_ANSWER_SUPPORT_STEADY_STATE_BINDING_DRIFT",
        "The installed steady-state operations binding drifted.",
    )


def _invalid(name: str) -> AnswerSupportPolicySteadyStateError:
    return AnswerSupportPolicySteadyStateError(
        "CX_ANSWER_SUPPORT_STEADY_STATE_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> AnswerSupportPolicySteadyStateError:
    return AnswerSupportPolicySteadyStateError(
        "CX_ANSWER_SUPPORT_STEADY_STATE_INTEGRITY", f"{name} integrity failed"
    )
