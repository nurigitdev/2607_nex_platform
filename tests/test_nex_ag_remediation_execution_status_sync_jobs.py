from __future__ import annotations

import pytest

from nex_ag.remediation_execution_status_sync_jobs import (
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_MAX_ATTEMPTS,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PLAN_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
    RemediationExecutionStatusSyncJobPlanningError,
    assert_remediation_execution_status_sync_job_redaction_safe,
    build_remediation_execution_status_sync_job,
    build_remediation_execution_status_sync_job_plan,
    remediation_execution_status_sync_idempotency_key,
    remediation_execution_status_sync_job_id,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def remediation_execution_operation(**overrides: object) -> dict[str, object]:
    operation: dict[str, object] = {
        "service_id": "nex-ag",
        "operation_type": "remediation_execution",
        "operation_timestamp": "2026-08-27T00:00:10Z",
        "remediation_action_id": "ag-remediation-action-001",
        "cx_generation_id": "cx-gen-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "tenant_id": "local-tenant",
        "action_type": "citation_repair",
        "priority": "HIGH",
        "task_status": "WAITING_ON_CX",
        "execution_status": "SUCCEEDED",
        "target_task_status": "COMPLETED",
        "status_sync_state": "SYNC_REQUIRED",
        "attention_required": True,
        "attempt_no": 1,
        "failure": None,
        "raw_prompt": "this input field must not be copied into the job",
    }
    operation.update(overrides)
    return operation


def test_status_sync_job_plan_builds_deterministic_common_job() -> None:
    plan = build_remediation_execution_status_sync_job_plan(
        remediation_execution_operation(),
        requested_at="2026-08-27T00:01:00Z",
    )

    assert plan["plan_schema_version"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PLAN_SCHEMA_VERSION
    )
    assert plan["plan_status"] == "READY"
    assert plan["reason_code"] is None
    assert plan["job_admission"] == {
        "enqueue_required": True,
        "job_type": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
        "idempotency_key": (
            "ag-remediation-execution-status-sync:ag-remediation-action-001"
        ),
        "dedupe_key": (
            "ag.remediation_execution.status_sync:"
            "ag-remediation-execution-status-sync:ag-remediation-action-001"
        ),
    }
    job = plan["job"]
    assert job["job_schema_version"] == "common_job.v1"
    assert job["job_id"] == remediation_execution_status_sync_job_id(
        "ag-remediation-action-001"
    )
    assert job["job_type"] == AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE
    assert job["subject_ref"] == {
        "type": "ag.remediation_execution.status_sync",
        "id": "ag-remediation-action-001",
    }
    assert job["idempotency_key"] == remediation_execution_status_sync_idempotency_key(
        "ag-remediation-action-001"
    )
    assert job["max_attempts"] == (
        AG_REMEDIATION_EXECUTION_STATUS_SYNC_DEFAULT_MAX_ATTEMPTS
    )
    assert job["retryable"] is True
    assert job["created_at"] == "2026-08-27T00:01:00Z"
    assert job["payload"] == {
        "payload_schema_version": (
            AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION
        ),
        "remediation_action_id": "ag-remediation-action-001",
        "cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "operation_timestamp": "2026-08-27T00:00:10Z",
        "requested_at": "2026-08-27T00:01:00Z",
        "status_sync_state": "SYNC_REQUIRED",
        "task_status": "WAITING_ON_CX",
        "execution_status": "SUCCEEDED",
        "target_task_status": "COMPLETED",
        "attempt_no": 1,
        "failure": None,
        "debug_paths": {
            "ag_remediation_task_path": (
                "/admin/v1/generation-audit/generations/cx-gen-001"
                "/remediation-tasks/ag-remediation-action-001"
            ),
            "ag_remediation_execution_operations_path": (
                "/admin/v1/operations/remediation-executions"
                "?remediation_action_id=ag-remediation-action-001"
            ),
            "cx_remediation_execution_path": (
                "/api/v1/generations/cx-gen-001"
                "/remediation-executions/ag-remediation-action-001"
            ),
        },
        "redaction_summary": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "provider_detail_included": False,
        },
    }
    assert "raw_prompt" not in job["payload"]
    assert job["payload"]["redaction_summary"]["raw_prompt_included"] is False


def test_status_sync_job_accepts_custom_idempotency_and_safe_failure_summary() -> None:
    job = build_remediation_execution_status_sync_job(
        remediation_execution_operation(
            execution_status="FAILED",
            target_task_status="FAILED",
            attempt_no="2",
            failure={
                "error_code": "cx.remediation.execution_failed",
                "error_detail_sha256": "a" * 64,
                "retryable": True,
                "raw_output": "ignored",
            },
        ),
        requested_at="2026-08-27T00:02:00Z",
        idempotency_key="operator-requested-sync-001",
    )

    assert job["idempotency_key"] == "operator-requested-sync-001"
    assert job["payload"]["attempt_no"] == 2
    assert job["payload"]["failure"] == {
        "error_code": "cx.remediation.execution_failed",
        "error_detail_sha256": "a" * 64,
        "retryable": True,
    }
    assert "raw_output" not in str(job)


def test_status_sync_job_plan_skips_non_attention_or_non_actionable_items() -> None:
    not_attention = build_remediation_execution_status_sync_job_plan(
        remediation_execution_operation(
            attention_required=False,
            status_sync_state="IN_SYNC",
            task_status="COMPLETED",
            target_task_status="COMPLETED",
        )
    )
    stale_attention = build_remediation_execution_status_sync_job_plan(
        remediation_execution_operation(status_sync_state="IN_SYNC")
    )

    assert not_attention["plan_status"] == "SKIPPED"
    assert not_attention["reason_code"] == "attention_not_required"
    assert not_attention["job"] is None
    assert stale_attention["plan_status"] == "SKIPPED"
    assert stale_attention["reason_code"] == "status_sync_state_not_actionable"


@pytest.mark.parametrize(
    "status_sync_state",
    [
        "NO_EXECUTION",
        "ORPHAN_EXECUTION",
        "TERMINAL_TASK_DIVERGED",
        "UNKNOWN_EXECUTION_STATUS",
    ],
)
def test_status_sync_job_plan_blocks_operator_review_states(
    status_sync_state: str,
) -> None:
    plan = build_remediation_execution_status_sync_job_plan(
        remediation_execution_operation(status_sync_state=status_sync_state)
    )

    assert plan["plan_status"] == "BLOCKED"
    assert plan["reason_code"] == (
        f"{status_sync_state.lower()}_requires_operator_review"
    )
    assert plan["job_admission"]["enqueue_required"] is False


def test_status_sync_job_plan_blocks_missing_runtime_correlation() -> None:
    plan = build_remediation_execution_status_sync_job_plan(
        remediation_execution_operation(trace_id=None, request_id=" ")
    )

    assert plan["plan_status"] == "BLOCKED"
    assert plan["reason_code"] == "runtime_correlation_missing"
    assert plan["job_admission"]["missing_fields"] == ["trace_id", "request_id"]

    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as exc_info:
        build_remediation_execution_status_sync_job(
            remediation_execution_operation(trace_id=None)
        )

    assert exc_info.value.error_code == (
        "ag.remediation_execution_status_sync_job_correlation_missing"
    )


def test_status_sync_job_planning_validates_required_fields_and_sensitive_keys() -> None:
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as missing:
        build_remediation_execution_status_sync_job_plan(
            remediation_execution_operation(remediation_action_id="")
        )
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as invalid:
        build_remediation_execution_status_sync_job_plan("not-an-operation")
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as bad_state:
        build_remediation_execution_status_sync_job(
            remediation_execution_operation(status_sync_state="ORPHAN_EXECUTION")
        )
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as sensitive:
        assert_remediation_execution_status_sync_job_redaction_safe(
            {"payload": {"raw_prompt": "nope"}}
        )
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as bad_summary:
        assert_remediation_execution_status_sync_job_redaction_safe(
            {"payload": {"redaction_summary": {"raw_prompt_included": True}}}
        )
    assert_remediation_execution_status_sync_job_redaction_safe(
        {"payload": {"items": [{"summary": "ok"}]}}
    )
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as blank_id:
        remediation_execution_status_sync_job_id(" ")
    with pytest.raises(RemediationExecutionStatusSyncJobPlanningError) as blank_key:
        remediation_execution_status_sync_idempotency_key("")

    assert missing.value.error_code == (
        "ag.remediation_execution_status_sync_remediation_action_id_required"
    )
    assert str(invalid.value) == (
        "Remediation execution status sync planning requires an operation."
    )
    assert bad_state.value.error_code == (
        "ag.remediation_execution_status_sync_job_state_not_ready"
    )
    assert sensitive.value.error_code == (
        "ag.remediation_execution_status_sync_job_sensitive_payload"
    )
    assert bad_summary.value.error_code == (
        "ag.remediation_execution_status_sync_job_sensitive_payload"
    )
    assert blank_id.value.error_code == (
        "ag.remediation_execution_status_sync_remediation_action_id_required"
    )
    assert blank_key.value.error_code == (
        "ag.remediation_execution_status_sync_remediation_action_id_required"
    )


def test_status_sync_job_normalizes_optional_values_and_runtime_timestamp() -> None:
    job = build_remediation_execution_status_sync_job(
        remediation_execution_operation(
            tenant_id=12345,
            operation_timestamp=None,
            task_status=None,
            execution_status=None,
            target_task_status=None,
            attempt_no=False,
            failure={"error_code": 9001, "error_detail_sha256": None},
        )
    )

    payload = job["payload"]
    assert job["created_at"].endswith("Z")
    assert payload["requested_at"] == job["created_at"]
    assert payload["tenant_id"] == "12345"
    assert payload["operation_timestamp"] is None
    assert payload["task_status"] is None
    assert payload["execution_status"] is None
    assert payload["target_task_status"] is None
    assert payload["attempt_no"] is None
    assert payload["failure"] == {
        "error_code": "9001",
        "error_detail_sha256": None,
        "retryable": False,
    }


@pytest.mark.parametrize("attempt_no", ["-1", "not-a-number", object()])
def test_status_sync_job_ignores_invalid_attempt_numbers(attempt_no: object) -> None:
    job = build_remediation_execution_status_sync_job(
        remediation_execution_operation(attempt_no=attempt_no),
        requested_at="2026-08-27T00:03:00Z",
    )

    assert job["payload"]["attempt_no"] is None
