from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from nex_ag.operator_review_liveness_ack import (
    AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
    LIVENESS_ACK_STATE_SCHEMA_VERSION,
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    _ack_state_filter_clause,
    _ack_state_record_params,
    _ack_state_select_sql,
    _ack_state_upsert_sql,
    build_operator_review_liveness_ack_state_list_response,
    build_operator_review_liveness_ack_state_record,
    default_operator_review_liveness_ack_state_store,
    normalize_ack_state_limit,
)
from nex_ag.operator_reviews import sha256_text
from nex_runtime import build_engine, build_session_factory


def sample_ack_record(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ack_state_id": "ack-state-0802",
        "acknowledgement_key": "nex-ag:ag-dispatch-execution-daemon:stale",
        "service_id": "nex-ag",
        "worker_id": "ag-dispatch-execution-daemon",
        "worker_type": "operator_review_escalation_dispatch_execution_daemon",
        "liveness_status": "STALE",
        "action": "suppress_for_ttl",
        "state_status": "SUPPRESSED",
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "reason_codes": ["planned-maintenance"],
        "comment": "Suppress while the daemon is intentionally stopped.",
        "idempotency_key": "idempotency-key-0802",
        "requested_ttl_seconds": 1800,
        "suppressed_until": "2026-09-16T01:30:00Z",
        "metadata": {"source_view": "dispatch_daemon_liveness"},
        "created_at": "2026-09-16T01:00:00Z",
        "updated_at": "2026-09-16T01:00:10Z",
    }
    payload.update(overrides)
    return build_operator_review_liveness_ack_state_record(**payload)


def sqlite_ack_state_store() -> tuple[SqlAlchemyOperatorReviewLivenessAckStateStore, Any]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE {AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE} (
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


def test_build_liveness_ack_state_record_redacts_raw_comment_and_key() -> None:
    record = sample_ack_record()

    assert record["ack_state_schema_version"] == LIVENESS_ACK_STATE_SCHEMA_VERSION
    assert record["comment_hash"] == sha256_text(
        "Suppress while the daemon is intentionally stopped."
    )
    assert record["comment_preview"] == (
        "Suppress while the daemon is intentionally stopped."
    )
    assert record["idempotency_key_hash"] == sha256_text("idempotency-key-0802")
    assert "comment" not in record
    assert "idempotency_key" not in record
    assert record["metadata"]["raw_comment_stored"] is False
    assert record["metadata"]["raw_idempotency_key_stored"] is False
    assert record["metadata"]["source_liveness_projection_suppressed"] is False


def test_liveness_ack_state_record_validates_inputs() -> None:
    cases = [
        ({"ack_state_id": ""}, "ag.operator_review_liveness_ack_state_id_invalid"),
        ({"action": "bad"}, "ag.operator_review_liveness_ack_state_action_invalid"),
        (
            {"state_status": "bad"},
            "ag.operator_review_liveness_ack_state_status_invalid",
        ),
        (
            {"liveness_status": "FRESH"},
            "ag.operator_review_liveness_ack_liveness_status_invalid",
        ),
        (
            {"operator_ref": "not-object"},
            "ag.operator_review_liveness_ack_operator_ref_invalid",
        ),
        (
            {"operator_ref": {"operator_type": "bot", "operator_id": "x"}},
            "ag.operator_review_liveness_ack_operator_type_invalid",
        ),
        (
            {"operator_ref": {"operator_type": "user", "operator_id": ""}},
            "ag.operator_review_liveness_ack_operator_id_invalid",
        ),
        (
            {"comment": 123},
            "ag.operator_review_liveness_ack_text_invalid",
        ),
        (
            {"reason_codes": []},
            "ag.operator_review_liveness_ack_reason_codes_required",
        ),
        (
            {"reason_codes": "not-list"},
            "ag.operator_review_liveness_ack_reason_codes_invalid",
        ),
        (
            {"reason_codes": ["x" * 81]},
            "ag.operator_review_liveness_ack_reason_code_too_long",
        ),
        (
            {"requested_ttl_seconds": "bad"},
            "ag.operator_review_liveness_ack_positive_int_invalid",
        ),
        (
            {"requested_ttl_seconds": 0},
            "ag.operator_review_liveness_ack_positive_int_invalid",
        ),
        (
            {"metadata": []},
            "ag.operator_review_liveness_ack_metadata_invalid",
        ),
        (
            {
                "action": "suppress_for_ttl",
                "state_status": "SUPPRESSED",
                "suppressed_until": None,
            },
            "ag.operator_review_liveness_ack_suppressed_until_required",
        ),
    ]
    for overrides, error_code in cases:
        with pytest.raises(OperatorReviewLivenessAckStateError) as exc_info:
            sample_ack_record(**overrides)
        assert exc_info.value.error_code == error_code


def test_liveness_ack_state_record_non_ttl_actions_allow_no_expiry() -> None:
    record = sample_ack_record(
        action="acknowledge_once",
        state_status="ACKNOWLEDGED",
        suppressed_until=None,
        requested_ttl_seconds=None,
        comment=None,
        idempotency_key=None,
        operator_ref={"operator_type": "service", "operator_id": "nex-ag"},
    )

    assert record["suppressed_until"] is None
    assert record["comment_hash"] is None
    assert record["idempotency_key_hash"] is None
    assert record["operator_ref"] == {"operator_type": "service", "operator_id": "nex-ag"}


def test_liveness_ack_state_record_default_metadata() -> None:
    record = sample_ack_record(metadata=None)

    assert record["metadata"] == {
        "state_storage": "ag_owned_ack_suppression_overlay_only",
        "raw_comment_stored": False,
        "raw_idempotency_key_stored": False,
        "source_liveness_projection_suppressed": False,
    }


def test_in_memory_liveness_ack_state_store_filters_and_deletes() -> None:
    store = OperatorReviewLivenessAckStateStore()
    stale = sample_ack_record()
    missing = sample_ack_record(
        ack_state_id="ack-state-missing",
        acknowledgement_key="nex-ag:ag-dispatch-execution-daemon:missing",
        liveness_status="MISSING",
        state_status="ACKNOWLEDGED",
        action="acknowledge_once",
        requested_ttl_seconds=None,
        suppressed_until=None,
        updated_at="2026-09-16T01:01:00Z",
    )

    assert store.save(stale) == stale
    assert store.save(missing) == missing
    assert store.get("ack-state-0802") == stale
    assert store.get_by_acknowledgement_key(
        "nex-ag:ag-dispatch-execution-daemon:missing"
    ) == missing
    assert store.get_by_acknowledgement_key("unknown") is None
    assert store.list_states(state_status="SUPPRESSED") == [stale]
    assert store.list_states(liveness_status="MISSING") == [missing]
    assert store.list_states(service_id="other") == []
    assert store.delete("ack-state-0802") == 1
    assert store.delete("ack-state-0802") == 0


def test_sqlalchemy_liveness_ack_state_store_round_trips_and_upserts() -> None:
    store, engine = sqlite_ack_state_store()
    record = sample_ack_record()
    updated = {
        **record,
        "state_status": "ACKNOWLEDGED",
        "action": "acknowledge_once",
        "requested_ttl_seconds": None,
        "suppressed_until": None,
        "updated_at": "2026-09-16T01:05:00Z",
    }

    assert store.save(record) == record
    assert store.get("ack-state-0802")["metadata"]["source_view"] == (
        "dispatch_daemon_liveness"
    )
    assert store.get_by_acknowledgement_key(record["acknowledgement_key"])[
        "state_status"
    ] == "SUPPRESSED"
    assert store.save(updated) == updated
    assert store.get("ack-state-0802")["state_status"] == "ACKNOWLEDGED"
    assert store.get("unknown") is None
    assert store.get_by_acknowledgement_key("unknown") is None
    assert store.list_states(worker_id="ag-dispatch-execution-daemon")[
        0
    ]["state_status"] == "ACKNOWLEDGED"
    assert store.list_states(state_status="SUPPRESSED") == []
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT operator_type, operator_id, tenant_id "
                "FROM ag_op_review_ack_state WHERE ack_state_id = :ack_state_id"
            ),
            {"ack_state_id": "ack-state-0802"},
        ).first()
    assert tuple(row) == ("user", "employee-0001", "local-tenant")
    assert store.delete("ack-state-0802") == 1
    assert store.get("ack-state-0802") is None


def test_liveness_ack_state_sql_helpers_and_projection_response() -> None:
    record = sample_ack_record()
    params = _ack_state_record_params(record)
    where, filter_params = _ack_state_filter_clause(
        service_id="nex-ag",
        worker_id=None,
        liveness_status="STALE",
        state_status=None,
    )
    response = build_operator_review_liveness_ack_state_list_response(
        [record],
        checked_at="2026-09-16T01:07:00Z",
    )

    assert json.loads(params["operator_ref"])["operator_id"] == "employee-0001"
    assert json.loads(params["reason_codes"]) == ["planned-maintenance"]
    assert "ON CONFLICT (ack_state_id)" in _ack_state_upsert_sql("sqlite")
    assert "FROM ag_op_review_ack_state" in _ack_state_select_sql("1 = 1")
    assert where == "1 = 1 AND service_id = :service_id AND liveness_status = :liveness_status"
    assert filter_params == {"service_id": "nex-ag", "liveness_status": "STALE"}
    assert response["state_count"] == 1
    assert response["source_table"] == AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE
    assert response["redaction"]["raw_comment_included"] is False


def test_liveness_ack_state_limit_and_default_store_selection() -> None:
    assert normalize_ack_state_limit(None) == 50
    assert normalize_ack_state_limit(0) == 1
    assert normalize_ack_state_limit(500) == 200
    with pytest.raises(OperatorReviewLivenessAckStateError) as exc_info:
        normalize_ack_state_limit("bad")
    assert exc_info.value.error_code == "ag.operator_review_liveness_ack_limit_invalid"

    memory_app = SimpleNamespace(state=SimpleNamespace())
    assert default_operator_review_liveness_ack_state_store(memory_app).__class__ is (
        OperatorReviewLivenessAckStateStore
    )
    store, _engine = sqlite_ack_state_store()
    persistent_app = SimpleNamespace(
        state=SimpleNamespace(
            nex_persistence=SimpleNamespace(api_session_factory=store._session_factory)
        )
    )
    assert isinstance(
        default_operator_review_liveness_ack_state_store(persistent_app),
        SqlAlchemyOperatorReviewLivenessAckStateStore,
    )


def test_liveness_ack_state_store_reports_sqlalchemy_failures() -> None:
    class BrokenFactory:
        def __call__(self) -> Any:
            raise RuntimeError("not a sqlalchemy context")

    store = SqlAlchemyOperatorReviewLivenessAckStateStore(BrokenFactory())

    with pytest.raises(RuntimeError):
        store.get("ack-state-0802")


def test_liveness_ack_state_store_wraps_sqlalchemy_errors() -> None:
    store, engine = sqlite_ack_state_store()
    record = sample_ack_record()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ag_op_review_ack_state"))

    for operation in (
        lambda: store.save(record),
        lambda: store.get("ack-state-0802"),
        lambda: store.get_by_acknowledgement_key(record["acknowledgement_key"]),
        lambda: store.list_states(service_id="nex-ag"),
        lambda: store.delete("ack-state-0802"),
    ):
        with pytest.raises(OperatorReviewLivenessAckStateError) as exc_info:
            operation()
        assert exc_info.value.error_code == (
            "ag.operator_review_liveness_ack_state_store_unavailable"
        )
        assert exc_info.value.status_code == 503


def test_liveness_ack_state_migration_shape() -> None:
    migration = Path(
        "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ag_op_review_ack_state" in migration
    assert "uq_ag_ack_state_key" in migration
    assert "idx_ag_ack_state_status_time" in migration
    assert "idx_ag_ack_state_worker_time" in migration
    assert "raw_comment" not in migration
    assert "raw_idempotency_key" not in migration
    assert all(
        len(name) <= 30
        for name in [
            "ag_op_review_ack_state",
            "uq_ag_ack_state_key",
            "idx_ag_ack_state_status_time",
            "idx_ag_ack_state_worker_time",
        ]
    )
