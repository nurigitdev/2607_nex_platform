from __future__ import annotations

from typing import Any

from .operator_review_liveness_ack import (
    _parse_datetime,
    apply_operator_review_liveness_ack_expiry_reconciliation,
    normalize_ack_state_limit,
)
from .operator_reviews import _datetime_value, _utc_now


LIVENESS_ACK_EXPIRY_RECONCILIATION_RUN_SCHEMA_VERSION = (
    "ag_operator_review_liveness_ack_expiry_reconciliation_run.v1"
)


def run_operator_review_liveness_ack_expiry_reconciliation(
    state_store: Any,
    *,
    observed_at: object | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    observed = _datetime_value(
        _parse_datetime(observed_at if observed_at is not None else _utc_now())
    )
    batch_limit = normalize_ack_state_limit(limit)
    candidates = state_store.list_expiry_candidates(
        observed_at=observed,
        limit=batch_limit,
    )
    outcomes: list[dict[str, Any]] = []
    for state in candidates:
        mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
            state,
            observed_at=observed,
        )
        candidate = mutation["candidate"]
        if mutation["mutation_status"] != "APPLIED":
            outcomes.append(
                _outcome(candidate, status="SKIPPED", reason=candidate["reason"])
            )
            continue
        applied = state_store.apply_expiry_reconciliation(
            mutation["state"],
            expected_updated_at=candidate["expected_updated_at"],
        )
        outcomes.append(
            _outcome(
                candidate,
                status="APPLIED" if applied else "CONFLICT",
                reason="suppression_expired" if applied else "compare_and_set_conflict",
            )
        )
    applied_count = sum(item["status"] == "APPLIED" for item in outcomes)
    conflict_count = sum(item["status"] == "CONFLICT" for item in outcomes)
    skipped_count = sum(item["status"] == "SKIPPED" for item in outcomes)
    return {
        "run_schema_version": (
            LIVENESS_ACK_EXPIRY_RECONCILIATION_RUN_SCHEMA_VERSION
        ),
        "run_status": (
            "COMPLETED_WITH_CONFLICTS" if conflict_count else "COMPLETED"
        ),
        "observed_at": observed,
        "batch_limit": batch_limit,
        "candidate_count": len(candidates),
        "applied_count": applied_count,
        "conflict_count": conflict_count,
        "skipped_count": skipped_count,
        "outcomes": outcomes,
        "guardrails": {
            "bounded_batch": True,
            "compare_and_set": True,
            "source_liveness_projection_mutated": False,
            "raw_comments_included": False,
            "raw_payloads_included": False,
        },
    }


def _outcome(
    candidate: dict[str, Any],
    *,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ack_state_id": candidate.get("ack_state_id"),
        "acknowledgement_key": candidate.get("acknowledgement_key"),
        "status": status,
        "reason": reason,
        "expected_state_status": candidate.get("expected_state_status"),
        "target_state_status": candidate.get("target_state_status"),
    }
