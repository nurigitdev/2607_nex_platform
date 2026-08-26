from __future__ import annotations

from typing import Any

import pytest

from nex_ag.generation_remediation import build_generation_remediation_action
from nex_ag.generation_remediation_execution import (
    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION,
    GenerationRemediationExecutionError,
    _status_path,
    apply_generation_remediation_execution_handoff_plan,
    build_generation_remediation_execution_handoff_plan,
    build_generation_remediation_execution_result_ref,
    clone_plan,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
NOW = "2026-08-26T00:00:00Z"


def remediation_record(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "remediation_action_id": "ag-remediation-action-001",
        "tenant_id": "tenant-001",
        "action_type": "citation_repair",
        "action_status": "PROPOSED",
        "priority": "HIGH",
        "reason_codes": ["citation_quality"],
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-ag",
            "tenant_id": "tenant-001",
        },
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_quality",
                "ref_id": "cx-gen-001",
                "relation": "caused_by",
            }
        ],
        "evidence_hashes": [
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ],
        "evidence_previews": ["citation quality failed"],
    }
    payload.update(overrides)
    return build_generation_remediation_action(
        payload,
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at=NOW,
    )


def cx_execution_result(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": None,
        "tenant_id": "tenant-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "ACCEPTED",
        "result_ref": None,
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return payload


def test_handoff_plan_moves_proposed_task_through_in_progress_to_waiting_on_cx() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    assert plan["plan_schema_version"] == (
        AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
    )
    assert plan["current_action_status"] == "PROPOSED"
    assert plan["target_action_status"] == "WAITING_ON_CX"
    assert [update["action_status"] for update in plan["status_updates"]] == [
        "IN_PROGRESS",
        "WAITING_ON_CX",
    ]
    assert plan["status_updates"][-1]["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    assert plan["result_ref"]["result_ref_schema_version"] == (
        AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION
    )
    assert plan["redaction_summary"]["raw_generation_output_included"] is False
    assert "cx-gen-001/remediation-tasks/ag-remediation-action-001" in plan[
        "debug_paths"
    ]["ag_remediation_task_path"]


def test_apply_handoff_plan_returns_sequential_records() -> None:
    record = remediation_record()
    plan = build_generation_remediation_execution_handoff_plan(
        record,
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    applied = apply_generation_remediation_execution_handoff_plan(
        record,
        plan,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        updated_at=NOW,
    )

    assert [item["action_status"] for item in applied] == [
        "IN_PROGRESS",
        "WAITING_ON_CX",
    ]
    assert applied[-1]["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    assert applied[-1]["updated_at"] == NOW


@pytest.mark.parametrize(
    ("current_status", "cx_status", "expected_updates"),
    [
        ("ASSIGNED", "ACCEPTED", ["IN_PROGRESS", "WAITING_ON_CX"]),
        ("IN_PROGRESS", "RUNNING", ["WAITING_ON_CX"]),
        ("WAITING_ON_CX", "RUNNING", ["WAITING_ON_CX"]),
        ("IN_PROGRESS", "SUCCEEDED", ["COMPLETED"]),
        ("WAITING_ON_CX", "FAILED", ["FAILED"]),
        ("PROPOSED", "CANCELLED", ["CANCELLED"]),
    ],
)
def test_handoff_plan_status_paths(
    current_status: str,
    cx_status: str,
    expected_updates: list[str],
) -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(action_status=current_status),
        cx_execution_result(execution_status=cx_status),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    assert [update["action_status"] for update in plan["status_updates"]] == (
        expected_updates
    )
    assert plan["cx_execution_status"] == cx_status


def test_result_ref_uses_supplied_cx_result_ref_and_repair_generation_id() -> None:
    result_ref = build_generation_remediation_execution_result_ref(
        cx_execution_result(
            execution_status="SUCCEEDED",
            repair_cx_generation_id="cx-gen-repair-001",
            result_ref={
                "source_service": "nex-cx",
                "ref_type": "repair_execution",
                "ref_id": "cx-repair-run-001",
                "relation": "result_of",
            },
        ),
        record=remediation_record(action_status="WAITING_ON_CX"),
    )

    assert result_ref["ref_id"] == "cx-repair-run-001"
    assert result_ref["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert result_ref["cx_execution_status"] == "SUCCEEDED"


@pytest.mark.parametrize(
    ("record_overrides", "result_overrides", "error_code"),
    [
        (
            {"action_schema_version": "old"},
            {},
            "ag.remediation_execution_record_schema_invalid",
        ),
        (
            {"action_type": "operator_followup"},
            {},
            "ag.remediation_execution_action_not_executable",
        ),
        (
            {"action_status": "UNKNOWN"},
            {},
            "ag.remediation_execution_status_invalid",
        ),
        (
            {"action_status": "COMPLETED"},
            {},
            "ag.remediation_execution_terminal_task",
        ),
        (
            {},
            {"result_schema_version": "old"},
            "ag.remediation_execution_cx_result_schema_invalid",
        ),
        (
            {},
            {"remediation_action_id": "other"},
            "ag.remediation_execution_action_mismatch",
        ),
        (
            {},
            {"parent_cx_generation_id": "other"},
            "ag.remediation_execution_generation_mismatch",
        ),
        (
            {},
            {"execution_status": "UNKNOWN"},
            "ag.remediation_execution_cx_status_invalid",
        ),
    ],
)
def test_handoff_plan_rejects_invalid_record_or_result(
    record_overrides: dict[str, Any],
    result_overrides: dict[str, Any],
    error_code: str,
) -> None:
    record = remediation_record()
    record.update(record_overrides)
    result = cx_execution_result(**result_overrides)

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        build_generation_remediation_execution_handoff_plan(
            record,
            result,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            planned_at=NOW,
        )

    assert exc_info.value.error_code == error_code


def test_handoff_plan_redaction_guard_rejects_sensitive_record() -> None:
    record = remediation_record()
    record["raw_prompt"] = "hidden prompt"

    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        build_generation_remediation_execution_handoff_plan(
            record,
            cx_execution_result(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            planned_at=NOW,
        )

    assert exc_info.value.error_code == "ag.cx_remediation_execution_sensitive_payload"


def test_apply_handoff_plan_validates_plan_shape() -> None:
    record = remediation_record()

    with pytest.raises(GenerationRemediationExecutionError) as schema_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {"plan_schema_version": "old", "status_updates": []},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert schema_error.value.error_code == (
        "ag.remediation_execution_plan_schema_invalid"
    )

    with pytest.raises(GenerationRemediationExecutionError) as updates_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": [],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert updates_error.value.error_code == (
        "ag.remediation_execution_plan_updates_invalid"
    )


def test_apply_handoff_plan_rejects_bad_update_and_transition() -> None:
    record = remediation_record(action_status="ASSIGNED")

    with pytest.raises(GenerationRemediationExecutionError) as object_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": ["WAITING_ON_CX"],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert object_error.value.error_code == "ag.remediation_execution_plan_update_invalid"

    with pytest.raises(GenerationRemediationExecutionError) as transition_error:
        apply_generation_remediation_execution_handoff_plan(
            record,
            {
                "plan_schema_version": (
                    AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
                ),
                "status_updates": [{"action_status": "WAITING_ON_CX"}],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert transition_error.value.error_code == (
        "ag.generation_remediation_status_transition_invalid"
    )


def test_clone_plan_returns_independent_copy() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        planned_at=NOW,
    )

    cloned = clone_plan(plan)
    cloned["status_updates"][0]["action_status"] = "CHANGED"

    assert plan["status_updates"][0]["action_status"] == "IN_PROGRESS"


def test_handoff_plan_default_clock_and_error_string() -> None:
    plan = build_generation_remediation_execution_handoff_plan(
        remediation_record(action_status="IN_PROGRESS"),
        cx_execution_result(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    error = GenerationRemediationExecutionError(
        status_code=409,
        error_code="example",
        detail="readable detail",
    )

    assert str(error) == "readable detail"
    assert str(plan["planned_at"]).endswith("Z")


def test_private_status_path_reports_unreachable_transition() -> None:
    with pytest.raises(GenerationRemediationExecutionError) as exc_info:
        _status_path("IN_PROGRESS", "PROPOSED")

    assert exc_info.value.error_code == (
        "ag.remediation_execution_status_transition_invalid"
    )
