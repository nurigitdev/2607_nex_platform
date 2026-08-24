from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nex_ae_api.generation_feedback import (
    GenerationFeedbackError,
    build_generation_feedback_record,
    feedback_reason_list,
    quality_issue_refs,
)
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


ROOT = Path(__file__).parents[1]


def generation_feedback_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "generation_feedback.v1.schema.json"
        ).read_text(encoding="utf-8")
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


def feedback_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": "local-tenant",
        "user_id": "employee-0001",
        "interaction_id": "ae-chat-001",
        "chat_document_id": "ae-chat-doc-001",
        "cx_generation_id": "cx-gen-001",
        "feedback_value": "negative",
        "feedback_reasons": ["citation_issue", "incomplete", "citation_issue"],
        "feedback_comment": "Citation [2] did not support the answer.",
        "quality_issue_refs": [
            {
                "source_service": "nex-cx",
                "issue_type": "citation_quality",
                "issue_code": "citation_missing",
                "issue_ref_id": "cx-gen-001",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_generation_feedback_record_hashes_comment_and_matches_schema() -> None:
    record = build_generation_feedback_record(
        feedback_payload(),
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    Draft202012Validator(generation_feedback_schema()).validate(record)
    assert record["feedback_schema_version"] == "ae_generation_feedback.v1"
    assert record["status"] == "RECORDED"
    assert record["feedback_reasons"] == ["citation_issue", "incomplete"]
    assert record["feedback_comment_hash"] == (
        "7e7ea00cfe346b8b19b334702341bf0d8c4eb2d7dabf8086"
        "763feba20375fecd"
    )
    assert record["feedback_comment_preview"] == (
        "Citation [2] did not support the answer."
    )
    assert "feedback_comment" not in record
    assert record["metadata"]["raw_prompt_stored"] is False
    assert record["metadata"]["raw_generation_output_stored"] is False


def test_generation_feedback_record_allows_empty_optional_links() -> None:
    record = build_generation_feedback_record(
        feedback_payload(
            feedback_value="positive",
            feedback_reasons=["helpful"],
            feedback_comment=None,
            chat_document_id="",
            cx_generation_id="",
            quality_issue_refs=None,
            submitted_via="document_detail",
        ),
        request_id="req-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-24T00:00:00Z",
    )

    assert record["chat_document_id"] is None
    assert record["cx_generation_id"] is None
    assert record["feedback_comment_hash"] is None
    assert record["feedback_comment_preview"] is None
    assert record["quality_issue_refs"] == []
    assert record["metadata"]["submitted_via"] == "document_detail"


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        ({"tenant_id": ""}, "ae.generation_feedback_tenant_id_required"),
        (
            {"feedback_value": "angry"},
            "ae.generation_feedback_feedback_value_unsupported",
        ),
        (
            {"feedback_reasons": "citation_issue"},
            "ae.generation_feedback_reasons_invalid",
        ),
        (
            {"feedback_reasons": ["unsupported"]},
            "ae.generation_feedback_reason_unsupported",
        ),
        (
            {"quality_issue_refs": "bad"},
            "ae.generation_feedback_quality_refs_invalid",
        ),
        (
            {"quality_issue_refs": [{"source_service": "nex-cx"}]},
            "ae.generation_feedback_issue_type_required",
        ),
        (
            {"raw_prompt": "never persist"},
            "ae.generation_feedback_sensitive_payload",
        ),
    ],
)
def test_generation_feedback_record_rejects_invalid_payloads(
    override: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        build_generation_feedback_record(
            feedback_payload(**override),
            request_id="req-001",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            created_at="2026-08-24T00:00:00Z",
        )

    assert exc_info.value.error_code == error_code


def test_feedback_reason_list_accepts_missing_and_rejects_bad_items() -> None:
    assert feedback_reason_list(None) == []

    with pytest.raises(GenerationFeedbackError) as exc_info:
        feedback_reason_list([""])

    assert exc_info.value.error_code == "ae.generation_feedback_reason_invalid"


def test_quality_issue_refs_rejects_non_object_items() -> None:
    with pytest.raises(GenerationFeedbackError) as exc_info:
        quality_issue_refs(["bad"])

    assert exc_info.value.error_code == "ae.generation_feedback_quality_ref_invalid"
