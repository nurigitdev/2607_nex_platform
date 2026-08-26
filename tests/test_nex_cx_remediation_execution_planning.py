from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx import remediation_execution_planning as planning
from nex_cx.remediation_execution_planning import (
    ACCEPTED,
    CANCELLED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS,
    RemediationExecutionPlanningError,
    apply_remediation_execution_transition,
    build_remediation_execution_transition,
    build_remediation_execution_worker_plan,
    remediation_execution_transition_allowed,
    validate_remediation_execution_record_for_worker,
    validate_remediation_execution_worker_plan,
    _transition_update,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def accepted_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "result_schema_version": "cx_remediation_execution_result.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "parent_cx_generation_id": "cx-gen-parent-001",
        "root_cx_generation_id": "cx-gen-root-001",
        "repair_cx_generation_id": None,
        "tenant_id": "local-tenant",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": ACCEPTED,
        "attempt_no": 1,
        "result_ref": None,
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
            "excluded_fields": [
                "raw_prompt",
                "messages",
                "source_text",
                "output_text",
                "raw_output",
                "provider_url",
                "provider_endpoint",
                "model_path",
                "storage_path",
                "api_key",
            ],
        },
        "created_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
    }
    record.update(overrides)
    return record


def result_ref(ref_id: str = "cx-gen-repair-001") -> dict[str, str]:
    return {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": ref_id,
        "relation": "result_of",
    }


def failure(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "failure_code": "mo.request_failed",
        "failure_class": "generation",
        "retryable": True,
        "safe_message": "MO generation request failed.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    (
        "action_type",
        "lineage_type",
        "retrieval_policy",
        "prompt_policy",
        "expected_stage",
    ),
    [
        (
            "retry_generation",
            "retry",
            "reuse_original_retrieval_package",
            "rebuild_with_retry_instruction_ref",
            "reuse_original_retrieval_package",
        ),
        (
            "retrieval_repair",
            "fresh_retrieval_regenerate",
            "fresh_retrieval_required",
            "rebuild_with_retrieval_repair_instruction_ref",
            "select_fresh_retrieval_package",
        ),
        (
            "citation_repair",
            "repair",
            "reuse_or_expand_cited_evidence",
            "rebuild_with_citation_repair_instruction_ref",
            "validate_repaired_citations",
        ),
    ],
)
def test_worker_plan_freezes_action_policy_and_state_machine(
    action_type: str,
    lineage_type: str,
    retrieval_policy: str,
    prompt_policy: str,
    expected_stage: str,
) -> None:
    plan = build_remediation_execution_worker_plan(
        accepted_record(
            action_type=action_type,
            lineage_type=lineage_type,
            attempt_no=2,
        ),
        planned_at="2026-08-26T00:00:01Z",
    )

    assert plan["plan_schema_version"] == "cx_remediation_execution_worker_plan.v1"
    assert plan["plan_id"] == "ag-remediation-action-001:attempt-2"
    assert plan["action_type"] == action_type
    assert plan["lineage_type"] == lineage_type
    assert plan["start_status"] == ACCEPTED
    assert plan["state_machine"] == {
        status: list(next_statuses)
        for status, next_statuses in CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS.items()
    }
    assert plan["retrieval_package_policy"] == retrieval_policy
    assert plan["prompt_package_policy"] == prompt_policy
    assert plan["provider_boundary"] == "cx_to_mo_service_api_only"
    assert plan["parent_generation_mutation_allowed"] is False
    assert plan["repair_generation_policy"] == {
        "creates_child_generation_record": True,
        "parent_generation_id": "cx-gen-parent-001",
        "root_generation_id": "cx-gen-root-001",
        "parent_generation_mutated": False,
        "repair_cx_generation_id_required_on_success": True,
    }
    assert expected_stage in [stage["stage_id"] for stage in plan["worker_stages"]]
    assert all(
        stage["raw_payload_storage"] == "forbidden"
        for stage in plan["worker_stages"]
    )
    mo_stage = [
        stage
        for stage in plan["worker_stages"]
        if stage["stage_id"] == "submit_mo_generation_request"
    ][0]
    assert mo_stage["owner_service"] == "nex-mo"
    assert mo_stage["provider_boundary"] == "cx_to_mo_service_api_only"


def test_worker_plan_defaults_root_and_attempt_for_running_resume() -> None:
    plan = build_remediation_execution_worker_plan(
        accepted_record(
            root_cx_generation_id=" ",
            attempt_no=0,
            execution_status=RUNNING,
        ),
        planned_at="2026-08-26T00:00:01Z",
    )

    assert plan["root_cx_generation_id"] == "cx-gen-parent-001"
    assert plan["attempt_no"] == 1
    assert plan["start_status"] == RUNNING


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"result_schema_version": "old"},
            "cx.remediation_execution_worker.record_schema_invalid",
        ),
        (
            {"action_type": "prompt_policy_review"},
            "cx.remediation_execution_worker.action_not_executable",
        ),
        (
            {"lineage_type": "fresh_retrieval_regenerate"},
            "cx.remediation_execution_worker.lineage_invalid",
        ),
        (
            {"execution_status": "BOGUS"},
            "cx.remediation_execution_worker.status_invalid",
        ),
        (
            {"execution_status": SUCCEEDED, "repair_cx_generation_id": "cx-repair"},
            "cx.remediation_execution_worker.status_not_plannable",
        ),
        (
            {"repair_cx_generation_id": "cx-gen-parent-001"},
            "cx.remediation_execution_worker.parent_mutation_forbidden",
        ),
        (
            {"raw_prompt": "do not store this"},
            "cx.remediation_execution_worker.sensitive_payload",
        ),
        (
            {"remediation_action_id": " "},
            "cx.remediation_execution_worker.remediation_action_id_required",
        ),
    ],
)
def test_worker_record_validation_rejects_invalid_or_sensitive_records(
    override: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        build_remediation_execution_worker_plan(accepted_record(**override))

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            {"plan_schema_version": "old"},
            "cx.remediation_execution_plan.schema_version_invalid",
        ),
        (
            {"lineage_type": "fresh_retrieval_regenerate"},
            "cx.remediation_execution_plan.lineage_invalid",
        ),
        (
            {"provider_boundary": "direct_provider"},
            "cx.remediation_execution_plan.provider_boundary_invalid",
        ),
        (
            {"parent_generation_mutation_allowed": True},
            "cx.remediation_execution_plan.parent_mutation_forbidden",
        ),
        (
            {"state_machine": {ACCEPTED: [SUCCEEDED]}},
            "cx.remediation_execution_plan.state_machine_invalid",
        ),
        (
            {"start_status": SUCCEEDED},
            "cx.remediation_execution_plan.start_status_invalid",
        ),
        (
            {"worker_stages": [{"stage_id": "load_parent_generation"}]},
            "cx.remediation_execution_plan.stages_invalid",
        ),
        (
            {
                "worker_stages": [
                    {
                        "stage_id": "load_parent_generation",
                        "raw_payload_storage": "allowed",
                    },
                    *[
                        stage
                        for stage in build_remediation_execution_worker_plan(
                            accepted_record()
                        )["worker_stages"][1:]
                    ],
                ]
            },
            "cx.remediation_execution_plan.raw_storage_forbidden",
        ),
        (
            {
                "worker_stages": [
                    {
                        **stage,
                        "provider_boundary": "direct_provider",
                    }
                    if stage["stage_id"] == "submit_mo_generation_request"
                    else stage
                    for stage in build_remediation_execution_worker_plan(
                        accepted_record()
                    )["worker_stages"]
                ]
            },
            "cx.remediation_execution_plan.provider_boundary_invalid",
        ),
        (
            {"repair_generation_policy": {"parent_generation_mutated": True}},
            "cx.remediation_execution_plan.parent_mutation_forbidden",
        ),
        (
            {"raw_output": "do not store this"},
            "cx.remediation_execution_worker.sensitive_payload",
        ),
    ],
)
def test_worker_plan_validation_rejects_mutated_shapes(
    mutation: dict[str, object],
    error_code: str,
) -> None:
    plan = build_remediation_execution_worker_plan(accepted_record())
    plan.update(mutation)

    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        validate_remediation_execution_worker_plan(plan)

    assert exc_info.value.error_code == error_code


def test_worker_plan_validation_rejects_non_list_stages() -> None:
    plan = build_remediation_execution_worker_plan(accepted_record())
    plan["worker_stages"] = "not-a-list"

    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        validate_remediation_execution_worker_plan(plan)

    assert exc_info.value.error_code == "cx.remediation_execution_plan.stages_invalid"


def test_worker_action_policy_rejects_internal_policy_drift(monkeypatch) -> None:
    drifted_policy = deepcopy(planning.ACTION_WORKER_POLICIES)
    drifted_policy["citation_repair"]["lineage_type"] = "retry"
    monkeypatch.setattr(planning, "ACTION_WORKER_POLICIES", drifted_policy)

    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        build_remediation_execution_worker_plan(accepted_record())

    assert exc_info.value.error_code == (
        "cx.remediation_execution_worker.action_policy_invalid"
    )


def test_transition_policy_and_apply_running_success_failure_and_cancel() -> None:
    assert remediation_execution_transition_allowed(ACCEPTED, RUNNING) is True
    assert remediation_execution_transition_allowed(ACCEPTED, SUCCEEDED) is False
    assert remediation_execution_transition_allowed("UNKNOWN", RUNNING) is False

    running = apply_remediation_execution_transition(
        accepted_record(),
        RUNNING,
        observed_at="2026-08-26T00:00:01Z",
    )
    assert running["execution_status"] == RUNNING
    assert running["updated_at"] == "2026-08-26T00:00:01Z"
    assert running["repair_cx_generation_id"] is None

    success_transition = build_remediation_execution_transition(
        running,
        SUCCEEDED,
        observed_at="2026-08-26T00:00:02Z",
        repair_cx_generation_id="cx-gen-repair-001",
        result_ref=result_ref(),
    )
    assert success_transition["terminal"] is True
    assert success_transition["parent_generation_mutated"] is False
    assert success_transition["record_update"]["execution_status"] == SUCCEEDED

    succeeded = apply_remediation_execution_transition(
        running,
        SUCCEEDED,
        observed_at="2026-08-26T00:00:02Z",
        repair_cx_generation_id="cx-gen-repair-001",
        result_ref=result_ref(),
    )
    assert succeeded["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert succeeded["result_ref"] == result_ref()
    assert succeeded["failure"] is None

    failed = apply_remediation_execution_transition(
        running,
        FAILED,
        observed_at="2026-08-26T00:00:03Z",
        failure=failure(),
    )
    assert failed["execution_status"] == FAILED
    assert failed["failure"] == failure()
    assert failed["result_ref"] is None

    cancelled = apply_remediation_execution_transition(
        accepted_record(),
        CANCELLED,
        observed_at="2026-08-26T00:00:04Z",
    )
    assert cancelled["execution_status"] == CANCELLED
    assert cancelled["failure"] is None

    cancelled_with_failure = apply_remediation_execution_transition(
        running,
        CANCELLED,
        observed_at="2026-08-26T00:00:05Z",
        failure=failure(failure_code="operator.cancelled", retryable=False),
    )
    assert cancelled_with_failure["failure"]["failure_code"] == "operator.cancelled"


@pytest.mark.parametrize(
    ("record", "next_status", "kwargs", "error_code"),
    [
        (
            accepted_record(),
            SUCCEEDED,
            {
                "repair_cx_generation_id": "cx-gen-repair-001",
                "result_ref": result_ref(),
            },
            "cx.remediation_execution_transition.invalid",
        ),
        (
            accepted_record(result_ref=result_ref()),
            RUNNING,
            {},
            "cx.remediation_execution_transition.terminal_payload_invalid",
        ),
        (
            accepted_record(execution_status=RUNNING),
            SUCCEEDED,
            {
                "repair_cx_generation_id": "cx-gen-parent-001",
                "result_ref": result_ref(),
            },
            "cx.remediation_execution_transition.parent_mutation_forbidden",
        ),
        (
            accepted_record(execution_status=RUNNING),
            SUCCEEDED,
            {"repair_cx_generation_id": "cx-gen-repair-001"},
            "cx.remediation_execution_transition.result_ref_invalid",
        ),
        (
            accepted_record(execution_status=RUNNING),
            FAILED,
            {},
            "cx.remediation_execution_transition.field_required",
        ),
        (
            accepted_record(execution_status=RUNNING),
            FAILED,
            {"failure": failure(failure_class="raw_prompt")},
            "cx.remediation_execution_transition.failure_class_invalid",
        ),
        (
            accepted_record(execution_status=RUNNING),
            FAILED,
            {"failure": failure(retryable="yes")},
            "cx.remediation_execution_transition.failure_retryable_invalid",
        ),
        (
            accepted_record(execution_status=RUNNING),
            FAILED,
            {"failure": failure(raw_prompt="do not store this")},
            "cx.remediation_execution_worker.sensitive_payload",
        ),
        (
            accepted_record(execution_status=RUNNING),
            "BOGUS",
            {},
            "cx.remediation_execution_transition.invalid",
        ),
    ],
)
def test_transitions_reject_invalid_terminal_shapes(
    record: dict[str, object],
    next_status: str,
    kwargs: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        build_remediation_execution_transition(record, next_status, **kwargs)

    assert exc_info.value.error_code == error_code


def test_planning_error_string_and_internal_transition_guard() -> None:
    error = RemediationExecutionPlanningError(
        error_code="example",
        detail="example detail",
    )
    assert str(error) == "example detail"

    with pytest.raises(RemediationExecutionPlanningError) as exc_info:
        _transition_update(
            accepted_record(),
            "BOGUS",
            repair_cx_generation_id=None,
            result_ref=None,
            failure=None,
            observed_at="2026-08-26T00:00:01Z",
        )

    assert exc_info.value.error_code == (
        "cx.remediation_execution_transition.status_invalid"
    )


def test_record_validation_can_skip_plannable_guard_for_terminal_read_model() -> None:
    record = accepted_record(
        execution_status=SUCCEEDED,
        repair_cx_generation_id="cx-gen-repair-001",
        result_ref=result_ref(),
    )

    assert validate_remediation_execution_record_for_worker(record) == record
