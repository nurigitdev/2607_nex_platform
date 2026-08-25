from __future__ import annotations

import pytest

from nex_ag.generation_remediation_boundary import (
    AE_FEEDBACK_OWNER_SERVICE,
    AG_REMEDIATION_OWNER_SERVICE,
    CX_REPAIR_EXECUTION_OWNER_SERVICE,
    GENERATION_REMEDIATION_BOUNDARY_DECISION_VERSION,
    MO_MODEL_EXECUTION_OWNER_SERVICE,
    GenerationRemediationBoundaryError,
    assert_generation_remediation_payload_redaction_safe,
    build_generation_remediation_boundary_decision,
    find_sensitive_generation_remediation_keys,
    remediation_transition_allowed,
    validate_generation_remediation_boundary_decision,
)


def test_generation_remediation_boundary_decision_assigns_owner_services() -> None:
    decision = validate_generation_remediation_boundary_decision(
        build_generation_remediation_boundary_decision()
    )

    assert decision["decision_schema_version"] == (
        GENERATION_REMEDIATION_BOUNDARY_DECISION_VERSION
    )
    assert decision["owner_services"] == {
        "remediation_orchestration": AG_REMEDIATION_OWNER_SERVICE,
        "generation_lineage_and_repair_execution": CX_REPAIR_EXECUTION_OWNER_SERVICE,
        "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
        "model_provider_execution": MO_MODEL_EXECUTION_OWNER_SERVICE,
    }
    assert decision["storage_contract"]["raw_content_policy"] == {
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_document_text_stored": False,
        "raw_feedback_comment_stored": False,
        "raw_operator_note_stored": False,
        "credential_material_stored": False,
        "free_text_storage": "hash_and_short_preview_only",
    }
    assert "remediation_id" in decision["storage_contract"]["safe_fields"]
    assert "evidence_hashes" in decision["storage_contract"]["safe_fields"]
    assert "raw_prompt" not in decision["storage_contract"]["safe_fields"]
    assert decision["next_slices"]["0345"].startswith(
        "prove remediation task persistence"
    )


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"decision_schema_version": "bad"},
            "ag.remediation_boundary.schema_version_invalid",
        ),
        (
            {"owner_services": {"remediation_orchestration": "nex-cx"}},
            "ag.remediation_boundary.owner_services_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["remediation_id"],
                    "raw_content_policy": {"raw_prompt_stored": True},
                }
            },
            "ag.remediation_boundary.raw_content_policy_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["remediation_id", "raw_generation_output"],
                    "raw_content_policy": {
                        "raw_prompt_stored": False,
                        "raw_generation_output_stored": False,
                        "raw_source_document_text_stored": False,
                        "raw_feedback_comment_stored": False,
                        "raw_operator_note_stored": False,
                        "credential_material_stored": False,
                    },
                    "status_transitions": {
                        "PROPOSED": ["ASSIGNED", "IN_PROGRESS", "CANCELLED"],
                        "ASSIGNED": ["IN_PROGRESS", "CANCELLED"],
                        "IN_PROGRESS": [
                            "WAITING_ON_CX",
                            "COMPLETED",
                            "FAILED",
                            "CANCELLED",
                        ],
                        "WAITING_ON_CX": [
                            "IN_PROGRESS",
                            "COMPLETED",
                            "FAILED",
                            "CANCELLED",
                        ],
                        "COMPLETED": [],
                        "FAILED": [],
                        "CANCELLED": [],
                    },
                }
            },
            "ag.remediation_boundary.safe_field_sensitive",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["remediation_id"],
                    "raw_content_policy": {
                        "raw_prompt_stored": False,
                        "raw_generation_output_stored": False,
                        "raw_source_document_text_stored": False,
                        "raw_feedback_comment_stored": False,
                        "raw_operator_note_stored": False,
                        "credential_material_stored": False,
                    },
                    "status_transitions": {"PROPOSED": ["COMPLETED"]},
                }
            },
            "ag.remediation_boundary.status_transitions_invalid",
        ),
    ],
)
def test_generation_remediation_boundary_decision_rejects_invalid_shape(
    override: dict[str, object],
    error_code: str,
) -> None:
    decision = build_generation_remediation_boundary_decision()
    decision.update(override)

    with pytest.raises(GenerationRemediationBoundaryError) as exc_info:
        validate_generation_remediation_boundary_decision(decision)

    assert exc_info.value.error_code == error_code


def test_generation_remediation_redaction_guard_reports_nested_sensitive_keys() -> None:
    payload = {
        "remediation_intent": "citation_repair",
        "metadata": {
            "evidence_hashes": ["a" * 64],
            "raw_prompt": "do not store this",
        },
        "events": [{"raw_generation_output": "do not store this"}],
    }

    assert find_sensitive_generation_remediation_keys(payload) == [
        "metadata.raw_prompt",
        "events[0].raw_generation_output",
    ]
    with pytest.raises(GenerationRemediationBoundaryError) as exc_info:
        assert_generation_remediation_payload_redaction_safe(payload)

    assert exc_info.value.error_code == "ag.remediation_payload.sensitive_key"


def test_generation_remediation_redaction_guard_accepts_safe_refs() -> None:
    payload = {
        "remediation_id": "ag-remediation-001",
        "remediation_intent": "citation_repair",
        "feedback_refs": [{"feedback_id": "ae-feedback-001"}],
        "evidence_hashes": ["a" * 64],
        "evidence_previews": ["Citation [2] did not support the answer."],
    }

    assert_generation_remediation_payload_redaction_safe(payload)


def test_generation_remediation_status_transition_policy() -> None:
    assert remediation_transition_allowed("PROPOSED", "ASSIGNED") is True
    assert remediation_transition_allowed("PROPOSED", "COMPLETED") is False
    assert remediation_transition_allowed("IN_PROGRESS", "WAITING_ON_CX") is True
    assert remediation_transition_allowed("WAITING_ON_CX", "IN_PROGRESS") is True
    assert remediation_transition_allowed("COMPLETED", "IN_PROGRESS") is False
    assert remediation_transition_allowed("UNKNOWN", "IN_PROGRESS") is False
