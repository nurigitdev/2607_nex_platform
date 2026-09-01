from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nex_ae_api.artifact_retention_scheduler as scheduler_module
from nex_ae_api.artifact_retention_scheduler import (
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    ArtifactRetentionSchedulerLeaseStore,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
    artifact_retention_scheduler_lease_table_sql,
    artifact_retention_scheduler_lease_idempotency_key,
    build_default_artifact_retention_scheduler_lease_store,
    build_artifact_retention_scheduler_lease_decision,
    build_artifact_retention_scheduler_lease_record,
    build_artifact_retention_scheduler_lease_request,
    normalize_artifact_retention_scheduler_lease_operation,
    normalize_artifact_retention_scheduler_lease_record_status,
    normalize_artifact_retention_scheduler_lease_ttl_seconds,
    release_artifact_retention_scheduler_lease,
    summarize_artifact_retention_scheduler_lease_decision,
    validate_artifact_retention_scheduler_lease_decision,
    validate_artifact_retention_scheduler_lease_record,
    validate_artifact_retention_scheduler_lease_request,
)
from nex_ae_api.artifacts import (
    ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS,
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
    ArtifactHandoffError,
    build_artifact_retention_scheduler_config,
)


REQUESTED_AT = "2026-09-01T02:00:00Z"
EXPIRES_AT = "2026-09-01T02:10:00Z"


def sqlite_scheduler_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text(artifact_retention_scheduler_lease_table_sql("sqlite")))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_artifact_retention_scheduler_lease_request_contract_defaults() -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        tick_id="tick-0512",
    )
    expected_key = artifact_retention_scheduler_lease_idempotency_key(
        scheduler_id="ae-artifact-retention-scheduler-local-v1",
        lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
        operation="manual_tick_once",
        requested_at=REQUESTED_AT,
    )
    serialized = json.dumps(request, ensure_ascii=False, sort_keys=True)

    assert request["lease_request_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION
    )
    assert request["service_id"] == "nex-ae-api"
    assert request["scheduler_id"] == "ae-artifact-retention-scheduler-local-v1"
    assert request["lease_owner_id"] == DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID
    assert request["operation"] == "manual_tick_once"
    assert request["requested_at"] == REQUESTED_AT
    assert request["expires_at"] == EXPIRES_AT
    assert request["lease_ttl_seconds"] == ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS
    assert request["stale_after_seconds"] == ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS
    assert request["idempotency_key"] == expected_key
    assert request["guardrails"] == {
        "lease_required_before_tick": True,
        "manual_once_runner": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
    }
    assert request["metadata"] == {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "job_enqueued": False,
        "worker_executed": False,
    }
    assert validate_artifact_retention_scheduler_lease_request(request) == request
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized


def test_artifact_retention_scheduler_lease_record_decision_and_release() -> None:
    config = build_artifact_retention_scheduler_config()
    request = build_artifact_retention_scheduler_lease_request(
        scheduler_config=config,
        scheduler_id="ae-artifact-retention-scheduler-custom",
        lease_owner_id="ae-retention-runner-0512",
        requested_at=REQUESTED_AT,
        lease_ttl_seconds="600",
        idempotency_key="lease-0512",
    )

    record = build_artifact_retention_scheduler_lease_record(
        request,
        fencing_token="7",
        last_observed_at="2026-09-01T02:01:00Z",
    )
    decision = build_artifact_retention_scheduler_lease_decision(
        request,
        lease_record=record,
        decision_at="2026-09-01T02:01:01Z",
    )
    released = release_artifact_retention_scheduler_lease(
        record,
        lease_token=record["lease_token"],
        released_at="2026-09-01T02:02:00Z",
    )
    idempotent_release = release_artifact_retention_scheduler_lease(
        released,
        lease_token=record["lease_token"],
        released_at="2026-09-01T02:03:00Z",
    )

    assert record["lease_record_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
    )
    assert record["scheduler_id"] == "ae-artifact-retention-scheduler-custom"
    assert record["lease_status"] == "HELD"
    assert record["fencing_token"] == 7
    assert record["released_at"] is None
    assert validate_artifact_retention_scheduler_lease_record(record) == record
    assert decision["lease_decision_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION
    )
    assert decision["decision_status"] == "ACQUIRED"
    assert decision["lease_acquired"] is True
    assert decision["lease_token"] == record["lease_token"]
    assert summarize_artifact_retention_scheduler_lease_decision(decision) == {
        "scheduler_id": "ae-artifact-retention-scheduler-custom",
        "decision_status": "ACQUIRED",
        "lease_acquired": True,
        "lease_owner_id": "ae-retention-runner-0512",
        "operation": "manual_tick_once",
        "fencing_token": 7,
        "skip_reason": None,
    }
    assert released["lease_status"] == "RELEASED"
    assert released["released_at"] == "2026-09-01T02:02:00Z"
    assert idempotent_release == released


def test_artifact_retention_scheduler_lease_busy_decision_contract() -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        lease_owner_id="second-runner",
    )
    blocking_request = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-09-01T01:59:00Z",
        lease_owner_id="first-runner",
    )
    blocking_lease = build_artifact_retention_scheduler_lease_record(
        blocking_request,
        fencing_token=3,
    )

    decision = build_artifact_retention_scheduler_lease_decision(
        request,
        blocking_lease=blocking_lease,
    )

    assert decision["decision_status"] == "BUSY"
    assert decision["lease_acquired"] is False
    assert decision["skip_reason"] == "lease_busy"
    assert decision["lease_record"] is None
    assert decision["lease_token"] is None
    assert decision["fencing_token"] is None
    assert decision["blocking_lease"]["lease_owner_id"] == "first-runner"
    assert summarize_artifact_retention_scheduler_lease_decision(decision)[
        "skip_reason"
    ] == "lease_busy"


def test_artifact_retention_scheduler_in_memory_lease_store_lifecycle() -> None:
    store = ArtifactRetentionSchedulerLeaseStore()
    first = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        lease_owner_id="runner-one",
        idempotency_key="lease-store-0513",
    )
    second = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-09-01T02:01:00Z",
        lease_owner_id="runner-two",
        idempotency_key="lease-store-0513-second",
    )

    acquired = store.acquire(first)
    duplicate = store.acquire(first)
    busy = store.acquire(second)
    stored = store.get(first["scheduler_id"])
    assert stored is not None
    stored["metadata"]["job_enqueued"] = True
    released = store.release(
        scheduler_id=first["scheduler_id"],
        lease_token=acquired["lease_token"],
        released_at="2026-09-01T02:02:00Z",
    )
    reacquired = store.acquire(second)

    assert store.ensure_available() is None
    assert acquired["decision_status"] == "ACQUIRED"
    assert duplicate["decision_status"] == "ACQUIRED"
    assert duplicate["lease_token"] == acquired["lease_token"]
    assert duplicate["fencing_token"] == acquired["fencing_token"]
    assert busy["decision_status"] == "BUSY"
    assert busy["blocking_lease"]["lease_owner_id"] == "runner-one"
    assert store.get(first["scheduler_id"])["metadata"]["job_enqueued"] is False  # type: ignore[index]
    assert released["lease_status"] == "RELEASED"
    assert reacquired["decision_status"] == "ACQUIRED"
    assert reacquired["fencing_token"] == 2


def test_artifact_retention_scheduler_in_memory_lease_store_expired_record_reacquires() -> None:
    store = ArtifactRetentionSchedulerLeaseStore()
    first = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        lease_owner_id="runner-one",
    )
    second = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-09-01T02:11:00Z",
        lease_owner_id="runner-two",
    )

    first_decision = store.acquire(first)
    second_decision = store.acquire(second)

    assert first_decision["decision_status"] == "ACQUIRED"
    assert second_decision["decision_status"] == "ACQUIRED"
    assert second_decision["fencing_token"] == 2
    assert second_decision["lease_record"]["lease_owner_id"] == "runner-two"


def test_artifact_retention_scheduler_lease_store_release_errors() -> None:
    store = ArtifactRetentionSchedulerLeaseStore()
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )
    acquired = store.acquire(request)

    with pytest.raises(ArtifactHandoffError) as invalid_get_exc:
        store.get(" ")
    assert invalid_get_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_store_invalid"
    )

    with pytest.raises(ArtifactHandoffError) as missing_release_exc:
        store.release(scheduler_id="missing", lease_token="token")
    assert missing_release_exc.value.status_code == 404
    assert missing_release_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_not_found"
    )

    with pytest.raises(ArtifactHandoffError) as mismatch_exc:
        store.release(
            scheduler_id=request["scheduler_id"],
            lease_token="wrong-token",
        )
    assert mismatch_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_token_mismatch"
    )

    released = store.release(
        scheduler_id=request["scheduler_id"],
        lease_token=acquired["lease_token"],
    )
    assert released["released_at"] == REQUESTED_AT
    assert released["last_observed_at"] == REQUESTED_AT


def test_artifact_retention_scheduler_sqlalchemy_lease_store_sqlite_lifecycle() -> None:
    session_factory = sqlite_scheduler_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    first = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        lease_owner_id="sql-runner-one",
        idempotency_key="sql-lease-0513",
    )
    second = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-09-01T02:01:00Z",
        lease_owner_id="sql-runner-two",
        idempotency_key="sql-lease-0513-second",
    )

    acquired = store.acquire(first)
    duplicate = store.acquire(first)
    busy = store.acquire(second)
    released = store.release(
        scheduler_id=first["scheduler_id"],
        lease_token=acquired["lease_token"],
        released_at="2026-09-01T02:02:00Z",
    )
    reacquired = store.acquire(second)

    with session_factory() as session:
        rows = (
            session.execute(
                text(
                    """
                    SELECT lease_status, fencing_token, guardrails, metadata
                    FROM ae_artifact_retention_scheduler_leases
                    WHERE scheduler_id = :scheduler_id
                    """
                ),
                {"scheduler_id": first["scheduler_id"]},
            )
            .mappings()
            .all()
        )

    assert store.ensure_available() is None
    assert acquired["decision_status"] == "ACQUIRED"
    assert duplicate["lease_token"] == acquired["lease_token"]
    assert busy["decision_status"] == "BUSY"
    assert released["lease_status"] == "RELEASED"
    assert reacquired["decision_status"] == "ACQUIRED"
    assert reacquired["fencing_token"] == 2
    assert rows == [
        {
            "lease_status": "HELD",
            "fencing_token": 2,
            "guardrails": json.dumps(reacquired["lease_record"]["guardrails"]),
            "metadata": json.dumps(reacquired["lease_record"]["metadata"]),
        }
    ]


def test_artifact_retention_scheduler_sqlalchemy_lease_store_expired_and_missing_edges() -> None:
    session_factory = sqlite_scheduler_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    first = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
        lease_owner_id="expired-sql-one",
    )
    second = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-09-01T02:11:00Z",
        lease_owner_id="expired-sql-two",
    )

    first_decision = store.acquire(first)
    second_decision = store.acquire(second)

    assert first_decision["decision_status"] == "ACQUIRED"
    assert second_decision["decision_status"] == "ACQUIRED"
    assert second_decision["fencing_token"] == 2
    assert store.get(first["scheduler_id"])["lease_owner_id"] == "expired-sql-two"  # type: ignore[index]
    assert store.get("missing-scheduler") is None

    with pytest.raises(ArtifactHandoffError) as missing_release_exc:
        store.release(scheduler_id="missing-scheduler", lease_token="token")
    assert missing_release_exc.value.status_code == 404


def test_artifact_retention_scheduler_sqlalchemy_lease_store_unavailable_edges() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )

    for operation in (
        store.ensure_available,
        lambda: store.get(request["scheduler_id"]),
        lambda: store.acquire(request),
        lambda: store.release(
            scheduler_id=request["scheduler_id"],
            lease_token="token",
        ),
    ):
        with pytest.raises(ArtifactHandoffError) as exc_info:
            operation()
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == (
            "ae.artifact_retention_scheduler_lease_store_unavailable"
        )
        assert exc_info.value.retryable is True


def test_artifact_retention_scheduler_sqlalchemy_acquire_rereads_missing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = sqlite_scheduler_session_factory()
    store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )

    def missing_select(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(scheduler_module, "_select_scheduler_lease", missing_select)

    with pytest.raises(ArtifactHandoffError) as exc_info:
        store.acquire(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_lease_store_unavailable"
    )
    assert exc_info.value.retryable is True


def test_artifact_retention_scheduler_default_store_factory_uses_persistence() -> None:
    session_factory = sqlite_scheduler_session_factory()
    app_with_persistence = SimpleNamespace(
        state=SimpleNamespace(
            nex_persistence=SimpleNamespace(api_session_factory=session_factory)
        )
    )
    app_without_persistence = SimpleNamespace(state=SimpleNamespace())

    persisted = build_default_artifact_retention_scheduler_lease_store(
        app_with_persistence
    )
    fallback = build_default_artifact_retention_scheduler_lease_store(
        app_without_persistence
    )

    assert isinstance(persisted, SqlAlchemyArtifactRetentionSchedulerLeaseStore)
    assert fallback is DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE


def test_artifact_retention_scheduler_lease_table_sql_profiles() -> None:
    postgres_sql = artifact_retention_scheduler_lease_table_sql("postgresql")
    sqlite_sql = artifact_retention_scheduler_lease_table_sql("sqlite")

    assert "JSONB" in postgres_sql
    assert "jsonb_typeof(guardrails)" in postgres_sql
    assert "TIMESTAMPTZ" in postgres_sql
    assert "JSONB" not in sqlite_sql
    assert "jsonb_typeof" not in sqlite_sql
    assert "updated_at TEXT NOT NULL" in sqlite_sql


def test_artifact_retention_scheduler_sql_helpers_json_fallback_edges() -> None:
    assert "CAST(:guardrails AS JSONB)" in scheduler_module._scheduler_lease_upsert_sql(
        "postgresql"
    )
    assert scheduler_module._json_value(None, {"fallback": True}) == {
        "fallback": True
    }
    assert scheduler_module._json_value({"live": True}, {}) == {"live": True}
    assert scheduler_module._json_value("{not-json", {"fallback": True}) == {
        "fallback": True
    }
    assert scheduler_module._json_value("null", {"fallback": True}) == {
        "fallback": True
    }
    assert scheduler_module._json_value(object(), {"fallback": True}) == {
        "fallback": True
    }


@pytest.mark.parametrize(
    ("patch", "error_code", "detail"),
    (
        (
            {"lease_request_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_lease_request_schema_invalid",
            "schema version",
        ),
        (
            {"service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "service id",
        ),
        (
            {"scheduler_id": " "},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "scheduler_id",
        ),
        (
            {"operation": "daemon_loop"},
            "ae.artifact_retention_scheduler_lease_operation_invalid",
            "operation",
        ),
        (
            {"lease_ttl_seconds": "ten"},
            "ae.artifact_retention_scheduler_lease_ttl_invalid",
            "integer",
        ),
        (
            {"lease_ttl_seconds": 59},
            "ae.artifact_retention_scheduler_lease_ttl_invalid",
            "range",
        ),
        (
            {"lease_ttl_seconds": 3601},
            "ae.artifact_retention_scheduler_lease_ttl_invalid",
            "range",
        ),
        (
            {"expires_at": "2026-09-01T02:09:00Z"},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "expires_at",
        ),
        (
            {"stale_after_seconds": 600},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "stale",
        ),
        (
            {"tick_id": " "},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "tick id",
        ),
        (
            {"guardrails": {"lease_required_before_tick": True}},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "guardrails",
        ),
        (
            {"metadata": {"metadata_only": True}},
            "ae.artifact_retention_scheduler_lease_request_invalid",
            "metadata",
        ),
        (
            {"storage_ref": "ae://private"},
            "ae.artifact_retention_payload_unsafe",
            "private material",
        ),
    ),
)
def test_artifact_retention_scheduler_lease_request_validation_edges(
    patch: dict[str, Any],
    error_code: str,
    detail: str,
) -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_lease_request({**request, **patch})

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_lease_request_type_and_normalizer_edges() -> None:
    with pytest.raises(ArtifactHandoffError) as request_type_exc:
        validate_artifact_retention_scheduler_lease_request([])  # type: ignore[arg-type]
    assert request_type_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_request_invalid"
    )

    with pytest.raises(ArtifactHandoffError):
        normalize_artifact_retention_scheduler_lease_operation(None)
    with pytest.raises(ArtifactHandoffError):
        normalize_artifact_retention_scheduler_lease_ttl_seconds(object())  # type: ignore[arg-type]
    with pytest.raises(ArtifactHandoffError):
        normalize_artifact_retention_scheduler_lease_record_status(None)

    assert normalize_artifact_retention_scheduler_lease_operation(
        "manual_tick_once"
    ) == "manual_tick_once"
    assert normalize_artifact_retention_scheduler_lease_ttl_seconds(None) == 600
    assert normalize_artifact_retention_scheduler_lease_record_status("held") == "HELD"

    config_without_checked_at = build_artifact_retention_scheduler_config()
    config_without_checked_at.pop("checked_at")
    fallback_request = build_artifact_retention_scheduler_lease_request(
        scheduler_config=config_without_checked_at,
    )
    assert fallback_request["requested_at"] == "2026-09-01T00:00:00Z"


@pytest.mark.parametrize(
    ("patch", "error_code", "detail"),
    (
        (
            {"lease_record_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_lease_record_schema_invalid",
            "schema version",
        ),
        (
            {"service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "service id",
        ),
        (
            {"lease_token": ""},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "lease_token",
        ),
        (
            {"operation": "daemon_loop"},
            "ae.artifact_retention_scheduler_lease_operation_invalid",
            "operation",
        ),
        (
            {"lease_status": "BUSY"},
            "ae.artifact_retention_scheduler_lease_record_status_invalid",
            "status",
        ),
        (
            {"fencing_token": 0},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "positive integer",
        ),
        (
            {"expires_at": "2026-09-01T01:59:00Z"},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "expiry",
        ),
        (
            {"lease_status": "RELEASED"},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "released_at",
        ),
        (
            {"lease_status": "HELD", "released_at": "2026-09-01T02:01:00Z"},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "released_at",
        ),
        (
            {"last_observed_at": "2026-09-01T01:59:00Z"},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "observation",
        ),
        (
            {"tick_id": ""},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "tick id",
        ),
        (
            {"guardrails": {}},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "guardrails",
        ),
        (
            {"metadata": {}},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "metadata",
        ),
    ),
)
def test_artifact_retention_scheduler_lease_record_validation_edges(
    patch: dict[str, Any],
    error_code: str,
    detail: str,
) -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )
    record = build_artifact_retention_scheduler_lease_record(request)

    with pytest.raises(ArtifactHandoffError) as exc_info:
        validate_artifact_retention_scheduler_lease_record({**record, **patch})

    assert exc_info.value.error_code == error_code
    assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_lease_record_type_release_and_datetime_edges() -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )
    record = build_artifact_retention_scheduler_lease_record(request)

    with pytest.raises(ArtifactHandoffError) as record_type_exc:
        validate_artifact_retention_scheduler_lease_record([])  # type: ignore[arg-type]
    assert record_type_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_record_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as release_token_exc:
        release_artifact_retention_scheduler_lease(record, lease_token="wrong")
    assert release_token_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_token_mismatch"
    )
    with pytest.raises(ArtifactHandoffError) as missing_token_exc:
        release_artifact_retention_scheduler_lease(record, lease_token=" ")
    assert missing_token_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_release_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as bad_fencing_exc:
        build_artifact_retention_scheduler_lease_record(
            request,
            fencing_token=object(),
        )
    assert bad_fencing_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_record_invalid"
    )
    with pytest.raises(ArtifactHandoffError) as released_before_exc:
        validate_artifact_retention_scheduler_lease_record(
            {
                **record,
                "lease_status": "RELEASED",
                "released_at": "2026-09-01T01:59:00Z",
            }
        )
    assert "release precedes" in released_before_exc.value.detail

    aware_request = build_artifact_retention_scheduler_lease_request(
        requested_at=datetime(2026, 9, 1, 2, 0, tzinfo=UTC).isoformat(),
        lease_ttl_seconds=120,
    )
    assert aware_request["requested_at"] == REQUESTED_AT
    assert aware_request["expires_at"] == "2026-09-01T02:02:00Z"


def test_artifact_retention_scheduler_lease_decision_validation_edges() -> None:
    request = build_artifact_retention_scheduler_lease_request(
        requested_at=REQUESTED_AT,
    )
    record = build_artifact_retention_scheduler_lease_record(request)
    decision = build_artifact_retention_scheduler_lease_decision(
        request,
        lease_record=record,
    )
    busy = build_artifact_retention_scheduler_lease_decision(
        request,
        blocking_lease=record,
    )

    with pytest.raises(ArtifactHandoffError) as both_exc:
        build_artifact_retention_scheduler_lease_decision(
            request,
            lease_record=record,
            blocking_lease=record,
        )
    assert "both acquired and busy" in both_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as no_blocker_exc:
        build_artifact_retention_scheduler_lease_decision(request)
    assert no_blocker_exc.value.error_code == (
        "ae.artifact_retention_scheduler_lease_decision_invalid"
    )

    invalid_cases = (
        (
            [],
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "object",
        ),
        (
            {**decision, "lease_decision_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_lease_decision_schema_invalid",
            "schema version",
        ),
        (
            {**decision, "service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "service id",
        ),
        (
            {**decision, "operation": "daemon_loop"},
            "ae.artifact_retention_scheduler_lease_operation_invalid",
            "operation",
        ),
        (
            {**decision, "decision_status": "RELEASED"},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "status",
        ),
        (
            {**decision, "lease_acquired": False},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Acquired",
        ),
        (
            {**decision, "lease_token": "other-token"},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Acquired",
        ),
        (
            {**decision, "fencing_token": 99},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Acquired",
        ),
        (
            {
                **decision,
                "lease_record": {
                    **record,
                    "scheduler_id": "other-scheduler",
                },
            },
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Acquired",
        ),
        (
            {**busy, "lease_acquired": True},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {**busy, "skip_reason": None},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {**busy, "lease_record": record},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {**busy, "lease_token": record["lease_token"]},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {**busy, "fencing_token": record["fencing_token"]},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {
                **busy,
                "blocking_lease": {
                    **record,
                    "scheduler_id": "other-scheduler",
                },
            },
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Busy",
        ),
        (
            {**decision, "guardrails": {}},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "guardrails",
        ),
        (
            {**decision, "metadata": {}},
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "metadata",
        ),
    )
    for payload, error_code, detail in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_lease_decision(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    mismatched = deepcopy(decision)
    mismatched["lease_record"]["lease_owner_id"] = "other-owner"
    with pytest.raises(ArtifactHandoffError) as owner_exc:
        validate_artifact_retention_scheduler_lease_decision(mismatched)
    assert "Acquired" in owner_exc.value.detail
