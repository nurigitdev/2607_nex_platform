from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from nex_ae_api.platform_approval_evidence import (
    PlatformApprovalEvidenceError,
    build_platform_approval_evidence,
)
from nex_eos import (
    EOS_APPROVAL_DOMAINS,
    EosApprovalTransitionError,
    EosBusinessApprovalTransitionService,
    deterministic_business_formal_work_item_id,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.approvals import APPROVAL_DOMAINS, APPROVAL_PROVIDERS

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
TENANT = "tenant-p8-s75"
INSTANCE_ID = "75000000-0000-4000-8000-000000000075"
STAGE_ID = "75000000-0000-4000-8001-000000000075"
WORK_ITEM_ID = deterministic_business_formal_work_item_id(
    tenant_id=TENANT,
    approval_stage_id=STAGE_ID,
)


class _Snapshot:
    def __init__(self, value: dict[str, Any]) -> None:
        self._value = value

    def to_data(self) -> dict[str, Any]:
        return deepcopy(self._value)


class _InstanceSource:
    def __init__(self, instance: dict[str, Any]) -> None:
        self._instance = instance

    def get_instance(self, *, tenant_id: str, approval_instance_id: str):
        if tenant_id == TENANT and approval_instance_id == INSTANCE_ID:
            return deepcopy(self._instance)
        return None


class _TransitionSink:
    def __init__(self) -> None:
        self.values: list[Any] = []

    def apply_decision(self, value):
        self.values.append(value)
        return {"outcome": "ADMITTED"}


def _formal_instance() -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "state": "PENDING",
        "active_stage_order": 1,
        "business_operation_id": "business-operation-p8-s75",
        "protected_operation_ref": "eos:business-operation:p8-s75",
        "org_unit_ref": {"type": "eos.org-unit", "id": "finance-team"},
        "project_ref": {"type": "eos.project", "id": "project-p8-s75"},
        "stages": [
            {
                "approval_stage_id": STAGE_ID,
                "stage_order": 1,
                "position_type": "TEAM_LEAD",
                "state": "ACTIVE",
            }
        ],
    }


def _formal_envelope(*, domain: str = "BUSINESS_FORMAL"):
    provider = APPROVAL_PROVIDERS[domain]
    decided_at = (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    item = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": TENANT,
        "approval_work_item_id": WORK_ITEM_ID,
        "approval_domain": domain,
        "source_ref": f"eos.approval-stage:{STAGE_ID}",
        "semantic_hash": semantic_sha256_hash_ref({"stage": STAGE_ID}),
        "title": "P8-S75 business approval",
        "display_safe_summary": "Dual approval separation acceptance.",
        "approval_provider_type": provider,
        "approval_target_ref": f"eos.approval-stage:{STAGE_ID}",
        "target_approver_ref": "employee-p8-s75-approver",
        "target_role_ref": "TEAM_LEAD",
        "target_org_scope_ref": "finance-team",
        "target_project_scope_ref": "project-p8-s75",
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": "business-operation-p8-s75",
        "approval_request_id": None,
        "protected_request_ref": "eos:business-operation:p8-s75",
        "resume_target_ref": f"eos.approval-instance:{INSTANCE_ID}:stage:1",
        "state": "APPROVED",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(days=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "version": 2,
    }
    decision = {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": TENANT,
        "decision_id": "75000000-0000-4000-8002-000000000075",
        "approval_work_item_id": WORK_ITEM_ID,
        "decision": "APPROVE",
        "decided_by": item["target_approver_ref"],
        "decision_comment": "Approved for P8-S75.",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-authz:p8-s75",
        "authorization_revision_hash": semantic_sha256_hash_ref({"oa": "s75"}),
        "authorization_checked_at": decided_at,
        "decided_at": decided_at,
    }
    event = {
        "schema_version": "wc_approval_event.v1",
        "tenant_id": TENANT,
        "event_id": "75000000-0000-4000-8003-000000000075",
        "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
        "approval_work_item_id": WORK_ITEM_ID,
        "decision_id": decision["decision_id"],
        "approval_domain": "BUSINESS_FORMAL",
        "decision": "APPROVE",
        "decided_by": decision["decided_by"],
        "oa_decision_ref": decision["oa_decision_ref"],
        "occurred_at": decided_at,
        "correlation_id": "p8-s75-correlation",
        "causation_id": "p8-s75-causation",
    }
    return item, decision, event


def _nsl_material() -> dict[str, Any]:
    request_id = "approval-request-p8-s75"
    execution_id = "nsl-execution-p8-s75"
    operation_id = "business-operation-p8-s75"
    agent_execution_id = "75000000-0000-4000-8004-000000000075"
    step_id = "75000000-0000-4000-8005-000000000075"
    protected_ref = "ae://nsl-approval-requests/75/" + "a" * 64 + ".json"
    request = {
        "tenant_id": TENANT,
        "execution_id": execution_id,
        "business_operation_id": operation_id,
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": request_id,
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": semantic_sha256_hash_ref({"skill": "s75"}),
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": semantic_sha256_hash_ref({"payload": "s75"}),
        "write_intent_hash": "write-intent-p8-s75",
        "risk_level": "R3",
        "message": "Approve the exact P8-S75 write intent.",
        "expires_at": (NOW + timedelta(days=1)).isoformat().replace(
            "+00:00", "Z"
        ),
        "display_safe_summary": {"line_count": 2},
        "protected_payload_ref": "snapshot://private/p8-s75",
        "data_classification": "CONFIDENTIAL",
    }
    protected = {
        "tenant_id": TENANT,
        "approval_request_id": request_id,
        "nsl_execution_id": execution_id,
        "business_operation_id": operation_id,
        "protected_request_ref": protected_ref,
        "approval_request_hash": semantic_sha256_hash_ref({"request": "s75"}),
    }
    wait = {
        "tenant_id": TENANT,
        "agent_execution_id": agent_execution_id,
        "executable_step_id": step_id,
        "wait_type": "NSL_APPROVAL",
        "external_ref": request_id,
        "state": "PENDING",
        "nsl_execution_id": execution_id,
        "business_operation_id": operation_id,
        "approval_request_id": request_id,
        "checkpoint_version": 75,
    }
    item = {
        "tenant_id": TENANT,
        "approval_work_item_id": "75000000-0000-4000-8006-000000000075",
        "approval_domain": "NSL_WRITE",
        "approval_provider_type": "NSL",
        "source_ref": request_id,
        "approval_target_ref": request_id,
        "semantic_hash": protected["approval_request_hash"],
        "agent_execution_id": agent_execution_id,
        "executable_step_id": step_id,
        "nsl_execution_id": execution_id,
        "business_operation_id": operation_id,
        "approval_request_id": request_id,
        "protected_request_ref": protected_ref,
        "state": "APPROVED",
        "expires_at": request["expires_at"],
    }
    decided_at = (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    decision = {
        "tenant_id": TENANT,
        "decision_id": "75000000-0000-4000-8007-000000000075",
        "approval_work_item_id": item["approval_work_item_id"],
        "decision": "APPROVE",
        "decided_by": "employee-p8-s75-approver",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-authz:p8-s75-nsl",
        "authorization_revision_hash": semantic_sha256_hash_ref(
            {"oa": "s75-nsl"}
        ),
        "authorization_checked_at": decided_at,
        "decided_at": decided_at,
    }
    return {
        "request": _Snapshot(request),
        "protected": protected,
        "wait": wait,
        "work_item": item,
        "decision": decision,
    }


def _build_nsl_evidence(material: dict[str, Any], *, work_item=None):
    return build_platform_approval_evidence(
        approval_request=material["request"],
        protected_request=material["protected"],
        wait_registration=material["wait"],
        approval_work_item=work_item or material["work_item"],
        approval_decision=material["decision"],
        created_at=NOW + timedelta(minutes=2),
    )


def _formal_service():
    sink = _TransitionSink()
    service = EosBusinessApprovalTransitionService(
        approval_instances=_InstanceSource(_formal_instance()),
        transitions=sink,
    )
    return service, sink


def _advance(service, envelope):
    work_item, decision, event = envelope
    return service.advance_from_wc_decision(
        tenant_id=TENANT,
        approval_instance_id=INSTANCE_ID,
        work_item=work_item,
        decision=decision,
        event=event,
    )


def test_three_approval_domains_have_distinct_providers() -> None:
    expected = {"AGENT_FORMAL", "NSL_WRITE", "BUSINESS_FORMAL"}
    assert APPROVAL_DOMAINS == expected
    assert EOS_APPROVAL_DOMAINS == expected
    assert APPROVAL_PROVIDERS == {
        "AGENT_FORMAL": "AGENT",
        "NSL_WRITE": "NSL",
        "BUSINESS_FORMAL": "EOS",
    }


def test_business_formal_boundary_accepts_only_its_exact_wc_domain() -> None:
    service, sink = _formal_service()
    assert _advance(service, _formal_envelope()) == {"outcome": "ADMITTED"}
    assert len(sink.values) == 1

    for domain in ("NSL_WRITE", "AGENT_FORMAL"):
        service, sink = _formal_service()
        with pytest.raises(EosApprovalTransitionError, match="approval_domain"):
            _advance(service, _formal_envelope(domain=domain))
        assert sink.values == []


def test_nsl_evidence_cannot_satisfy_business_formal() -> None:
    evidence = _build_nsl_evidence(_nsl_material())
    _, decision, event = _formal_envelope()
    service, sink = _formal_service()

    with pytest.raises(EosApprovalTransitionError, match="EOS approval stage"):
        _advance(service, (evidence, decision, event))
    assert sink.values == []


@pytest.mark.parametrize(
    ("domain", "provider"),
    (("BUSINESS_FORMAL", "EOS"), ("AGENT_FORMAL", "AGENT")),
)
def test_non_nsl_gate_cannot_create_nsl_write_evidence(domain, provider) -> None:
    material = _nsl_material()
    substituted = {**material["work_item"]}
    substituted.update(
        approval_domain=domain,
        approval_provider_type=provider,
    )

    with pytest.raises(
        PlatformApprovalEvidenceError,
        match="does not bind the protected NSL request",
    ):
        _build_nsl_evidence(material, work_item=substituted)


def test_business_formal_proof_cannot_satisfy_nsl_write() -> None:
    material = _nsl_material()
    formal_proof = {
        "schema_version": "eos_approval_proof.v1",
        "tenant_id": TENANT,
        "approval_proof_id": "75000000-0000-4000-8008-000000000075",
        "approval_domain": "BUSINESS_FORMAL",
        "business_operation_id": "business-operation-p8-s75",
        "payload_hash": semantic_sha256_hash_ref({"payload": "s75"}),
        "write_intent_hash": "write-intent-p8-s75",
        "proof_hash": semantic_sha256_hash_ref({"proof": "s75"}),
    }

    with pytest.raises(PlatformApprovalEvidenceError, match="lineage differs"):
        _build_nsl_evidence(material, work_item=formal_proof)
