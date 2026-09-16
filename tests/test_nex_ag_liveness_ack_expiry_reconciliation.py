from __future__ import annotations

from typing import Any

import pytest

from nex_ag.liveness_ack_expiry_reconciliation import (
    LIVENESS_ACK_EXPIRY_RECONCILIATION_RUN_SCHEMA_VERSION,
    run_operator_review_liveness_ack_expiry_reconciliation,
)
from nex_ag.operator_review_liveness_ack import (
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)


def state(
    *,
    ack_state_id: str,
    acknowledgement_key: str,
    suppressed_until: str,
    updated_at: str = "2026-09-17T01:00:00Z",
) -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=ack_state_id,
        acknowledgement_key=acknowledgement_key,
        service_id="nex-ag",
        worker_id="dispatch-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "user", "operator_id": "employee-1"},
        reason_codes=["planned-maintenance"],
        requested_ttl_seconds=1800,
        suppressed_until=suppressed_until,
        created_at="2026-09-17T01:00:00Z",
        updated_at=updated_at,
    )


def test_reconciliation_worker_applies_bounded_expiry_batch() -> None:
    store = OperatorReviewLivenessAckStateStore()
    for item in (
        state(
            ack_state_id="ack-1",
            acknowledgement_key="nex-ag:dispatch:stale:1",
            suppressed_until="2026-09-17T01:10:00Z",
        ),
        state(
            ack_state_id="ack-2",
            acknowledgement_key="nex-ag:dispatch:stale:2",
            suppressed_until="2026-09-17T01:20:00Z",
        ),
        state(
            ack_state_id="ack-active",
            acknowledgement_key="nex-ag:dispatch:stale:active",
            suppressed_until="2026-09-17T03:00:00Z",
        ),
    ):
        store.save(item)

    result = run_operator_review_liveness_ack_expiry_reconciliation(
        store,
        observed_at="2026-09-17T02:00:00Z",
        limit=10,
    )

    assert result["run_schema_version"] == (
        LIVENESS_ACK_EXPIRY_RECONCILIATION_RUN_SCHEMA_VERSION
    )
    assert result["run_status"] == "COMPLETED"
    assert result["candidate_count"] == 2
    assert result["applied_count"] == 2
    assert result["conflict_count"] == 0
    assert result["skipped_count"] == 0
    assert [item["ack_state_id"] for item in result["outcomes"]] == [
        "ack-1",
        "ack-2",
    ]
    assert store.get("ack-1")["state_status"] == "EXPIRED"
    assert store.get("ack-active")["state_status"] == "SUPPRESSED"
    assert result["guardrails"]["raw_payloads_included"] is False

    rerun = run_operator_review_liveness_ack_expiry_reconciliation(
        store,
        observed_at="2026-09-17T02:00:00Z",
    )
    assert rerun["candidate_count"] == 0
    assert rerun["applied_count"] == 0


def test_reconciliation_worker_reports_compare_and_set_conflict() -> None:
    candidate = state(
        ack_state_id="ack-conflict",
        acknowledgement_key="nex-ag:dispatch:stale:conflict",
        suppressed_until="2026-09-17T01:10:00Z",
    )

    class ConflictStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return [candidate]

        def apply_expiry_reconciliation(self, *_args: Any, **_kwargs: Any) -> bool:
            return False

    result = run_operator_review_liveness_ack_expiry_reconciliation(
        ConflictStore(),
        observed_at="2026-09-17T02:00:00Z",
        limit=1,
    )

    assert result["run_status"] == "COMPLETED_WITH_CONFLICTS"
    assert result["conflict_count"] == 1
    assert result["outcomes"][0]["reason"] == "compare_and_set_conflict"


def test_reconciliation_worker_defensively_skips_ineligible_candidate() -> None:
    active = state(
        ack_state_id="ack-active",
        acknowledgement_key="nex-ag:dispatch:stale:active",
        suppressed_until="2026-09-17T03:00:00Z",
    )

    class StaleCandidateStore:
        def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
            return [active]

        def apply_expiry_reconciliation(self, *_args: Any, **_kwargs: Any) -> bool:
            raise AssertionError("ineligible state must not be persisted")

    result = run_operator_review_liveness_ack_expiry_reconciliation(
        StaleCandidateStore(),
        observed_at="2026-09-17T02:00:00Z",
    )

    assert result["run_status"] == "COMPLETED"
    assert result["skipped_count"] == 1
    assert result["outcomes"][0]["reason"] == "suppression_active"


def test_reconciliation_worker_normalizes_limit_and_validates_inputs() -> None:
    class SpyStore:
        observed_at: str | None = None
        limit: int | None = None

        def list_expiry_candidates(
            self,
            *,
            observed_at: str,
            limit: int,
        ) -> list[dict[str, Any]]:
            self.observed_at = observed_at
            self.limit = limit
            return []

    store = SpyStore()
    result = run_operator_review_liveness_ack_expiry_reconciliation(
        store,
        observed_at="2026-09-17T02:00:00Z",
        limit=999,
    )

    assert result["batch_limit"] == 200
    assert store.observed_at == "2026-09-17T02:00:00Z"
    assert store.limit == 200

    with pytest.raises(OperatorReviewLivenessAckStateError):
        run_operator_review_liveness_ack_expiry_reconciliation(
            store,
            observed_at="bad-time",
        )
    with pytest.raises(OperatorReviewLivenessAckStateError):
        run_operator_review_liveness_ack_expiry_reconciliation(
            store,
            observed_at="2026-09-17T02:00:00Z",
            limit="bad",
        )
