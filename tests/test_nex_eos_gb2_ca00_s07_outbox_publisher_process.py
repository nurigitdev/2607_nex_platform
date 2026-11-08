from __future__ import annotations

import json
import signal
from io import StringIO
from types import SimpleNamespace

import nex_eos.outbox_publisher_process as process
import pytest
from nex_eos.outbox_publication import EosOutboxPublicationError
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


class _Publisher:
    def __init__(self, results=None) -> None:
        self.results = list(results or [None])

    def publish_next(self, _transport):
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _LoopProcess:
    def __init__(self, results=None, *, ready=True) -> None:
        self.heartbeat = _Heartbeat()
        self.poll_interval_seconds = 0.01
        self.results = list(
            results
            or [
                {
                    "status": "IDLE",
                    "published_count": 0,
                    "failed_count": 0,
                }
            ]
        )
        self.ready = ready
        self.closed = False

    def readiness(self):
        return {"readiness_status": "READY" if self.ready else "NOT_READY"}

    def queue_projection(self, *, probe):
        return {"status": "IDLE", "probe": probe, "pending_outbox_count": 0}

    def run_once(self):
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


def _installed(*, sessions=None, publisher=None):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessions or sessionmaker(bind=engine, expire_on_commit=False)
    return process.InstalledEosOutboxPublisherProcess(
        profile="test",
        database_environment="NEX_EOS_TEST_DATABASE_URL",
        engine=engine,
        sessions=factory,
        heartbeat=_Heartbeat(),
        publisher=publisher or _Publisher(),
        transport=object(),
        worker_id="worker-1",
        poll_interval_seconds=1.0,
    )


def _result(
    *,
    state="PUBLISHED",
    retry=False,
    attempt=1,
    error_code=None,
):
    return SimpleNamespace(
        delivery_state=state,
        retry_required=retry,
        attempt_count=attempt,
        error_code=error_code,
    )


def test_source_check_is_canonical_and_demo_independent() -> None:
    report = process.build_source_check()
    source = process.Path(process.__file__).read_text(encoding="utf-8")

    assert report["status"] == "PASS"
    assert report["process_id"] == "nex-eos-outbox-publisher"
    assert report["work_capability"] == "outbox_publishing"
    assert report["publisher_type"] == "SqlAlchemyEosOutboxPublisher"
    assert "nex_eos.demo_runtime" not in source
    assert "demo_process_runtime" not in source


def test_shutdown_token_is_first_request_wins_and_rejects_blank() -> None:
    token = process.EosOutboxPublisherShutdownToken()
    token.request("SIGTERM")
    token.request("SIGINT")
    assert token.requested is True
    assert token.reason_code == "SIGTERM"
    with pytest.raises(process.EosOutboxPublisherProcessError):
        process.EosOutboxPublisherShutdownToken().request(" ")


@pytest.mark.parametrize("value", ["wrong", "", None])
def test_profile_rejects_unsupported_values(value) -> None:
    with pytest.raises(
        process.EosOutboxPublisherProcessError,
        match="unsupported EOS outbox publisher profile",
    ):
        process._profile(value)


def test_environment_and_numeric_guards_fail_closed() -> None:
    with pytest.raises(process.EosOutboxPublisherProcessError, match="TOKEN"):
        process._required_environment({}, "TOKEN")
    assert process._required_environment({}, "WORKER", "worker-1") == "worker-1"
    for value in ("bad", "0", "121"):
        with pytest.raises(process.EosOutboxPublisherProcessError):
            process._bounded_float(value, "TIMEOUT", minimum=0.001, maximum=120)
    assert process._bounded_float("12.5", "TIMEOUT", minimum=0.001, maximum=120) == 12.5


@pytest.mark.parametrize("value", ["ae.local", "ftp://ae.local", "http:///missing"])
def test_ae_base_url_requires_http_endpoint(value) -> None:
    with pytest.raises(process.EosOutboxPublisherProcessError):
        process._ae_base_url({"NEX_AE_API_BASE_URL": value})
    assert (
        process._ae_base_url({"NEX_AE_API_BASE_URL": "https://ae.local/"})
        == "https://ae.local"
    )


def test_builder_rejects_package_only_and_missing_transport() -> None:
    with pytest.raises(
        process.EosOutboxPublisherProcessError, match="package admission"
    ):
        process.build_installed_eos_outbox_publisher_process("local_mock", environ={})
    with pytest.raises(
        process.EosOutboxPublisherProcessError, match="NEX_AE_API_BASE_URL"
    ):
        process.build_installed_eos_outbox_publisher_process(
            "test", environ={"NEX_EOS_TEST_DATABASE_URL": "sqlite+pysqlite://"}
        )


@pytest.mark.parametrize("profile", ["staging_live", "production"])
def test_protected_profiles_use_owner_local_database_environment(profile) -> None:
    assert process._profile(profile) == profile
    assert process.DATABASE_ENVIRONMENTS[profile] == "NEX_EOS_DATABASE_URL"


def test_builder_assembles_existing_components_and_disposes_on_check_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    env = {
        "NEX_EOS_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_AE_API_BASE_URL": "http://ae.local",
        "NEX_EOS_TO_AE_SERVICE_TOKEN": "signed-token",
        "NEX_EOS_OUTBOX_PUBLISHER_WORKER_ID": "worker-s07",
        "NEX_EOS_OUTBOX_PUBLISH_POLL_SECONDS": "0.5",
    }
    installed = process.build_installed_eos_outbox_publisher_process(
        "test",
        environ=env,
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
    )
    assert installed.worker_id == "worker-s07"
    assert installed.poll_interval_seconds == 0.5
    assert installed.publisher.__class__.__name__ == "SqlAlchemyEosOutboxPublisher"
    assert installed.transport.__class__.__name__ == "HttpAeEosOutboxTransport"
    installed.close()

    rejected = _Engine()
    with pytest.raises(
        process.EosOutboxPublisherProcessError, match="readiness failed"
    ):
        process.build_installed_eos_outbox_publisher_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: rejected,
            engine_checker=lambda _engine: False,
        )
    assert rejected.disposed is True


def test_builder_wraps_component_failure_and_rejects_blank_worker() -> None:
    env = {
        "NEX_EOS_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_AE_API_BASE_URL": "http://ae.local",
        "NEX_EOS_TO_AE_SERVICE_TOKEN": "signed-token",
    }
    with pytest.raises(process.EosOutboxPublisherProcessError, match="unavailable"):
        process.build_installed_eos_outbox_publisher_process(
            "test",
            environ=env,
            engine_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("database secret")
            ),
        )
    with pytest.raises(process.EosOutboxPublisherProcessError, match="WORKER_ID"):
        process.build_installed_eos_outbox_publisher_process(
            "test",
            environ={**env, "NEX_EOS_OUTBOX_PUBLISHER_WORKER_ID": " "},
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
    installed.publisher = None
    assert installed.readiness()["readiness_status"] == "NOT_READY"
    installed.close()


def test_database_readiness_detects_current_and_drifted_inventory(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path
    migrations = root / "database/nex-eos/migrations"
    migrations.mkdir(parents=True)
    (migrations / "2500_eos.sql").write_text("-- fixture", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for table in process.REQUIRED_TABLES - {"schema_migrations"}:
            connection.execute(text(f"CREATE TABLE {table} (id TEXT)"))
        connection.execute(text("CREATE TABLE schema_migrations (version TEXT)"))
        connection.execute(
            text("INSERT INTO schema_migrations(version) VALUES ('2500_eos')")
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
        process.EosOutboxPublisherProcessError,
        match="database check failed",
    ) as exc:
        process._database_readiness(BrokenSessions())
    assert "secret" not in str(exc.value)


def test_run_once_reports_idle_success_and_retry() -> None:
    installed = _installed(
        publisher=_Publisher(
            [
                None,
                _result(),
                _result(
                    state="PENDING",
                    retry=True,
                    attempt=2,
                    error_code="EOS_OUTBOX_ACK_UNCONFIRMED",
                ),
            ]
        )
    )
    assert installed.run_once()["status"] == "IDLE"
    published = installed.run_once()
    assert published["published_count"] == 1
    assert published["failed_count"] == 0
    retry = installed.run_once()
    assert retry["published_count"] == 0
    assert retry["failed_count"] == 1
    assert retry["attempt_count"] == 2
    installed.close()


def test_run_once_wraps_publication_error() -> None:
    installed = _installed(
        publisher=_Publisher(
            [EosOutboxPublicationError("EOS_OUTBOX_INVALID", "bad", retryable=False)]
        )
    )
    with pytest.raises(process.EosOutboxPublisherProcessError, match="publication"):
        installed.run_once()
    installed.close()


def test_queue_projection_counts_publication_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE eos_outbox (delivery_state TEXT)"))
        connection.execute(
            text(
                "INSERT INTO eos_outbox VALUES ('PENDING'),('PUBLISHED'),('PUBLISHED')"
            )
        )
    installed = _installed(sessions=sessionmaker(bind=engine))
    projection = installed.queue_projection(probe="RECOVERY")
    assert projection["pending_outbox_count"] == 1
    assert projection["published_outbox_count"] == 2
    installed.close()


def test_process_loop_emits_lifecycle_and_failure_counts() -> None:
    fake = _LoopProcess(
        [
            {"status": "WORK", "published_count": 0, "failed_count": 1},
            {"status": "WORK", "published_count": 1, "failed_count": 0},
        ]
    )
    output = StringIO()
    ticks = iter((100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
    result = process.run_installed_eos_outbox_publisher_process(
        fake,
        max_cycles=2,
        sleeper=lambda _seconds: None,
        clock=lambda: next(ticks),
        out=output,
    )
    assert result["status"] == "STOPPED"
    assert result["work_cycles"] == 2
    assert result["published_count"] == 1
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
    with pytest.raises(process.EosOutboxPublisherProcessError, match="max_cycles"):
        process.run_installed_eos_outbox_publisher_process(_LoopProcess(), max_cycles=0)
    with pytest.raises(process.EosOutboxPublisherProcessError, match="not ready"):
        process.run_installed_eos_outbox_publisher_process(
            _LoopProcess(ready=False), max_cycles=1
        )
    failed = _LoopProcess([RuntimeError("secret")])
    with pytest.raises(process.EosOutboxPublisherProcessError, match="loop failed"):
        process.run_installed_eos_outbox_publisher_process(failed, max_cycles=1)
    assert failed.heartbeat.events[-1][0] == "ERROR"
    owned = _LoopProcess(
        [process.EosOutboxPublisherProcessError("owned publication failure")]
    )
    with pytest.raises(
        process.EosOutboxPublisherProcessError, match="owned publication failure"
    ):
        process.run_installed_eos_outbox_publisher_process(owned, max_cycles=1)


def test_process_loop_honors_shutdown_before_claim() -> None:
    fake = _LoopProcess()
    result = process.run_installed_eos_outbox_publisher_process(
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
        "run_installed_eos_outbox_publisher_process",
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
    token = process.EosOutboxPublisherShutdownToken()
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
                process.EosOutboxPublisherProcessError(
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
