from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from nex_ag.generation_quality_feedback_rollup import (
    build_generation_quality_feedback_rollup,
    normalize_rollup_limit,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def rollup_schema() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/generation/ag_generation_quality_feedback_rollup.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def build_rollup(**overrides: Any) -> dict[str, Any]:
    kwargs = {
        "quality_items": [
            {
                "cx_generation_id": "cx-gen-open",
                "attention_required": True,
                "severity": "ERROR",
                "coverage_status": "FAIL",
                "boundary_status": "WARN",
                "issue_codes": [
                    "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS",
                    "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS",
                ],
                "recommended_action": "complete_source_quality_metadata",
                "raw_prompt": "SECRET_PROMPT_SHOULD_NOT_LEAK",
            },
            {
                "cx_generation_id": "cx-gen-progress",
                "attention_required": True,
                "severity": "WARNING",
                "coverage_status": "WARN",
                "boundary_status": "PASS",
                "issue_codes": ["LOW_CITATION_COVERAGE"],
            },
        ],
        "feedback_records": [
            {
                "feedback_id": "feedback-open",
                "cx_generation_id": "cx-gen-open",
                "feedback_value": "negative",
                "created_at": "2026-08-25T00:03:00Z",
                "quality_issue_refs": [{"issue_code": "citation_missing"}],
                "feedback_comment_preview": "SECRET_COMMENT_SHOULD_NOT_LEAK",
            },
            {
                "feedback_id": "feedback-ok",
                "cx_generation_id": "cx-gen-ok",
                "feedback_value": "positive",
                "created_at": "2026-08-25T00:01:00Z",
            },
            {
                "feedback_id": "feedback-unlinked",
                "feedback_value": "negative",
                "created_at": "2026-08-25T00:02:00Z",
            },
        ],
        "disposition_records": [
            {
                "disposition_id": "disp-progress",
                "cx_generation_id": "cx-gen-progress",
                "disposition_status": "IN_REPAIR",
                "operator_action": "needs_cx_repair",
                "updated_at": "2026-08-25T00:04:00Z",
                "reason_codes": ["citation_quality", "user_feedback"],
                "operator_note_preview": "SECRET_NOTE_SHOULD_NOT_LEAK",
            },
            {
                "disposition_id": "disp-closed",
                "cx_generation_id": "cx-gen-closed",
                "disposition_status": "RESOLVED",
                "operator_action": "resolved",
                "updated_at": "2026-08-25T00:05:00Z",
                "reason_codes": ["metadata_gap"],
            },
        ],
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
        "checked_at": "2026-08-25T00:06:00Z",
    }
    kwargs.update(overrides)
    return build_generation_quality_feedback_rollup(**kwargs)


def test_generation_quality_feedback_rollup_matches_contract_and_summarizes_signals() -> None:
    rollup = build_rollup()

    Draft202012Validator(rollup_schema()).validate(rollup)
    assert rollup["summary"] == {
        "generation_count": 4,
        "quality_item_count": 2,
        "feedback_count": 2,
        "negative_feedback_count": 1,
        "disposition_count": 2,
        "open_attention_count": 2,
        "closed_attention_count": 1,
        "unlinked_feedback_count": 1,
    }
    assert rollup["by_feedback_value"] == {"negative": 1, "positive": 1}
    assert rollup["by_disposition_status"] == {"IN_REPAIR": 1, "RESOLVED": 1}
    assert [item["cx_generation_id"] for item in rollup["items"]] == [
        "cx-gen-open",
        "cx-gen-progress",
        "cx-gen-closed",
        "cx-gen-ok",
    ]
    open_item = rollup["items"][0]
    progress_item = rollup["items"][1]
    closed_item = rollup["items"][2]
    assert open_item["attention_status"] == "OPEN"
    assert open_item["severity"] == "ERROR"
    assert open_item["recommended_operator_action"] == "record_operator_disposition"
    assert open_item["quality"]["issue_codes"] == [
        "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"
    ]
    assert progress_item["attention_status"] == "IN_PROGRESS"
    assert progress_item["recommended_operator_action"] == "continue_operator_disposition"
    assert closed_item["attention_status"] == "CLOSED"
    assert closed_item["recommended_operator_action"] == "monitor_closed_disposition"


def test_generation_quality_feedback_rollup_does_not_copy_raw_text_or_previews() -> None:
    serialized = json.dumps(build_rollup(), ensure_ascii=False)

    assert "SECRET_PROMPT_SHOULD_NOT_LEAK" not in serialized
    assert "SECRET_COMMENT_SHOULD_NOT_LEAK" not in serialized
    assert "SECRET_NOTE_SHOULD_NOT_LEAK" not in serialized
    assert '"raw_prompt":' not in serialized
    assert "feedback_comment_preview" not in serialized
    assert "operator_note_preview" not in serialized


def test_generation_quality_feedback_rollup_handles_empty_inputs() -> None:
    rollup = build_generation_quality_feedback_rollup(
        quality_items=[],
        feedback_records=[],
        disposition_records=[],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        checked_at="2026-08-25T00:00:00Z",
    )

    Draft202012Validator(rollup_schema()).validate(rollup)
    assert rollup["items"] == []
    assert rollup["summary"] == {
        "generation_count": 0,
        "quality_item_count": 0,
        "feedback_count": 0,
        "negative_feedback_count": 0,
        "disposition_count": 0,
        "open_attention_count": 0,
        "closed_attention_count": 0,
        "unlinked_feedback_count": 0,
    }
    assert rollup["by_feedback_value"] == {}
    assert rollup["by_disposition_status"] == {}


def test_generation_quality_feedback_rollup_fetches_quality_detail_when_feedback_is_untriaged() -> None:
    rollup = build_generation_quality_feedback_rollup(
        quality_items=[],
        feedback_records=[
            {
                "feedback_id": "feedback-only",
                "cx_generation_id": "cx-gen-feedback-only",
                "feedback_value": "negative",
                "created_at": "2026-08-25T00:00:00Z",
            }
        ],
        disposition_records=[],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        checked_at="2026-08-25T00:00:00Z",
    )

    item = rollup["items"][0]
    assert item["attention_status"] == "OPEN"
    assert item["severity"] == "WARNING"
    assert item["recommended_operator_action"] == "fetch_generation_quality_detail"


def test_generation_quality_feedback_rollup_follows_escalation_and_ok_paths() -> None:
    rollup = build_generation_quality_feedback_rollup(
        quality_items=[
            {
                "cx_generation_id": "cx-gen-escalated",
                "attention_required": True,
                "severity": "WARNING",
            }
        ],
        feedback_records=[],
        disposition_records=[
            {
                "disposition_id": "disp-escalated",
                "cx_generation_id": "cx-gen-escalated",
                "disposition_status": "ESCALATED",
                "operator_action": "escalated",
                "updated_at": "2026-08-25T00:00:00Z",
            },
            {
                "disposition_id": "disp-ok",
                "cx_generation_id": "cx-gen-ok",
                "disposition_status": "ACKNOWLEDGED",
                "operator_action": "acknowledged",
                "updated_at": "2026-08-25T00:00:00Z",
            },
        ],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        checked_at="2026-08-25T00:00:00Z",
    )

    escalated = next(
        item for item in rollup["items"] if item["cx_generation_id"] == "cx-gen-escalated"
    )
    acknowledged = next(
        item for item in rollup["items"] if item["cx_generation_id"] == "cx-gen-ok"
    )
    assert escalated["attention_status"] == "IN_PROGRESS"
    assert escalated["recommended_operator_action"] == "follow_escalation"
    assert acknowledged["attention_status"] == "IN_PROGRESS"


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (0, 1),
        (-5, 1),
        (2, 2),
        (999, 500),
        ("bad", 50),
    ],
)
def test_normalize_rollup_limit(limit: Any, expected: int) -> None:
    assert normalize_rollup_limit(limit) == expected
