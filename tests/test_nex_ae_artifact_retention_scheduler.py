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
from nex_runtime import InMemoryJobQueue
from nex_ae_api.artifact_retention_scheduler import (
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    ArtifactRetentionSchedulerLeaseStore,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
    artifact_retention_scheduler_lease_table_sql,
    artifact_retention_scheduler_lease_idempotency_key,
    build_default_artifact_retention_scheduler_lease_store,
    build_artifact_retention_scheduler_daemon_config,
    build_artifact_retention_scheduler_daemon_control_plan,
    build_artifact_retention_scheduler_lease_decision,
    build_artifact_retention_scheduler_lease_record,
    build_artifact_retention_scheduler_lease_request,
    normalize_artifact_retention_scheduler_daemon_control_action,
    normalize_artifact_retention_scheduler_lease_operation,
    normalize_artifact_retention_scheduler_lease_record_status,
    normalize_artifact_retention_scheduler_lease_ttl_seconds,
    release_artifact_retention_scheduler_lease,
    run_artifact_retention_scheduler_tick_once,
    summarize_artifact_retention_scheduler_daemon_config,
    summarize_artifact_retention_scheduler_daemon_control_plan,
    summarize_artifact_retention_scheduler_lease_decision,
    summarize_artifact_retention_scheduler_tick_once_result,
    validate_artifact_retention_scheduler_daemon_config,
    validate_artifact_retention_scheduler_daemon_control_plan,
    validate_artifact_retention_scheduler_lease_decision,
    validate_artifact_retention_scheduler_lease_record,
    validate_artifact_retention_scheduler_lease_request,
    validate_artifact_retention_scheduler_tick_once_result,
)
from nex_ae_api.artifacts import (
    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION,
    ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS,
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
    ArtifactHandoffError,
    build_artifact_retention_batch_plan,
    build_artifact_retention_candidate_filter,
    build_artifact_retention_scheduler_config,
)


REQUESTED_AT = "2026-09-01T02:00:00Z"
EXPIRES_AT = "2026-09-01T02:10:00Z"
READY_TICK_AT = "2026-08-31T17:30:00Z"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeArtifactRetentionStore:
    def __init__(self, *, candidate_count: int = 1) -> None:
        self.candidate_count = candidate_count
        self.calls: list[dict[str, Any]] = []

    def plan_retention_batch(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        retention_days: int | str | None = None,
        as_of: str | None = None,
        scan_limit: int | str | None = None,
        max_delete_count: int | str | None = None,
        checked_at: str | None = None,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "retention_days": retention_days,
                "as_of": as_of,
                "scan_limit": scan_limit,
                "max_delete_count": max_delete_count,
                "checked_at": checked_at,
                "requested_by": requested_by,
                "idempotency_key": idempotency_key,
            }
        )
        candidate_filter = build_artifact_retention_candidate_filter(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            as_of=as_of,
            limit=scan_limit,
        )
        items = [
            {
                "artifact_id": f"artifact-retention-candidate-{index}",
                "display_title": f"Old artifact {index}",
                "artifact_status": "DELETED",
                "logical_purged_at": "2026-07-31T00:00:00Z",
                "purge_eligible_at": "2026-08-30T00:00:00Z",
                "age_days_after_logical_purge": 32,
                "version_count": 1,
                "file_count": 1,
                "link_count": 0,
                "render_job_count": 1,
            }
            for index in range(self.candidate_count)
        ]
        return build_artifact_retention_batch_plan(
            {
                "artifact_retention_candidate_collection_schema_version": (
                    AE_ARTIFACT_RETENTION_CANDIDATE_COLLECTION_SCHEMA_VERSION
                ),
                "filter": candidate_filter,
                "count": len(items),
                "limit": candidate_filter["limit"],
                "items": items,
            },
            max_delete_count=max_delete_count,
            checked_at=checked_at,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )


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


def test_artifact_retention_scheduler_daemon_config_and_control_contract_ready() -> None:
    queue = InMemoryJobQueue()
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=REQUESTED_AT,
    )
    control_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action="manual_tick_once",
        daemon_config=daemon_config,
        requested_at=REQUESTED_AT,
        requested_by={
            "actor_type": "operator",
            "actor_id": "ag-retention-operator",
            "tenant_id": "tenant-001",
        },
        reason="manual dry-run tick",
    )
    serialized_config = json.dumps(daemon_config, ensure_ascii=False, sort_keys=True)
    serialized_plan = json.dumps(control_plan, ensure_ascii=False, sort_keys=True)

    assert daemon_config["daemon_config_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION
    )
    assert daemon_config["runtime"]["scheduler_daemon_enabled"] is False
    assert daemon_config["runtime"]["scheduler_daemon_started"] is False
    assert daemon_config["runtime"]["continuous_loop_started"] is False
    assert daemon_config["runtime"]["manual_tick_once_enabled"] is True
    assert daemon_config["lease_repository"] == {
        "required": True,
        "available": True,
        "backend": "in_memory",
        "lease_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
        ),
        "failure_code": None,
    }
    assert summarize_artifact_retention_scheduler_daemon_config(daemon_config) == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "scheduler_daemon_enabled": False,
        "scheduler_daemon_started": False,
        "manual_tick_once_decision_status": "READY",
        "manual_tick_once_block_reason": None,
        "lease_repository_available": True,
        "job_queue_available": True,
    }
    assert control_plan["daemon_control_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION
    )
    assert control_plan["decision_status"] == "READY"
    assert control_plan["block_reason"] is None
    assert control_plan["execution_plan"] == {
        "requires_lease": True,
        "runs_tick_once": True,
        "dispatches_job_queue": True,
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "writes_history": False,
        "physical_delete_enabled": False,
    }
    assert summarize_artifact_retention_scheduler_daemon_control_plan(control_plan) == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "action": "manual_tick_once",
        "decision_status": "READY",
        "block_reason": None,
        "runs_tick_once": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
    }
    assert validate_artifact_retention_scheduler_daemon_config(daemon_config) == (
        daemon_config
    )
    assert validate_artifact_retention_scheduler_daemon_control_plan(control_plan) == (
        control_plan
    )
    assert "postgresql://" not in serialized_config
    assert "/data/nex-platform" not in serialized_config
    assert "postgresql://" not in serialized_plan
    assert "/data/nex-platform" not in serialized_plan


def test_artifact_retention_scheduler_daemon_control_blocks_start_and_noops_status() -> None:
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=REQUESTED_AT,
    )

    status_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action="STATUS_PROBE",
        daemon_config=daemon_config,
        requested_at=REQUESTED_AT,
    )
    start_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action="start_daemon",
        daemon_config=daemon_config,
        requested_at=REQUESTED_AT,
    )
    stop_plan = build_artifact_retention_scheduler_daemon_control_plan(
        action="stop_daemon",
        daemon_config=daemon_config,
        requested_at=REQUESTED_AT,
    )

    assert normalize_artifact_retention_scheduler_daemon_control_action(
        "STATUS_PROBE"
    ) == "status_probe"
    assert status_plan["decision_status"] == "NOOP"
    assert status_plan["execution_plan"]["runs_tick_once"] is False
    assert start_plan["decision_status"] == "BLOCKED"
    assert start_plan["block_reason"] == "daemon_disabled_by_policy"
    assert start_plan["execution_plan"]["starts_daemon"] is False
    assert start_plan["execution_plan"]["starts_continuous_loop"] is False
    assert stop_plan["decision_status"] == "NOOP"
    assert stop_plan["block_reason"] is None


def test_artifact_retention_scheduler_daemon_config_reports_blocked_readiness() -> None:
    no_queue_config = build_artifact_retention_scheduler_daemon_config(
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=REQUESTED_AT,
    )
    invalid_store_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        lease_store=object(),
        checked_at=REQUESTED_AT,
    )

    class BrokenLeaseStore:
        def ensure_available(self) -> None:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.test_lease_store_unavailable",
                detail="lease store unavailable",
                retryable=True,
            )

        def acquire(self, _request: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("acquire should not be called")

        def release(self, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("release should not be called")

    broken_store_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        lease_store=BrokenLeaseStore(),
        checked_at=REQUESTED_AT,
    )

    assert summarize_artifact_retention_scheduler_daemon_config(no_queue_config) == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "scheduler_daemon_enabled": False,
        "scheduler_daemon_started": False,
        "manual_tick_once_decision_status": "BLOCKED",
        "manual_tick_once_block_reason": "job_queue_unavailable",
        "lease_repository_available": True,
        "job_queue_available": False,
    }
    assert invalid_store_config["lease_repository"]["available"] is False
    assert invalid_store_config["lease_repository"]["failure_code"] == (
        "ae.artifact_retention_scheduler_lease_store_invalid"
    )
    assert summarize_artifact_retention_scheduler_daemon_config(
        invalid_store_config
    )["manual_tick_once_block_reason"] == "lease_repository_unavailable"
    assert broken_store_config["lease_repository"]["available"] is False
    assert broken_store_config["lease_repository"]["backend"] == "BrokenLeaseStore"
    assert broken_store_config["lease_repository"]["failure_code"] == (
        "ae.test_lease_store_unavailable"
    )


def test_artifact_retention_scheduler_daemon_config_validation_edges() -> None:
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=REQUESTED_AT,
    )
    invalid_runtime = {**daemon_config["runtime"], "scheduler_daemon_enabled": True}
    invalid_bool_runtime = {
        **daemon_config["runtime"],
        "job_queue_available": "yes",
    }
    invalid_jitter_runtime = {
        **daemon_config["runtime"],
        "scheduler_tick_jitter_seconds": -1,
    }
    missing_runtime_key = dict(daemon_config["runtime"])
    missing_runtime_key.pop("job_queue_backend")
    invalid_lease_repository = {
        **daemon_config["lease_repository"],
        "available": True,
        "failure_code": "should-not-exist",
    }
    unavailable_without_failure = {
        **daemon_config["lease_repository"],
        "available": False,
    }

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "object",
        ),
        (
            {**daemon_config, "daemon_config_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_config_schema_invalid",
            "schema version",
        ),
        (
            {**daemon_config, "service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "service id",
        ),
        (
            {**daemon_config, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "scheduler_id",
        ),
        (
            {**daemon_config, "checked_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "checked_at",
        ),
        (
            {**daemon_config, "source_scheduler_config_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "source config",
        ),
        (
            {**daemon_config, "runtime": "bad"},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "runtime",
        ),
        (
            {**daemon_config, "runtime": missing_runtime_key},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "runtime keys",
        ),
        (
            {**daemon_config, "runtime": invalid_runtime},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "runtime",
        ),
        (
            {
                **daemon_config,
                "runtime": {
                    **daemon_config["runtime"],
                    "manual_tick_once_enabled": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "runtime",
        ),
        (
            {**daemon_config, "runtime": invalid_bool_runtime},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "boolean",
        ),
        (
            {
                **daemon_config,
                "runtime": {**daemon_config["runtime"], "default_execution_mode": "EXECUTE"},
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "mode",
        ),
        (
            {
                **daemon_config,
                "runtime": {**daemon_config["runtime"], "job_queue_backend": " "},
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "job_queue_backend",
        ),
        (
            {
                **daemon_config,
                "runtime": {
                    **daemon_config["runtime"],
                    "scheduler_tick_interval_seconds": 0,
                },
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "positive integer",
        ),
        (
            {
                **daemon_config,
                "runtime": {
                    **daemon_config["runtime"],
                    "scheduler_tick_jitter_seconds": "bad",
                },
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "jitter",
        ),
        (
            {**daemon_config, "runtime": invalid_jitter_runtime},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "jitter",
        ),
        (
            {**daemon_config, "lease_repository": None},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "lease repository",
        ),
        (
            {**daemon_config, "lease_repository": {"required": True}},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "lease repository keys",
        ),
        (
            {
                **daemon_config,
                "lease_repository": {
                    **daemon_config["lease_repository"],
                    "required": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "lease repository",
        ),
        (
            {
                **daemon_config,
                "lease_repository": {
                    **daemon_config["lease_repository"],
                    "lease_record_schema_version": "wrong",
                },
            },
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "lease schema",
        ),
        (
            {**daemon_config, "lease_repository": invalid_lease_repository},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "cannot include failure",
        ),
        (
            {**daemon_config, "lease_repository": unavailable_without_failure},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "failure_code",
        ),
        (
            {**daemon_config, "supported_actions": []},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "supported actions",
        ),
        (
            {**daemon_config, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "guardrails",
        ),
        (
            {**daemon_config, "metadata": {}},
            "ae.artifact_retention_scheduler_daemon_config_invalid",
            "metadata",
        ),
        (
            {**daemon_config, "storage_ref": "ae://private"},
            "ae.artifact_retention_payload_unsafe",
            "private material",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_config(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_daemon_control_plan_validation_edges() -> None:
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=REQUESTED_AT,
    )
    plan = build_artifact_retention_scheduler_daemon_control_plan(
        action="manual_tick_once",
        daemon_config=daemon_config,
        requested_at=REQUESTED_AT,
    )
    scoped_daemon = {**daemon_config, "scheduler_id": "other-scheduler"}
    scoped_daemon["supported_actions"] = daemon_config["supported_actions"]

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "object",
        ),
        (
            {**plan, "daemon_control_plan_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_control_plan_schema_invalid",
            "schema version",
        ),
        (
            {**plan, "service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "service id",
        ),
        (
            {**plan, "daemon_control_plan_id": " "},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "daemon_control_plan_id",
        ),
        (
            {**plan, "action": "daemon_loop"},
            "ae.artifact_retention_scheduler_daemon_control_action_invalid",
            "action",
        ),
        (
            {**plan, "daemon_config": scoped_daemon},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "scope",
        ),
        (
            {**plan, "requested_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "requested_at",
        ),
        (
            {**plan, "daemon_control_plan_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "plan id",
        ),
        (
            {**plan, "decision_status": "BLOCKED"},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "decision",
        ),
        (
            {**plan, "block_reason": "daemon_disabled_by_policy"},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "block reason",
        ),
        (
            {**plan, "requested_by": {"actor_type": "operator", "actor_id": " "}},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "actor_id",
        ),
        (
            {**plan, "reason": " "},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "reason",
        ),
        (
            {
                **plan,
                "execution_plan": {**plan["execution_plan"], "starts_daemon": True},
            },
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "execution plan",
        ),
        (
            {**plan, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "guardrails",
        ),
        (
            {**plan, "metadata": {**plan["metadata"], "tick_once_dispatched": False}},
            "ae.artifact_retention_scheduler_daemon_control_plan_invalid",
            "metadata",
        ),
        (
            {**plan, "raw_text": "private execution payload"},
            "ae.artifact_retention_payload_unsafe",
            "private material",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_control_plan(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as action_exc:
        normalize_artifact_retention_scheduler_daemon_control_action(None)
    assert action_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_control_action_invalid"
    )


def test_artifact_retention_scheduler_tick_once_enqueues_ready_tick() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()

    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        tick_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="tick-once-0514",
    )
    validated = validate_artifact_retention_scheduler_tick_once_result(result)
    summary = summarize_artifact_retention_scheduler_tick_once_result(result)
    enqueued_job = queue.get_job(
        result["enqueue_result"]["scheduled_job_enqueue_result"]["job_id"]
    )
    released = lease_store.get(result["scheduler_id"])

    assert result["tick_once_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
    )
    assert validated == result
    assert result["result_status"] == "SUCCEEDED"
    assert result["skip_reason"] is None
    assert result["lease_decision"]["decision_status"] == "ACQUIRED"
    assert result["lease_release"]["lease_status"] == "RELEASED"
    assert result["tick_plan"]["tick_status"] == "READY"
    assert result["enqueue_result"]["enqueue_status"] == "ENQUEUED"
    assert result["metadata"] == {
        "metadata_only": True,
        "lease_acquired_before_tick": True,
        "lease_released": True,
        "job_enqueued": True,
        "admission_performed": True,
        "worker_executed": False,
        "history_write_executed": False,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
        "dry_run": True,
    }
    assert result["guardrails"]["scheduler_daemon_started"] is False
    assert result["guardrails"]["continuous_loop_started"] is False
    assert result["guardrails"]["physical_delete_automation_enabled"] is False
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "lease_acquired": True,
        "lease_released": True,
        "job_enqueued": True,
        "worker_executed": False,
    }
    assert artifact_store.calls[0]["checked_at"] == READY_TICK_AT
    assert enqueued_job is not None
    assert enqueued_job["payload"]["trigger_type"] == "scheduler_tick"
    assert released is not None
    assert released["lease_status"] == "RELEASED"


def test_artifact_retention_scheduler_tick_once_noops_without_candidates() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=0)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()

    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        tick_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    assert result["result_status"] == "NOOP"
    assert result["skip_reason"] == "no_retention_candidates"
    assert result["tick_plan"]["tick_status"] == "NOOP"
    assert result["enqueue_result"]["enqueue_status"] == "SKIPPED"
    assert result["metadata"]["job_enqueued"] is False
    assert result["metadata"]["lease_released"] is True


def test_artifact_retention_scheduler_tick_once_skips_when_lease_busy() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    blocking_request = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-08-31T17:29:00Z",
        lease_owner_id="active-runner",
    )
    lease_store.acquire(blocking_request)

    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=artifact_store,
        job_queue=InMemoryJobQueue(),
        lease_store=lease_store,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        tick_at=READY_TICK_AT,
        lease_owner_id="second-runner",
    )

    assert result["result_status"] == "SKIPPED"
    assert result["skip_reason"] == "lease_busy"
    assert result["lease_decision"]["decision_status"] == "BUSY"
    assert result["lease_release"] is None
    assert result["batch_plan"] is None
    assert result["tick_plan"] is None
    assert result["enqueue_result"] is None
    assert result["metadata"]["lease_acquired_before_tick"] is False
    assert artifact_store.calls == []


def test_artifact_retention_scheduler_tick_once_worker_summary_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()
    worker_calls: list[dict[str, Any]] = []

    class FakeWorkerExecution:
        def to_summary(self) -> dict[str, Any]:
            return {
                "status": "SUCCEEDED",
                "handler_result": {"history": {"history_written": True}},
            }

    def fake_worker_once(**kwargs: Any) -> FakeWorkerExecution:
        worker_calls.append(kwargs)
        return FakeWorkerExecution()

    monkeypatch.setattr(
        scheduler_module,
        "run_artifact_retention_scheduled_worker_once",
        fake_worker_once,
    )

    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        history_store=object(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        tick_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        run_worker=True,
        worker_id="worker-0514",
        clock=lambda: READY_TICK_AT,
    )

    assert result["result_status"] == "SUCCEEDED"
    assert result["worker_result"]["status"] == "SUCCEEDED"
    assert result["metadata"]["worker_executed"] is True
    assert result["metadata"]["history_write_executed"] is True
    assert worker_calls[0]["worker_id"] == "worker-0514"
    assert worker_calls[0]["artifact_store"] is artifact_store


def test_artifact_retention_scheduler_tick_once_releases_lease_on_failure() -> None:
    lease_store = ArtifactRetentionSchedulerLeaseStore()

    with pytest.raises(ArtifactHandoffError) as exc_info:
        run_artifact_retention_scheduler_tick_once(
            artifact_store=object(),
            job_queue=InMemoryJobQueue(),
            lease_store=lease_store,
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            tick_at=READY_TICK_AT,
        )

    released = lease_store.get("ae-artifact-retention-scheduler-local-v1")
    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_artifact_store_invalid"
    )
    assert released is not None
    assert released["lease_status"] == "RELEASED"


def test_artifact_retention_scheduler_tick_once_rejects_invalid_lease_store() -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        run_artifact_retention_scheduler_tick_once(
            artifact_store=FakeArtifactRetentionStore(candidate_count=1),
            job_queue=InMemoryJobQueue(),
            lease_store=object(),
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            tick_at=READY_TICK_AT,
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_lease_store_invalid"
    )


def test_artifact_retention_scheduler_tick_once_validation_edges() -> None:
    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=FakeArtifactRetentionStore(candidate_count=1),
        job_queue=InMemoryJobQueue(),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        tick_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    invalid_cases = (
        (
            [],
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "object",
        ),
        (
            {**result, "tick_once_result_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_tick_once_result_schema_invalid",
            "schema version",
        ),
        (
            {**result, "service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "service id",
        ),
        (
            {**result, "result_status": "QUEUED"},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "status",
        ),
        (
            {**result, "skip_reason": "manual-stop"},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "skip reason",
        ),
        (
            {
                **result,
                "lease_decision": {
                    **result["lease_decision"],
                    "lease_owner_id": "other-owner",
                },
            },
            "ae.artifact_retention_scheduler_lease_decision_invalid",
            "Acquired",
        ),
        (
            {**result, "lease_owner_id": "other-owner"},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "lease scope",
        ),
        (
            {**result, "lease_release": None},
            "ae.artifact_retention_scheduler_lease_record_invalid",
            "object",
        ),
        (
            {
                **result,
                "tick_plan": {
                    **result["tick_plan"],
                    "source_plan_id": "other-plan",
                },
            },
            "ae.artifact_retention_scheduler_tick_plan_invalid",
            "command preview",
        ),
        (
            {**result, "metadata": {**result["metadata"], "dry_run": False}},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "metadata",
        ),
        (
            {
                **result,
                "guardrails": {
                    **result["guardrails"],
                    "scheduler_daemon_started": True,
                },
            },
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "guardrails",
        ),
    )
    for payload, error_code, detail in invalid_cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_tick_once_result(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    busy_result = run_artifact_retention_scheduler_tick_once(
        artifact_store=FakeArtifactRetentionStore(candidate_count=1),
        job_queue=InMemoryJobQueue(),
        lease_store=ArtifactRetentionSchedulerLeaseStore(
            records={
                "ae-artifact-retention-scheduler-local-v1": build_artifact_retention_scheduler_lease_record(
                    build_artifact_retention_scheduler_lease_request(
                        requested_at="2026-08-31T17:29:00Z",
                        lease_owner_id="active-runner",
                    )
                )
            }
        ),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        tick_at=READY_TICK_AT,
        lease_owner_id="second-runner",
    )
    with pytest.raises(ArtifactHandoffError) as busy_exc:
        validate_artifact_retention_scheduler_tick_once_result(
            {**busy_result, "batch_plan": result["batch_plan"]}
        )
    assert busy_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_once_result_invalid"
    )


def test_artifact_retention_scheduler_tick_once_lineage_status_and_helper_edges() -> None:
    result = run_artifact_retention_scheduler_tick_once(
        artifact_store=FakeArtifactRetentionStore(candidate_count=1),
        job_queue=InMemoryJobQueue(),
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        tick_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )

    with pytest.raises(ArtifactHandoffError) as lineage_exc:
        validate_artifact_retention_scheduler_tick_once_result(
            {
                **result,
                "lease_release": {
                    **result["lease_release"],
                    "lease_token": "other-token",
                },
            }
        )
    assert lineage_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_once_result_invalid"
    )
    assert "lineage" in lineage_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as status_exc:
        validate_artifact_retention_scheduler_tick_once_result(
            {**result, "result_status": "FAILED"}
        )
    assert status_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_once_result_invalid"
    )
    assert "status" in status_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as worker_exc:
        validate_artifact_retention_scheduler_tick_once_result(
            {**result, "worker_result": "done"}
        )
    assert worker_exc.value.error_code == (
        "ae.artifact_retention_scheduler_tick_once_result_invalid"
    )
    assert "worker result" in worker_exc.value.detail

    assert scheduler_module._scheduler_tick_once_result_status(
        tick_plan=None,
        enqueue_result=result["enqueue_result"],
        worker_result=None,
    ) == "FAILED"
    assert scheduler_module._scheduler_tick_once_result_status(
        tick_plan=result["tick_plan"],
        enqueue_result=result["enqueue_result"],
        worker_result={"status": "FAILED"},
    ) == "FAILED"
    assert scheduler_module._scheduler_tick_once_result_status(
        tick_plan={"tick_status": "SKIPPED"},
        enqueue_result={"enqueue_status": "SKIPPED"},
        worker_result=None,
    ) == "SKIPPED"
    assert scheduler_module._scheduler_tick_once_result_status(
        tick_plan={"tick_status": "READY"},
        enqueue_result={"enqueue_status": "SKIPPED"},
        worker_result=None,
    ) == "SKIPPED"
    assert scheduler_module._scheduler_tick_once_skip_reason(None) is None
    assert scheduler_module._scheduler_tick_once_worker_summary(
        {"status": "SUCCEEDED"}
    ) == {"status": "SUCCEEDED"}
    assert scheduler_module._scheduler_tick_once_worker_summary("idle") == {
        "status": "idle"
    }
    assert (
        scheduler_module._scheduler_tick_once_history_written(
            {"handler_result": "not-a-dict"}
        )
        is False
    )


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
