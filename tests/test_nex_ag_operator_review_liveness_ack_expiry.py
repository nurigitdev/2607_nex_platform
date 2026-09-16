from __future__ import annotations

from typing import Any

import pytest

from nex_ag.operator_review_liveness_ack import (
    LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION,
    OperatorReviewLivenessAckStateError,
    apply_operator_review_liveness_ack_expiry_reconciliation,
    build_operator_review_liveness_ack_expiry_reconciliation_candidate,
    build_operator_review_liveness_ack_state_record,
)


def sample_state(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ack_state_id": "ack-expiry-0812",
        "acknowledgement_key": "nex-ag:dispatch-daemon:stale",
        "service_id": "nex-ag",
        "worker_id": "dispatch-daemon",
        "worker_type": "operator_review_dispatch_daemon",
        "liveness_status": "STALE",
        "action": "suppress_for_ttl",
        "state_status": "SUPPRESSED",
        "operator_ref": {"operator_type": "user", "operator_id": "employee-1"},
        "reason_codes": ["planned-maintenance"],
        "requested_ttl_seconds": 1800,
        "suppressed_until": "2026-09-17T01:30:00Z",
        "metadata": {"source": "s81"},
        "created_at": "2026-09-17T01:00:00Z",
        "updated_at": "2026-09-17T01:00:00Z",
    }
    payload.update(overrides)
    return build_operator_review_liveness_ack_state_record(**payload)


def test_expiry_reconciliation_candidate_is_eligible_at_deadline() -> None:
    candidate = build_operator_review_liveness_ack_expiry_reconciliation_candidate(
        sample_state(),
        observed_at="2026-09-17T01:30:00Z",
    )

    assert candidate["reconciliation_schema_version"] == (
        LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION
    )
    assert candidate["candidate_status"] == "ELIGIBLE"
    assert candidate["reason"] == "suppression_expired"
    assert candidate["expected_state_status"] == "SUPPRESSED"
    assert candidate["expected_updated_at"] == "2026-09-17T01:00:00Z"
    assert candidate["target_state_status"] == "EXPIRED"
    assert candidate["guardrails"] == {
        "compare_and_set_required": True,
        "source_liveness_projection_mutated": False,
        "raw_comment_required": False,
        "raw_payload_required": False,
    }


@pytest.mark.parametrize(
    ("state", "observed_at", "reason"),
    [
        (None, "2026-09-17T01:30:00Z", "state_missing"),
        (
            sample_state(
                action="acknowledge_once",
                state_status="ACKNOWLEDGED",
                requested_ttl_seconds=None,
                suppressed_until=None,
            ),
            "2026-09-17T01:30:00Z",
            "state_not_suppressed",
        ),
        (sample_state(), "2026-09-17T01:29:59Z", "suppression_active"),
    ],
)
def test_expiry_reconciliation_candidate_skip_reasons(
    state: dict[str, Any] | None,
    observed_at: str,
    reason: str,
) -> None:
    candidate = build_operator_review_liveness_ack_expiry_reconciliation_candidate(
        state,
        observed_at=observed_at,
    )

    assert candidate["candidate_status"] == "SKIPPED"
    assert candidate["reason"] == reason
    assert candidate["target_state_status"] is None


def test_expiry_reconciliation_detects_missing_deadline_in_legacy_row() -> None:
    state = sample_state()
    state["suppressed_until"] = None

    candidate = build_operator_review_liveness_ack_expiry_reconciliation_candidate(
        state,
        observed_at="2026-09-17T02:00:00Z",
    )

    assert candidate["candidate_status"] == "SKIPPED"
    assert candidate["reason"] == "suppression_deadline_missing"


def test_expiry_reconciliation_applies_safe_state_transition() -> None:
    original = sample_state()

    mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
        original,
        observed_at="2026-09-17T01:30:01Z",
    )

    assert mutation["mutation_status"] == "APPLIED"
    assert mutation["state"]["state_status"] == "EXPIRED"
    assert mutation["state"]["updated_at"] == "2026-09-17T01:30:01Z"
    assert mutation["state"]["created_at"] == original["created_at"]
    assert mutation["state"]["comment_hash"] == original["comment_hash"]
    assert mutation["state"]["metadata"]["source"] == "s81"
    assert mutation["state"]["metadata"]["last_expiry_reconciliation"] == {
        "observed_at": "2026-09-17T01:30:01Z",
        "previous_state_status": "SUPPRESSED",
        "target_state_status": "EXPIRED",
        "reason": "suppression_expired",
    }
    assert original["state_status"] == "SUPPRESSED"
    assert "last_expiry_reconciliation" not in original["metadata"]


def test_expiry_reconciliation_skip_is_non_mutating() -> None:
    original = sample_state()

    mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
        original,
        observed_at="2026-09-17T01:20:00Z",
    )

    assert mutation["mutation_status"] == "SKIPPED"
    assert mutation["state"] == original
    assert mutation["state"] is not original
    assert apply_operator_review_liveness_ack_expiry_reconciliation(
        None,
        observed_at="2026-09-17T01:20:00Z",
    )["state"] is None


def test_expiry_reconciliation_validates_datetime() -> None:
    with pytest.raises(OperatorReviewLivenessAckStateError) as exc_info:
        build_operator_review_liveness_ack_expiry_reconciliation_candidate(
            sample_state(),
            observed_at="not-a-time",
        )

    assert exc_info.value.error_code == (
        "ag.operator_review_liveness_ack_datetime_invalid"
    )
