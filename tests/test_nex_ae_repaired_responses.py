from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from nex_ae_api.repaired_responses import (
    AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION,
    DEFAULT_HANDOFF_STATUS,
    RepairedResponseHandoffError,
    actor_claims_ref_from_payload,
    assert_repaired_response_handoff_redaction_safe,
    build_repaired_response_handoff_record,
    find_sensitive_repaired_response_handoff_keys,
    presentation_mode_from_payload,
    validate_repaired_response_handoff_record,
)


ROOT = Path(__file__).parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def repaired_response_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "repaired_response_handoff.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def source_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tenant_id": "tenant-001",
        "workspace_id": "workspace-001",
        "owner_user_id": "user-001",
        "chat_document_id": "chat-doc-001",
        "interaction_id": "interaction-001",
        "original_cx_generation_id": "cx-gen-001",
        "handoff_request_id": "ae-repaired-request-001",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "user-001",
            "tenant_id": "tenant-001",
        },
    }
    payload.update(overrides)
    return payload


def cx_remediation_detail(**overrides: Any) -> dict[str, Any]:
    lineage = {
        "lineage_schema_version": "cx_repaired_generation_lineage.v1",
        "lineage_status": "LINKED",
        "parent_cx_generation_id": "cx-gen-001",
        "root_cx_generation_id": "cx-gen-001",
        "repair_cx_generation_id": "cx-gen-repair-001",
        "remediation_action_id": "ag-remediation-action-001",
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "SUCCEEDED",
        "attempt_no": 1,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": "ag-remediation-action-001",
            "relation": "result_of",
        },
        "diagnostics": {
            "lineage_consistent": True,
            "repair_generation_linked": True,
            "result_ref_present": True,
            "result_ref_matches_remediation_action": True,
            "parent_generation_mutated": False,
        },
        "debug_paths": {
            "parent_generation_path": "/api/v1/generations/cx-gen-001",
            "root_generation_path": "/api/v1/generations/cx-gen-001",
            "repair_generation_path": "/api/v1/generations/cx-gen-repair-001",
            "cx_remediation_execution_path": (
                "/api/v1/generations/cx-gen-001/remediation-executions/"
                "ag-remediation-action-001"
            ),
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail = {
        "detail_schema_version": "cx_remediation_execution_detail.v1",
        "projection_status": "READY",
        "checked_at": "2026-08-27T00:00:00Z",
        "parent_cx_generation_id": "cx-gen-001",
        "remediation_action_id": "ag-remediation-action-001",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "execution_status": "SUCCEEDED",
        "execution": {
            "result_schema_version": "cx_remediation_execution_result.v1",
            "remediation_action_id": "ag-remediation-action-001",
            "parent_cx_generation_id": "cx-gen-001",
            "repair_cx_generation_id": "cx-gen-repair-001",
            "execution_status": "SUCCEEDED",
        },
        "repaired_generation_lineage": lineage,
        "attention_required": False,
        "debug_paths": {},
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    detail.update(overrides)
    return detail


def repaired_generation_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": "cx-gen-repair-001",
        "status": "COMPLETED",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": "mo-gen-repair-001",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "response_format_type": "text",
            "source_has_messages": True,
            "source_has_prompt": False,
            "grounding_required": True,
            "retrieval_package_id": "cx-ret-001",
            "retrieval_package_hash": "d" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": "draft-repair-001",
            "draft_validation_status": "VALIDATED",
            "grounded_response_quality_status": "PASS",
            "grounded_response_quality_issue_count": 0,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "c" * 64,
            "output_preview": "Repaired answer with citation support.",
        },
        "mo_runtime_metadata": {
            "request_id": REQUEST_ID,
            "trace_id": TRACE_ID,
        },
        "usage": {
            "input_tokens": 12,
            "output_tokens": 16,
            "total_tokens": 28,
        },
        "created_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
    }
    record.update(overrides)
    return record


def build_handoff(
    *,
    payload: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_repaired_response_handoff_record(
        source_payload=payload or source_payload(),
        cx_remediation_detail=detail or cx_remediation_detail(),
        repaired_generation_record=generation or repaired_generation_record(),
        handoff_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-27T00:00:00Z",
    )


def test_build_repaired_response_handoff_record_is_schema_valid_and_raw_safe() -> None:
    record = build_handoff()

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["handoff_schema_version"] == AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION
    assert record["handoff_status"] == DEFAULT_HANDOFF_STATUS
    assert record["source"]["parent_cx_generation_id"] == "cx-gen-001"
    assert record["source"]["repair_cx_generation_id"] == "cx-gen-repair-001"
    assert record["source"]["result_ref"]["ref_id"] == "ag-remediation-action-001"
    assert record["repaired_response"]["output_hash"] == "c" * 64
    assert record["repaired_response"]["output_preview"] == (
        "Repaired answer with citation support."
    )
    assert record["lineage"]["parent_generation_mutated"] is False
    assert record["user_surface"]["presentation_mode"] == "side_by_side_review"
    assert record["user_surface"]["available_actions"] == [
        "view_original",
        "view_repaired",
        "accept_repair",
        "keep_original",
        "view_lineage",
    ]
    serialized = json.dumps(record, sort_keys=True)
    assert "raw answer body" not in serialized
    assert "hidden prompt" not in serialized
    assert "/data/nex-platform" not in serialized


def test_repaired_response_handoff_defaults_ids_actor_and_nullable_refs() -> None:
    detail = cx_remediation_detail()
    detail["repaired_generation_lineage"]["result_ref"] = {
        "source_service": "nex-ag",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
        "relation": "result_of",
    }
    generation = repaired_generation_record(
        response_metadata={
            "finish_reason": "STOP",
            "output_hash": None,
            "output_preview": "x" * 140,
        },
        request_metadata={
            "grounding_required": False,
            "grounded_response_quality_issue_count": -1,
        },
        usage={},
    )
    record = build_handoff(
        payload=source_payload(
            handoff_request_id=None,
            actor_claims_ref={},
            presentation_mode="append_revision_note",
        ),
        detail=detail,
        generation=generation,
    )

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["source"]["result_ref"] is None
    assert record["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-001",
        "tenant_id": "tenant-001",
    }
    assert record["repaired_response"]["output_hash"] is None
    assert record["repaired_response"]["output_preview"] == "x" * 120
    assert record["repaired_response"]["quality_summary"] == {
        "grounding_required": False,
        "retrieval_package_id": None,
        "retrieval_package_hash": None,
        "structured_draft_id": None,
        "draft_validation_status": None,
        "grounded_response_quality_status": None,
        "grounded_response_quality_issue_count": 0,
    }
    assert record["user_surface"]["presentation_mode"] == "append_revision_note"


def test_repaired_response_handoff_covers_runtime_default_edges() -> None:
    detail = cx_remediation_detail()
    detail["repaired_generation_lineage"]["result_ref"] = {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": "ag-remediation-action-001",
    }
    record = build_repaired_response_handoff_record(
        source_payload=source_payload(handoff_request_id=None),
        cx_remediation_detail=detail,
        repaired_generation_record=repaired_generation_record(
            request_metadata={
                "grounded_response_quality_issue_count": True,
            }
        ),
        handoff_request_id=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    Draft202012Validator(repaired_response_schema()).validate(record)
    assert record["created_at"].endswith("Z")
    assert record["updated_at"] == record["created_at"]
    assert record["source"]["result_ref"] is None
    assert (
        record["repaired_response"]["quality_summary"][
            "grounded_response_quality_issue_count"
        ]
        == 0
    )


@pytest.mark.parametrize(
    ("detail_override", "generation_override", "payload_override", "error_code"),
    [
        (
            {"detail_schema_version": "old"},
            {},
            {},
            "ae.repaired_response_cx_detail_invalid",
        ),
        (
            {"execution_status": "RUNNING"},
            {},
            {},
            "ae.repaired_response_execution_not_succeeded",
        ),
        (
            {
                "repaired_generation_lineage": {
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "lineage_status": "PENDING_REPAIR_GENERATION",
                }
            },
            {},
            {},
            "ae.repaired_response_lineage_not_linked",
        ),
        (
            {
                "repaired_generation_lineage": {
                    **cx_remediation_detail()["repaired_generation_lineage"],
                    "diagnostics": {
                        "lineage_consistent": False,
                        "parent_generation_mutated": False,
                    },
                }
            },
            {},
            {},
            "ae.repaired_response_lineage_invalid",
        ),
        (
            {},
            {"record_schema_version": "old"},
            {},
            "ae.repaired_response_generation_invalid",
        ),
        (
            {},
            {"cx_generation_id": "cx-gen-other"},
            {},
            "ae.repaired_response_generation_mismatch",
        ),
        (
            {},
            {"status": "FAILED"},
            {},
            "ae.repaired_response_generation_not_completed",
        ),
        (
            {},
            {},
            {"original_cx_generation_id": "cx-gen-other"},
            "ae.repaired_response_original_generation_mismatch",
        ),
        (
            {},
            {},
            {"presentation_mode": "raw_replace"},
            "ae.repaired_response_presentation_mode_invalid",
        ),
        (
            {},
            {},
            {"tenant_id": " "},
            "ae.repaired_response_tenant_id_required",
        ),
    ],
)
def test_repaired_response_handoff_rejects_invalid_boundaries(
    detail_override: dict[str, Any],
    generation_override: dict[str, Any],
    payload_override: dict[str, Any],
    error_code: str,
) -> None:
    detail = cx_remediation_detail()
    detail.update(detail_override)
    generation = repaired_generation_record()
    generation.update(generation_override)
    payload = source_payload(**payload_override)

    with pytest.raises(RepairedResponseHandoffError) as exc_info:
        build_handoff(payload=payload, detail=detail, generation=generation)

    assert exc_info.value.error_code == error_code


def test_validate_repaired_response_handoff_record_rejects_mutations() -> None:
    record = build_handoff()

    bad_schema = {**record, "handoff_schema_version": "old"}
    bad_status = {**record, "handoff_status": "PENDING"}
    bad_lineage = deepcopy(record)
    bad_lineage["lineage"]["repair_cx_generation_id"] = "cx-gen-other"
    bad_parent_mutation = deepcopy(record)
    bad_parent_mutation["lineage"]["parent_generation_mutated"] = True
    bad_redaction = deepcopy(record)
    bad_redaction["redaction_summary"]["raw_output_included"] = True

    for candidate, error_code in (
        (bad_schema, "ae.repaired_response_handoff_schema_invalid"),
        (bad_status, "ae.repaired_response_handoff_status_invalid"),
        (bad_lineage, "ae.repaired_response_lineage_mismatch"),
        (bad_parent_mutation, "ae.repaired_response_parent_mutation_forbidden"),
        (bad_redaction, "ae.repaired_response_redaction_invalid"),
    ):
        with pytest.raises(RepairedResponseHandoffError) as exc_info:
            validate_repaired_response_handoff_record(candidate)
        assert exc_info.value.error_code == error_code


def test_repaired_response_handoff_redaction_guard_rejects_sensitive_payloads() -> None:
    with pytest.raises(RepairedResponseHandoffError) as raw_key_error:
        build_handoff(payload=source_payload(raw_prompt="hidden prompt"))

    assert raw_key_error.value.error_code == "ae.repaired_response_sensitive_payload"
    assert find_sensitive_repaired_response_handoff_keys(
        {"items": [{"raw_prompt": "hidden"}]}
    ) == ["items[0].raw_prompt"]

    with pytest.raises(RepairedResponseHandoffError) as content_error:
        assert_repaired_response_handoff_redaction_safe(
            {"safe_key": "raw answer body"}
        )

    assert content_error.value.error_code == "ae.repaired_response_sensitive_payload"


def test_repaired_response_handoff_helpers_cover_optional_edges() -> None:
    assert presentation_mode_from_payload({}) == "side_by_side_review"
    assert presentation_mode_from_payload(
        {"presentation_mode": "replace_answer_candidate"}
    ) == "replace_answer_candidate"
    assert actor_claims_ref_from_payload(
        {
            "tenant_id": "tenant-001",
            "owner_user_id": "user-001",
            "actor_claims_ref": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "tenant_id": "tenant-001",
            },
        }
    ) == {
        "actor_type": "service",
        "actor_id": "nex-ag",
        "tenant_id": "tenant-001",
    }
    assert str(
        RepairedResponseHandoffError(
            status_code=422,
            error_code="example",
            detail="readable detail",
        )
    ) == "readable detail"
