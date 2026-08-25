from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from nex_ag.generation_remediation import (
    REMEDIATION_ACTION_SCHEMA_VERSION,
    GenerationRemediationError,
    build_generation_remediation_action,
    evidence_summary,
    hash_list,
    preview_list,
    reason_code_list,
    result_ref,
    source_ref_list,
)


ROOT = Path(__file__).parents[1]


def remediation_action_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "generation"
            / "ag_generation_remediation_action.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def remediation_action_example() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "examples"
            / "generation"
            / "ag_generation_remediation_action.citation_repair.json"
        ).read_text(encoding="utf-8")
    )


def remediation_action_negative_example() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "tests"
            / "negative"
            / "generation"
            / "ag_generation_remediation_action.raw_output_field.json"
        ).read_text(encoding="utf-8")
    )


def action_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "remediation_action_id": "ag-remediation-action-test",
        "tenant_id": "local-tenant",
        "action_type": "citation_repair",
        "priority": "HIGH",
        "reason_codes": [
            "negative_user_feedback",
            "citation_quality",
            "citation_quality",
        ],
        "owner_ref": {
            "owner_type": "user",
            "owner_id": "employee-0001",
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
                "ref_id": "ag-gq-disposition-001",
                "relation": "recommended_by",
            },
        ],
        "evidence_previews": [
            "Citation [2] did not support the generated answer.",
        ],
        "action_source": "operator_disposition",
    }
    payload.update(overrides)
    return payload


def build_action(**overrides: object) -> dict[str, object]:
    return build_generation_remediation_action(
        action_payload(**overrides),
        cx_generation_id="cx-gen-001",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )


def test_generation_remediation_action_example_matches_contract() -> None:
    Draft202012Validator(remediation_action_schema()).validate(
        remediation_action_example()
    )


def test_generation_remediation_negative_example_rejects_raw_output_field() -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(remediation_action_schema()).validate(
            remediation_action_negative_example()
        )


def test_generation_remediation_action_builder_matches_contract() -> None:
    action = build_action()

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert action["action_schema_version"] == REMEDIATION_ACTION_SCHEMA_VERSION
    assert action["action_status"] == "PROPOSED"
    assert action["priority"] == "HIGH"
    assert action["reason_codes"] == [
        "negative_user_feedback",
        "citation_quality",
    ]
    assert action["owner_ref"] == {
        "owner_type": "user",
        "owner_id": "employee-0001",
        "tenant_id": "local-tenant",
    }
    assert action["metadata"] == {
        "action_source": "operator_disposition",
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "raw_source_document_text_stored": False,
        "raw_feedback_comment_stored": False,
        "raw_operator_note_stored": False,
        "free_text_storage": "hash_and_short_preview_only",
    }
    assert action["evidence"]["raw_evidence_stored"] is False
    assert action["evidence"]["evidence_hashes"][0]


def test_generation_remediation_action_builder_defaults_owner_priority_and_id() -> None:
    action = build_generation_remediation_action(
        {
            "tenant_id": "local-tenant",
            "action_type": "retry_generation",
            "reason_codes": ["generation_quality"],
        },
        cx_generation_id="cx-gen-defaults",
        request_id="request-defaults",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        created_at="2026-08-25T00:00:00Z",
    )

    assert action["remediation_action_id"]
    assert action["priority"] == "NORMAL"
    assert action["owner_ref"] == {
        "owner_type": "service",
        "owner_id": "nex-ag",
        "tenant_id": "local-tenant",
    }
    assert action["source_refs"] == []
    assert action["result_ref"] is None


def test_generation_remediation_action_builder_accepts_result_ref() -> None:
    action = build_action(
        result_ref={
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "cx-repair-run-001",
        },
        action_status="COMPLETED",
    )

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert action["result_ref"] == {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "cx-repair-run-001",
        "relation": "result_of",
    }


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({}, "ag.generation_remediation_action_type_required"),
        (
            {"action_type": "unknown"},
            "ag.generation_remediation_action_type_unsupported",
        ),
        (
            {"action_type": "citation_repair", "action_status": "DONE"},
            "ag.generation_remediation_action_status_unsupported",
        ),
        (
            {"action_type": "citation_repair", "priority": "SOON"},
            "ag.generation_remediation_priority_unsupported",
        ),
        (
            {"action_type": "citation_repair", "owner_ref": "bad"},
            "ag.generation_remediation_owner_ref_invalid",
        ),
        (
            {"action_type": "citation_repair", "reason_codes": "bad"},
            "ag.generation_remediation_reason_codes_invalid",
        ),
        (
            {"action_type": "citation_repair", "reason_codes": ["bad"]},
            "ag.generation_remediation_reason_code_unsupported",
        ),
        (
            {"action_type": "citation_repair", "source_refs": "bad"},
            "ag.generation_remediation_source_refs_invalid",
        ),
        (
            {"action_type": "citation_repair", "source_refs": ["bad"]},
            "ag.generation_remediation_source_ref_invalid",
        ),
        (
            {"action_type": "citation_repair", "result_ref": "bad"},
            "ag.generation_remediation_result_ref_invalid",
        ),
        (
            {
                "action_type": "citation_repair",
                "result_ref": {
                    "source_service": "nex-ae-api",
                    "ref_type": "repair_execution",
                    "ref_id": "bad-result-source",
                },
            },
            "ag.generation_remediation_source_service_unsupported",
        ),
        (
            {"action_type": "citation_repair", "evidence_hashes": ["not-sha"]},
            "ag.generation_remediation_evidence_hash_invalid",
        ),
        (
            {"action_type": "citation_repair", "raw_generation_output": "bad"},
            "ag.generation_remediation_sensitive_payload",
        ),
    ],
)
def test_generation_remediation_action_builder_rejects_invalid_payloads(
    overrides: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(GenerationRemediationError) as exc_info:
        build_generation_remediation_action(
            overrides,
            cx_generation_id="cx-gen-001",
            request_id="request-invalid",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            created_at="2026-08-25T00:00:00Z",
        )

    assert exc_info.value.error_code == error_code


def test_generation_remediation_action_builder_requires_generation_id() -> None:
    with pytest.raises(GenerationRemediationError) as exc_info:
        build_generation_remediation_action(
            {"action_type": "retry_generation"},
            cx_generation_id=" ",
            request_id="request-invalid",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )

    assert exc_info.value.error_code == (
        "ag.generation_remediation_cx_generation_id_required"
    )


def test_generation_remediation_list_helpers_cover_invalid_and_dedup_paths() -> None:
    assert reason_code_list(["other", "other"]) == ["other"]
    assert source_ref_list(None) == []
    assert evidence_summary(
        {
            "evidence_hashes": ["a" * 64, "a" * 64],
            "evidence_previews": ["preview", "preview"],
        }
    ) == {
        "evidence_hashes": ["a" * 64],
        "evidence_previews": ["preview"],
        "raw_evidence_stored": False,
    }

    with pytest.raises(GenerationRemediationError):
        hash_list("bad")
    with pytest.raises(GenerationRemediationError):
        preview_list("bad")
    with pytest.raises(GenerationRemediationError):
        result_ref({"source_service": "nex-cx", "ref_type": "bad", "ref_id": "x"})
