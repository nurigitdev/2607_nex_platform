from __future__ import annotations

import json

import pytest
from nex_wc import approvals


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8-s74",
        "approval_work_item_id": "74000000-0000-4000-8000-000000000001",
        "approval_domain": "BUSINESS_FORMAL",
        "source_ref": "eos.approval-stage:stage-p8-s74",
        "semantic_hash": "sha256:" + "7" * 64,
        "title": "Approve business operation",
        "display_safe_summary": json.dumps(
            {
                "operation": "CREATE_VOUCHER_DRAFT",
                "stage_order": 2,
                "stage_count": 4,
                "position_type": "GROUP_LEAD",
                "org_unit_id": "org-finance",
                "project_id": "project-p8-s74",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        "approval_provider_type": "EOS",
        "approval_target_ref": "eos.approval-stage:stage-p8-s74",
        "target_approver_ref": "approver-p8-s74",
        "target_role_ref": "GROUP_LEAD",
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8-s74",
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": "operation-p8-s74",
        "approval_request_id": None,
        "protected_request_ref": "eos:business-operation:operation-p8-s74",
        "resume_target_ref": "eos.approval-instance:instance-p8-s74:stage:2",
        "state": "PENDING",
        "created_at": "2026-10-23T10:00:00Z",
        "expires_at": "2026-10-30T10:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


def test_business_formal_gate_projects_safe_eos_stage_progress() -> None:
    view = approvals._human_gate_view(_work_item())

    assert view["approval_domain"] == "BUSINESS_FORMAL"
    assert view["approval_provider_type"] == "EOS"
    assert view["formal_approval"] == {
        "schema_version": "business_formal_gate_view.p8.v1",
        "current_stage": 2,
        "stage_count": 4,
        "requested_role": "GROUP_LEAD",
        "eos_target_ref": "eos.approval-stage:stage-p8-s74",
        "org_unit_id": "org-finance",
        "project_id": "project-p8-s74",
        "terminal_state": None,
    }
    serialized = json.dumps(view, sort_keys=True)
    for forbidden in (
        "protected_request_ref",
        "resume_target_ref",
        "semantic_hash",
        "source_ref",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "summary",
    (
        "display-safe legacy summary",
        "{",
        json.dumps({"stage_order": 0, "stage_count": 2}),
        json.dumps({"stage_order": 3, "stage_count": 2}),
        json.dumps({"stage_order": True, "stage_count": 2}),
    ),
)
def test_legacy_or_invalid_summary_keeps_compatible_formal_projection(summary) -> None:
    formal = approvals._human_gate_view(_work_item(display_safe_summary=summary))[
        "formal_approval"
    ]

    assert formal["current_stage"] is None
    assert formal["stage_count"] is None
    assert formal["requested_role"] == "GROUP_LEAD"
    assert formal["eos_target_ref"] == "eos.approval-stage:stage-p8-s74"


@pytest.mark.parametrize(
    ("state", "terminal_state"),
    (
        ("PENDING", None),
        ("APPROVED", "APPROVED"),
        ("REJECTED", "REJECTED"),
        ("EXPIRED", "EXPIRED"),
        ("CANCELLED", "CANCELLED"),
    ),
)
def test_formal_projection_exposes_only_terminal_work_item_state(
    state, terminal_state
) -> None:
    view = approvals._human_gate_view(_work_item(state=state))
    assert view["formal_approval"]["terminal_state"] == terminal_state


def test_non_business_domain_does_not_receive_eos_projection() -> None:
    item = _work_item(
        approval_domain="AGENT_FORMAL",
        source_ref="agent-formal-p8-s74",
        approval_provider_type="AGENT",
        approval_target_ref="agent-formal-p8-s74",
        target_role_ref=None,
        agent_execution_id="agent-execution-p8-s74",
        executable_step_id="step-p8-s74",
        nsl_execution_id=None,
        business_operation_id="operation-agent-p8-s74",
        approval_request_id=None,
        protected_request_ref="ae-private:agent-formal-p8-s74",
        resume_target_ref="ae-wait:agent-formal-p8-s74",
        display_safe_summary="Agent formal approval.",
    )

    assert "formal_approval" not in approvals._human_gate_view(item)
