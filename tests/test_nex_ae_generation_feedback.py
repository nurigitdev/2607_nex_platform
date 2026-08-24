from __future__ import annotations

import pytest

from nex_ae_api.generation_feedback_boundary import (
    AE_FEEDBACK_OWNER_SERVICE,
    AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
    CX_GENERATION_LINEAGE_OWNER_SERVICE,
    GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION,
    GenerationFeedbackBoundaryError,
    assert_feedback_payload_redaction_safe,
    build_generation_feedback_boundary_decision,
    find_sensitive_feedback_keys,
    validate_generation_feedback_boundary_decision,
)


def test_generation_feedback_boundary_decision_assigns_owner_services() -> None:
    decision = validate_generation_feedback_boundary_decision(
        build_generation_feedback_boundary_decision()
    )

    assert decision["decision_schema_version"] == (
        GENERATION_FEEDBACK_BOUNDARY_DECISION_VERSION
    )
    assert decision["owner_services"] == {
        "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
        "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
        "operator_disposition": AG_OPERATOR_DISPOSITION_OWNER_SERVICE,
    }
    assert decision["storage_contract"]["raw_content_policy"] == {
        "raw_user_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_document_text_stored": False,
        "credential_material_stored": False,
        "free_text_comment_storage": "hash_and_short_preview_only",
    }
    assert "feedback_comment_hash" in decision["storage_contract"]["safe_fields"]
    assert "feedback_comment_preview" in decision["storage_contract"]["safe_fields"]
    assert "raw_prompt" not in decision["storage_contract"]["safe_fields"]


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (
            {"decision_schema_version": "bad"},
            "ae.feedback_boundary.schema_version_invalid",
        ),
        (
            {"owner_services": {"user_feedback_intake": "nex-cx"}},
            "ae.feedback_boundary.owner_services_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["feedback_id"],
                    "raw_content_policy": {"raw_user_prompt_stored": True},
                }
            },
            "ae.feedback_boundary.raw_content_policy_invalid",
        ),
        (
            {
                "storage_contract": {
                    "safe_fields": ["feedback_id", "raw_output"],
                    "raw_content_policy": {
                        "raw_user_prompt_stored": False,
                        "raw_generation_output_stored": False,
                        "raw_source_document_text_stored": False,
                        "credential_material_stored": False,
                    },
                }
            },
            "ae.feedback_boundary.safe_field_sensitive",
        ),
    ],
)
def test_generation_feedback_boundary_decision_rejects_invalid_shape(
    override: dict[str, object],
    error_code: str,
) -> None:
    decision = build_generation_feedback_boundary_decision()
    decision.update(override)

    with pytest.raises(GenerationFeedbackBoundaryError) as exc_info:
        validate_generation_feedback_boundary_decision(decision)

    assert exc_info.value.error_code == error_code


def test_feedback_payload_redaction_guard_reports_nested_sensitive_keys() -> None:
    payload = {
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue"],
        "metadata": {
            "quality_issue_refs": [{"issue_code": "citation_missing"}],
            "raw_prompt": "should not be stored",
        },
        "comments": [{"raw_generation_output": "should not be stored"}],
    }

    assert find_sensitive_feedback_keys(payload) == [
        "metadata.raw_prompt",
        "comments[0].raw_generation_output",
    ]
    with pytest.raises(GenerationFeedbackBoundaryError) as exc_info:
        assert_feedback_payload_redaction_safe(payload)

    assert exc_info.value.error_code == "ae.feedback_payload.sensitive_key"


def test_feedback_payload_redaction_guard_accepts_hash_and_preview_only() -> None:
    payload = {
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue"],
        "feedback_comment_hash": "a" * 64,
        "feedback_comment_preview": "Citation [2] did not support the answer.",
        "quality_issue_refs": [{"issue_code": "citation_missing"}],
    }

    assert_feedback_payload_redaction_safe(payload)
