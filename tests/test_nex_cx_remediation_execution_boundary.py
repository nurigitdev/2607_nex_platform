from __future__ import annotations

import pytest

from nex_cx.remediation_execution_boundary import (
    AE_RESULT_SURFACE_OWNER_SERVICE,
    AG_REMEDIATION_OWNER_SERVICE,
    CX_EXECUTABLE_REMEDIATION_ACTION_TYPES,
    CX_GENERATION_LINEAGE_OWNER_SERVICE,
    CX_REMEDIATION_EXECUTION_BOUNDARY_DECISION_VERSION,
    CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
    MO_PROVIDER_EXECUTION_OWNER_SERVICE,
    REMEDIATION_EXECUTION_STAGES,
    RemediationExecutionBoundaryError,
    assert_cx_remediation_execution_payload_redaction_safe,
    build_cx_remediation_execution_boundary_decision,
    build_remediation_action_intake_summary,
    find_sensitive_cx_remediation_execution_keys,
    remediation_action_executable_by_cx,
    remediation_lineage_type_for_action,
    validate_cx_remediation_execution_boundary_decision,
)


def safe_remediation_action(**overrides: object) -> dict[str, object]:
    action: dict[str, object] = {
        "action_schema_version": "ag_generation_remediation_action.v1",
        "remediation_action_id": "ag-remediation-action-001",
        "cx_generation_id": "cx-gen-parent-001",
        "tenant_id": "local-tenant",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "action_type": "citation_repair",
        "action_status": "WAITING_ON_CX",
        "priority": "HIGH",
        "reason_codes": ["negative_user_feedback", "citation_quality"],
        "owner_ref": {
            "owner_type": "service",
            "owner_id": "nex-ag",
            "tenant_id": "local-tenant",
        },
        "source_refs": [
            {
                "source_service": "nex-ae-api",
                "ref_type": "feedback",
                "ref_id": "ae-feedback-001",
                "relation": "caused_by",
            },
            {
                "source_service": "nex-ag",
                "ref_type": "operator_disposition",
                "ref_id": "ag-disposition-001",
                "relation": "recommended_by",
            },
        ],
        "evidence": {
            "evidence_hashes": ["a" * 64],
            "evidence_previews": ["Citation [2] did not support the answer."],
            "raw_evidence_stored": False,
        },
        "result_ref": None,
        "metadata": {
            "action_source": "operator_disposition",
            "raw_prompt_stored": False,
            "raw_generation_output_stored": False,
            "raw_source_document_text_stored": False,
            "raw_feedback_comment_stored": False,
            "raw_operator_note_stored": False,
            "free_text_storage": "hash_and_short_preview_only",
        },
    }
    action.update(overrides)
    return action


def test_cx_remediation_execution_boundary_assigns_owner_services() -> None:
    decision = validate_cx_remediation_execution_boundary_decision(
        build_cx_remediation_execution_boundary_decision()
    )

    assert decision["decision_schema_version"] == (
        CX_REMEDIATION_EXECUTION_BOUNDARY_DECISION_VERSION
    )
    assert decision["owner_services"] == {
        "remediation_task_orchestration": AG_REMEDIATION_OWNER_SERVICE,
        "remediation_execution": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
        "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
        "provider_execution": MO_PROVIDER_EXECUTION_OWNER_SERVICE,
        "user_visible_result_surface": AE_RESULT_SURFACE_OWNER_SERVICE,
    }
    assert tuple(decision["execution_stages"]) == REMEDIATION_EXECUTION_STAGES
    assert decision["refactoring_checkpoint"] == {
        "external_api_changed": False,
        "database_schema_changed": False,
        "remote_provider_required": False,
        "next_slice": "0352_cx_remediation_execution_contract_schema_foundation",
    }


def test_cx_remediation_execution_boundary_error_string_is_detail() -> None:
    error = RemediationExecutionBoundaryError(
        error_code="cx.remediation_execution_boundary.test",
        detail="Readable boundary failure.",
    )

    assert str(error) == "Readable boundary failure."


def test_cx_remediation_execution_boundary_freezes_action_policy() -> None:
    decision = validate_cx_remediation_execution_boundary_decision(
        build_cx_remediation_execution_boundary_decision()
    )
    policy = decision["action_execution_policy"]

    assert tuple(policy["executable_by_cx"]) == CX_EXECUTABLE_REMEDIATION_ACTION_TYPES
    assert policy["executable_by_cx"]["retry_generation"]["lineage_type"] == "retry"
    assert policy["executable_by_cx"]["retrieval_repair"]["lineage_type"] == (
        "fresh_retrieval_regenerate"
    )
    assert policy["executable_by_cx"]["citation_repair"]["lineage_type"] == "repair"
    assert set(policy["ag_only"]) == {
        "prompt_policy_review",
        "operator_followup",
        "mark_accepted",
    }
    assert remediation_action_executable_by_cx("citation_repair") is True
    assert remediation_action_executable_by_cx("mark_accepted") is False
    assert remediation_action_executable_by_cx("unknown") is False


def test_cx_remediation_execution_boundary_freezes_parent_child_lineage() -> None:
    decision = validate_cx_remediation_execution_boundary_decision(
        build_cx_remediation_execution_boundary_decision()
    )
    lineage = decision["lineage_contract"]

    assert lineage["parent_generation_id_required"] is True
    assert lineage["parent_generation_id_source"] == "ag_action.cx_generation_id"
    assert lineage["root_generation_id_policy"] == "inherit_from_parent_or_parent_id"
    assert lineage["attempt_no_policy"] == "cx_increments_from_parent_attempt"
    assert lineage["original_generation_record_mutated"] is False
    assert lineage["child_generation_record_schema_version"] == (
        "cx_generation_execution_record.v1"
    )
    assert lineage["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "relation": "result_of",
    }


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"decision_schema_version": "bad"},
            "cx.remediation_execution_boundary.schema_version_invalid",
        ),
        (
            {"owner_services": {"remediation_execution": "nex-ag"}},
            "cx.remediation_execution_boundary.owner_services_invalid",
        ),
        (
            {
                "action_execution_policy": {
                    "executable_by_cx": {"citation_repair": {}},
                    "ag_only": {},
                }
            },
            "cx.remediation_execution_boundary.action_policy_invalid",
        ),
        (
            {
                "lineage_contract": {
                    "parent_generation_id_required": False,
                    "original_generation_record_mutated": False,
                    "result_ref": {
                        "source_service": "nex-cx",
                        "ref_type": "repair_execution",
                        "relation": "result_of",
                    },
                }
            },
            "cx.remediation_execution_boundary.lineage_contract_invalid",
        ),
        (
            {
                "lineage_contract": {
                    "parent_generation_id_required": True,
                    "original_generation_record_mutated": True,
                    "result_ref": {
                        "source_service": "nex-cx",
                        "ref_type": "repair_execution",
                        "relation": "result_of",
                    },
                }
            },
            "cx.remediation_execution_boundary.lineage_contract_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["raw_generation_output"],
                    "raw_content_policy": {
                        "raw_prompt_stored": False,
                        "raw_generation_output_stored": False,
                        "raw_source_document_text_stored": False,
                        "raw_feedback_comment_stored": False,
                        "raw_operator_note_stored": False,
                        "raw_evidence_stored": False,
                        "credential_material_stored": False,
                        "provider_endpoint_stored": False,
                    },
                }
            },
            "cx.remediation_execution_boundary.safe_field_sensitive",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["remediation_action_id"],
                    "raw_content_policy": {"raw_prompt_stored": True},
                }
            },
            "cx.remediation_execution_boundary.raw_content_policy_invalid",
        ),
        (
            {"execution_stages": ["task_intake"]},
            "cx.remediation_execution_boundary.execution_stages_invalid",
        ),
    ],
)
def test_cx_remediation_execution_boundary_rejects_invalid_shapes(
    override: dict[str, object],
    error_code: str,
) -> None:
    decision = build_cx_remediation_execution_boundary_decision()
    decision.update(override)

    with pytest.raises(RemediationExecutionBoundaryError) as exc_info:
        validate_cx_remediation_execution_boundary_decision(decision)

    assert exc_info.value.error_code == error_code


def test_cx_remediation_execution_boundary_rejects_bad_executable_result_ref() -> None:
    decision = build_cx_remediation_execution_boundary_decision()
    decision["action_execution_policy"]["executable_by_cx"]["citation_repair"] = {
        "lineage_type": "repair",
        "result_ref_type": "generation_quality",
    }

    with pytest.raises(RemediationExecutionBoundaryError) as exc_info:
        validate_cx_remediation_execution_boundary_decision(decision)

    assert exc_info.value.error_code == (
        "cx.remediation_execution_boundary.action_policy_invalid"
    )


def test_cx_remediation_execution_boundary_rejects_bad_lineage_result_ref() -> None:
    decision = build_cx_remediation_execution_boundary_decision()
    decision["lineage_contract"]["result_ref"] = {
        "source_service": "nex-ag",
        "ref_type": "repair_execution",
        "relation": "result_of",
    }

    with pytest.raises(RemediationExecutionBoundaryError) as exc_info:
        validate_cx_remediation_execution_boundary_decision(decision)

    assert exc_info.value.error_code == (
        "cx.remediation_execution_boundary.lineage_contract_invalid"
    )


def test_cx_remediation_execution_intake_summary_accepts_citation_repair() -> None:
    summary = build_remediation_action_intake_summary(safe_remediation_action())

    assert summary["summary_schema_version"] == (
        "cx_remediation_execution_intake_summary.v1"
    )
    assert summary["remediation_action_id"] == "ag-remediation-action-001"
    assert summary["parent_cx_generation_id"] == "cx-gen-parent-001"
    assert summary["action_type"] == "citation_repair"
    assert summary["executable_by_cx"] is True
    assert summary["lineage_type"] == "repair"
    assert summary["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "relation": "result_of",
    }
    assert summary["source_ref_count"] == 2
    assert summary["evidence_hash_count"] == 1
    assert summary["evidence_preview_count"] == 1
    assert summary["redaction"]["raw_generation_output_included"] is False


def test_cx_remediation_execution_intake_summary_marks_ag_only_actions() -> None:
    summary = build_remediation_action_intake_summary(
        safe_remediation_action(action_type="prompt_policy_review")
    )

    assert summary["executable_by_cx"] is False
    assert summary["lineage_type"] is None
    assert summary["result_ref"] is None
    assert summary["non_executable_reason"] == "ag_owned_operator_state"


def test_cx_remediation_execution_intake_summary_marks_unknown_action() -> None:
    summary = build_remediation_action_intake_summary(
        safe_remediation_action(action_type="unexpected")
    )

    assert summary["executable_by_cx"] is False
    assert summary["non_executable_reason"] == "unknown_action_type"


def test_cx_remediation_execution_intake_summary_handles_sparse_payload() -> None:
    summary = build_remediation_action_intake_summary(
        {
            "source_refs": {"not": "a list"},
            "evidence": {
                "evidence_hashes": "not-a-list",
                "evidence_previews": "not-a-list",
                "raw_evidence_stored": False,
            },
        }
    )

    assert summary["remediation_action_id"] is None
    assert summary["parent_cx_generation_id"] is None
    assert summary["action_type"] == ""
    assert summary["executable_by_cx"] is False
    assert summary["non_executable_reason"] == "missing_action_type"
    assert summary["source_ref_count"] == 0
    assert summary["evidence_hash_count"] == 0
    assert summary["evidence_preview_count"] == 0


def test_cx_remediation_execution_lineage_helper_handles_action_types() -> None:
    assert remediation_lineage_type_for_action("retry_generation") == "retry"
    assert remediation_lineage_type_for_action("unknown") is None


def test_cx_remediation_execution_redaction_guard_accepts_false_policy_flags() -> None:
    action = safe_remediation_action()

    assert find_sensitive_cx_remediation_execution_keys(action) == []
    assert_cx_remediation_execution_payload_redaction_safe(action)


def test_cx_remediation_execution_redaction_guard_reports_nested_sensitive_keys() -> None:
    payload = {
        "remediation_action_id": "ag-remediation-action-001",
        "metadata": {
            "raw_prompt_stored": False,
            "raw_prompt": "do not store this",
        },
        "events": [{"provider_url": "http://internal.provider.local"}],
    }

    assert find_sensitive_cx_remediation_execution_keys(payload) == [
        "metadata.raw_prompt",
        "events[0].provider_url",
    ]
    with pytest.raises(RemediationExecutionBoundaryError) as exc_info:
        assert_cx_remediation_execution_payload_redaction_safe(payload)

    assert exc_info.value.error_code == (
        "cx.remediation_execution_payload.sensitive_key"
    )


def test_cx_remediation_execution_redaction_guard_rejects_true_raw_flag() -> None:
    action = safe_remediation_action(
        evidence={
            "evidence_hashes": ["a" * 64],
            "evidence_previews": ["preview"],
            "raw_evidence_stored": True,
        }
    )

    with pytest.raises(RemediationExecutionBoundaryError) as exc_info:
        build_remediation_action_intake_summary(action)

    assert exc_info.value.error_code == (
        "cx.remediation_execution_payload.sensitive_key"
    )
