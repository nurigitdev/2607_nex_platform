from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from nex_ag.operator_review_liveness_ack import (
    LIVENESS_ACK_EXPIRY_RECONCILIATION_SCHEMA_VERSION,
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    _ack_expiry_candidate_select_sql,
    _ack_expiry_cas_update_sql,
    apply_operator_review_liveness_ack_expiry_reconciliation,
    build_operator_review_liveness_ack_expiry_reconciliation_candidate,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import build_engine, build_session_factory


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


def sqlite_store() -> tuple[SqlAlchemyOperatorReviewLivenessAckStateStore, Any]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ag_op_review_ack_state (
                    ack_state_id TEXT PRIMARY KEY,
                    ack_state_schema_version TEXT NOT NULL,
                    acknowledgement_key TEXT NOT NULL UNIQUE,
                    service_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    worker_type TEXT NOT NULL,
                    liveness_status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    state_status TEXT NOT NULL,
                    operator_type TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    tenant_id TEXT,
                    operator_ref TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    comment_hash TEXT,
                    comment_preview TEXT,
                    idempotency_key_hash TEXT,
                    requested_ttl_seconds INTEGER,
                    suppressed_until TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cleared_at TEXT
                )
                """
            )
        )
    return (
        SqlAlchemyOperatorReviewLivenessAckStateStore(build_session_factory(engine)),
        engine,
    )


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


def test_memory_store_lists_bounded_candidates_and_applies_cas() -> None:
    store = OperatorReviewLivenessAckStateStore()
    first = sample_state()
    second = sample_state(
        ack_state_id="ack-expiry-0812-b",
        acknowledgement_key="nex-ag:dispatch-daemon:missing",
        liveness_status="MISSING",
        suppressed_until="2026-09-17T01:20:00Z",
    )
    active = sample_state(
        ack_state_id="ack-expiry-active",
        acknowledgement_key="nex-ag:dispatch-daemon:active",
        suppressed_until="2026-09-17T02:30:00Z",
    )
    for state in (first, second, active):
        store.save(state)

    candidates = store.list_expiry_candidates(
        observed_at="2026-09-17T02:00:00Z",
        limit=1,
    )
    mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
        candidates[0],
        observed_at="2026-09-17T02:00:00Z",
    )

    assert [item["ack_state_id"] for item in candidates] == ["ack-expiry-0812-b"]
    assert store.apply_expiry_reconciliation(
        mutation["state"],
        expected_updated_at=mutation["candidate"]["expected_updated_at"],
    ) is True
    assert store.get("ack-expiry-0812-b")["state_status"] == "EXPIRED"
    assert store.apply_expiry_reconciliation(
        mutation["state"],
        expected_updated_at=mutation["candidate"]["expected_updated_at"],
    ) is False
    assert store.apply_expiry_reconciliation(
        {**mutation["state"], "ack_state_id": "unknown"},
        expected_updated_at=mutation["candidate"]["expected_updated_at"],
    ) is False


def test_memory_store_cas_rejects_stale_or_renewed_state() -> None:
    store = OperatorReviewLivenessAckStateStore()
    original = sample_state()
    store.save(original)
    mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
        original,
        observed_at="2026-09-17T02:00:00Z",
    )

    assert store.apply_expiry_reconciliation(
        mutation["state"],
        expected_updated_at="2026-09-17T00:00:00Z",
    ) is False
    renewed = {
        **original,
        "suppressed_until": "2026-09-17T03:00:00Z",
        "updated_at": "2026-09-17T01:10:00Z",
    }
    store.save(renewed)
    stale_mutation = {
        **mutation["state"],
        "updated_at": "2026-09-17T02:00:00Z",
    }
    assert store.apply_expiry_reconciliation(
        stale_mutation,
        expected_updated_at="2026-09-17T01:10:00Z",
    ) is False


def test_sqlalchemy_store_lists_candidates_and_applies_cas() -> None:
    store, _engine = sqlite_store()
    expired = sample_state()
    active = sample_state(
        ack_state_id="ack-active",
        acknowledgement_key="nex-ag:dispatch-daemon:active",
        suppressed_until="2026-09-17T03:00:00Z",
    )
    store.save(expired)
    store.save(active)

    candidates = store.list_expiry_candidates(
        observed_at="2026-09-17T02:00:00Z",
        limit=10,
    )
    mutation = apply_operator_review_liveness_ack_expiry_reconciliation(
        candidates[0],
        observed_at="2026-09-17T02:00:00Z",
    )

    assert [item["ack_state_id"] for item in candidates] == ["ack-expiry-0812"]
    assert store.apply_expiry_reconciliation(
        mutation["state"],
        expected_updated_at=mutation["candidate"]["expected_updated_at"],
    ) is True
    persisted = store.get("ack-expiry-0812")
    assert persisted["state_status"] == "EXPIRED"
    assert persisted["metadata"]["last_expiry_reconciliation"]["reason"] == (
        "suppression_expired"
    )
    assert store.apply_expiry_reconciliation(
        mutation["state"],
        expected_updated_at=mutation["candidate"]["expected_updated_at"],
    ) is False


def test_expiry_persistence_sql_and_migration_shape() -> None:
    select_sql = _ack_expiry_candidate_select_sql()
    sqlite_update = _ack_expiry_cas_update_sql("sqlite")
    postgres_update = _ack_expiry_cas_update_sql("postgresql")
    migration = Path(
        "database/nex-ag/migrations/0813_ag_ack_expiry_index.sql"
    ).read_text(encoding="utf-8")

    assert "suppressed_until <= :observed_at" in select_sql
    assert "ORDER BY suppressed_until ASC" in select_sql
    assert "metadata = :metadata" in sqlite_update
    assert "CAST(:metadata AS jsonb)" in postgres_update
    assert "idx_ag_ack_state_expiry" in migration
    assert len("idx_ag_ack_state_expiry") <= 30


def test_sqlalchemy_expiry_persistence_wraps_database_errors() -> None:
    store, engine = sqlite_store()
    state = sample_state()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ag_op_review_ack_state"))

    with pytest.raises(OperatorReviewLivenessAckStateError) as list_exc:
        store.list_expiry_candidates(observed_at="2026-09-17T02:00:00Z")
    assert list_exc.value.error_code == (
        "ag.operator_review_liveness_ack_state_store_unavailable"
    )

    with pytest.raises(OperatorReviewLivenessAckStateError) as update_exc:
        store.apply_expiry_reconciliation(
            {**state, "updated_at": "2026-09-17T02:00:00Z"},
            expected_updated_at=state["updated_at"],
        )
    assert update_exc.value.status_code == 503
