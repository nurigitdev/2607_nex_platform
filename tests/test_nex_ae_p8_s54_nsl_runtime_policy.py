from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import pytest
from nex_ae_api.nsl_runtime_policy import (
    GOVERNED_WRITE_POLICY_ID,
    GOVERNED_WRITE_POLICY_VERSION,
    PlatformRuntimePolicyAdapter,
    PlatformRuntimePolicyError,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

HASH = "sha256:" + "a" * 64
_MISSING = object()


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class WritePolicyRequest:
    tenant_id: str
    subject_id: str
    action: str
    tool_id: str
    risk_level: object
    business_operation_id: str
    write_node_id: str
    write_intent_hash: str


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    policy_id: str
    policy_version: str
    effect: PolicyEffect
    tenant_id: str
    subject_id: str
    action: str
    tool_id: str
    risk_level: object
    business_operation_id: str
    write_node_id: str
    write_intent_hash: str
    evidence_ref: str
    evaluated_at: datetime
    expires_at: datetime

    def matches(self, request: WritePolicyRequest) -> bool:
        return all(
            getattr(self, field) == getattr(request, field)
            for field in (
                "tenant_id",
                "subject_id",
                "action",
                "tool_id",
                "risk_level",
                "business_operation_id",
                "write_node_id",
                "write_intent_hash",
            )
        )


@runtime_checkable
class RuntimePolicyPort(Protocol):
    def authorize_write(self, request: WritePolicyRequest) -> PolicyDecision: ...


class Source:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[WritePolicyRequest] = []

    def resolve(self, request: WritePolicyRequest) -> Any:
        self.calls.append(request)
        if isinstance(self.value, Exception):
            raise self.value
        return copy.deepcopy(self.value)


def _request() -> WritePolicyRequest:
    return WritePolicyRequest(
        tenant_id="tenant-p8-s54",
        subject_id="employee-1004",
        action="WRITE",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        risk_level=object(),
        business_operation_id="business-operation-p8-s54",
        write_node_id="write-voucher-draft",
        write_intent_hash="sha256:" + "b" * 64,
    )


def _authorization() -> dict[str, Any]:
    return {
        "tenant_id": "tenant-p8-s54",
        "business_operation_id": "business-operation-p8-s54",
        "oa_decision_ref": "oa-authz:p8-s54",
        "oa_allowed": True,
        "protected_operation": {
            "tenant_id": "tenant-p8-s54",
            "agent_execution_id": "agent-execution-p8-s54",
            "executable_step_id": "agent-step-p8-s54",
            "business_operation_id": "business-operation-p8-s54",
            "actor_ref": "employee-1004",
            "agent_ref": "ia-1004",
            "org_scope_refs": ["org:finance"],
            "project_ref": "project:p8-s54",
            "resource_refs": ["voucher:draft"],
            "capability": "WRITE",
            "operation_class": "CREATE",
            "data_classification": "CONFIDENTIAL",
            "typed_parameters": {"voucher_type": "GENERAL"},
            "business_object_type": "VOUCHER_DRAFT",
            "operation_fingerprint": "sha256:" + "c" * 64,
        },
        "operation_trust_decision": {
            "decision": "ALLOW",
            "decision_mode": "RULE_EVALUATED",
            "assurance_level": "HIGH",
            "operation_fingerprint": "sha256:" + "c" * 64,
            "rule_set_ref": "policy:finance-write",
            "rule_set_version": "7",
            "facts_hash": "sha256:" + "d" * 64,
            "proof_ref": "trust-proof:p8-s54",
            "reason_code": None,
            "decision_hash": "sha256:" + "e" * 64,
            "evaluated_at": "2026-10-22T10:00:00Z",
            "expires_at": "2026-10-22T10:05:00Z",
        },
        "required_assurance_level": "HIGH",
    }


def _public_api(
    *,
    decision_type: object = PolicyDecision,
    request_type: object = WritePolicyRequest,
    effect_type: object = PolicyEffect,
) -> NslV02PublicApiAdapter:
    return NslV02PublicApiAdapter(
        approval_request=object,
        approval_evidence=object,
        approval_suspension_coordinator=object,
        approval_resume_coordinator=object,
        resume_token=object,
        checkpoint_port=object,
        resume_checkpoint_port=object,
        idempotency_coordinator=object,
        idempotency_evidence_port=object,
        idempotency_evidence_record=object,
        idempotency_reservation=object,
        idempotency_disposition=object,
        write_execution_port=object,
        post_write_verification_port=object,
        runtime_policy_port=RuntimePolicyPort,
        write_policy_request=request_type,
        policy_decision=decision_type,
        policy_effect=effect_type,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _adapter(value: object = _MISSING, **api: object):
    source = Source(_authorization() if value is _MISSING else value)
    return (
        PlatformRuntimePolicyAdapter(
            authorization_source=source,
            public_api=_public_api(**api),
        ),
        source,
    )


def test_adapter_projects_exact_current_platform_authority_to_nsl_policy() -> None:
    request = _request()
    adapter, source = _adapter()

    decision = adapter.authorize_write(request)

    assert isinstance(adapter, RuntimePolicyPort)
    assert source.calls == [request]
    assert decision.effect is PolicyEffect.ALLOW
    assert decision.matches(request)
    assert decision.decision_id == "sha256:" + "e" * 64
    assert decision.policy_id == "policy:finance-write"
    assert decision.policy_version == "7"
    assert decision.evidence_ref == "oa-authz:p8-s54"
    assert decision.evaluated_at == datetime(2026, 10, 22, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("tenant_id",), "other-tenant"),
        (("business_operation_id",), "other-operation"),
        (("protected_operation", "tenant_id"), "other-tenant"),
        (("protected_operation", "business_operation_id"), "other-operation"),
        (("protected_operation", "capability"), "READ"),
        (("protected_operation", "actor_ref"), "employee-other"),
        (("operation_trust_decision", "decision"), "DENY"),
        (("operation_trust_decision", "decision"), "REVIEW"),
        (("operation_trust_decision", "decision"), "INDETERMINATE"),
        (("operation_trust_decision", "operation_fingerprint"), "other"),
        (("operation_trust_decision", "assurance_level"), "STANDARD"),
        (("operation_trust_decision", "decision_mode"), "DUMMY_ALWAYS_ALLOW"),
    ),
)
def test_every_required_denial_blocks_even_when_other_controls_allow(
    path: tuple[str, ...], value: object
) -> None:
    authorization = _authorization()
    target = authorization
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    adapter, _ = _adapter(authorization)

    decision = adapter.authorize_write(_request())

    assert decision.effect is PolicyEffect.DENY


def test_none_assurance_permits_dummy_mode_and_uses_safe_fallback_metadata() -> None:
    authorization = _authorization()
    authorization["required_assurance_level"] = "NONE"
    descriptor = authorization["protected_operation"]
    descriptor.pop("actor_ref")
    descriptor.pop("agent_ref")
    descriptor.pop("org_scope_refs")
    descriptor.pop("resource_refs")
    descriptor.pop("data_classification")
    trust = authorization["operation_trust_decision"]
    trust["decision_mode"] = "DUMMY_ALWAYS_ALLOW"
    trust.pop("rule_set_ref")
    trust.pop("rule_set_version")
    trust.pop("proof_ref")
    trust.pop("reason_code")
    adapter, _ = _adapter(authorization)

    decision = adapter.authorize_write(_request())

    assert decision.effect is PolicyEffect.ALLOW
    assert decision.policy_id == GOVERNED_WRITE_POLICY_ID
    assert decision.policy_version == GOVERNED_WRITE_POLICY_VERSION
    assert decision.evidence_ref == authorization["oa_decision_ref"]


@pytest.mark.parametrize(
    "mutator",
    (
        None,
        lambda value: value.pop("oa_decision_ref"),
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.__setitem__("oa_allowed", "yes"),
        lambda value: value.__setitem__("oa_allowed", False),
        lambda value: value.__setitem__("protected_operation", []),
        lambda value: value["protected_operation"].pop("project_ref"),
        lambda value: value["protected_operation"].__setitem__("unexpected", True),
        lambda value: value["protected_operation"].__setitem__("typed_parameters", []),
        lambda value: value["protected_operation"].__setitem__("actor_ref", ""),
        lambda value: value["protected_operation"].__setitem__("org_scope_refs", [""]),
        lambda value: value.__setitem__("operation_trust_decision", []),
        lambda value: value["operation_trust_decision"].pop("decision_hash"),
        lambda value: value["operation_trust_decision"].__setitem__("unexpected", True),
        lambda value: value["operation_trust_decision"].__setitem__("decision", "MAYBE"),
        lambda value: value["operation_trust_decision"].__setitem__("assurance_level", "MAX"),
        lambda value: value.__setitem__("required_assurance_level", "MAX"),
        lambda value: value["operation_trust_decision"].__setitem__("evaluated_at", ""),
        lambda value: value["operation_trust_decision"].__setitem__("evaluated_at", "bad"),
        lambda value: value["operation_trust_decision"].__setitem__("evaluated_at", "2026-10-22T10:00:00"),
        lambda value: value["operation_trust_decision"].__setitem__("expires_at", "2026-10-22T10:00:00Z"),
    ),
)
def test_malformed_authority_fails_closed(mutator) -> None:
    authorization = _authorization()
    if mutator is None:
        value = None
    else:
        mutator(authorization)
        value = authorization
    adapter, _ = _adapter(value)

    with pytest.raises(PlatformRuntimePolicyError) as caught:
        adapter.authorize_write(_request())
    assert caught.value.error_code == "ae.nsl_runtime_policy_invalid"


def test_invalid_request_and_authority_failure_are_typed_and_sanitized() -> None:
    adapter, _ = _adapter()
    with pytest.raises(PlatformRuntimePolicyError, match="request type"):
        adapter.authorize_write(object())

    unavailable, _ = _adapter(RuntimeError("secret upstream detail"))
    with pytest.raises(PlatformRuntimePolicyError) as caught:
        unavailable.authorize_write(_request())
    assert caught.value.error_code == "ae.nsl_runtime_policy_authority_unavailable"
    assert "secret" not in str(caught.value)

    typed = PlatformRuntimePolicyError("typed", "typed authority failure")
    passthrough, _ = _adapter(typed)
    with pytest.raises(PlatformRuntimePolicyError) as preserved:
        passthrough.authorize_write(_request())
    assert preserved.value is typed


def test_constructor_and_incompatible_public_types_fail_closed() -> None:
    with pytest.raises(PlatformRuntimePolicyError):
        PlatformRuntimePolicyAdapter(
            authorization_source=Source(_authorization()),
            public_api=object(),  # type: ignore[arg-type]
        )

    for field in (
        "runtime_policy_port",
        "write_policy_request",
        "policy_decision",
        "policy_effect",
    ):
        public_api = _public_api()
        object.__setattr__(public_api, field, None)
        with pytest.raises(PlatformRuntimePolicyError, match=field):
            PlatformRuntimePolicyAdapter(
                authorization_source=Source(_authorization()),
                public_api=public_api,
            )

    public_api = _public_api()
    object.__setattr__(public_api, "write_policy_request", object())
    with pytest.raises(PlatformRuntimePolicyError, match="write_policy_request"):
        PlatformRuntimePolicyAdapter(
            authorization_source=Source(_authorization()),
            public_api=public_api,
        )

    incompatible, _ = _adapter(decision_type=object)
    with pytest.raises(PlatformRuntimePolicyError, match="incompatible"):
        incompatible.authorize_write(_request())


def test_policy_decision_that_changes_binding_is_rejected() -> None:
    class MutatingDecision(PolicyDecision):
        def matches(self, request: WritePolicyRequest) -> bool:
            return False

    adapter, _ = _adapter(decision_type=MutatingDecision)

    with pytest.raises(PlatformRuntimePolicyError, match="changed"):
        adapter.authorize_write(_request())

    class BrokenDecision(PolicyDecision):
        def matches(self, request: WritePolicyRequest) -> bool:
            raise RuntimeError("broken public type")

    broken, _ = _adapter(decision_type=BrokenDecision)
    with pytest.raises(PlatformRuntimePolicyError, match="compatibility"):
        broken.authorize_write(_request())


def test_error_string_is_safe_detail() -> None:
    assert str(PlatformRuntimePolicyError("code", "safe detail")) == "safe detail"
