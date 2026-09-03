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
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
)
from nex_ae_api.artifact_retention_scheduler import (
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
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
    build_artifact_retention_scheduler_daemon_loop_plan,
    build_artifact_retention_scheduler_daemon_runtime_config,
    build_artifact_retention_scheduler_daemon_runtime_state,
    build_artifact_retention_scheduler_daemon_start_stop_guardrail,
    build_artifact_retention_scheduler_lease_decision,
    build_artifact_retention_scheduler_lease_record,
    build_artifact_retention_scheduler_lease_request,
    dispatch_artifact_retention_scheduler_daemon_control,
    normalize_artifact_retention_scheduler_daemon_control_action,
    normalize_artifact_retention_scheduler_lease_operation,
    normalize_artifact_retention_scheduler_lease_record_status,
    normalize_artifact_retention_scheduler_lease_ttl_seconds,
    release_artifact_retention_scheduler_lease,
    run_artifact_retention_scheduler_daemon_one_cycle,
    run_artifact_retention_scheduler_tick_once,
    summarize_artifact_retention_scheduler_daemon_one_cycle_result,
    summarize_artifact_retention_scheduler_daemon_config,
    summarize_artifact_retention_scheduler_daemon_control_plan,
    summarize_artifact_retention_scheduler_daemon_dispatch_result,
    summarize_artifact_retention_scheduler_daemon_loop_plan,
    summarize_artifact_retention_scheduler_daemon_runtime_config,
    summarize_artifact_retention_scheduler_daemon_runtime_state,
    summarize_artifact_retention_scheduler_daemon_start_stop_guardrail,
    summarize_artifact_retention_scheduler_lease_decision,
    summarize_artifact_retention_scheduler_tick_once_result,
    validate_artifact_retention_scheduler_daemon_config,
    validate_artifact_retention_scheduler_daemon_control_plan,
    validate_artifact_retention_scheduler_daemon_dispatch_result,
    validate_artifact_retention_scheduler_daemon_loop_plan,
    validate_artifact_retention_scheduler_daemon_one_cycle_result,
    validate_artifact_retention_scheduler_daemon_runtime_config,
    validate_artifact_retention_scheduler_daemon_runtime_state,
    validate_artifact_retention_scheduler_daemon_start_stop_guardrail,
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


class FailingArtifactRetentionStore(FakeArtifactRetentionStore):
    def plan_retention_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        raise RuntimeError("artifact store unavailable")


class FailingHeartbeatStore:
    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("heartbeat store unavailable")


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


def test_artifact_retention_scheduler_daemon_runtime_config_explicit_opt_in() -> None:
    queue = InMemoryJobQueue()
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        profile="TEST",
        enabled=True,
        explicit_opt_in=True,
        checked_at=REQUESTED_AT,
        interval_seconds="120",
        jitter_seconds="30",
        max_ticks_per_run="1",
        lease_ttl_seconds="120",
        backoff_seconds="45",
    )
    summary = summarize_artifact_retention_scheduler_daemon_runtime_config(
        runtime_config
    )
    serialized = json.dumps(runtime_config, ensure_ascii=False, sort_keys=True)

    assert runtime_config["daemon_runtime_config_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION
    )
    assert runtime_config["enablement"] == {
        "profile": "test",
        "enabled": True,
        "explicit_opt_in": True,
        "enablement_status": "READY",
        "block_reason": None,
    }
    assert runtime_config["timing"] == {
        "interval_seconds": 120,
        "jitter_seconds": 30,
        "backoff_seconds": 45,
    }
    assert runtime_config["runtime"]["job_queue_available"] is True
    assert runtime_config["runtime"]["default_execution_mode"] == "DRY_RUN"
    assert runtime_config["runtime"]["physical_delete_automation_enabled"] is False
    assert runtime_config["loop_policy"] == {
        "one_cycle_runner_required_before_loop": True,
        "max_ticks_per_run": 1,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_enabled": False,
        "continuous_loop_started": False,
        "start_control_enabled": False,
        "stop_control_enabled": False,
    }
    assert runtime_config["lease_policy"]["lease_ttl_seconds"] == 120
    assert runtime_config["lease_policy"]["stale_after_seconds"] >= 120
    assert runtime_config["batch_window"] == {
        "timezone": "Asia/Seoul",
        "start_local_time": "02:00",
        "end_local_time": "05:00",
    }
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "profile": "test",
        "enabled": True,
        "explicit_opt_in": True,
        "enablement_status": "READY",
        "block_reason": None,
        "interval_seconds": 120,
        "jitter_seconds": 30,
        "max_ticks_per_run": 1,
        "lease_ttl_seconds": 120,
        "job_queue_available": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert validate_artifact_retention_scheduler_daemon_runtime_config(
        runtime_config
    ) == runtime_config
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_runtime_config_default_and_blocked() -> None:
    disabled = build_artifact_retention_scheduler_daemon_runtime_config(
        checked_at=REQUESTED_AT,
    )
    blocked = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        enabled=True,
        explicit_opt_in=False,
        checked_at=REQUESTED_AT,
    )

    assert disabled["enablement"]["enablement_status"] == "DISABLED"
    assert disabled["enablement"]["block_reason"] is None
    assert disabled["runtime"]["job_queue_available"] is False
    assert disabled["timing"]["interval_seconds"] == 900
    assert disabled["timing"]["jitter_seconds"] == 60
    assert blocked["enablement"]["enablement_status"] == "BLOCKED"
    assert blocked["enablement"]["block_reason"] == "explicit_opt_in_required"
    assert summarize_artifact_retention_scheduler_daemon_runtime_config(blocked)[
        "job_queue_available"
    ] is True


def test_artifact_retention_scheduler_daemon_runtime_config_validation_edges() -> None:
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=build_artifact_retention_scheduler_config(
            job_queue=InMemoryJobQueue()
        ),
        enabled=True,
        explicit_opt_in=True,
        checked_at=REQUESTED_AT,
    )
    enablement = dict(runtime_config["enablement"])
    timing = dict(runtime_config["timing"])
    runtime = dict(runtime_config["runtime"])
    loop_policy = dict(runtime_config["loop_policy"])
    lease_policy = dict(runtime_config["lease_policy"])
    batch_window = dict(runtime_config["batch_window"])
    missing_enablement_key = dict(enablement)
    missing_enablement_key.pop("block_reason")
    missing_timing_key = dict(timing)
    missing_timing_key.pop("backoff_seconds")
    missing_runtime_key = dict(runtime)
    missing_runtime_key.pop("job_queue_backend")
    missing_loop_key = dict(loop_policy)
    missing_loop_key.pop("stop_control_enabled")
    missing_lease_key = dict(lease_policy)
    missing_lease_key.pop("stale_after_seconds")
    missing_batch_key = dict(batch_window)
    missing_batch_key.pop("timezone")

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "object",
        ),
        (
            {**runtime_config, "daemon_runtime_config_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_schema_invalid",
            "schema version",
        ),
        (
            {**runtime_config, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "service id",
        ),
        (
            {**runtime_config, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "scheduler_id",
        ),
        (
            {**runtime_config, "checked_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "checked_at",
        ),
        (
            {**runtime_config, "source_scheduler_config_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "source config",
        ),
        (
            {**runtime_config, "enablement": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "enablement",
        ),
        (
            {**runtime_config, "enablement": missing_enablement_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "enablement keys",
        ),
        (
            {**runtime_config, "enablement": {**enablement, "profile": "prod"}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "profile",
        ),
        (
            {**runtime_config, "enablement": {**enablement, "enabled": "yes"}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "enabled",
        ),
        (
            {
                **runtime_config,
                "enablement": {**enablement, "enablement_status": "DISABLED"},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "enablement decision",
        ),
        (
            {
                **runtime_config,
                "enablement": {**enablement, "block_reason": "wrong"},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "block reason",
        ),
        (
            {**runtime_config, "timing": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "timing",
        ),
        (
            {**runtime_config, "timing": missing_timing_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "timing keys",
        ),
        (
            {**runtime_config, "timing": {**timing, "interval_seconds": 0}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "positive integer",
        ),
        (
            {**runtime_config, "timing": {**timing, "interval_seconds": 86_401}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "supported maximum",
        ),
        (
            {**runtime_config, "timing": {**timing, "jitter_seconds": -1}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "non-negative integer",
        ),
        (
            {**runtime_config, "timing": {**timing, "jitter_seconds": "bad"}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "non-negative integer",
        ),
        (
            {
                **runtime_config,
                "timing": {**timing, "interval_seconds": 10, "jitter_seconds": 11},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "jitter",
        ),
        (
            {**runtime_config, "timing": {**timing, "backoff_seconds": 3_601}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "supported maximum",
        ),
        (
            {**runtime_config, "runtime": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "runtime section",
        ),
        (
            {**runtime_config, "runtime": missing_runtime_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "runtime section keys",
        ),
        (
            {
                **runtime_config,
                "runtime": {**runtime, "scheduler_tick_admission_enabled": "yes"},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "scheduler_tick_admission_enabled",
        ),
        (
            {
                **runtime_config,
                "runtime": {**runtime, "default_execution_mode": "EXECUTE"},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "mode",
        ),
        (
            {**runtime_config, "runtime": {**runtime, "job_queue_backend": " "}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "job_queue_backend",
        ),
        (
            {
                **runtime_config,
                "runtime": {**runtime, "physical_delete_automation_enabled": True},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "physical delete",
        ),
        (
            {**runtime_config, "loop_policy": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "loop policy",
        ),
        (
            {**runtime_config, "loop_policy": missing_loop_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "loop policy keys",
        ),
        (
            {
                **runtime_config,
                "loop_policy": {
                    **loop_policy,
                    "one_cycle_runner_required_before_loop": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "loop policy",
        ),
        (
            {
                **runtime_config,
                "loop_policy": {**loop_policy, "scheduler_daemon_started": True},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "loop policy",
        ),
        (
            {
                **runtime_config,
                "loop_policy": {**loop_policy, "max_ticks_per_run": 2},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "supported maximum",
        ),
        (
            {**runtime_config, "lease_policy": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "lease policy",
        ),
        (
            {**runtime_config, "lease_policy": missing_lease_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "lease policy keys",
        ),
        (
            {
                **runtime_config,
                "lease_policy": {**lease_policy, "lease_required_before_tick": False},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "lease policy",
        ),
        (
            {
                **runtime_config,
                "lease_policy": {**lease_policy, "stale_after_seconds": 59},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "stale window",
        ),
        (
            {**runtime_config, "batch_window": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "batch window",
        ),
        (
            {**runtime_config, "batch_window": missing_batch_key},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "batch window keys",
        ),
        (
            {
                **runtime_config,
                "batch_window": {**batch_window, "timezone": " "},
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "timezone",
        ),
        (
            {**runtime_config, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "guardrails",
        ),
        (
            {**runtime_config, "metadata": {}},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "metadata",
        ),
        (
            {**runtime_config, "storage_ref": "ae://private"},
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "keys",
        ),
        (
            {
                **runtime_config,
                "metadata": {
                    **runtime_config["metadata"],
                    "secret": "dummy-secret-token",
                },
            },
            "ae.artifact_retention_scheduler_daemon_runtime_config_invalid",
            "metadata",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_runtime_config(  # type: ignore[arg-type]
                payload
            )
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as profile_exc:
        build_artifact_retention_scheduler_daemon_runtime_config(profile="prod")
    assert profile_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_runtime_config_invalid"
    )


def test_artifact_retention_scheduler_daemon_loop_plan_ready_without_side_effects() -> None:
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )

    plan = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        requested_at=READY_TICK_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_loop_plan(plan)
    serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)

    assert plan["daemon_loop_plan_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION
    )
    assert plan["decision_status"] == "READY"
    assert plan["decision_reason"] is None
    assert plan["execution_plan"] == {
        "pure_planning_only": True,
        "evaluates_batch_window": True,
        "in_batch_window": True,
        "acquires_lease": True,
        "runs_tick_once": True,
        "dispatches_job_queue": True,
        "max_ticks_this_run": 1,
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "writes_history": False,
        "physical_delete_enabled": False,
    }
    assert plan["metadata"]["decision_ready"] is True
    assert plan["metadata"]["lease_acquired"] is False
    assert plan["metadata"]["job_enqueued"] is False
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "decision_status": "READY",
        "decision_reason": None,
        "runs_tick_once": True,
        "in_batch_window": True,
        "lease_repository_available": True,
        "job_queue_available": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
    }
    assert validate_artifact_retention_scheduler_daemon_loop_plan(plan) == plan
    assert lease_store.get("ae-artifact-retention-scheduler-local-v1") is None
    assert queue.list_jobs() == []
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_loop_plan_decision_states() -> None:
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    ready_runtime = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    ready_daemon = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )
    disabled = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        requested_at=READY_TICK_AT,
    )
    opt_in_blocked = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=build_artifact_retention_scheduler_daemon_runtime_config(
            scheduler_config=scheduler_config,
            enabled=True,
            explicit_opt_in=False,
            checked_at=READY_TICK_AT,
        ),
        daemon_config=ready_daemon,
        requested_at=READY_TICK_AT,
    )
    outside_window = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=ready_runtime,
        daemon_config=ready_daemon,
        requested_at=REQUESTED_AT,
    )
    stopped = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=ready_runtime,
        daemon_config=ready_daemon,
        requested_at=READY_TICK_AT,
        stop_requested=True,
    )
    no_queue_runtime = build_artifact_retention_scheduler_daemon_runtime_config(
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    no_queue = build_artifact_retention_scheduler_daemon_loop_plan(
        runtime_config=no_queue_runtime,
        daemon_config=build_artifact_retention_scheduler_daemon_config(
            lease_store=lease_store,
            checked_at=READY_TICK_AT,
        ),
        requested_at=READY_TICK_AT,
    )
    no_lease = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=ready_runtime,
        daemon_config=build_artifact_retention_scheduler_daemon_config(
            scheduler_config=scheduler_config,
            lease_store=object(),
            checked_at=READY_TICK_AT,
        ),
        requested_at=READY_TICK_AT,
    )
    tick_admission_disabled_runtime = {
        **ready_runtime,
        "runtime": {
            **ready_runtime["runtime"],
            "scheduler_tick_admission_enabled": False,
        },
    }
    operator_admission_disabled_runtime = {
        **ready_runtime,
        "runtime": {
            **ready_runtime["runtime"],
            "operator_dispatch_admission_enabled": False,
        },
    }
    tick_admission_disabled = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=tick_admission_disabled_runtime,
        daemon_config=ready_daemon,
        requested_at=READY_TICK_AT,
    )
    operator_admission_disabled = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=operator_admission_disabled_runtime,
        daemon_config=ready_daemon,
        requested_at=READY_TICK_AT,
    )

    assert disabled["decision_status"] == "DISABLED"
    assert disabled["decision_reason"] == "runtime_disabled"
    assert disabled["execution_plan"]["runs_tick_once"] is False
    assert opt_in_blocked["decision_status"] == "BLOCKED"
    assert opt_in_blocked["decision_reason"] == "explicit_opt_in_required"
    assert outside_window["decision_status"] == "BLOCKED"
    assert outside_window["decision_reason"] == "outside_batch_window"
    assert outside_window["execution_plan"]["in_batch_window"] is False
    assert stopped["decision_status"] == "NOOP"
    assert stopped["decision_reason"] == "stop_requested"
    assert no_queue["decision_reason"] == "job_queue_unavailable"
    assert no_lease["decision_reason"] == "lease_repository_unavailable"
    assert tick_admission_disabled["decision_reason"] == (
        "scheduler_tick_admission_disabled"
    )
    assert operator_admission_disabled["decision_reason"] == (
        "operator_dispatch_admission_disabled"
    )
    assert queue.list_jobs() == []


def test_artifact_retention_scheduler_daemon_loop_plan_validation_edges() -> None:
    queue = InMemoryJobQueue()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=READY_TICK_AT,
    )
    plan = build_artifact_retention_scheduler_daemon_loop_plan(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        requested_at=READY_TICK_AT,
    )
    runtime_with_bad_timezone = {
        **runtime_config,
        "batch_window": {**runtime_config["batch_window"], "timezone": "Moon/Base"},
    }
    runtime_with_bad_time = {
        **runtime_config,
        "batch_window": {
            **runtime_config["batch_window"],
            "start_local_time": "25:00",
        },
    }
    scoped_runtime = {**runtime_config, "scheduler_id": "other-scheduler"}

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "object",
        ),
        (
            {**plan, "daemon_loop_plan_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_schema_invalid",
            "schema version",
        ),
        (
            {**plan, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "service id",
        ),
        (
            {**plan, "daemon_loop_plan_id": " "},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "daemon_loop_plan_id",
        ),
        (
            {**plan, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "scheduler_id",
        ),
        (
            {**plan, "requested_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "requested_at",
        ),
        (
            {**plan, "stop_requested": "no"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "stop_requested",
        ),
        (
            {**plan, "runtime_config": scoped_runtime},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "scope",
        ),
        (
            {**plan, "runtime_config": runtime_with_bad_timezone},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "timezone",
        ),
        (
            {**plan, "runtime_config": runtime_with_bad_time},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "time",
        ),
        (
            {**plan, "decision_status": "BLOCKED"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "decision",
        ),
        (
            {**plan, "decision_reason": "outside_batch_window"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "decision reason",
        ),
        (
            {**plan, "daemon_loop_plan_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "plan id",
        ),
        (
            {
                **plan,
                "execution_plan": {
                    **plan["execution_plan"],
                    "runs_tick_once": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "execution plan",
        ),
        (
            {**plan, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "guardrails",
        ),
        (
            {**plan, "metadata": {**plan["metadata"], "job_enqueued": True}},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "metadata",
        ),
        (
            {**plan, "storage_ref": "ae://private"},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_loop_plan(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as stop_exc:
        build_artifact_retention_scheduler_daemon_loop_plan(
            scheduler_config=scheduler_config,
            runtime_config=runtime_config,
            daemon_config=daemon_config,
            requested_at=READY_TICK_AT,
            stop_requested="yes",  # type: ignore[arg-type]
        )
    assert stop_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_loop_plan_invalid"
    )


def test_artifact_retention_scheduler_daemon_one_cycle_runs_ready_tick_once() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )

    result = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="daemon-one-cycle-0534",
    )
    summary = summarize_artifact_retention_scheduler_daemon_one_cycle_result(result)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert result["daemon_one_cycle_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION
    )
    assert result["result_status"] == "SUCCEEDED"
    assert result["skip_reason"] is None
    assert result["loop_plan"]["decision_status"] == "READY"
    assert result["tick_once_result"]["result_status"] == "SUCCEEDED"
    assert result["tick_once_result"]["lease_owner_id"] == (
        "ae-artifact-retention-scheduler-daemon-one-cycle"
    )
    assert result["metadata"]["loop_plan_ready"] is True
    assert result["metadata"]["tick_once_ran"] is True
    assert result["metadata"]["daemon_heartbeat_emitted"] is False
    assert result["metadata"]["daemon_heartbeat_failed"] is False
    assert result["metadata"]["daemon_heartbeat_error_observed"] is False
    assert result["metadata"]["lease_acquired_before_tick"] is True
    assert result["metadata"]["lease_released"] is True
    assert result["metadata"]["job_enqueued"] is True
    assert result["metadata"]["scheduler_daemon_started"] is False
    assert result["metadata"]["continuous_loop_started"] is False
    assert result["daemon_heartbeat_results"] == []
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "loop_decision_status": "READY",
        "loop_decision_reason": None,
        "tick_once_ran": True,
        "daemon_heartbeat_emitted": False,
        "daemon_heartbeat_error_observed": False,
        "job_enqueued": True,
        "lease_released": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
    }
    assert validate_artifact_retention_scheduler_daemon_one_cycle_result(result) == (
        result
    )
    assert len(artifact_store.calls) == 1
    assert len(queue.list_jobs()) == 1
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_one_cycle_emits_heartbeat() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id="ae-retention-daemon-heartbeat-test",
        worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        store=heartbeat_store,
        started_at=READY_TICK_AT,
        metadata={"slice": "0537"},
    )
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )

    result = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="daemon-one-cycle-heartbeat-0537",
        daemon_heartbeat_emitter=heartbeat_emitter,
    )
    heartbeat_results = result["daemon_heartbeat_results"]
    heartbeat = heartbeat_store.get_heartbeat(
        "nex-ae-api",
        "ae-retention-daemon-heartbeat-test",
    )
    summary = summarize_artifact_retention_scheduler_daemon_one_cycle_result(result)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert [item["status"] for item in heartbeat_results] == [
        "STARTING",
        "BUSY",
        "IDLE",
    ]
    assert heartbeat_results[1]["active_job_id"] == (
        result["loop_plan"]["daemon_loop_plan_id"]
    )
    assert heartbeat_results[2]["active_job_id"] is None
    assert result["metadata"]["daemon_heartbeat_emitted"] is True
    assert result["metadata"]["daemon_heartbeat_failed"] is False
    assert result["metadata"]["daemon_heartbeat_error_observed"] is False
    assert summary["daemon_heartbeat_emitted"] is True
    assert summary["daemon_heartbeat_error_observed"] is False
    assert heartbeat is not None
    assert heartbeat["status"] == "IDLE"
    assert heartbeat["active_job_id"] is None
    assert heartbeat["metadata"]["slice"] == "0537"
    assert heartbeat["metadata"]["phase"] == "one_cycle_finished"
    assert heartbeat["metadata"]["one_cycle_only"] is True
    assert heartbeat["metadata"]["scheduler_daemon_started"] is False
    assert heartbeat["metadata"]["continuous_loop_started"] is False
    assert validate_artifact_retention_scheduler_daemon_one_cycle_result(result) == (
        result
    )
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized


def test_artifact_retention_scheduler_daemon_one_cycle_heartbeat_failure_is_safe() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id="ae-retention-daemon-heartbeat-failing-store",
        worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        store=FailingHeartbeatStore(),
        started_at=READY_TICK_AT,
    )

    result = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        daemon_heartbeat_emitter=heartbeat_emitter,
    )

    assert result["result_status"] == "SKIPPED"
    assert result["skip_reason"] == "runtime_disabled"
    assert result["daemon_heartbeat_results"] == [
        {
            "ok": False,
            "error_code": "worker_heartbeat.emit_failed",
            "detail": "worker heartbeat emission failed",
            "status_code": 503,
        },
        {
            "ok": False,
            "error_code": "worker_heartbeat.emit_failed",
            "detail": "worker heartbeat emission failed",
            "status_code": 503,
        },
    ]
    assert result["metadata"]["daemon_heartbeat_emitted"] is True
    assert result["metadata"]["daemon_heartbeat_failed"] is True
    assert result["metadata"]["daemon_heartbeat_error_observed"] is False
    assert artifact_store.calls == []
    assert queue.list_jobs() == []


def test_artifact_retention_scheduler_daemon_one_cycle_rejects_bad_heartbeat_emitter() -> None:
    with pytest.raises(ArtifactHandoffError) as exc_info:
        run_artifact_retention_scheduler_daemon_one_cycle(
            artifact_store=FakeArtifactRetentionStore(candidate_count=1),
            job_queue=InMemoryJobQueue(),
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            requested_at=READY_TICK_AT,
            daemon_heartbeat_emitter=object(),
        )

    assert exc_info.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_heartbeat_invalid"
    )
    assert "emitter" in exc_info.value.detail


def test_artifact_retention_scheduler_daemon_one_cycle_emits_error_heartbeat() -> None:
    artifact_store = FailingArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    heartbeat_store = InMemoryWorkerHeartbeatStore()
    heartbeat_emitter = WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id="ae-retention-daemon-heartbeat-error-test",
        worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        store=heartbeat_store,
        started_at=READY_TICK_AT,
    )
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )

    with pytest.raises(RuntimeError) as exc_info:
        run_artifact_retention_scheduler_daemon_one_cycle(
            artifact_store=artifact_store,
            job_queue=queue,
            lease_store=lease_store,
            scheduler_config=scheduler_config,
            runtime_config=runtime_config,
            daemon_config=daemon_config,
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            owner_user_id="user-001",
            requested_at=READY_TICK_AT,
            daemon_heartbeat_emitter=heartbeat_emitter,
        )
    heartbeat = heartbeat_store.get_heartbeat(
        "nex-ae-api",
        "ae-retention-daemon-heartbeat-error-test",
    )

    assert "artifact store unavailable" in str(exc_info.value)
    assert heartbeat is not None
    assert heartbeat["status"] == "ERROR"
    assert heartbeat["active_job_id"] is not None
    assert heartbeat["metadata"]["phase"] == "tick_once_failed"
    assert heartbeat["metadata"]["loop_decision_status"] == "READY"
    assert artifact_store.calls[0]["checked_at"] == READY_TICK_AT
    released_lease = lease_store.get("ae-artifact-retention-scheduler-local-v1")
    assert released_lease is not None
    assert released_lease["lease_status"] == "RELEASED"


def test_artifact_retention_scheduler_daemon_one_cycle_skips_before_tick() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    ready_runtime = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    ready_daemon = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )

    disabled = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )
    outside_window = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=ready_runtime,
        daemon_config=ready_daemon,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=REQUESTED_AT,
    )
    stopped = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=ready_runtime,
        daemon_config=ready_daemon,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        stop_requested=True,
    )

    assert disabled["result_status"] == "SKIPPED"
    assert disabled["skip_reason"] == "runtime_disabled"
    assert disabled["tick_once_result"] is None
    assert disabled["metadata"]["skipped_before_tick"] is True
    assert outside_window["result_status"] == "SKIPPED"
    assert outside_window["skip_reason"] == "outside_batch_window"
    assert outside_window["metadata"]["tick_once_ran"] is False
    assert stopped["result_status"] == "NOOP"
    assert stopped["skip_reason"] == "stop_requested"
    assert artifact_store.calls == []
    assert queue.list_jobs() == []
    assert lease_store.get("ae-artifact-retention-scheduler-local-v1") is None


def test_artifact_retention_scheduler_daemon_one_cycle_tick_result_branches() -> None:
    queue = InMemoryJobQueue()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    no_candidate_store = FakeArtifactRetentionStore(candidate_count=0)
    no_candidate_lease_store = ArtifactRetentionSchedulerLeaseStore()
    no_candidate = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=no_candidate_store,
        job_queue=queue,
        lease_store=no_candidate_lease_store,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=build_artifact_retention_scheduler_daemon_config(
            scheduler_config=scheduler_config,
            lease_store=no_candidate_lease_store,
            checked_at=READY_TICK_AT,
        ),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        as_of="2026-09-01T00:00:00Z",
        idempotency_key="daemon-one-cycle-noop-0534",
    )
    busy_store = FakeArtifactRetentionStore(candidate_count=1)
    busy_queue = InMemoryJobQueue()
    busy_scheduler_config = build_artifact_retention_scheduler_config(
        job_queue=busy_queue
    )
    busy_runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=busy_scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    busy_lease_store = ArtifactRetentionSchedulerLeaseStore()
    busy_lease_store.acquire(
        build_artifact_retention_scheduler_lease_request(
            scheduler_config=busy_scheduler_config,
            requested_at="2026-08-31T17:29:00Z",
            lease_owner_id="already-running-daemon",
        )
    )
    busy = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=busy_store,
        job_queue=busy_queue,
        lease_store=busy_lease_store,
        scheduler_config=busy_scheduler_config,
        runtime_config=busy_runtime_config,
        daemon_config=build_artifact_retention_scheduler_daemon_config(
            scheduler_config=busy_scheduler_config,
            lease_store=busy_lease_store,
            checked_at=READY_TICK_AT,
        ),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )

    assert no_candidate["result_status"] == "NOOP"
    assert no_candidate["skip_reason"] == "no_retention_candidates"
    assert no_candidate["metadata"]["tick_once_ran"] is True
    assert no_candidate["metadata"]["lease_released"] is True
    assert no_candidate_store.calls[0]["checked_at"] == READY_TICK_AT
    assert busy["result_status"] == "SKIPPED"
    assert busy["skip_reason"] == "lease_busy"
    assert busy["metadata"]["tick_once_ran"] is True
    assert busy["metadata"]["lease_acquired_before_tick"] is False
    assert busy["metadata"]["job_enqueued"] is False
    assert busy_store.calls == []
    assert busy_queue.list_jobs() == []


def test_artifact_retention_scheduler_daemon_one_cycle_validation_edges() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )
    result = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        as_of="2026-09-01T00:00:00Z",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="daemon-one-cycle-validation-0534",
    )
    skipped = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=FakeArtifactRetentionStore(candidate_count=1),
        job_queue=InMemoryJobQueue(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )
    scoped_loop_plan = {**result["loop_plan"], "scheduler_id": "other-scheduler"}
    valid_heartbeat = {
        "ok": True,
        "service_id": "nex-ae-api",
        "worker_id": "ae-retention-daemon-validation",
        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        "status": "STARTING",
        "active_job_id": None,
    }

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "object",
        ),
        (
            {**result, "daemon_one_cycle_result_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_schema_invalid",
            "schema version",
        ),
        (
            {**result, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "service id",
        ),
        (
            {**result, "daemon_one_cycle_result_id": " "},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "daemon_one_cycle_result_id",
        ),
        (
            {**result, "scheduler_id": " "},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "scheduler_id",
        ),
        (
            {**result, "run_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "run_at",
        ),
        (
            {**result, "result_status": "UNKNOWN"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "status",
        ),
        (
            {**result, "loop_plan": scoped_loop_plan},
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "scope",
        ),
        (
            {**result, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "scope",
        ),
        (
            {**result, "run_at": REQUESTED_AT},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "run time",
        ),
        (
            {**result, "tick_once_result": None},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "object",
        ),
        (
            {**result, "daemon_heartbeat_results": "bad"},
            "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            "list",
        ),
        (
            {
                **result,
                "daemon_heartbeat_results": [
                    {**valid_heartbeat, "worker_type": "wrong-worker-type"}
                ],
            },
            "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            "worker type",
        ),
        (
            {
                **result,
                "daemon_heartbeat_results": [
                    {
                        "ok": False,
                        "error_code": "worker_heartbeat.emit_failed",
                        "detail": "worker heartbeat emission failed",
                        "status_code": 0,
                    }
                ],
            },
            "ae.artifact_retention_scheduler_daemon_heartbeat_invalid",
            "status_code",
        ),
        (
            {**skipped, "tick_once_result": result["tick_once_result"]},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "cannot include a tick",
        ),
        (
            {**result, "skip_reason": "lease_busy"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "skip reason",
        ),
        (
            {**result, "daemon_one_cycle_result_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "result id",
        ),
        (
            {
                **result,
                "execution_plan": {
                    **result["execution_plan"],
                    "runs_tick_once": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "execution plan",
        ),
        (
            {**result, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "guardrails",
        ),
        (
            {**result, "metadata": {**result["metadata"], "job_enqueued": False}},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "metadata",
        ),
        (
            {
                **result,
                "daemon_heartbeat_results": [valid_heartbeat],
                "metadata": {
                    **result["metadata"],
                    "daemon_heartbeat_emitted": False,
                },
            },
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "metadata",
        ),
        (
            {**result, "storage_ref": "ae://private"},
            "ae.artifact_retention_scheduler_daemon_one_cycle_result_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_one_cycle_result(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


def test_artifact_retention_scheduler_daemon_runtime_state_defaults() -> None:
    state = build_artifact_retention_scheduler_daemon_runtime_state(
        observed_at=READY_TICK_AT,
    )
    summary = summarize_artifact_retention_scheduler_daemon_runtime_state(state)
    serialized = json.dumps(state, ensure_ascii=False, sort_keys=True)

    assert state["daemon_runtime_state_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION
    )
    assert state["service_id"] == "nex-ae-api"
    assert state["scheduler_id"] == "ae-artifact-retention-scheduler-local-v1"
    assert state["daemon_instance_id"]
    assert state["observed_at"] == READY_TICK_AT
    assert state["lifecycle_status"] == "STOPPED"
    assert state["lifecycle_reason"] == "initialized"
    assert state["stop_requested"] is False
    assert state["shutdown_requested_at"] is None
    assert state["last_cycle"] is None
    assert state["next_tick_at"] is None
    assert state["cycle_count"] == 0
    assert state["consecutive_failure_count"] == 0
    assert state["heartbeat_worker_id"] is None
    assert state["runtime_config"]["enablement"]["enablement_status"] == "DISABLED"
    assert state["daemon_config"]["service_id"] == "nex-ae-api"
    assert state["guardrails"] == {
        "metadata_only": True,
        "state_snapshot_only": True,
        "daemon_process_owner_ae": True,
        "daemon_as_jobqueue_job_allowed": False,
        "retention_work_uses_job_queue": True,
        "job_enqueue_performed": False,
        "worker_execution_performed": False,
        "runtime_state_persisted_by_builder": False,
        "continuous_loop_started_by_builder": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }
    assert state["metadata"] == {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "safe_for_ag_projection": True,
        "state_snapshot_only": True,
        "lifecycle_running": False,
        "lifecycle_stopped": True,
        "lifecycle_error": False,
        "stop_requested": False,
        "shutdown_requested": False,
        "last_cycle_present": False,
        "last_cycle_failed": False,
        "next_tick_scheduled": False,
        "consecutive_failures_present": False,
        "job_enqueued": False,
        "worker_executed": False,
        "runtime_state_persisted": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "daemon_instance_id": state["daemon_instance_id"],
        "lifecycle_status": "STOPPED",
        "lifecycle_reason": "initialized",
        "stop_requested": False,
        "shutdown_requested": False,
        "last_cycle_status": None,
        "next_tick_at": None,
        "cycle_count": 0,
        "consecutive_failure_count": 0,
        "heartbeat_worker_id": None,
        "state_snapshot_only": True,
        "retention_work_uses_job_queue": True,
        "continuous_loop_started_by_builder": False,
    }
    assert validate_artifact_retention_scheduler_daemon_runtime_state(state) == state
    assert "postgresql://" not in serialized
    assert "/data/nex-platform" not in serialized
    assert "dummy-secret-token" not in serialized


def test_artifact_retention_scheduler_daemon_runtime_state_running_last_cycle() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
        interval_seconds=120,
        jitter_seconds=10,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        checked_at=READY_TICK_AT,
    )
    one_cycle = run_artifact_retention_scheduler_daemon_one_cycle(
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        as_of="2026-09-01T00:00:00Z",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="daemon-runtime-state-0542",
    )

    state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status="RUNNING",
        lifecycle_reason=None,
        observed_at=READY_TICK_AT,
        last_cycle_result=one_cycle,
        next_tick_at="2026-08-31T17:32:00Z",
        cycle_count="1",
        heartbeat_worker_id="ae-retention-daemon-001",
    )
    summary = summarize_artifact_retention_scheduler_daemon_runtime_state(state)

    assert state["lifecycle_reason"] == "bounded_loop_running"
    assert state["last_cycle"] == {
        "daemon_one_cycle_result_id": one_cycle["daemon_one_cycle_result_id"],
        "run_at": READY_TICK_AT,
        "result_status": "SUCCEEDED",
        "skip_reason": None,
        "loop_decision_status": "READY",
        "loop_decision_reason": None,
        "tick_once_ran": True,
        "job_enqueued": True,
        "worker_executed": False,
        "history_write_executed": False,
    }
    assert state["metadata"]["lifecycle_running"] is True
    assert state["metadata"]["last_cycle_present"] is True
    assert state["metadata"]["next_tick_scheduled"] is True
    assert state["metadata"]["job_enqueued"] is False
    assert summary["last_cycle_status"] == "SUCCEEDED"
    assert summary["next_tick_at"] == "2026-08-31T17:32:00Z"
    assert summary["cycle_count"] == 1
    assert summary["heartbeat_worker_id"] == "ae-retention-daemon-001"
    assert len(queue.list_jobs()) == 1
    assert validate_artifact_retention_scheduler_daemon_runtime_state(state) == state


def test_artifact_retention_scheduler_daemon_runtime_state_disabled_reason_defaults() -> None:
    queue = InMemoryJobQueue()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    blocked_runtime = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=False,
        checked_at=READY_TICK_AT,
    )

    disabled = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=blocked_runtime,
        lifecycle_status="DISABLED",
        lifecycle_reason=None,
        observed_at=READY_TICK_AT,
    )

    assert blocked_runtime["enablement"]["enablement_status"] == "BLOCKED"
    assert disabled["lifecycle_reason"] == "explicit_opt_in_required"
    assert disabled["metadata"]["lifecycle_stopped"] is False
    assert disabled["metadata"]["lifecycle_running"] is False


def test_artifact_retention_scheduler_daemon_runtime_state_error_lifecycle() -> None:
    queue = InMemoryJobQueue()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=READY_TICK_AT,
    )
    failed_cycle = {
        "daemon_one_cycle_result_id": "daemon-one-cycle-error-0542",
        "run_at": READY_TICK_AT,
        "result_status": "FAILED",
        "skip_reason": "tick_failed",
        "loop_decision_status": "READY",
        "loop_decision_reason": None,
        "tick_once_ran": True,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
    }

    state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status="ERROR",
        lifecycle_reason=None,
        observed_at=READY_TICK_AT,
        last_cycle_result=failed_cycle,
        consecutive_failure_count=2,
    )

    assert state["lifecycle_reason"] == "cycle_failed"
    assert state["metadata"]["lifecycle_error"] is True
    assert state["metadata"]["last_cycle_failed"] is True
    assert state["metadata"]["consecutive_failures_present"] is True


def test_artifact_retention_scheduler_daemon_runtime_state_validation_edges() -> None:
    queue = InMemoryJobQueue()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
        scheduler_config=scheduler_config,
        enabled=True,
        explicit_opt_in=True,
        checked_at=READY_TICK_AT,
    )
    daemon_config = build_artifact_retention_scheduler_daemon_config(
        scheduler_config=scheduler_config,
        lease_store=ArtifactRetentionSchedulerLeaseStore(),
        checked_at=READY_TICK_AT,
    )
    stopped = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        observed_at=READY_TICK_AT,
    )
    failed_cycle_summary = {
        "daemon_one_cycle_result_id": "daemon-one-cycle-failed-001",
        "run_at": READY_TICK_AT,
        "result_status": "FAILED",
        "skip_reason": "tick_failed",
        "loop_decision_status": "READY",
        "loop_decision_reason": None,
        "tick_once_ran": True,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
    }
    error_state = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status="ERROR",
        lifecycle_reason=None,
        observed_at=READY_TICK_AT,
        last_cycle_result=failed_cycle_summary,
        consecutive_failure_count=1,
    )
    disabled_state = build_artifact_retention_scheduler_daemon_runtime_state(
        observed_at=READY_TICK_AT,
        lifecycle_status="DISABLED",
        lifecycle_reason=None,
    )
    summary_with_bad_bool = {
        **failed_cycle_summary,
        "worker_executed": "yes",
    }

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "object",
        ),
        (
            {**stopped, "daemon_runtime_state_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_schema_invalid",
            "schema version",
        ),
        (
            {**stopped, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "service id",
        ),
        (
            {**stopped, "daemon_instance_id": " "},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "daemon_instance_id",
        ),
        (
            {**stopped, "observed_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "observed_at",
        ),
        (
            {**stopped, "lifecycle_status": "UNKNOWN"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "status",
        ),
        (
            {**stopped, "lifecycle_reason": "wrong"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "reason",
        ),
        (
            {**stopped, "stop_requested": "yes"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "stop_requested",
        ),
        (
            {**stopped, "last_cycle": {"bad": "payload"}},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "last cycle keys",
        ),
        (
            {**stopped, "last_cycle": summary_with_bad_bool},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "worker_executed",
        ),
        (
            {**stopped, "next_tick_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "next_tick_at",
        ),
        (
            {**stopped, "cycle_count": -1},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "cycle_count",
        ),
        (
            {**stopped, "consecutive_failure_count": "bad"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "consecutive_failure_count",
        ),
        (
            {
                **stopped,
                "runtime_config": {
                    **runtime_config,
                    "scheduler_id": "other-scheduler",
                },
            },
            "ae.artifact_retention_scheduler_daemon_loop_plan_invalid",
            "scope",
        ),
        (
            {**disabled_state, "lifecycle_reason": "initialized"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "disabled state reason",
        ),
        (
            {
                **stopped,
                "lifecycle_status": "RUNNING",
                "lifecycle_reason": "bounded_loop_running",
            },
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "state id",
        ),
        (
            {
                **stopped,
                "lifecycle_status": "STOPPING",
                "lifecycle_reason": "stop_requested",
            },
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "stop request",
        ),
        (
            {**error_state, "last_cycle": None},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "failed cycle",
        ),
        (
            {**error_state, "lifecycle_reason": "bounded_loop_running"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "error reason",
        ),
        (
            {**stopped, "daemon_runtime_state_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "state id",
        ),
        (
            {**stopped, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "guardrails",
        ),
        (
            {
                **stopped,
                "metadata": {
                    **stopped["metadata"],
                    "runtime_state_persisted": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "metadata",
        ),
        (
            {**stopped, "storage_ref": "ae://private"},
            "ae.artifact_retention_scheduler_daemon_runtime_state_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_runtime_state(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    stopping = build_artifact_retention_scheduler_daemon_runtime_state(
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        lifecycle_status="STOPPING",
        lifecycle_reason=None,
        observed_at=READY_TICK_AT,
        stop_requested=True,
        shutdown_requested_at=READY_TICK_AT,
        cycle_count=1,
    )
    assert stopping["lifecycle_reason"] == "stop_requested"
    assert stopping["metadata"]["shutdown_requested"] is True
    assert validate_artifact_retention_scheduler_daemon_runtime_state(stopping) == (
        stopping
    )


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


def test_artifact_retention_scheduler_daemon_start_stop_guardrail_blocks_and_noops() -> (
    None
):
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)

    start_guardrail = build_artifact_retention_scheduler_daemon_start_stop_guardrail(
        action="start_daemon",
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        requested_at=READY_TICK_AT,
        requested_by={"actor_type": "operator", "actor_id": "ag-retention-operator"},
        reason="operator start request",
    )
    stop_guardrail = build_artifact_retention_scheduler_daemon_start_stop_guardrail(
        action="stop_daemon",
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        requested_at=READY_TICK_AT,
        requested_by={"actor_type": "operator", "actor_id": "ag-retention-operator"},
        reason="operator stop request",
    )

    assert start_guardrail["daemon_start_stop_guardrail_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_START_STOP_GUARDRAIL_SCHEMA_VERSION
    )
    assert start_guardrail["guardrail_status"] == "BLOCKED"
    assert start_guardrail["guardrail_reason"] == "daemon_disabled_by_policy"
    assert start_guardrail["action_allowed"] is False
    assert start_guardrail["runtime_state_transition"] == "NONE"
    assert start_guardrail["execution_plan"] == {
        "requires_control_plan": True,
        "requires_lease": False,
        "runs_tick_once": False,
        "dispatches_job_queue": False,
        "starts_daemon": False,
        "stops_daemon": False,
        "sends_stop_signal": False,
        "starts_continuous_loop": False,
        "runtime_state_mutated": False,
        "writes_history": False,
        "physical_delete_enabled": False,
        "mirrors_control_action": "start_daemon",
    }
    assert start_guardrail["guardrails"][
        "future_supervisor_required_before_start"
    ] is True
    assert start_guardrail["metadata"] == {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "safe_for_ag_projection": True,
        "start_stop_guardrail_evaluated": True,
        "start_action": True,
        "stop_action": False,
        "guardrail_blocked": True,
        "guardrail_noop": False,
        "policy_reason_present": True,
        "action_allowed": False,
        "runtime_state_mutated": False,
        "stop_signal_sent": False,
        "tick_once_dispatched": False,
        "lease_acquired_before_tick": False,
        "lease_released": False,
        "job_enqueued": False,
        "worker_executed": False,
        "history_write_executed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert summarize_artifact_retention_scheduler_daemon_start_stop_guardrail(
        start_guardrail
    ) == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "action": "start_daemon",
        "guardrail_status": "BLOCKED",
        "guardrail_reason": "daemon_disabled_by_policy",
        "action_allowed": False,
        "runtime_state_transition": "NONE",
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "stop_signal_sent": False,
    }
    assert stop_guardrail["guardrail_status"] == "NOOP"
    assert stop_guardrail["guardrail_reason"] == "daemon_not_running"
    assert stop_guardrail["metadata"]["stop_action"] is True
    assert stop_guardrail["metadata"]["guardrail_noop"] is True
    assert stop_guardrail["execution_plan"]["mirrors_control_action"] == "stop_daemon"
    assert validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
        start_guardrail
    ) == start_guardrail
    assert validate_artifact_retention_scheduler_daemon_start_stop_guardrail(
        stop_guardrail
    ) == stop_guardrail
    assert queue.list_jobs() == []
    assert lease_store.get("ae-artifact-retention-scheduler-local-v1") is None
    assert "postgresql://" not in json.dumps(start_guardrail)
    assert "/data/nex-platform" not in json.dumps(start_guardrail)
    assert "dummy-secret-token" not in json.dumps(start_guardrail)


def test_artifact_retention_scheduler_daemon_start_stop_guardrail_validation_edges() -> (
    None
):
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    scheduler_config = build_artifact_retention_scheduler_config(job_queue=queue)
    start_guardrail = build_artifact_retention_scheduler_daemon_start_stop_guardrail(
        action="start_daemon",
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        requested_at=READY_TICK_AT,
    )
    stop_guardrail = build_artifact_retention_scheduler_daemon_start_stop_guardrail(
        action="stop_daemon",
        scheduler_config=scheduler_config,
        lease_store=lease_store,
        requested_at=READY_TICK_AT,
    )

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "object",
        ),
        (
            {
                **start_guardrail,
                "daemon_start_stop_guardrail_schema_version": "wrong",
            },
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_schema_invalid",
            "schema version",
        ),
        (
            {**start_guardrail, "service_id": "nex-ag"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "service id",
        ),
        (
            {**start_guardrail, "daemon_start_stop_guardrail_id": " "},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "daemon_start_stop_guardrail_id",
        ),
        (
            {**start_guardrail, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "scope",
        ),
        (
            {**start_guardrail, "action": "manual_tick_once"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_action_invalid",
            "action",
        ),
        (
            {**start_guardrail, "requested_at": "not-a-time"},
            "ae.artifact_retention_timestamp_invalid",
            "requested_at",
        ),
        (
            {**start_guardrail, "guardrail_status": "READY"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "status",
        ),
        (
            {**start_guardrail, "guardrail_status": "NOOP"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "decision",
        ),
        (
            {**start_guardrail, "guardrail_reason": "unknown"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "reason",
        ),
        (
            {**stop_guardrail, "guardrail_reason": "daemon_disabled_by_policy"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "reason",
        ),
        (
            {**start_guardrail, "action_allowed": True},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "not allowed",
        ),
        (
            {**start_guardrail, "runtime_state_transition": "STARTED"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "runtime state",
        ),
        (
            {
                **start_guardrail,
                "execution_plan": {
                    **start_guardrail["execution_plan"],
                    "starts_daemon": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "execution plan",
        ),
        (
            {**start_guardrail, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "guardrails",
        ),
        (
            {
                **start_guardrail,
                "metadata": {
                    **start_guardrail["metadata"],
                    "runtime_state_mutated": True,
                },
            },
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "metadata",
        ),
        (
            {**start_guardrail, "daemon_start_stop_guardrail_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "guardrail id",
        ),
        (
            {**start_guardrail, "raw_text": "private start stop payload"},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_start_stop_guardrail(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail

    with pytest.raises(ArtifactHandoffError) as start_decision_exc:
        scheduler_module._scheduler_daemon_start_stop_guardrail_decision(
            {
                **start_guardrail["control_plan"],
                "decision_status": "NOOP",
                "block_reason": None,
            }
        )
    assert start_decision_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
    )
    assert "start guardrail decision" in start_decision_exc.value.detail

    with pytest.raises(ArtifactHandoffError) as stop_decision_exc:
        scheduler_module._scheduler_daemon_start_stop_guardrail_decision(
            {
                **stop_guardrail["control_plan"],
                "decision_status": "BLOCKED",
                "block_reason": "daemon_disabled_by_policy",
            }
        )
    assert stop_decision_exc.value.error_code == (
        "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid"
    )
    assert "stop guardrail decision" in stop_decision_exc.value.detail


def test_artifact_retention_scheduler_daemon_dispatch_runs_manual_tick_once() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()

    result = dispatch_artifact_retention_scheduler_daemon_control(
        action="manual_tick_once",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        retention_days=30,
        as_of="2026-09-01T00:00:00Z",
        scan_limit=10,
        max_delete_count=1,
        requested_at=READY_TICK_AT,
        requested_by={"actor_type": "operator", "actor_id": "ag-retention-operator"},
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        idempotency_key="daemon-dispatch-0517",
    )
    validated = validate_artifact_retention_scheduler_daemon_dispatch_result(result)
    summary = summarize_artifact_retention_scheduler_daemon_dispatch_result(result)
    job_id = result["tick_once_result"]["enqueue_result"][
        "scheduled_job_enqueue_result"
    ]["job_id"]

    assert result["daemon_dispatch_result_schema_version"] == (
        AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
    )
    assert validated == result
    assert result["dispatch_status"] == "DISPATCHED"
    assert result["control_plan"]["decision_status"] == "READY"
    assert result["tick_once_result"]["result_status"] == "SUCCEEDED"
    assert result["start_stop_guardrail"] is None
    assert result["tick_once_result"]["guardrails"]["scheduler_daemon_started"] is False
    assert result["metadata"] == {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "control_plan_ready": True,
        "tick_once_dispatched": True,
        "start_stop_guardrail_evaluated": False,
        "lease_acquired_before_tick": True,
        "lease_released": True,
        "job_enqueued": True,
        "worker_executed": False,
        "runtime_state_mutated": False,
        "stop_signal_sent": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "physical_delete_automation_enabled": False,
    }
    assert summary == {
        "scheduler_id": "ae-artifact-retention-scheduler-local-v1",
        "action": "manual_tick_once",
        "dispatch_status": "DISPATCHED",
        "tick_once_result_status": "SUCCEEDED",
        "start_stop_guardrail_status": None,
        "start_stop_guardrail_reason": None,
        "job_enqueued": True,
        "lease_released": True,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
    }
    assert queue.get_job(job_id) is not None
    assert artifact_store.calls[0]["checked_at"] == READY_TICK_AT


def test_artifact_retention_scheduler_daemon_dispatch_blocks_without_side_effects() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    queue = InMemoryJobQueue()
    lease_store = ArtifactRetentionSchedulerLeaseStore()

    start_result = dispatch_artifact_retention_scheduler_daemon_control(
        action="start_daemon",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    status_result = dispatch_artifact_retention_scheduler_daemon_control(
        action="status_probe",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    stop_result = dispatch_artifact_retention_scheduler_daemon_control(
        action="stop_daemon",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    no_queue_result = dispatch_artifact_retention_scheduler_daemon_control(
        action="manual_tick_once",
        artifact_store=artifact_store,
        job_queue=None,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )

    assert start_result["dispatch_status"] == "BLOCKED"
    assert start_result["control_plan"]["block_reason"] == "daemon_disabled_by_policy"
    assert start_result["tick_once_result"] is None
    assert start_result["start_stop_guardrail"]["guardrail_status"] == "BLOCKED"
    assert start_result["start_stop_guardrail"]["guardrail_reason"] == (
        "daemon_disabled_by_policy"
    )
    assert start_result["metadata"]["start_stop_guardrail_evaluated"] is True
    assert start_result["metadata"]["runtime_state_mutated"] is False
    assert start_result["metadata"]["stop_signal_sent"] is False
    assert status_result["dispatch_status"] == "NOOP"
    assert status_result["tick_once_result"] is None
    assert status_result["start_stop_guardrail"] is None
    assert stop_result["dispatch_status"] == "NOOP"
    assert stop_result["control_plan"]["block_reason"] is None
    assert stop_result["tick_once_result"] is None
    assert stop_result["start_stop_guardrail"]["guardrail_status"] == "NOOP"
    assert stop_result["start_stop_guardrail"]["guardrail_reason"] == (
        "daemon_not_running"
    )
    assert stop_result["start_stop_guardrail"]["metadata"]["stop_signal_sent"] is False
    assert stop_result["start_stop_guardrail"]["metadata"][
        "scheduler_daemon_started"
    ] is False
    assert no_queue_result["dispatch_status"] == "BLOCKED"
    assert no_queue_result["control_plan"]["block_reason"] == "job_queue_unavailable"
    assert no_queue_result["tick_once_result"] is None
    assert no_queue_result["start_stop_guardrail"] is None
    assert artifact_store.calls == []


def test_artifact_retention_scheduler_daemon_dispatch_records_busy_tick_once() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()
    blocking_request = build_artifact_retention_scheduler_lease_request(
        requested_at="2026-08-31T17:29:00Z",
        lease_owner_id="active-daemon-runner",
    )
    lease_store.acquire(blocking_request)

    result = dispatch_artifact_retention_scheduler_daemon_control(
        action="manual_tick_once",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        lease_owner_id="second-daemon-runner",
    )

    assert result["dispatch_status"] == "DISPATCHED"
    assert result["control_plan"]["decision_status"] == "READY"
    assert result["tick_once_result"]["result_status"] == "SKIPPED"
    assert result["tick_once_result"]["skip_reason"] == "lease_busy"
    assert result["metadata"]["lease_acquired_before_tick"] is False
    assert result["metadata"]["lease_released"] is False
    assert result["metadata"]["job_enqueued"] is False
    assert artifact_store.calls == []


def test_artifact_retention_scheduler_daemon_dispatch_result_validation_edges() -> None:
    artifact_store = FakeArtifactRetentionStore(candidate_count=1)
    lease_store = ArtifactRetentionSchedulerLeaseStore()
    queue = InMemoryJobQueue()
    result = dispatch_artifact_retention_scheduler_daemon_control(
        action="manual_tick_once",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    blocked = dispatch_artifact_retention_scheduler_daemon_control(
        action="start_daemon",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )
    stopped = dispatch_artifact_retention_scheduler_daemon_control(
        action="stop_daemon",
        artifact_store=artifact_store,
        job_queue=queue,
        lease_store=lease_store,
        scheduler_config=build_artifact_retention_scheduler_config(job_queue=queue),
        tenant_id="tenant-001",
        workspace_id="workspace-001",
        owner_user_id="user-001",
        requested_at=READY_TICK_AT,
    )

    cases: tuple[tuple[Any, str, str], ...] = (
        (
            [],
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "object",
        ),
        (
            {
                key: value
                for key, value in result.items()
                if key != "start_stop_guardrail"
            },
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "keys",
        ),
        (
            {**result, "daemon_dispatch_result_schema_version": "wrong"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_schema_invalid",
            "schema version",
        ),
        (
            {**result, "service_id": "nex-cx"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "service id",
        ),
        (
            {**result, "daemon_dispatch_result_id": " "},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "daemon_dispatch_result_id",
        ),
        (
            {**result, "dispatch_status": "SUCCEEDED"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "dispatch status",
        ),
        (
            {**result, "scheduler_id": "other-scheduler"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "scope",
        ),
        (
            {**result, "tick_once_result": None},
            "ae.artifact_retention_scheduler_tick_once_result_invalid",
            "object",
        ),
        (
            {**result, "dispatch_status": "BLOCKED"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "Ready",
        ),
        (
            {**blocked, "tick_once_result": result["tick_once_result"]},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "Blocked",
        ),
        (
            {**blocked, "start_stop_guardrail": None},
            "ae.artifact_retention_scheduler_daemon_start_stop_guardrail_invalid",
            "object",
        ),
        (
            {**result, "start_stop_guardrail": blocked["start_stop_guardrail"]},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "Non start/stop",
        ),
        (
            {**blocked, "start_stop_guardrail": stopped["start_stop_guardrail"]},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "start/stop guardrail",
        ),
        (
            {**result, "daemon_dispatch_result_id": "wrong"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "result id",
        ),
        (
            {**result, "guardrails": {}},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "guardrails",
        ),
        (
            {**result, "metadata": {**result["metadata"], "job_enqueued": False}},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "metadata",
        ),
        (
            {**result, "raw_text": "private dispatch payload"},
            "ae.artifact_retention_scheduler_daemon_dispatch_result_invalid",
            "keys",
        ),
    )

    for payload, error_code, detail in cases:
        with pytest.raises(ArtifactHandoffError) as exc_info:
            validate_artifact_retention_scheduler_daemon_dispatch_result(payload)  # type: ignore[arg-type]
        assert exc_info.value.error_code == error_code
        assert detail in exc_info.value.detail


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
