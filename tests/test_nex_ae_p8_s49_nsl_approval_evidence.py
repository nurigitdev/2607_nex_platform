from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import SimpleNamespace
from typing import Any

import pytest
from nex_ae_api.nsl_approval_evidence import (
    NslApprovalEvidenceProjectionError,
    PlatformApprovalEvidenceVerifier,
    project_nsl_approval_evidence,
)
from nex_ae_api.platform_approval_evidence import build_platform_approval_evidence

HASH = "sha256:" + "a" * 64
WORK_ITEM_ID = "f36602c8-172d-4a9a-b268-18439ce6cbd5"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ApprovalEvidence:
    tenant_id: str
    execution_id: str
    business_operation_id: str
    approval_id: str
    approval_request_id: str
    skill_semantic_hash: str
    decision: Decision
    approver_id: str
    decided_at: datetime
    expires_at: datetime | None
    payload_hash: str
    write_intent_hash: str
    evidence_integrity: str


class Request:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def to_data(self) -> dict[str, object]:
        return dict(self._value)


def _platform(*, decision: str = "APPROVE") -> dict[str, Any]:
    terminal = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}[decision]
    request = {
        "tenant_id": "tenant-p8-s49",
        "execution_id": "nsl-execution-p8-s49",
        "business_operation_id": "business-operation-p8-s49",
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": "approval-request-p8-s49",
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": "sha256:" + "b" * 64,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": "sha256:" + "c" * 64,
        "write_intent_hash": "write-intent-p8-s49",
        "risk_level": "R3",
        "message": "Create voucher draft.",
        "expires_at": "2026-10-23T12:00:00Z",
        "display_safe_summary": {"line_count": 2},
        "protected_payload_ref": "snapshot://private/p8-s49",
        "data_classification": "CONFIDENTIAL",
    }
    protected_ref = "ae://nsl-approval-requests/ab/" + "d" * 64 + ".json"
    agent_execution_id = "f15919c8-3cc8-48ee-a5cb-39bbc6060384"
    executable_step_id = "2e5f28cc-2c3c-44af-aa1f-426566174784"
    wait = {
        "tenant_id": request["tenant_id"],
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "wait_type": "NSL_APPROVAL",
        "external_ref": request["approval_request_id"],
        "state": "PENDING",
        "nsl_execution_id": request["execution_id"],
        "business_operation_id": request["business_operation_id"],
        "approval_request_id": request["approval_request_id"],
        "checkpoint_version": 7,
    }
    protected = {
        "tenant_id": request["tenant_id"],
        "approval_request_id": request["approval_request_id"],
        "nsl_execution_id": request["execution_id"],
        "business_operation_id": request["business_operation_id"],
        "protected_request_ref": protected_ref,
        "approval_request_hash": "sha256:" + "e" * 64,
    }
    work_item = {
        "tenant_id": request["tenant_id"],
        "approval_work_item_id": WORK_ITEM_ID,
        "approval_domain": "NSL_WRITE",
        "approval_provider_type": "NSL",
        "source_ref": request["approval_request_id"],
        "approval_target_ref": request["approval_request_id"],
        "semantic_hash": protected["approval_request_hash"],
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "nsl_execution_id": request["execution_id"],
        "business_operation_id": request["business_operation_id"],
        "approval_request_id": request["approval_request_id"],
        "protected_request_ref": protected_ref,
        "state": terminal,
        "expires_at": request["expires_at"],
    }
    approval_decision = {
        "tenant_id": request["tenant_id"],
        "decision_id": "d54ad674-672e-43bd-a249-ea5acd3be245",
        "approval_work_item_id": WORK_ITEM_ID,
        "decision": decision,
        "decided_by": "employee-1004",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-authz:" + "f" * 64,
        "authorization_revision_hash": "sha256:" + "f" * 64,
        "authorization_checked_at": "2026-10-22T11:59:00Z",
        "decided_at": "2026-10-22T12:00:00Z",
    }
    return build_platform_approval_evidence(
        approval_request=Request(request),
        protected_request=protected,
        wait_registration=wait,
        approval_work_item=work_item,
        approval_decision=approval_decision,
        created_at=datetime(2026, 10, 22, 12, 1, tzinfo=UTC),
    )


def _authority(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_item": {
            "tenant_id": evidence["tenant_id"],
            "approval_work_item_id": evidence["approval_work_item_ref"],
            "approval_domain": "NSL_WRITE",
            "approval_provider_type": "NSL",
            "source_ref": evidence["approval_request_id"],
            "approval_target_ref": evidence["approval_request_id"],
            "agent_execution_id": evidence["agent_execution_id"],
            "executable_step_id": evidence["executable_step_id"],
            "nsl_execution_id": evidence["nsl_execution_id"],
            "business_operation_id": evidence["business_operation_id"],
            "approval_request_id": evidence["approval_request_id"],
            "protected_request_ref": evidence["protected_request_ref"],
            "state": {"APPROVE": "APPROVED", "REJECT": "REJECTED"}[
                evidence["decision"]
            ],
        },
        "decision": {
            "tenant_id": evidence["tenant_id"],
            "approval_work_item_id": evidence["approval_work_item_ref"],
            "decision": evidence["decision"],
            "decided_by": evidence["approver_id"],
            "decided_at": evidence["decided_at"],
            "oa_decision_ref": evidence["oa_decision_ref"],
            "authorized_by_oa": True,
        },
    }


class EvidenceSource:
    def __init__(self, evidence: dict[str, Any] | None) -> None:
        self.evidence = evidence

    def get(self, **_values: object) -> dict[str, Any] | None:
        return copy.deepcopy(self.evidence)


class WcSource:
    def __init__(self, authority: dict[str, Any]) -> None:
        self.authority = authority

    def resolve(self, **_values: object) -> dict[str, Any]:
        return copy.deepcopy(self.authority)


class OaSource:
    def __init__(self, authorization: object | None = None) -> None:
        self.authorization = authorization or {
            "active": True,
            "scopes": ["approval:decide"],
            "revision_hash": "f" * 64,
        }

    def effective_authorization(self, **_values: object) -> Any:
        return copy.deepcopy(self.authorization)


def _verifier(
    evidence: dict[str, Any],
    *,
    authority: dict[str, Any] | None = None,
    authorization: object | None = None,
) -> PlatformApprovalEvidenceVerifier:
    return PlatformApprovalEvidenceVerifier(
        evidence_source=EvidenceSource(evidence),
        wc_source=WcSource(authority or _authority(evidence)),
        oa_source=OaSource(authorization),
    )


@pytest.mark.parametrize(
    ("platform_decision", "nsl_decision"),
    (("APPROVE", Decision.APPROVED), ("REJECT", Decision.REJECTED)),
)
def test_projection_uses_actual_public_type_shape_without_binding_override(
    platform_decision: str, nsl_decision: Decision
) -> None:
    evidence = _platform(decision=platform_decision)

    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )

    assert isinstance(projected, ApprovalEvidence)
    assert projected.decision is nsl_decision
    assert projected.execution_id == evidence["nsl_execution_id"]
    assert projected.business_operation_id == evidence["business_operation_id"]
    assert projected.payload_hash == evidence["payload_hash"]
    assert projected.write_intent_hash == evidence["write_intent_hash"]
    assert _verifier(evidence).verify(projected) is True


def test_projection_rejects_incompatible_or_binding_mutating_type() -> None:
    evidence = _platform()

    with pytest.raises(NslApprovalEvidenceProjectionError):
        project_nsl_approval_evidence(evidence, approval_evidence_type=object)

    class MutatingEvidence(ApprovalEvidence):
        def __getattribute__(self, name: str) -> object:
            if name == "tenant_id":
                return "other-tenant"
            return super().__getattribute__(name)

    with pytest.raises(NslApprovalEvidenceProjectionError):
        project_nsl_approval_evidence(
            evidence, approval_evidence_type=MutatingEvidence
        )


def test_verifier_fails_closed_for_missing_or_changed_platform_evidence() -> None:
    evidence = _platform()
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )
    missing = PlatformApprovalEvidenceVerifier(
        evidence_source=EvidenceSource(None),
        wc_source=WcSource(_authority(evidence)),
        oa_source=OaSource(),
    )
    changed = copy.deepcopy(evidence)
    changed["approver_id"] = "employee-other"
    changed_projection = replace(projected, approver_id="employee-other")

    assert missing.verify(projected) is False
    assert _verifier(changed).verify(projected) is False
    assert _verifier(evidence).verify(changed_projection) is False
    assert _verifier(evidence).verify(object()) is False


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("work_item", "tenant_id", "other-tenant"),
        ("work_item", "state", "PENDING"),
        ("decision", "decision", "REJECT"),
        ("decision", "authorized_by_oa", False),
    ),
)
def test_verifier_rejects_changed_wc_authority(
    section: str, field: str, value: object
) -> None:
    evidence = _platform()
    authority = _authority(evidence)
    authority[section][field] = value
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )

    assert _verifier(evidence, authority=authority).verify(projected) is False


@pytest.mark.parametrize(
    "authorization",
    (
        {"active": False, "scopes": ["approval:decide"], "revision_hash": "f" * 64},
        {"active": True, "scopes": [], "revision_hash": "f" * 64},
        {"active": True, "scopes": "approval:decide", "revision_hash": "f" * 64},
        {"active": True, "scopes": ["approval:decide"], "revision_hash": "bad"},
        {
            "active": True,
            "scopes": ["approval:decide"],
            "revision_hash": "f" * 64,
            "decision_ref": "oa-other",
        },
    ),
)
def test_verifier_rejects_inactive_or_changed_oa_authority(
    authorization: dict[str, object],
) -> None:
    evidence = _platform()
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )

    assert (
        _verifier(evidence, authorization=authorization).verify(projected) is False
    )


def test_verifier_accepts_explicit_current_oa_decision_ref() -> None:
    evidence = _platform()
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )
    authorization = {
        "active": True,
        "scopes": ["approval:decide", "approval:read"],
        "revision_hash": "sha256:" + "f" * 64,
        "decision_ref": evidence["oa_decision_ref"],
    }

    assert _verifier(evidence, authorization=authorization).verify(projected) is True


def test_verifier_converts_source_failure_or_malformed_authority_to_false() -> None:
    evidence = _platform()
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )
    malformed = _verifier(evidence, authority={"work_item": {}})

    class FailingSource:
        def get(self, **_values: object) -> None:
            raise RuntimeError("unavailable")

    unavailable = PlatformApprovalEvidenceVerifier(
        evidence_source=FailingSource(),
        wc_source=WcSource(_authority(evidence)),
        oa_source=OaSource(),
    )

    assert malformed.verify(projected) is False
    assert unavailable.verify(projected) is False


def test_non_enum_decision_like_value_is_supported_by_structural_protocol() -> None:
    evidence = _platform()
    projected = project_nsl_approval_evidence(
        evidence, approval_evidence_type=ApprovalEvidence
    )
    structural = SimpleNamespace(**projected.__dict__)
    structural.decision = SimpleNamespace(value="APPROVED")

    assert _verifier(evidence).verify(structural) is True

    structural.decided_at = "not-a-datetime"
    assert _verifier(evidence).verify(structural) is False
