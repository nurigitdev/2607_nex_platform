from __future__ import annotations

import json
import signal
from io import StringIO
from types import SimpleNamespace

import nex_wc.event_delivery_process as process
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class _Heartbeat:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def emit(self, *, status, **kwargs):
        self.events.append((status, dict(kwargs)))
        return SimpleNamespace(to_wire=lambda: {"status": status})

    def safe_emit(self, *, status, **kwargs):
        self.events.append((status, dict(kwargs)))
        return SimpleNamespace(to_wire=lambda: {"status": status})


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _LoopProcess:
    def __init__(self, results=None, *, ready=True) -> None:
        self.heartbeat = _Heartbeat()
        self.poll_interval_seconds = 0.01
        self.results = list(
            results
            or [
                {
                    "status": "IDLE",
                    "failed_count": 0,
                }
            ]
        )
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


def _installed(*, sessions=None) -> process.InstalledWcEventDeliveryProcess:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessions or sessionmaker(bind=engine, expire_on_commit=False)
    return process.InstalledWcEventDeliveryProcess(
        profile="test",
        database_environment="NEX_WC_TEST_DATABASE_URL",
        engine=engine,
        sessions=factory,
        heartbeat=_Heartbeat(),
        queue=object(),
        coordination=object(),
        work_results=object(),
        approval_store=object(),
        handoff_client=object(),
        result_client=object(),
        approval_client=object(),
        worker_id="worker-1",
        poll_interval_seconds=1.0,
    )


def test_source_check_is_canonical_and_demo_independent() -> None:
    report = process.build_source_check()
    source = process.Path(process.__file__).read_text(encoding="utf-8")

    assert report["status"] == "PASS"
    assert report["process_id"] == "nex-wc-event-delivery-worker"
    assert report["work_capability"] == "event_delivering"
    assert report["delivery_paths"] == [
        "CLAIM_HANDOFF",
        "WORK_RESULT",
        "APPROVAL_EVENT",
    ]
    assert "nex_wc.demo_runtime" not in source
    assert "demo_process_runtime" not in source


def test_shutdown_token_is_first_request_wins_and_rejects_blank() -> None:
    token = process.WcEventDeliveryShutdownToken()
    token.request("SIGTERM")
    token.request("SIGINT")
    assert token.requested is True
    assert token.reason_code == "SIGTERM"
    with pytest.raises(process.WcEventDeliveryProcessError):
        process.WcEventDeliveryShutdownToken().request(" ")


@pytest.mark.parametrize("value", ["wrong", "", None])
def test_profile_rejects_unsupported_values(value) -> None:
    with pytest.raises(
        process.WcEventDeliveryProcessError,
        match="unsupported WC event-delivery profile",
    ):
        process._profile(value)


def test_environment_and_numeric_guards_fail_closed() -> None:
    with pytest.raises(process.WcEventDeliveryProcessError, match="TOKEN"):
        process._required_environment({}, "TOKEN")
    assert process._required_environment({}, "WORKER", "worker-1") == "worker-1"
    for value in ("bad", "0", "121"):
        with pytest.raises(process.WcEventDeliveryProcessError):
            process._bounded_float(value, "TIMEOUT", minimum=0.001, maximum=120)
    assert process._bounded_float("12.5", "TIMEOUT", minimum=0.001, maximum=120) == 12.5


@pytest.mark.parametrize("value", ["wc.local", "ftp://wc.local", "http:///missing"])
def test_ae_base_url_requires_http_endpoint(value) -> None:
    with pytest.raises(process.WcEventDeliveryProcessError):
        process._ae_base_url({"NEX_WC_AE_BASE_URL": value})
    assert (
        process._ae_base_url({"NEX_WC_AE_BASE_URL": "https://ae.local/"})
        == "https://ae.local"
    )


def test_builder_rejects_package_only_and_missing_transport() -> None:
    with pytest.raises(process.WcEventDeliveryProcessError, match="package admission"):
        process.build_installed_wc_event_delivery_process("local_mock", environ={})
    with pytest.raises(process.WcEventDeliveryProcessError, match="NEX_WC_AE_BASE_URL"):
        process.build_installed_wc_event_delivery_process(
            "test", environ={"NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite://"}
        )


@pytest.mark.parametrize("profile", ["staging_live", "production"])
def test_protected_profiles_use_owner_local_database_environment(profile) -> None:
    assert process._profile(profile) == profile
    assert process.DATABASE_ENVIRONMENTS[profile] == "NEX_WC_DATABASE_URL"


def test_builder_assembles_existing_components_and_disposes_on_check_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    env = {
        "NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_WC_AE_BASE_URL": "http://ae.local",
        "NEX_WC_TO_AE_SERVICE_TOKEN": "signed-token",
        "NEX_WC_EVENT_DELIVERY_WORKER_ID": "worker-s06",
        "NEX_WC_EVENT_DELIVERY_POLL_SECONDS": "0.5",
    }
    installed = process.build_installed_wc_event_delivery_process(
        "test",
        environ=env,
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
    )
    assert installed.worker_id == "worker-s06"
    assert installed.poll_interval_seconds == 0.5
    assert installed.queue.__class__.__name__ == "SqlAlchemyJobQueue"
    installed.close()

    rejected = _Engine()
    with pytest.raises(process.WcEventDeliveryProcessError, match="readiness failed"):
        process.build_installed_wc_event_delivery_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: rejected,
            engine_checker=lambda _engine: False,
        )
    assert rejected.disposed is True


def test_builder_wraps_component_failure_and_rejects_blank_worker() -> None:
    env = {
        "NEX_WC_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_WC_AE_BASE_URL": "http://ae.local",
        "NEX_WC_TO_AE_SERVICE_TOKEN": "signed-token",
    }
    with pytest.raises(process.WcEventDeliveryProcessError, match="unavailable"):
        process.build_installed_wc_event_delivery_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("database secret")
            ),
        )
    with pytest.raises(process.WcEventDeliveryProcessError, match="WORKER_ID"):
        process.build_installed_wc_event_delivery_process(
            "test",
            environ={**env, "NEX_WC_EVENT_DELIVERY_WORKER_ID": " "},
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
    installed.queue = None
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
        process.WcEventDeliveryProcessError,
        match="database check failed",
    ) as exc:
        process._database_readiness(BrokenSessions())
    assert "secret" not in str(exc.value)


def test_run_once_reuses_all_delivery_paths(monkeypatch) -> None:
    installed = _installed()
    monkeypatch.setattr(
        process,
        "enqueue_pending_handoffs",
        lambda **_kwargs: [{"job_id": "handoff"}],
    )
    monkeypatch.setattr(
        process,
        "enqueue_pending_result_events",
        lambda **_kwargs: [{"job_id": "result"}],
    )
    monkeypatch.setattr(
        process,
        "run_worker_once",
        lambda **_kwargs: SimpleNamespace(
            job={"job_id": "handoff"}, status="SUCCEEDED", error_code=None
        ),
    )
    monkeypatch.setattr(
        process,
        "deliver_pending_approval_events",
        lambda **_kwargs: {"pending_count": 1, "delivered_count": 1},
    )
    result = installed.run_once()
    assert result == {
        "status": "WORK",
        "enqueued_count": 2,
        "claimed_count": 1,
        "delivered_count": 1,
        "failed_count": 0,
        "delivery_status": "SUCCEEDED",
        "delivery_error_code": None,
        "approval_delivered_count": 1,
        "content_included": False,
        "secret_included": False,
    }
    installed.close()


def test_run_once_preserves_retry_and_wraps_approval_failure(monkeypatch) -> None:
    installed = _installed()
    monkeypatch.setattr(process, "enqueue_pending_handoffs", lambda **_kwargs: [])
    monkeypatch.setattr(process, "enqueue_pending_result_events", lambda **_kwargs: [])
    monkeypatch.setattr(
        process,
        "run_worker_once",
        lambda **_kwargs: SimpleNamespace(
            job={"job_id": "retry"},
            status="FAILED",
            error_code="nex.signed_token_invalid",
        ),
    )
    monkeypatch.setattr(
        process,
        "deliver_pending_approval_events",
        lambda **_kwargs: {"pending_count": 0, "delivered_count": 0},
    )
    retry = installed.run_once()
    assert retry["failed_count"] == 1
    assert retry["delivery_error_code"] == "nex.signed_token_invalid"
    monkeypatch.setattr(
        process,
        "deliver_pending_approval_events",
        lambda **_kwargs: (_ for _ in ()).throw(
            process.ApprovalEventDeliveryError("offline")
        ),
    )
    with pytest.raises(process.WcEventDeliveryProcessError, match="approval"):
        installed.run_once()
    installed.close()


def test_delivery_job_routes_by_persisted_event_type(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE wc_event_outbox "
                "(outbox_id TEXT, event_id TEXT, event_type TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_event_outbox VALUES "
                "('handoff','e1','CLAIM_EXECUTION_HANDOFF'), "
                "('result','e2','WORK_RESULT_SUBMITTED'), "
                "('bad','e3','UNKNOWN')"
            )
        )
    installed = _installed(sessions=sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(
        process,
        "run_handoff_delivery_job",
        lambda *_args, **_kwargs: {"path": "handoff"},
    )
    monkeypatch.setattr(
        process,
        "run_work_result_delivery_job",
        lambda *_args, **_kwargs: {"path": "result"},
    )
    assert installed._deliver_job(
        {"payload": {"outbox_id": "handoff", "event_id": "e1"}}
    ) == {"path": "handoff"}
    assert installed._deliver_job(
        {"payload": {"outbox_id": "result", "event_id": "e2"}}
    ) == {"path": "result"}
    with pytest.raises(process.WcEventDeliveryProcessError, match="unsupported"):
        installed._deliver_job({"payload": {"outbox_id": "bad", "event_id": "e3"}})
    with pytest.raises(process.WcEventDeliveryProcessError, match="payload"):
        installed._deliver_job({"payload": "bad"})
    installed.close()


def test_queue_projection_counts_only_delivery_work() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE service_jobs (job_type TEXT, status TEXT)")
        )
        connection.execute(text("CREATE TABLE wc_event_outbox (delivery_state TEXT)"))
        connection.execute(
            text("CREATE TABLE wc_approval_outbox (delivery_state TEXT)")
        )
        connection.execute(
            text(
                "INSERT INTO service_jobs VALUES "
                "('WC_EVENT_DELIVERY','QUEUED'),('OTHER','QUEUED')"
            )
        )
        connection.execute(text("INSERT INTO wc_event_outbox VALUES ('ENQUEUED')"))
        connection.execute(text("INSERT INTO wc_approval_outbox VALUES ('PENDING')"))
    installed = _installed(sessions=sessionmaker(bind=engine))
    projection = installed.queue_projection(probe="RECOVERY")
    assert projection["active_job_count"] == 1
    assert projection["coordination_event_count"] == 1
    assert projection["approval_event_count"] == 1
    installed.close()


def test_process_loop_emits_lifecycle_and_failure_counts() -> None:
    fake = _LoopProcess(
        [
            {"status": "WORK", "failed_count": 1},
            {"status": "IDLE", "failed_count": 0},
        ]
    )
    output = StringIO()
    ticks = iter((100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
    result = process.run_installed_wc_event_delivery_process(
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
    assert json.loads(output.getvalue())["process_id"] == process.PROCESS_ID


def test_process_loop_validates_limits_readiness_and_wraps_failures() -> None:
    with pytest.raises(process.WcEventDeliveryProcessError, match="max_cycles"):
        process.run_installed_wc_event_delivery_process(_LoopProcess(), max_cycles=0)
    with pytest.raises(process.WcEventDeliveryProcessError, match="not ready"):
        process.run_installed_wc_event_delivery_process(
            _LoopProcess(ready=False), max_cycles=1
        )
    failed = _LoopProcess([RuntimeError("secret")])
    with pytest.raises(process.WcEventDeliveryProcessError, match="loop failed"):
        process.run_installed_wc_event_delivery_process(failed, max_cycles=1)
    assert failed.heartbeat.events[-1][0] == "ERROR"
    owned = _LoopProcess(
        [process.WcEventDeliveryProcessError("owned delivery failure")]
    )
    with pytest.raises(
        process.WcEventDeliveryProcessError, match="owned delivery failure"
    ):
        process.run_installed_wc_event_delivery_process(owned, max_cycles=1)


def test_process_loop_honors_shutdown_before_claim() -> None:
    fake = _LoopProcess()
    result = process.run_installed_wc_event_delivery_process(
        fake,
        should_stop=lambda: True,
        clock=lambda: 100.0,
        out=StringIO(),
    )
    assert result["completed_cycles"] == 0
    assert result["stop_reason"] == "SHUTDOWN_REQUESTED"


def test_live_check_closes_runtime_and_local_check_stays_offline() -> None:
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


def test_run_live_restores_signal_handlers_and_closes(monkeypatch) -> None:
    fake = _LoopProcess()
    restored = []
    monkeypatch.setattr(process, "install_signal_handlers", lambda _token: {1: "old"})
    monkeypatch.setattr(
        process, "restore_signal_handlers", lambda previous: restored.append(previous)
    )
    monkeypatch.setattr(
        process,
        "run_installed_wc_event_delivery_process",
        lambda *_args, **_kwargs: {"status": "STOPPED"},
    )
    result = process.run_live("test", process_builder=lambda *_args, **_kwargs: fake)
    assert result["status"] == "STOPPED"
    assert restored == [{1: "old"}]
    assert fake.closed is True


def test_signal_install_and_restore(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(process.signal, "getsignal", lambda signum: f"old-{signum}")
    monkeypatch.setattr(
        process.signal,
        "signal",
        lambda signum, handler: observed.append((signum, handler)),
    )
    token = process.WcEventDeliveryShutdownToken()
    previous = process.install_signal_handlers(token)
    handlers = [item[1] for item in observed]
    handlers[0](signal.SIGINT, None)
    assert token.reason_code == "SIGINT"
    process.restore_signal_handlers(previous)
    assert len(observed) == 4


def test_main_check_run_and_blocked_paths_do_not_expose_secrets() -> None:
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
                process.WcEventDeliveryProcessError(
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
                ValueError("plain configuration failure")
            ),
        )
        == 2
    )
    assert json.loads(output.getvalue())["detail"] == "plain configuration failure"


def test_main_package_check_keeps_staging_command_offline() -> None:
    output = StringIO()
    assert (
        process.main(
            ["--profile", "staging_live", "--check"],
            environ={"NEX_RUNTIME_CHECK_MODE": "PACKAGE"},
            stdout=output,
            live_check=lambda *_args, **_kwargs: pytest.fail(
                "package admission must not contact the database"
            ),
        )
        == 0
    )
    record = json.loads(output.getvalue())
    assert record["package_ready"] is True
    assert record["runtime_ready"] is False
    assert record["database"] == {"status": "NOT_REQUESTED"}
