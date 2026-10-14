from __future__ import annotations

from itertools import count
from pathlib import Path
from typing import Any

import nex_ae_api.agent_runtime_dispatcher as dispatcher_module
import nex_ae_api.runtime_jobs as runtime_job_module
import pytest
from nex_ae_api.agent_runtime_dispatcher import (
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    AgentRuntimeDispatcherConfig,
    AgentRuntimeDispatcherError,
    SqlAlchemyAgentRuntimeAssignmentSource,
    SqlAlchemyAgentRuntimeDispatcher,
    agent_runtime_dispatcher_table_sql,
    load_agent_runtime_dispatcher_config,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2200_ae_runtime_dispatch.sql"
NOW = "2026-10-14T01:00:00Z"
_RUNTIME_ID_SEQUENCE = count(1)


@pytest.fixture
def runtime_store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, agent_execution_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT NOT NULL,
                    executable_step_id TEXT NOT NULL,
                    executor_kind TEXT NULL,
                    PRIMARY KEY (tenant_id, executable_step_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job (
                    tenant_id TEXT NOT NULL,
                    runtime_job_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    executable_step_id TEXT NULL,
                    wait_id TEXT NULL,
                    reconciliation_id TEXT NULL,
                    result_delivery_id TEXT NULL,
                    publication_reconciliation_id TEXT NULL,
                    state TEXT NOT NULL,
                    dedup_key TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    run_after TEXT NOT NULL,
                    lease_owner TEXT NULL,
                    lease_token TEXT NULL,
                    lease_until TEXT NULL,
                    payload_json TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, runtime_job_id),
                    UNIQUE (tenant_id, dedup_key)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job_attempt (
                    attempt_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    runtime_job_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_token TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NULL,
                    outcome TEXT NOT NULL,
                    error_ref TEXT NULL,
                    retry_disposition_ref TEXT NULL,
                    UNIQUE (tenant_id, runtime_job_id, attempt_no)
                )
                """
            )
        )
        for statement in agent_runtime_dispatcher_table_sql("sqlite"):
            connection.execute(text(statement))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def _queue(factory, **kwargs: Any) -> SqlAlchemyRuntimeJobQueue:
    return SqlAlchemyRuntimeJobQueue(
        factory,
        id_factory=lambda: f"id-{next(_RUNTIME_ID_SEQUENCE)}",
        **kwargs,
    )


def _add_job(
    engine,
    queue: SqlAlchemyRuntimeJobQueue,
    *,
    tenant_id: str,
    suffix: str,
    executor_kind: str | None = "LOCAL_SKILL",
    executable_step_id: str | None = None,
    insert_step: bool = True,
    run_after: str = NOW,
) -> dict[str, Any]:
    execution_id = f"execution-{tenant_id}-{suffix}"
    step_id = executable_step_id
    if step_id is None and insert_step:
        step_id = f"step-{tenant_id}-{suffix}"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO ae_agent_execution VALUES (:tenant, :execution)"),
            {"tenant": tenant_id, "execution": execution_id},
        )
        if insert_step and step_id is not None:
            connection.execute(
                text("INSERT INTO ae_executable_step VALUES (:tenant, :step, :kind)"),
                {"tenant": tenant_id, "step": step_id, "kind": executor_kind},
            )
    return queue.enqueue_unique(
        tenant_id=tenant_id,
        runtime_job_id=f"job-{tenant_id}-{suffix}",
        job_type="START_EXECUTION",
        execution_id=execution_id,
        executable_step_id=step_id,
        dedup_key=f"dedup-{tenant_id}-{suffix}",
        run_after=run_after,
        correlation_id=f"correlation-{tenant_id}-{suffix}",
        now=NOW,
        payload={"fixture_ref": f"fixture-{suffix}"},
    )


def _dispatcher(factory, *, dispatcher_id="dispatcher-a", **overrides: Any):
    config = AgentRuntimeDispatcherConfig(
        dispatcher_id=dispatcher_id,
        dispatch_batch_size=overrides.pop("dispatch_batch_size", 3),
        global_active_claim_cap=overrides.pop("global_active_claim_cap", 3),
        per_tenant_active_claim_cap=overrides.pop("per_tenant_active_claim_cap", 1),
        tenant_snapshot_limit=overrides.pop("tenant_snapshot_limit", 8),
        **overrides,
    )
    return SqlAlchemyAgentRuntimeDispatcher(
        factory,
        config=config,
        queue=_queue(factory),
        id_factory=iter(f"issue-{number}" for number in range(20)).__next__,
    )


def test_migration_contract_uses_short_tables_indexes_and_required_constraints() -> (
    None
):
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "2200_ae_runtime_dispatch" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_rt_dispatch_lease" in sql
    assert "CREATE TABLE IF NOT EXISTS ae_rt_job_issue" in sql
    assert "fencing_token BIGINT" in sql
    assert "idx_ae_rt_job_runnable" in sql
    assert "idx_ae_rt_job_expired" in sql
    assert "idx_ae_step_executor" in sql
    assert all(
        len(name) <= 30
        for name in (
            "ae_rt_dispatch_lease",
            "ae_rt_job_issue",
            "idx_ae_rt_dispatch_expiry",
            "idx_ae_rt_job_issue_state",
            "idx_ae_rt_job_runnable",
            "idx_ae_rt_job_expired",
            "idx_ae_step_executor",
        )
    )


def test_config_defaults_env_and_validation() -> None:
    config = load_agent_runtime_dispatcher_config({})
    assert config.to_record() == {
        "schema_version": "ae_agent_runtime_dispatcher.v1",
        "dispatcher_id": "ae-agent-runtime-dispatcher-1",
        "queue_name": "ae-runtime",
        "leadership_lease_seconds": 15,
        "tenant_snapshot_limit": 64,
        "dispatch_batch_size": 8,
        "global_active_claim_cap": 16,
        "per_tenant_active_claim_cap": 2,
        "max_runnable_depth": 1000,
        "admission_policy": "DELAY",
        "admission_delay_seconds": 5,
        "malformed_reconcile_batch": 16,
    }
    custom = load_agent_runtime_dispatcher_config(
        {
            "NEX_AE_AGENT_DISPATCHER_ID": "dispatcher-custom",
            "NEX_AE_AGENT_DISPATCHER_QUEUE": "queue-custom",
            "NEX_AE_AGENT_DISPATCHER_LEASE_SECONDS": "20",
            "NEX_AE_AGENT_DISPATCHER_TENANT_SNAPSHOT": "12",
            "NEX_AE_AGENT_DISPATCHER_BATCH_SIZE": "4",
            "NEX_AE_AGENT_DISPATCHER_GLOBAL_ACTIVE_CAP": "6",
            "NEX_AE_AGENT_DISPATCHER_TENANT_ACTIVE_CAP": "2",
            "NEX_AE_AGENT_DISPATCHER_MAX_RUNNABLE_DEPTH": "50",
            "NEX_AE_AGENT_DISPATCHER_ADMISSION_POLICY": "reject",
            "NEX_AE_AGENT_DISPATCHER_ADMISSION_DELAY_SECONDS": "10",
            "NEX_AE_AGENT_DISPATCHER_RECONCILE_BATCH": "5",
        }
    )
    assert custom.dispatcher_id == "dispatcher-custom"
    assert custom.admission_policy == "REJECT"
    assert custom.dispatch_batch_size == 4

    invalid_values = (
        {"dispatch_batch_size": 3, "global_active_claim_cap": 2},
        {"per_tenant_active_claim_cap": 3, "global_active_claim_cap": 2},
        {"dispatch_batch_size": 2, "tenant_snapshot_limit": 1},
        {"admission_policy": "DROP"},
        {"dispatcher_id": ""},
    )
    for values in invalid_values:
        with pytest.raises(AgentRuntimeDispatcherError):
            AgentRuntimeDispatcherConfig(**values)
    with pytest.raises(AgentRuntimeDispatcherError):
        load_agent_runtime_dispatcher_config(
            {"NEX_AE_AGENT_DISPATCHER_BATCH_SIZE": "not-an-int"}
        )


def test_db_leadership_is_exclusive_renewable_releasable_and_fenced(
    runtime_store,
) -> None:
    _engine, factory = runtime_store
    first = _dispatcher(factory, dispatcher_id="dispatcher-a")
    standby = _dispatcher(factory, dispatcher_id="dispatcher-b")

    acquired = first.acquire_leadership(observed_at=NOW)
    assert acquired is not None
    assert acquired["fencing_token"] == 1
    assert standby.acquire_leadership(observed_at="2026-10-14T01:00:01Z") is None

    renewed = first.acquire_leadership(observed_at="2026-10-14T01:00:02Z")
    assert renewed is not None
    assert renewed["fencing_token"] == 1
    takeover = standby.acquire_leadership(observed_at="2026-10-14T01:00:18Z")
    assert takeover is not None
    assert takeover["fencing_token"] == 2
    assert (
        first.release_leadership(fencing_token=1, observed_at="2026-10-14T01:00:19Z")
        is False
    )
    assert (
        standby.release_leadership(fencing_token=2, observed_at="2026-10-14T01:00:19Z")
        is True
    )
    assert standby.get_leadership()["released_at"] == "2026-10-14T01:00:19Z"

    reacquired = first.acquire_leadership(observed_at="2026-10-14T01:00:20Z")
    assert reacquired is not None
    assert reacquired["fencing_token"] == 3


def test_capability_claim_is_atomic_and_stale_dispatcher_cannot_claim(
    runtime_store,
) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    _add_job(engine, queue, tenant_id="tenant-a", suffix="local")
    _add_job(
        engine,
        queue,
        tenant_id="tenant-a",
        suffix="other",
        executor_kind="DETERMINISTIC_REPORT",
    )
    first = _dispatcher(factory, dispatcher_id="dispatcher-a")
    second = _dispatcher(factory, dispatcher_id="dispatcher-b")
    lease_one = first.acquire_leadership(observed_at=NOW)
    assert lease_one is not None
    lease_two = second.acquire_leadership(observed_at="2026-10-14T01:00:20Z")
    assert lease_two is not None

    stale = queue.claim_capability_aware(
        tenant_id="tenant-a",
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        lease_seconds=60,
        now="2026-10-14T01:00:20Z",
        queue_name="ae-runtime",
        dispatcher_id="dispatcher-a",
        fencing_token=1,
    )
    assert stale is None
    claimed = queue.claim_capability_aware(
        tenant_id="tenant-a",
        worker_id="worker-b",
        supported_executor_kinds=("LOCAL_SKILL",),
        lease_seconds=60,
        now="2026-10-14T01:00:20Z",
        queue_name="ae-runtime",
        dispatcher_id="dispatcher-b",
        fencing_token=2,
    )
    assert claimed is not None
    assert claimed.executor_kind == "LOCAL_SKILL"
    assert queue.get("tenant-a", "job-tenant-a-other")["state"] == "QUEUED"

    with pytest.raises(RuntimeJobError):
        queue.claim_capability_aware(
            tenant_id="tenant-a",
            worker_id="worker-b",
            supported_executor_kinds=(),
            lease_seconds=60,
            now=NOW,
        )
    with pytest.raises(RuntimeJobError):
        queue.claim_capability_aware(
            tenant_id="tenant-a",
            worker_id="worker-b",
            supported_executor_kinds=("LOCAL_SKILL",),
            lease_seconds=60,
            now=NOW,
            queue_name="ae-runtime",
        )


def test_dispatch_round_is_bounded_fair_and_capacity_aware(runtime_store) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    for suffix in ("a1", "a2", "a3"):
        _add_job(engine, queue, tenant_id="tenant-a", suffix=suffix)
    _add_job(engine, queue, tenant_id="tenant-b", suffix="b1")
    _add_job(engine, queue, tenant_id="tenant-c", suffix="c1")
    dispatcher = _dispatcher(factory)

    tenants = dispatcher.discover_runnable_tenants(
        supported_executor_kinds=("LOCAL_SKILL",), observed_at=NOW
    )
    assert [item["tenant_id"] for item in tenants] == [
        "tenant-a",
        "tenant-b",
        "tenant-c",
    ]
    result = dispatcher.dispatch_round(
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        lease_seconds=60,
        observed_at=NOW,
    )
    assert result["status"] == "DISPATCHED"
    assert [item.tenant_id for item in result["assignments"]] == [
        "tenant-a",
        "tenant-b",
        "tenant-c",
    ]
    assert result["metrics"] == {
        "candidate_tenant_count": 3,
        "claimed_count": 3,
        "active_claim_count": 3,
        "capacity": 3,
        "capacity_saturated": True,
    }
    assert result["high_cardinality_labels_included"] is False

    saturated = dispatcher.dispatch_round(
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        lease_seconds=60,
        observed_at="2026-10-14T01:00:01Z",
    )
    assert saturated["status"] == "SATURATED"
    assert saturated["assignments"] == ()


def test_standby_and_capability_backend_fail_closed(runtime_store) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    _add_job(engine, queue, tenant_id="tenant-a", suffix="a1")
    leader = _dispatcher(factory, dispatcher_id="leader")
    standby = _dispatcher(factory, dispatcher_id="standby")
    assert leader.acquire_leadership(observed_at=NOW) is not None

    result = standby.dispatch_round(
        worker_id="worker-standby",
        supported_executor_kinds=("LOCAL_SKILL",),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        lease_seconds=60,
        observed_at="2026-10-14T01:00:01Z",
    )
    assert result["status"] == "STANDBY"
    with pytest.raises(AgentRuntimeDispatcherError) as exc_info:
        leader.dispatch_round(
            worker_id="worker-leader",
            supported_executor_kinds=("LOCAL_SKILL",),
            supported_backend_profiles=("OTHER_BACKEND",),
            lease_seconds=60,
            observed_at="2026-10-14T01:00:01Z",
        )
    assert (
        exc_info.value.error_code
        == "ae.agent_runtime_dispatcher.capability_unavailable"
    )


def test_assignment_source_prefetches_bounded_round_and_binds_worker(
    runtime_store,
) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    _add_job(engine, queue, tenant_id="tenant-a", suffix="a1")
    _add_job(engine, queue, tenant_id="tenant-b", suffix="b1")
    source = SqlAlchemyAgentRuntimeAssignmentSource(
        _dispatcher(factory, dispatch_batch_size=2, global_active_claim_cap=2),
        prefetch_limit=2,
    )
    values = [
        source.claim_next(
            worker_id="worker-a",
            supported_executor_kinds=("LOCAL_SKILL",),
            supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
            lease_seconds=60,
            observed_at=NOW,
        ),
        source.claim_next(
            worker_id="worker-a",
            supported_executor_kinds=("LOCAL_SKILL",),
            supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
            lease_seconds=60,
            observed_at=NOW,
        ),
    ]
    assert [value.tenant_id for value in values if value is not None] == [
        "tenant-a",
        "tenant-b",
    ]
    with pytest.raises(AgentRuntimeDispatcherError):
        source.claim_next(
            worker_id="worker-b",
            supported_executor_kinds=("LOCAL_SKILL",),
            supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
            lease_seconds=60,
            observed_at=NOW,
        )


def test_backpressure_reject_delay_future_and_idempotency(runtime_store) -> None:
    engine, factory = runtime_store
    delayed_queue = _queue(
        factory,
        max_runnable_depth=1,
        admission_policy="DELAY",
        admission_delay_seconds=7,
    )
    first = _add_job(engine, delayed_queue, tenant_id="tenant-a", suffix="one")
    assert (
        delayed_queue.enqueue_unique(
            tenant_id="tenant-a",
            runtime_job_id="job-tenant-a-one",
            job_type="START_EXECUTION",
            execution_id="execution-tenant-a-one",
            executable_step_id="step-tenant-a-one",
            dedup_key="dedup-tenant-a-one",
            run_after=NOW,
            correlation_id="correlation-tenant-a-one",
            now=NOW,
            payload={"fixture_ref": "fixture-one"},
        )
        == first
    )
    with pytest.raises(RuntimeJobError) as delayed:
        _add_job(engine, delayed_queue, tenant_id="tenant-b", suffix="two")
    assert delayed.value.error_code == "ae.runtime_job_backpressure_delayed"
    assert delayed.value.retryable is True
    assert delayed.value.retry_after_seconds == 7

    future = _add_job(
        engine,
        delayed_queue,
        tenant_id="tenant-c",
        suffix="future",
        run_after="2026-10-14T02:00:00Z",
    )
    assert future["run_after"] == "2026-10-14T02:00:00Z"

    reject_queue = _queue(
        factory,
        max_runnable_depth=1,
        admission_policy="REJECT",
    )
    with pytest.raises(RuntimeJobError) as rejected:
        _add_job(engine, reject_queue, tenant_id="tenant-d", suffix="three")
    assert rejected.value.error_code == "ae.runtime_job_backpressure_rejected"


def test_malformed_jobs_follow_explicit_dead_letter_issue_path(runtime_store) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    missing_id = _add_job(
        engine,
        queue,
        tenant_id="tenant-a",
        suffix="missing-id",
        executable_step_id=None,
        insert_step=False,
    )
    _add_job(
        engine,
        queue,
        tenant_id="tenant-b",
        suffix="missing-step",
        executable_step_id="step-does-not-exist",
        insert_step=False,
    )
    _add_job(
        engine,
        queue,
        tenant_id="tenant-c",
        suffix="missing-kind",
        executor_kind=None,
    )
    _add_job(
        engine,
        queue,
        tenant_id="tenant-d",
        suffix="unknown-executor",
        executor_kind="UNREGISTERED_EXECUTOR",
    )
    known_jobs = [
        _add_job(
            engine,
            queue,
            tenant_id=f"tenant-known-{index}",
            suffix=executor_kind.lower(),
            executor_kind=executor_kind,
        )
        for index, executor_kind in enumerate(
            (
                "DETERMINISTIC_REPORT",
                "DETERMINISTIC_AGGREGATE",
                "P4_CHAT_RAG_COMPATIBILITY",
            ),
            start=1,
        )
    ]
    valid = _add_job(
        engine,
        queue,
        tenant_id="tenant-e",
        suffix="valid",
        executor_kind="LOCAL_SKILL",
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_runtime_job SET reconciliation_id = :reconciliation_id "
                "WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id"
            ),
            {
                "reconciliation_id": "agent-reconciliation-1",
                "tenant_id": missing_id["tenant_id"],
                "runtime_job_id": missing_id["runtime_job_id"],
            },
        )
    dispatcher = _dispatcher(factory, malformed_reconcile_batch=16)

    result = dispatcher.reconcile_malformed_jobs(observed_at=NOW)
    assert result == {
        "schema_version": "ae_agent_runtime_reconciliation.v1",
        "status": "COMPLETED",
        "reconciled_count": 4,
        "reason_counts": {
            "EXECUTOR_KIND_MISSING": 1,
            "EXECUTOR_UNSUPPORTED": 1,
            "STEP_ID_MISSING": 1,
            "STEP_NOT_FOUND": 1,
        },
        "content_included": False,
    }
    with engine.connect() as connection:
        states = connection.execute(
            text("SELECT state, count(*) FROM ae_runtime_job GROUP BY state")
        ).all()
        issues = (
            connection.execute(
                text("SELECT reason_code FROM ae_rt_job_issue ORDER BY reason_code")
            )
            .scalars()
            .all()
        )
    assert dict(states) == {"DEAD_LETTER": 4, "QUEUED": 4}
    assert issues == [
        "EXECUTOR_KIND_MISSING",
        "EXECUTOR_UNSUPPORTED",
        "STEP_ID_MISSING",
        "STEP_NOT_FOUND",
    ]
    assert (
        queue.get("tenant-a", missing_id["runtime_job_id"])["reconciliation_id"]
        == "agent-reconciliation-1"
    )
    issue = dispatcher.get_job_issue(
        tenant_id="tenant-a", runtime_job_id=missing_id["runtime_job_id"]
    )
    assert issue is not None
    assert issue["issue_id"] == "issue-0"
    assert issue["issue_id"] != "agent-reconciliation-1"
    assert issue["reason_code"] == "STEP_ID_MISSING"
    assert (
        dispatcher.get_job_issue(
            tenant_id="tenant-e", runtime_job_id=valid["runtime_job_id"]
        )
        is None
    )
    for known_job in known_jobs:
        assert (
            queue.get(known_job["tenant_id"], known_job["runtime_job_id"])["state"]
            == "QUEUED"
        )
    assert queue.get("tenant-e", valid["runtime_job_id"])["state"] == "QUEUED"


def test_store_failures_are_translated() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    dispatcher = SqlAlchemyAgentRuntimeDispatcher(sessionmaker(bind=engine))
    with pytest.raises(AgentRuntimeDispatcherError) as exc_info:
        dispatcher.acquire_leadership(observed_at=NOW)
    assert exc_info.value.error_code == "ae.agent_runtime_dispatcher.store_unavailable"
    with pytest.raises(AgentRuntimeDispatcherError) as issue_error:
        dispatcher.get_job_issue(tenant_id="tenant-a", runtime_job_id="job-a")
    assert issue_error.value.error_code == (
        "ae.agent_runtime_dispatcher.store_unavailable"
    )
    engine.dispose()


def test_error_helpers_and_additional_config_guards(runtime_store) -> None:
    assert str(AgentRuntimeDispatcherError("code", "detail")) == "detail"
    with pytest.raises(AgentRuntimeDispatcherError):
        AgentRuntimeDispatcherConfig(leadership_lease_seconds=True)
    with pytest.raises(AgentRuntimeDispatcherError):
        SqlAlchemyAgentRuntimeDispatcher(runtime_store[1], executor_backends={})
    with pytest.raises(AgentRuntimeDispatcherError):
        SqlAlchemyAgentRuntimeDispatcher(
            runtime_store[1], executor_backends={"UNKNOWN": "backend"}
        )
    with pytest.raises(AgentRuntimeDispatcherError):
        _dispatcher(runtime_store[1]).discover_runnable_tenants(
            supported_executor_kinds="LOCAL_SKILL",  # type: ignore[arg-type]
            observed_at=NOW,
        )
    with pytest.raises(AgentRuntimeDispatcherError):
        _dispatcher(runtime_store[1]).discover_runnable_tenants(
            supported_executor_kinds=(), observed_at=NOW
        )
    assert len(agent_runtime_dispatcher_table_sql("postgresql")) == 2


def test_dispatch_skips_tenant_at_cap_and_stops_at_round_limit(runtime_store) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    _add_job(engine, queue, tenant_id="tenant-a", suffix="active")
    active = queue.claim_capability_aware(
        tenant_id="tenant-a",
        worker_id="existing-worker",
        supported_executor_kinds=("LOCAL_SKILL",),
        lease_seconds=60,
        now=NOW,
    )
    assert active is not None
    _add_job(engine, queue, tenant_id="tenant-a", suffix="queued")
    _add_job(engine, queue, tenant_id="tenant-b", suffix="queued")
    _add_job(engine, queue, tenant_id="tenant-c", suffix="queued")
    dispatcher = _dispatcher(
        factory,
        dispatch_batch_size=1,
        global_active_claim_cap=3,
        per_tenant_active_claim_cap=1,
    )

    result = dispatcher.dispatch_round(
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        lease_seconds=60,
        observed_at="2026-10-14T01:00:01Z",
    )
    assert [assignment.tenant_id for assignment in result["assignments"]] == [
        "tenant-b"
    ]
    assert queue.get("tenant-a", "job-tenant-a-queued")["state"] == "QUEUED"
    assert queue.get("tenant-c", "job-tenant-c-queued")["state"] == "QUEUED"


def test_capability_claim_reclaims_expired_attempt_without_leadership(
    runtime_store,
) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    _add_job(engine, queue, tenant_id="tenant-a", suffix="reclaim")
    first = queue.claim_capability_aware(
        tenant_id="tenant-a",
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        lease_seconds=1,
        now=NOW,
    )
    assert first is not None
    reclaimed = queue.claim_capability_aware(
        tenant_id="tenant-a",
        worker_id="worker-b",
        supported_executor_kinds=("LOCAL_SKILL",),
        lease_seconds=30,
        now="2026-10-14T01:00:02Z",
    )
    assert reclaimed is not None
    assert reclaimed.job["attempt_no"] == 2
    assert [
        attempt["outcome"]
        for attempt in queue.list_attempts("tenant-a", "job-tenant-a-reclaim")
    ] == ["LEASE_EXPIRED", "RUNNING"]
    with pytest.raises(RuntimeJobError):
        queue.claim_capability_aware(
            tenant_id="tenant-a",
            worker_id="worker-b",
            supported_executor_kinds=("LOCAL_SKILL",),
            lease_seconds=False,
            now=NOW,
        )


def test_reconciliation_expires_malformed_running_attempt(runtime_store) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    job = _add_job(
        engine,
        queue,
        tenant_id="tenant-a",
        suffix="expired-malformed",
        executable_step_id=None,
        insert_step=False,
    )
    claim = queue.claim(
        tenant_id="tenant-a", worker_id="worker-a", lease_seconds=1, now=NOW
    )
    assert claim is not None
    dispatcher = _dispatcher(factory)
    result = dispatcher.reconcile_malformed_jobs(observed_at="2026-10-14T01:00:02Z")
    assert result["reconciled_count"] == 1
    assert queue.get("tenant-a", job["runtime_job_id"])["state"] == "DEAD_LETTER"
    assert (
        queue.list_attempts("tenant-a", job["runtime_job_id"])[0]["outcome"]
        == "LEASE_EXPIRED"
    )


def test_each_dispatcher_store_operation_translates_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    dispatcher = SqlAlchemyAgentRuntimeDispatcher(sessionmaker(bind=engine))
    operations = (
        lambda: dispatcher.release_leadership(fencing_token=1, observed_at=NOW),
        dispatcher.get_leadership,
        lambda: dispatcher.discover_runnable_tenants(
            supported_executor_kinds=("LOCAL_SKILL",), observed_at=NOW
        ),
        lambda: dispatcher.active_claim_counts(observed_at=NOW),
        lambda: dispatcher.reconcile_malformed_jobs(observed_at=NOW),
    )
    for operation in operations:
        with pytest.raises(AgentRuntimeDispatcherError) as exc_info:
            operation()
        assert exc_info.value.retryable is True
    engine.dispose()


def test_dispatcher_rejects_invalid_clock_and_preserves_domain_errors(
    runtime_store,
) -> None:
    engine, factory = runtime_store
    dispatcher = _dispatcher(factory)
    assert dispatcher.get_leadership() is None
    for observed_at in (None, "not-a-time", "2026-10-14T01:00:00"):
        with pytest.raises(AgentRuntimeDispatcherError) as exc_info:
            dispatcher.acquire_leadership(  # type: ignore[arg-type]
                observed_at=observed_at
            )
        assert exc_info.value.error_code == "ae.agent_runtime_dispatcher.invalid"

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ae_rt_dispatch_lease (
                    queue_name, owner_id, fencing_token, acquired_at,
                    renewed_at, lease_until, released_at
                ) VALUES (
                    'ae-runtime', 'dispatcher-a', 1, :now, :now,
                    'invalid-lease-time', NULL
                )
                """
            ),
            {"now": NOW},
        )
    with pytest.raises(AgentRuntimeDispatcherError) as exc_info:
        dispatcher.acquire_leadership(observed_at=NOW)
    assert exc_info.value.error_code == "ae.agent_runtime_dispatcher.invalid"


def test_dispatch_round_tolerates_candidate_lost_before_claim(runtime_store) -> None:
    engine, factory = runtime_store
    source_queue = _queue(factory)
    _add_job(engine, source_queue, tenant_id="tenant-a", suffix="claim-race")

    class LostCandidateQueue:
        def claim_capability_aware(self, **_kwargs: Any):
            return None

    dispatcher = SqlAlchemyAgentRuntimeDispatcher(
        factory,
        queue=LostCandidateQueue(),  # type: ignore[arg-type]
    )
    result = dispatcher.dispatch_round(
        worker_id="worker-a",
        supported_executor_kinds=("LOCAL_SKILL",),
        supported_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
        lease_seconds=60,
        observed_at=NOW,
    )
    assert result["status"] == "IDLE"
    assert result["metrics"]["claimed_count"] == 0


def test_capability_claim_validation_store_failure_and_reload_rollback(
    runtime_store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = runtime_store
    queue = _queue(factory)
    job = _add_job(engine, queue, tenant_id="tenant-a", suffix="reload-conflict")

    invalid_calls = (
        {"supported_executor_kinds": "LOCAL_SKILL"},
        {"supported_executor_kinds": ()},
        {"supported_executor_kinds": ("LOCAL_SKILL",), "queue_name": "ae-runtime"},
        {
            "supported_executor_kinds": ("LOCAL_SKILL",),
            "queue_name": "ae-runtime",
            "dispatcher_id": "dispatcher-a",
            "fencing_token": 0,
        },
    )
    for overrides in invalid_calls:
        params = {
            "tenant_id": "tenant-a",
            "worker_id": "worker-a",
            "supported_executor_kinds": ("LOCAL_SKILL",),
            "lease_seconds": 60,
            "now": NOW,
            **overrides,
        }
        with pytest.raises(RuntimeJobError) as exc_info:
            queue.claim_capability_aware(**params)  # type: ignore[arg-type]
        assert exc_info.value.error_code == "ae.runtime_job_invalid"

    with pytest.raises(RuntimeJobError):
        SqlAlchemyRuntimeJobQueue(factory, admission_policy="unknown")

    monkeypatch.setattr(runtime_job_module, "_load_attempt", lambda *_args: None)
    with pytest.raises(RuntimeJobError) as exc_info:
        queue.claim_capability_aware(
            tenant_id="tenant-a",
            worker_id="worker-a",
            supported_executor_kinds=("LOCAL_SKILL",),
            lease_seconds=60,
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.runtime_job_write_conflict"
    assert queue.get("tenant-a", job["runtime_job_id"])["state"] == "QUEUED"

    broken_engine = create_engine("sqlite+pysqlite:///:memory:")
    broken_queue = _queue(sessionmaker(bind=broken_engine))
    with pytest.raises(RuntimeJobError) as exc_info:
        broken_queue.claim_capability_aware(
            tenant_id="tenant-a",
            worker_id="worker-a",
            supported_executor_kinds=("LOCAL_SKILL",),
            lease_seconds=60,
            now=NOW,
        )
    assert exc_info.value.error_code == "ae.runtime_job_store_unavailable"
    broken_engine.dispose()


def test_postgres_admission_lock_uses_transaction_advisory_lock() -> None:
    statements: list[str] = []

    class PostgreSqlBind:
        class dialect:
            name = "postgresql"

    class RecordingSession:
        def get_bind(self):
            return PostgreSqlBind()

        def execute(self, statement):
            statements.append(str(statement))

    runtime_job_module._lock_runtime_admission(RecordingSession())  # type: ignore[arg-type]
    assert statements == [
        "SELECT pg_advisory_xact_lock(hashtext('ae-runtime-admission'))"
    ]


def test_private_lease_loader_adds_postgres_row_lock() -> None:
    statements: list[str] = []

    class PostgreSqlBind:
        class dialect:
            name = "postgresql"

    class EmptyMappings:
        def first(self):
            return None

    class EmptyResult:
        def mappings(self):
            return EmptyMappings()

    class RecordingSession:
        def get_bind(self):
            return PostgreSqlBind()

        def execute(self, statement, _params):
            statements.append(str(statement))
            return EmptyResult()

    assert (
        dispatcher_module._load_lease(  # type: ignore[arg-type]
            RecordingSession(), "ae-runtime", for_update=True
        )
        is None
    )
    assert statements[0].rstrip().endswith("FOR UPDATE")


def test_malformed_reconciliation_tolerates_lost_compare_and_swap() -> None:
    class SqliteBind:
        class dialect:
            name = "sqlite"

    class Result:
        def __init__(self, *, rows=(), rowcount=0):
            self._rows = list(rows)
            self.rowcount = rowcount

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class RacingSession:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get_bind(self):
            return SqliteBind()

        def execute(self, statement, _params):
            sql = str(statement)
            if "SELECT job.tenant_id" in sql:
                return Result(
                    rows=(
                        {
                            "tenant_id": "tenant-a",
                            "runtime_job_id": "job-racing",
                            "state": "QUEUED",
                            "attempt_no": 0,
                            "lease_token": None,
                            "executor_kind": None,
                            "reason_code": "STEP_ID_MISSING",
                        },
                    )
                )
            if "SET state = 'DEAD_LETTER'" in sql:
                return Result(rowcount=0)
            raise AssertionError(f"unexpected SQL: {sql}")

        def commit(self):
            self.committed = True

    session = RacingSession()
    dispatcher = SqlAlchemyAgentRuntimeDispatcher(
        lambda: session,  # type: ignore[arg-type]
        id_factory=lambda: "issue-racing",
    )
    result = dispatcher.reconcile_malformed_jobs(observed_at=NOW)
    assert result["reconciled_count"] == 0
    assert session.committed is True
