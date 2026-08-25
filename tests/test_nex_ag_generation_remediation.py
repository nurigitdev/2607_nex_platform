from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from nex_ag.generation_remediation import (
    REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION,
    REMEDIATION_ACTION_SCHEMA_VERSION,
    GenerationRemediationError,
    build_generation_remediation_candidate_projection,
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


def rollup_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "cx_generation_id": "cx-gen-001",
        "tenant_id": "local-tenant",
        "attention_status": "OPEN",
        "severity": "WARNING",
        "quality": {
            "count": 1,
            "attention_required": True,
            "max_severity": "WARNING",
            "coverage_statuses": ["READY"],
            "boundary_statuses": ["OK"],
            "issue_codes": ["CITATION_MISSING"],
            "recommended_actions": ["repair_citation"],
        },
        "feedback": {
            "count": 1,
            "negative_count": 1,
            "latest_feedback_id": "ae-feedback-001",
        },
        "disposition": {
            "count": 1,
            "latest_disposition_id": "ag-gq-disposition-001",
            "latest_status": "IN_REPAIR",
            "latest_action": "needs_cx_repair",
        },
    }
    item.update(overrides)
    return item


def build_projection(items: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "rollup_items": items,
        "request_id": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "checked_at": "2026-08-25T00:00:00Z",
    }
    kwargs.update(overrides)
    return build_generation_remediation_candidate_projection(**kwargs)


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


def test_generation_remediation_error_stringifies_detail() -> None:
    error = GenerationRemediationError(
        status_code=422,
        error_code="ag.generation_remediation_test",
        detail="human readable detail",
    )

    assert str(error) == "human readable detail"


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


def test_generation_remediation_candidate_projection_builds_citation_repair() -> None:
    projection = build_projection([rollup_item()])
    candidate = projection["items"][0]
    action = candidate["action"]

    Draft202012Validator(remediation_action_schema()).validate(action)
    assert projection["projection_schema_version"] == (
        REMEDIATION_CANDIDATE_PROJECTION_SCHEMA_VERSION
    )
    assert projection["summary"] == {
        "candidate_count": 1,
        "returned_count": 1,
        "by_action_type": {"citation_repair": 1},
        "by_priority": {"HIGH": 1},
        "skipped_count": 0,
    }
    assert candidate["candidate_reason"] == "operator_requested_cx_repair"
    assert action["action_type"] == "citation_repair"
    assert action["reason_codes"] == [
        "negative_user_feedback",
        "operator_requested_repair",
        "citation_quality",
    ]
    assert action["metadata"]["action_source"] == "operator_disposition"
    assert action["source_refs"] == [
        {
            "source_service": "nex-ag",
            "ref_type": "generation_quality",
            "ref_id": "cx-gen-001",
            "relation": "caused_by",
        },
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
    ]


def test_generation_remediation_candidate_projection_selects_retrieval_repair() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-retrieval",
                severity="ERROR",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["NO_ANSWER_FOR_SCOPE"],
                    "coverage_statuses": ["NO_ANSWER"],
                    "boundary_statuses": [],
                    "recommended_actions": ["repair_retrieval"],
                },
                feedback={"negative_count": 0},
                disposition={"latest_status": None, "latest_action": None},
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert action["action_type"] == "retrieval_repair"
    assert action["priority"] == "URGENT"
    assert action["reason_codes"] == ["retrieval_quality"]
    assert action["metadata"]["action_source"] == "candidate_projection"


def test_generation_remediation_candidate_projection_selects_retry_generation() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-retry",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["METADATA_GAP_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"],
                    "coverage_statuses": [],
                    "boundary_statuses": [],
                    "recommended_actions": [],
                },
                feedback={"negative_count": 0},
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-retry",
                    "latest_action": "needs_cx_repair",
                    "latest_status": "IN_REPAIR",
                },
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert action["action_type"] == "retry_generation"
    assert action["reason_codes"] == [
        "operator_requested_repair",
        "generation_quality",
        "metadata_gap",
    ]


def test_generation_remediation_candidate_projection_uses_operator_followup() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-feedback-only",
                quality={
                    "count": 0,
                    "attention_required": False,
                    "issue_codes": [],
                    "coverage_statuses": [],
                    "boundary_statuses": [],
                    "recommended_actions": [],
                },
                feedback={"negative_count": 3, "latest_feedback_id": "ae-feedback-003"},
                disposition={"latest_action": None, "latest_disposition_id": None},
            )
        ]
    )
    action = projection["items"][0]["action"]

    assert projection["items"][0]["candidate_reason"] == (
        "negative_feedback_needs_triage"
    )
    assert action["action_type"] == "operator_followup"
    assert action["priority"] == "HIGH"
    assert action["reason_codes"] == ["negative_user_feedback"]


def test_generation_remediation_candidate_projection_skips_closed_ok_and_missing_ids() -> None:
    projection = build_projection(
        [
            rollup_item(cx_generation_id="cx-gen-ok", attention_status="OK"),
            rollup_item(cx_generation_id="cx-gen-closed", attention_status="CLOSED"),
            rollup_item(cx_generation_id=" "),
        ]
    )

    assert projection["items"] == []
    assert projection["summary"]["candidate_count"] == 0
    assert projection["summary"]["skipped_count"] == 3


def test_generation_remediation_candidate_projection_sorts_and_limits_candidates() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-normal",
                severity="INFO",
                feedback={"negative_count": 0},
                disposition={"latest_action": None},
                quality={"count": 1, "attention_required": True, "issue_codes": []},
            ),
            rollup_item(
                cx_generation_id="cx-gen-urgent",
                severity="ERROR",
                quality={"count": 1, "attention_required": True, "issue_codes": []},
            ),
        ],
        limit=1,
    )

    assert projection["summary"]["candidate_count"] == 2
    assert projection["summary"]["returned_count"] == 1
    assert projection["items"][0]["cx_generation_id"] == "cx-gen-urgent"


def test_generation_remediation_candidate_projection_accepts_generator_and_bad_limit() -> None:
    projection = build_generation_remediation_candidate_projection(
        rollup_items=(item for item in [rollup_item()]),
        request_id="request-generator",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        limit="bad",  # type: ignore[arg-type]
    )

    assert projection["summary"]["returned_count"] == 1
    assert projection["redaction_summary"] == {
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_feedback_comment_included": False,
        "raw_operator_note_included": False,
    }


def test_generation_remediation_candidate_projection_covers_operator_branches() -> None:
    projection = build_projection(
        [
            rollup_item(
                cx_generation_id="cx-gen-ae-followup",
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-ae",
                    "latest_action": "needs_ae_followup",
                    "latest_status": "IN_REPAIR",
                },
            ),
            rollup_item(
                cx_generation_id="cx-gen-escalated",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": 0},
                disposition={
                    "latest_disposition_id": "ag-gq-disposition-escalated",
                    "latest_action": "escalated",
                    "latest_status": "ESCALATED",
                },
            ),
            rollup_item(
                cx_generation_id="cx-gen-in-progress",
                attention_status="IN_PROGRESS",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": "not-a-number"},
                disposition={},
            ),
            rollup_item(
                cx_generation_id="cx-gen-open-fallback",
                severity="INFO",
                quality={
                    "count": 1,
                    "attention_required": True,
                    "issue_codes": ["UNCLASSIFIED_WARNING"],
                },
                feedback={"negative_count": 0},
                disposition={},
            ),
            rollup_item(
                cx_generation_id="cx-gen-no-signal",
                severity="INFO",
                quality={"count": 0, "attention_required": False},
                feedback={"negative_count": 0},
                disposition={},
            ),
        ],
        limit=10,
    )
    items = {item["cx_generation_id"]: item for item in projection["items"]}

    assert items["cx-gen-ae-followup"]["candidate_reason"] == (
        "operator_requested_ae_followup"
    )
    assert items["cx-gen-ae-followup"]["action"]["action_type"] == "operator_followup"
    assert items["cx-gen-escalated"]["candidate_reason"] == (
        "operator_escalated_generation_quality"
    )
    assert items["cx-gen-escalated"]["action"]["action_type"] == "prompt_policy_review"
    assert items["cx-gen-escalated"]["action"]["priority"] == "URGENT"
    assert items["cx-gen-escalated"]["action"]["reason_codes"] == [
        "operator_requested_repair",
        "policy_review",
    ]
    assert items["cx-gen-in-progress"]["candidate_reason"] == (
        "open_operator_disposition_in_progress"
    )
    assert items["cx-gen-in-progress"]["action"]["priority"] == "HIGH"
    assert items["cx-gen-open-fallback"]["action"]["action_type"] == "retry_generation"
    assert items["cx-gen-no-signal"]["candidate_reason"] == (
        "attention_signal_needs_triage"
    )
    assert items["cx-gen-no-signal"]["action"]["reason_codes"] == ["other"]


def test_generation_remediation_validation_helpers_cover_invalid_scalar_branches() -> None:
    with pytest.raises(GenerationRemediationError) as reason_exc:
        reason_code_list([" "])
    assert reason_exc.value.error_code == "ag.generation_remediation_reason_code_invalid"

    with pytest.raises(GenerationRemediationError) as choice_exc:
        build_action(action_status=" ")
    assert choice_exc.value.error_code == "ag.generation_remediation_action_status_invalid"
