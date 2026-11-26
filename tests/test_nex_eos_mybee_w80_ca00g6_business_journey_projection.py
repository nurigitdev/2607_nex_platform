from __future__ import annotations

import pytest
from nex_eos.business_journeys import (
    project_proposal_journey,
    project_voucher_journey,
)


@pytest.mark.parametrize(
    ("state", "current_stage", "statuses", "terminal"),
    [
        ("DRAFT", "PROPOSAL_DRAFT", ["CURRENT", "UPCOMING", "UPCOMING"], False),
        ("SUBMITTED", "BUSINESS_APPROVAL", ["COMPLETED", "CURRENT", "UPCOMING"], False),
        ("APPROVED", "VOUCHER_PREPARATION", ["COMPLETED", "COMPLETED", "AVAILABLE"], False),
        ("REJECTED", "BUSINESS_APPROVAL", ["COMPLETED", "REJECTED", "BLOCKED"], True),
        ("WITHDRAWN", "BUSINESS_APPROVAL", ["COMPLETED", "CANCELLED", "BLOCKED"], True),
    ],
)
def test_proposal_journey_projects_authoritative_state_without_internal_ids(
    state: str, current_stage: str, statuses: list[str], terminal: bool
) -> None:
    projection = project_proposal_journey(
        {"state": state, "approval_line": [{"subject_id": "private-principal"}]}
    )

    assert projection["current_stage"] == current_stage
    assert projection["terminal"] is terminal
    assert projection["approval_stage_count"] == 1
    assert [step["status"] for step in projection["steps"]] == statuses
    assert "private-principal" not in str(projection)


@pytest.mark.parametrize(
    ("state", "current_stage", "statuses", "terminal"),
    [
        ("DRAFT", "VOUCHER_REVIEW", ["CURRENT", "UPCOMING", "UPCOMING"], False),
        ("READY_FOR_REVIEW", "ACCOUNTING_APPROVAL", ["COMPLETED", "CURRENT", "UPCOMING"], False),
        ("RETURNED_FOR_CORRECTION", "VOUCHER_REVIEW", ["CURRENT", "RETURNED", "BLOCKED"], False),
        ("POSTED", "JOURNAL_POSTING", ["COMPLETED", "COMPLETED", "COMPLETED"], True),
    ],
)
def test_voucher_journey_projects_review_and_posting_boundaries(
    state: str, current_stage: str, statuses: list[str], terminal: bool
) -> None:
    projection = project_voucher_journey({"state": state})

    assert projection["current_stage"] == current_stage
    assert projection["terminal"] is terminal
    assert projection["approval_stage_count"] is None
    assert [step["status"] for step in projection["steps"]] == statuses


@pytest.mark.parametrize(
    "projector,value",
    [
        (project_proposal_journey, {"state": "UNKNOWN"}),
        (project_voucher_journey, {"state": "APPROVED"}),
    ],
)
def test_journey_projection_fails_closed_for_unowned_states(projector, value) -> None:
    with pytest.raises(ValueError):
        projector(value)


def test_empty_approval_line_has_zero_stages() -> None:
    assert project_proposal_journey({"state": "DRAFT", "approval_line": None})[
        "approval_stage_count"
    ] == 0
