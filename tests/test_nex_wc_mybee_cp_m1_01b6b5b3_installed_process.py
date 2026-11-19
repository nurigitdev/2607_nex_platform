from __future__ import annotations

import json
import os
import signal
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

import nex_wc.assignment_dispatch_process as process
import pytest
from nex_runtime import (
    ServiceLogEmitter,
    SqlAlchemyJobQueue,
    SqlAlchemyServiceLogStore,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
)
from nex_wc.coordination import (
    SqlAlchemyCoordinationRepository,
    WorkCoordinationService,
)
from nex_wc.work_items import SqlAlchemyWorkItemRepository, WorkItemService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

NOW_DT = datetime(2099, 2, 1, 0, 0, 1, tzinfo=UTC)
NOW = "2099-02-01T00:00:01Z"
TENANT = "tenant-b5b3"
PROJECT = "project-b5b3"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111115203"


class _Heartbeat:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def emit(self, *, status, **kwargs):
        self.events.append((status, dict(kwargs)))
        return SimpleNamespace(to_wire=lambda: {"status": status})

    def safe_emit(self, *, status, **kwargs):
        self.events.append((status, dict(kwargs)))
        return SimpleNamespace(to_wire=lambda: {"status": status})


class _ServiceLog:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def safe_emit(self, **kwargs):
        self.events.append(dict(kwargs))
        return SimpleNamespace(ok=True)


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Agents:
    def list_agents(self, **_kwargs):
        return [
            {
                "schema_version": "2.1",
                "tenant_id": TENANT,
                "agent_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "agent_type": "PA",
                "profile_ref": "agent-profile://nex-platform/project-agent/v1",
                "status": "ACTIVE",
                "project_id": PROJECT,
                "created_at": NOW,
                "version": 1,
            }
        ]

    def get_agent(self, *, tenant_id: str, agent_id: str):
        return next(
            (
                item
                for item in self.list_agents()
                if item["tenant_id"] == tenant_id and item["agent_id"] == agent_id
            ),
            None,
        )


class _Authorization:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "scopes": ["work:delegate", "work:claim"],
            "revision_hash": "sha256:" + "b" * 64,
        }


class _LoopProcess:
    def __init__(self, results=None, *, ready=True) -> None:
        self.heartbeat = _Heartbeat()
        self.service_log = _ServiceLog()
        self.poll_interval_seconds = 0.01
        self.results = list(results or [{"status": "IDLE", "failed_count": 0}])
        self.ready = ready
        self.closed = False

    def readiness(self):
        return {"readiness_status": "READY" if self.ready else "NOT_READY"}

    def queue_projection(self, *, probe):
        return {"status": "IDLE", "probe": probe, "active_job_count": 0}

    def run_once(self):
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


def _installed(*, sessions=None) -> process.InstalledWcAssignmentDispatchProcess:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessions or sessionmaker(bind=engine, expire_on_commit=False)
    return process.InstalledWcAssignmentDispatchProcess(
        profile="test",
        database_environment="NEX_WC_TEST_DATABASE_URL",
        engine=engine,
        sessions=factory,
        heartbeat=_Heartbeat(),
        service_log=_ServiceLog(),
        queue=object(),
        repository=object(),
        service=object(),
        candidate_source=object(),
        authorization_source=object(),
        worker_id="worker-5b3",
        poll_interval_seconds=1.0,
        scan_limit=100,
    )


def _execution(*, status="IDLE", job=None, error_code=None):
    return SimpleNamespace(status=status, job=job, error_code=error_code)


def _work_item_payload() -> dict[str, object]:
    return {
        "delegation_spec": {
            "schema_version": "1.0",
            "delegation_id": "delegation-b5b3",
            "tenant_id": TENANT,
            "parent_agent_execution_id": "execution-b5b3",
            "parent_executable_plan_id": "plan-b5b3",
            "parent_executable_step_id": "step-b5b3",
            "delegation_revision": 1,
            "goal": "Execute an admitted project operation",
            "work_class": "BUSINESS_TRANSACTION",
            "required_agent_type": "PA",
            "required_capability": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "project_ref": {"entity_type": "PROJECT", "entity_id": PROJECT},
            "project_scope_ref": PROJECT,
            "result_contract_ref": "urn:nex:result:business:v1",
            "completion_policy": "OWNER_SUBMITS",
            "correlation_id": "trace-b5b3",
            "causation_id": "cause-b5b3",
        },
        "requester": {"entity_type": "USER", "entity_id": "requester-b5b3"},
        "accountable_owner": {
            "entity_type": "USER",
            "entity_id": "owner-b5b3",
        },
    }


def _postgres_installed(engine, sessions, *, id_start: int):
    repository = SqlAlchemyCoordinationRepository(sessions)
    identifiers = iter(range(id_start, id_start + 100))
    agents = _Agents()
    authorization = _Authorization()
    service = WorkCoordinationService(
        repository,
        candidate_source=agents,
        authorization_source=authorization,
        id_factory=lambda: str(UUID(int=next(identifiers))),
        token_factory=lambda: "postgres-private-lease-b5b3",
        clock=lambda: NOW_DT,
        lease_seconds=process.DEFAULT_CLAIM_LEASE_SECONDS,
    )
    worker_id = f"wc-assignment-dispatch-postgres-{id_start}"
    return process.InstalledWcAssignmentDispatchProcess(
        profile="test",
        database_environment="NEX_WC_TEST_DATABASE_URL",
        engine=engine,
        sessions=sessions,
        heartbeat=WorkerHeartbeatEmitter(
            service_id="nex-wc",
            worker_id=worker_id,
            worker_type=process.WC_ASSIGNMENT_DISPATCH_WORKER_TYPE,
            store=SqlAlchemyWorkerHeartbeatStore(sessions),
        ),
        service_log=ServiceLogEmitter(
            service_id="nex-wc",
            logger_name="nex_wc.assignment_dispatch_process",
            store=SqlAlchemyServiceLogStore(sessions),
        ),
        queue=SqlAlchemyJobQueue(sessions),
        repository=repository,
        service=service,
        candidate_source=agents,
        authorization_source=authorization,
        worker_id=worker_id,
        poll_interval_seconds=0.01,
        scan_limit=100,
        claim_lease_seconds=process.DEFAULT_CLAIM_LEASE_SECONDS,
    )


def test_source_check_is_generic_content_free_and_offline() -> None:
    report = process.build_source_check()
    source = process.Path(process.__file__).read_text(encoding="utf-8")

    assert report["status"] == "PASS"
    assert report["process_id"] == "nex-wc-assignment-dispatch-worker"
    assert report["dispatch_actions"] == ["ROUTE", "CLAIM"]
    assert report["dispatch_paths"] == [
        "CREATED_TO_ROUTED",
        "ROUTED_TO_ASSIGNED",
    ]
    assert report["runtime_ready"] is False
    assert report["content_included"] is False
    assert report["secret_included"] is False
    assert "demo_runtime" not in source
    assert "NEX_P8_DEMO" not in source


def test_shutdown_token_is_first_request_wins_and_rejects_blank() -> None:
    token = process.WcAssignmentDispatchShutdownToken()
    token.request("SIGTERM")
    token.request("SIGINT")
    assert token.requested is True
    assert token.reason_code == "SIGTERM"
    with pytest.raises(process.WcAssignmentDispatchProcessError):
        process.WcAssignmentDispatchShutdownToken().request(" ")


@pytest.mark.parametrize("value", ["wrong", "", None])
def test_profile_rejects_unsupported_values(value) -> None:
    with pytest.raises(
        process.WcAssignmentDispatchProcessError,
        match="unsupported WC assignment-dispatch profile",
    ):
        process._profile(value)


def test_environment_url_and_numeric_guards_fail_closed() -> None:
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="TOKEN"):
        process._required_environment({}, "TOKEN")
    assert process._required_environment({}, "WORKER", "worker-1") == "worker-1"
    for value in ("bad", "0", "121"):
        with pytest.raises(process.WcAssignmentDispatchProcessError):
            process._bounded_float(value, "TIMEOUT", minimum=0.001, maximum=120)
    for value in (True, "bad", "0", "501"):
        with pytest.raises(process.WcAssignmentDispatchProcessError):
            process._bounded_int(value, "LIMIT", minimum=1, maximum=500)
    assert process._bounded_float("12.5", "TIMEOUT", minimum=0.001, maximum=120) == 12.5
    assert process._bounded_int("100", "LIMIT", minimum=1, maximum=500) == 100
    for value in ("wc.local", "ftp://wc.local", "http:///missing"):
        with pytest.raises(process.WcAssignmentDispatchProcessError):
            process._http_base_url({"URL": value}, "URL")
    assert (
        process._http_base_url({"URL": "https://wc.local/"}, "URL")
        == "https://wc.local"
    )


def test_builder_rejects_package_only_and_missing_dependency_contracts() -> None:
    with pytest.raises(
        process.WcAssignmentDispatchProcessError, match="package admission"
    ):
        process.build_installed_wc_assignment_dispatch_process("local_mock", environ={})
    with pytest.raises(
        process.WcAssignmentDispatchProcessError, match="NEX_WC_AE_BASE_URL"
    ):
        process.build_installed_wc_assignment_dispatch_process(
            "test", environ={"NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite://"}
        )


@pytest.mark.parametrize("profile", ["staging_live", "production"])
def test_protected_profiles_use_owner_local_database_environment(profile) -> None:
    assert process._profile(profile) == profile
    assert process.DATABASE_ENVIRONMENTS[profile] == "NEX_WC_DATABASE_URL"


def test_builder_assembles_existing_authorities_and_disposes_failures() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    env = {
        "NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_WC_AE_BASE_URL": "http://ae.local",
        "NEX_WC_TO_AE_SERVICE_TOKEN": "ae-signed-token",
        "NEX_WC_OA_BASE_URL": "http://oa.local",
        "NEX_WC_TO_OA_SERVICE_TOKEN": "oa-signed-token",
        "NEX_WC_ASSIGNMENT_DISPATCH_WORKER_ID": "worker-installed",
        "NEX_WC_ASSIGNMENT_DISPATCH_POLL_SECONDS": "0.5",
        "NEX_WC_ASSIGNMENT_DISPATCH_SCAN_LIMIT": "37",
        "NEX_WC_CLAIM_LEASE_SECONDS": "600",
    }
    installed = process.build_installed_wc_assignment_dispatch_process(
        "test",
        environ=env,
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
    )
    assert installed.worker_id == "worker-installed"
    assert installed.poll_interval_seconds == 0.5
    assert installed.scan_limit == 37
    assert installed.claim_lease_seconds == 600
    assert installed.service._lease_seconds == 600
    assert installed.queue.__class__.__name__ == "SqlAlchemyJobQueue"
    assert installed.repository.__class__.__name__ == "SqlAlchemyCoordinationRepository"
    assert installed.service.__class__.__name__ == "WorkCoordinationService"
    assert installed.service_log.__class__.__name__ == "ServiceLogEmitter"
    installed.close()

    rejected = _Engine()
    with pytest.raises(
        process.WcAssignmentDispatchProcessError, match="readiness failed"
    ):
        process.build_installed_wc_assignment_dispatch_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: rejected,
            engine_checker=lambda _engine: False,
        )
    assert rejected.disposed is True

    for value in ("29", "3601", "invalid"):
        with pytest.raises(process.WcAssignmentDispatchProcessError, match="LEASE"):
            process.build_installed_wc_assignment_dispatch_process(
                "test",
                environ={**env, "NEX_WC_CLAIM_LEASE_SECONDS": value},
                engine_factory=lambda *_args, **_kwargs: engine,
                engine_checker=lambda _engine: True,
            )


def test_builder_wraps_component_failure_and_rejects_blank_worker() -> None:
    env = {
        "NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_WC_AE_BASE_URL": "http://ae.local",
        "NEX_WC_TO_AE_SERVICE_TOKEN": "ae-token",
        "NEX_WC_OA_BASE_URL": "http://oa.local",
        "NEX_WC_TO_OA_SERVICE_TOKEN": "oa-token",
    }
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="unavailable"):
        process.build_installed_wc_assignment_dispatch_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("database secret")
            ),
        )
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="WORKER_ID"):
        process.build_installed_wc_assignment_dispatch_process(
            "test",
            environ={**env, "NEX_WC_ASSIGNMENT_DISPATCH_WORKER_ID": " "},
        )


def test_readiness_reports_exact_component_state(monkeypatch) -> None:
    installed = _installed()
    monkeypatch.setattr(
        process,
        "_database_readiness",
        lambda _sessions: {
            "connected": True,
            "migrations_current": True,
            "missing_tables": [],
        },
    )
    report = installed.readiness()
    assert report["readiness_status"] == "READY"
    assert all(report["checks"].values())
    assert report["secret_included"] is False
    assert report["claim_lease_seconds"] == 600
    installed.authorization_source = None
    assert installed.readiness()["readiness_status"] == "NOT_READY"
    installed.close()


def test_database_readiness_detects_current_and_drifted_inventory(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path
    migrations = root / "database/nex-wc/migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_wc.sql").write_text("-- fixture", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for table in process.REQUIRED_TABLES - {"schema_migrations"}:
            connection.execute(text(f"CREATE TABLE {table} (id TEXT)"))
        connection.execute(text("CREATE TABLE schema_migrations (version TEXT)"))
        connection.execute(
            text("INSERT INTO schema_migrations(version) VALUES ('0001_wc')")
        )
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(process, "ROOT", root)
    current = process._database_readiness(sessions)
    assert current["migrations_current"] is True
    assert current["missing_tables"] == []
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_migrations(version) VALUES ('unexpected')")
        )
    assert process._database_readiness(sessions)["unexpected_migrations"] == [
        "unexpected"
    ]


def test_database_readiness_redacts_database_failures() -> None:
    class BrokenSessions:
        def __call__(self):
            raise RuntimeError("postgresql://user:secret@host/db")

    with pytest.raises(
        process.WcAssignmentDispatchProcessError,
        match="database check failed",
    ) as exc:
        process._database_readiness(BrokenSessions())
    assert "secret" not in str(exc.value)


def test_queue_projection_counts_only_dispatch_work() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE service_jobs (job_type TEXT, status TEXT)")
        )
        connection.execute(text("CREATE TABLE wc_work_item (state TEXT)"))
        connection.execute(
            text(
                "INSERT INTO service_jobs VALUES "
                "('WC_ASSIGNMENT_DISPATCH','QUEUED'),('OTHER','QUEUED')"
            )
        )
        connection.execute(
            text("INSERT INTO wc_work_item VALUES ('CREATED'),('ROUTED'),('ASSIGNED')")
        )
    installed = _installed(sessions=sessionmaker(bind=engine))
    projection = installed.queue_projection(probe="RECOVERY")
    assert projection["status"] == "WORK"
    assert projection["active_job_count"] == 1
    assert projection["created_work_item_count"] == 1
    assert projection["routed_work_item_count"] == 1
    installed.close()


def test_run_once_schedules_route_then_claim_and_forwards_service_log(
    monkeypatch,
) -> None:
    installed = _installed()
    observed_states: list[str] = []
    executions = iter(
        (
            _execution(status="SUCCEEDED", job={"job_id": "route"}),
            _execution(status="SUCCEEDED", job={"job_id": "claim"}),
        )
    )

    def enqueue(**kwargs):
        observed_states.append(kwargs["state"])
        return {"scanned_count": 1, "enqueued_count": 1}

    forwarded = []

    def run_worker(**kwargs):
        forwarded.append(kwargs)
        return next(executions)

    monkeypatch.setattr(process, "enqueue_claimable_assignment_jobs", enqueue)
    monkeypatch.setattr(process, "run_assignment_dispatch_worker_once", run_worker)
    result = installed.run_once()
    assert observed_states == ["CREATED", "ROUTED"]
    assert result["status"] == "WORK"
    assert result["claimed_job_count"] == 2
    assert result["succeeded_count"] == 2
    assert result["failed_count"] == 0
    assert all(
        item["service_log_emitter"] is installed.service_log for item in forwarded
    )
    installed.close()


def test_run_once_preserves_idle_and_failure_projection(monkeypatch) -> None:
    installed = _installed()
    monkeypatch.setattr(
        process,
        "enqueue_claimable_assignment_jobs",
        lambda **_kwargs: {"scanned_count": 0, "enqueued_count": 0},
    )
    executions = iter(
        (
            _execution(),
            _execution(
                status="FAILED",
                job={"job_id": "retry"},
                error_code="wc.agent_registry_unavailable",
            ),
        )
    )
    monkeypatch.setattr(
        process,
        "run_assignment_dispatch_worker_once",
        lambda **_kwargs: next(executions),
    )
    result = installed.run_once()
    assert result["status"] == "WORK"
    assert result["failed_count"] == 1
    assert result["execution_statuses"] == ["IDLE", "FAILED"]
    installed.close()


def test_restart_recovers_route_completed_before_claim_scan(monkeypatch) -> None:
    state = {"value": "CREATED", "crash": True}
    pending: list[str] = []
    installed = _installed()

    def enqueue(**kwargs):
        if kwargs["state"] == "ROUTED" and state["crash"]:
            raise RuntimeError("simulated crash after route commit")
        count = int(state["value"] == kwargs["state"])
        if count:
            pending.append(kwargs["state"])
        return {"scanned_count": count, "enqueued_count": count}

    def worker(**_kwargs):
        if not pending:
            return _execution()
        scheduled_state = pending.pop(0)
        if scheduled_state == "CREATED":
            state["value"] = "ROUTED"
            return _execution(status="SUCCEEDED", job={"job_id": "route"})
        if scheduled_state == "ROUTED":
            state["value"] = "ASSIGNED"
            return _execution(status="SUCCEEDED", job={"job_id": "claim"})
        return _execution()

    monkeypatch.setattr(process, "enqueue_claimable_assignment_jobs", enqueue)
    monkeypatch.setattr(process, "run_assignment_dispatch_worker_once", worker)
    with pytest.raises(RuntimeError, match="simulated crash"):
        installed.run_once()
    assert state["value"] == "ROUTED"

    restarted = _installed()
    state["crash"] = False
    result = restarted.run_once()
    assert state["value"] == "ASSIGNED"
    assert result["claim_scanned_count"] == 1
    assert result["succeeded_count"] == 1
    installed.close()
    restarted.close()


def test_process_loop_emits_lifecycle_logs_and_failure_counts() -> None:
    fake = _LoopProcess(
        [
            {"status": "WORK", "failed_count": 1},
            {"status": "IDLE", "failed_count": 0},
        ]
    )
    output = StringIO()
    ticks = iter((100.0, 101.0, 102.0, 103.0, 104.0))
    result = process.run_installed_wc_assignment_dispatch_process(
        fake,
        max_cycles=2,
        sleeper=lambda _seconds: None,
        clock=lambda: next(ticks),
        out=output,
    )
    assert result["status"] == "STOPPED"
    assert result["work_cycles"] == 1
    assert result["failed_count"] == 1
    assert [item[0] for item in fake.heartbeat.events] == [
        "STARTING",
        "ERROR",
        "IDLE",
        "STOPPING",
        "STOPPED",
    ]
    assert [item["severity"] for item in fake.service_log.events] == ["INFO", "INFO"]
    assert json.loads(output.getvalue())["process_id"] == process.PROCESS_ID


def test_process_loop_validates_readiness_limits_and_wraps_failures() -> None:
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="max_cycles"):
        process.run_installed_wc_assignment_dispatch_process(
            _LoopProcess(), max_cycles=0
        )
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="not ready"):
        process.run_installed_wc_assignment_dispatch_process(
            _LoopProcess(ready=False), max_cycles=1
        )
    failed = _LoopProcess([RuntimeError("secret")])
    with pytest.raises(process.WcAssignmentDispatchProcessError, match="loop failed"):
        process.run_installed_wc_assignment_dispatch_process(failed, max_cycles=1)
    assert failed.heartbeat.events[-1][0] == "ERROR"
    assert failed.service_log.events[-1]["severity"] == "ERROR"
    owned = _LoopProcess(
        [process.WcAssignmentDispatchProcessError("owned dispatch failure")]
    )
    with pytest.raises(
        process.WcAssignmentDispatchProcessError, match="owned dispatch failure"
    ):
        process.run_installed_wc_assignment_dispatch_process(owned, max_cycles=1)


def test_process_loop_honors_shutdown_before_claim() -> None:
    fake = _LoopProcess()
    result = process.run_installed_wc_assignment_dispatch_process(
        fake,
        should_stop=lambda: True,
        clock=lambda: 100.0,
        out=StringIO(),
    )
    assert result["completed_cycles"] == 0
    assert result["stop_reason"] == "SHUTDOWN_REQUESTED"


def test_live_check_and_run_close_runtime_and_restore_signals(monkeypatch) -> None:
    assert process.build_live_check("local_mock")["runtime_ready"] is False
    fake = _LoopProcess()
    fake.readiness = lambda: {"status": "PASS", "readiness_status": "READY"}
    assert (
        process.build_live_check(
            "test", process_builder=lambda *_args, **_kwargs: fake
        )["status"]
        == "PASS"
    )
    assert fake.closed is True

    running = _LoopProcess()
    restored = []
    monkeypatch.setattr(process, "install_signal_handlers", lambda _token: {1: "old"})
    monkeypatch.setattr(
        process, "restore_signal_handlers", lambda previous: restored.append(previous)
    )
    monkeypatch.setattr(
        process,
        "run_installed_wc_assignment_dispatch_process",
        lambda *_args, **_kwargs: {"status": "STOPPED"},
    )
    assert (
        process.run_live("test", process_builder=lambda *_args, **_kwargs: running)[
            "status"
        ]
        == "STOPPED"
    )
    assert restored == [{1: "old"}]
    assert running.closed is True


def test_signal_install_and_restore(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(process.signal, "getsignal", lambda signum: f"old-{signum}")
    monkeypatch.setattr(
        process.signal,
        "signal",
        lambda signum, handler: observed.append((signum, handler)),
    )
    token = process.WcAssignmentDispatchShutdownToken()
    previous = process.install_signal_handlers(token)
    handlers = [item[1] for item in observed]
    handlers[0](signal.SIGINT, None)
    assert token.reason_code == "SIGINT"
    process.restore_signal_handlers(previous)
    assert len(observed) == 4


def test_main_check_run_package_and_blocked_paths_redact_secrets() -> None:
    output = StringIO()
    assert process.main(["--check"], environ={}, stdout=output) == 0
    assert json.loads(output.getvalue())["status"] == "PASS"

    output = StringIO()
    assert (
        process.main(
            ["--profile", "test", "--max-cycles", "1"],
            environ={},
            stdout=output,
            live_run=lambda *_args, **_kwargs: {"status": "STOPPED"},
        )
        == 0
    )
    assert json.loads(output.getvalue())["status"] == "STOPPED"

    output = StringIO()
    assert (
        process.main(
            ["--profile", "test", "--check"],
            environ={},
            stdout=output,
            live_check=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                process.WcAssignmentDispatchProcessError(
                    "postgresql://user:secret@host/db unavailable"
                )
            ),
        )
        == 2
    )
    blocked = json.loads(output.getvalue())
    assert blocked["status"] == "BLOCKED"
    assert blocked["secret_included"] is False
    assert "user:secret" not in output.getvalue()

    output = StringIO()
    assert (
        process.main(
            ["--profile", "test", "--check"],
            environ={},
            stdout=output,
            live_check=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("plain assignment configuration failure")
            ),
        )
        == 2
    )
    assert (
        json.loads(output.getvalue())["detail"]
        == "plain assignment configuration failure"
    )

    output = StringIO()
    assert (
        process.main(
            ["--profile", "staging_live", "--check"],
            environ={"NEX_RUNTIME_CHECK_MODE": "PACKAGE"},
            stdout=output,
            live_check=lambda *_args, **_kwargs: pytest.fail(
                "package admission must stay offline"
            ),
        )
        == 0
    )
    assert json.loads(output.getvalue())["package_ready"] is True


@pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)
def test_actual_postgres_restart_after_route_recovers_claim_and_liveness() -> None:
    database_url = os.environ["NEX_WC_TEST_DATABASE_URL"]
    engine = create_engine(database_url)

    def cleanup(target_engine) -> None:
        with target_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM service_jobs "
                    "WHERE job_type = 'WC_ASSIGNMENT_DISPATCH' "
                    "AND request_id = :work_item_id"
                ),
                {"work_item_id": WORK_ITEM_ID},
            )
            connection.execute(
                text(
                    "DELETE FROM service_worker_heartbeats "
                    "WHERE worker_id IN "
                    "('wc-assignment-dispatch-postgres-500', "
                    "'wc-assignment-dispatch-postgres-700')"
                )
            )
            for table in (
                "wc_event_outbox",
                "wc_claim",
                "wc_assignment",
                "wc_routing_decision",
                "wc_work_item",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": TENANT},
                )

    cleanup(engine)
    with engine.connect() as connection:
        initial_log_count = connection.execute(
            text(
                "SELECT count(*) FROM service_log_entries "
                "WHERE logger_name = 'nex_wc.assignment_dispatch_process'"
            )
        ).scalar_one()
    first = None
    restarted = None
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        WorkItemService(
            SqlAlchemyWorkItemRepository(sessions),
            authorization_source=_Authorization(),
            id_factory=lambda: WORK_ITEM_ID,
            clock=lambda: NOW_DT,
        ).create(_work_item_payload())
        first = _postgres_installed(engine, sessions, id_start=500)

        route_scan = process.enqueue_claimable_assignment_jobs(
            repository=first.repository,
            queue=first.queue,
            state="CREATED",
            limit=100,
        )
        routed = first._run_worker_once()
        assert route_scan["enqueued_count"] >= 1
        assert routed.status == "SUCCEEDED"
        route_authority = first.repository.get_work_item(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
        )
        assert route_authority["state"] == "ROUTED"
        assert (
            first.repository.get_current_assignment_authority(
                tenant_id=TENANT,
                work_item_id=WORK_ITEM_ID,
            )
            is None
        )

        first.close()
        first = None
        restarted_engine = create_engine(database_url)
        restarted_sessions = sessionmaker(bind=restarted_engine, expire_on_commit=False)
        restarted = _postgres_installed(
            restarted_engine,
            restarted_sessions,
            id_start=700,
        )
        recovered = restarted.run_once()
        authority = restarted.repository.get_current_assignment_authority(
            tenant_id=TENANT,
            work_item_id=WORK_ITEM_ID,
        )
        assert recovered["claim_scanned_count"] >= 1
        assert recovered["succeeded_count"] >= 1
        assert authority is not None
        assert authority["assignment"]["status"] == "ACTIVE"
        assert authority["claim"]["state"] == "ACTIVE"
        with restarted_engine.connect() as connection:
            claim_timing = (
                connection.execute(
                    text(
                        "SELECT created_at, lease_expires_at FROM wc_claim "
                        "WHERE tenant_id = :tenant_id AND work_item_id = :work_item_id "
                        "AND state = 'ACTIVE'"
                    ),
                    {"tenant_id": TENANT, "work_item_id": WORK_ITEM_ID},
                )
                .mappings()
                .one()
            )
            heartbeat_count = connection.execute(
                text(
                    "SELECT count(*) FROM service_worker_heartbeats "
                    "WHERE worker_id = 'wc-assignment-dispatch-postgres-700'"
                )
            ).scalar_one()
            log_count = connection.execute(
                text(
                    "SELECT count(*) FROM service_log_entries "
                    "WHERE logger_name = 'nex_wc.assignment_dispatch_process'"
                )
            ).scalar_one()
        assert claim_timing["lease_expires_at"] - claim_timing["created_at"] == timedelta(
            seconds=600
        )
        assert heartbeat_count == 1
        assert log_count > initial_log_count
    finally:
        cleanup_engine = (
            restarted.engine
            if restarted is not None
            else first.engine if first is not None else create_engine(database_url)
        )
        cleanup(cleanup_engine)
        cleanup_engine.dispose()
        if restarted is not None:
            restarted.close()
        if first is not None:
            first.close()

    verification_engine = create_engine(database_url)
    try:
        with verification_engine.connect() as connection:
            residue = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": TENANT},
            ).scalar_one()
    finally:
        verification_engine.dispose()
    assert residue == 0
