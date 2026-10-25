from __future__ import annotations

from datetime import UTC, datetime, timedelta
import signal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from nex_runtime.demo_process_runtime import (
    DemoProcessDatabaseResource,
    DemoProcessRuntimeConfig,
    DemoProcessRuntimeError,
    DemoProcessShutdownToken,
    build_demo_process_database_resource,
    demo_process_database_check,
    install_demo_process_signal_handlers,
    restore_demo_process_signal_handlers,
    run_demo_process_loop,
)


NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


class Heartbeats:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def emit(self, **kwargs):
        self.records.append(dict(kwargs))
        return kwargs

    def safe_emit(self, **kwargs):
        self.records.append(dict(kwargs))
        return SimpleNamespace(ok=True)


class Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _config(**overrides) -> DemoProcessRuntimeConfig:
    values = {
        "process_id": "nex-eos-outbox-publisher",
        "service_id": "nex-eos",
        "worker_id": "worker-1",
        "worker_type": "eos.outbox.publisher",
        "database_environment": "NEX_EOS_DATABASE_URL",
        "poll_interval_seconds": 0.1,
    }
    values.update(overrides)
    return DemoProcessRuntimeConfig(**values)


def _resource() -> tuple[DemoProcessDatabaseResource, Heartbeats]:
    heartbeats = Heartbeats()
    resource = DemoProcessDatabaseResource(
        _config(), Engine(), object(), heartbeats  # type: ignore[arg-type]
    )
    return resource, heartbeats


@pytest.mark.parametrize(
    "overrides",
    (
        {"process_id": ""},
        {"service_id": " "},
        {"worker_id": ""},
        {"worker_type": ""},
        {"database_environment": ""},
        {"poll_interval_seconds": True},
        {"poll_interval_seconds": 0},
        {"poll_interval_seconds": 301},
    ),
)
def test_runtime_config_fails_closed(overrides) -> None:
    with pytest.raises(DemoProcessRuntimeError):
        _config(**overrides)


def test_database_resource_uses_worker_pool_and_disposes() -> None:
    engine = Engine()
    observed = {}

    def build(_url, *, pool_settings):
        observed["pool"] = pool_settings
        return engine

    resource = build_demo_process_database_resource(
        _config(),
        environ={
            "NEX_EOS_DATABASE_URL": "postgresql+psycopg://user:private@localhost/db"
        },
        engine_factory=build,  # type: ignore[arg-type]
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda _engine: object(),  # type: ignore[arg-type]
    )

    assert observed["pool"].pool_size >= 1
    assert resource.config.service_id == "nex-eos"
    resource.close()
    assert engine.disposed is True


def test_database_resource_disposes_failed_engine_and_redacts_error() -> None:
    engine = Engine()

    with pytest.raises(DemoProcessRuntimeError) as raised:
        build_demo_process_database_resource(
            _config(),
            environ={"NEX_EOS_DATABASE_URL": "postgresql://user:private@localhost/db"},
            engine_factory=lambda *_args, **_kwargs: engine,  # type: ignore[arg-type]
            engine_checker=lambda _engine: False,
        )

    assert engine.disposed is True
    assert "private" not in str(raised.value)

    with pytest.raises(DemoProcessRuntimeError, match="resource is unavailable"):
        build_demo_process_database_resource(
            _config(),
            environ={"NEX_EOS_DATABASE_URL": "postgresql://user:private@localhost/db"},
            engine_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("private")
            ),
        )


def test_database_check_requires_all_declared_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE one (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE two (id INTEGER PRIMARY KEY)"))
    resource = DemoProcessDatabaseResource(
        _config(),
        engine,
        sessionmaker(bind=engine),
        Heartbeats(),  # type: ignore[arg-type]
    )

    result = demo_process_database_check(resource, required_tables=("two", "one"))
    assert result["required_tables"] == ["one", "two"]
    assert result["secret_included"] is False
    with pytest.raises(DemoProcessRuntimeError, match="tables are missing"):
        demo_process_database_check(resource, required_tables=("missing",))
    with pytest.raises(DemoProcessRuntimeError, match="table name is invalid"):
        demo_process_database_check(resource, required_tables=("bad-name",))

    broken = SimpleNamespace(
        config=_config(),
        sessions=lambda: (_ for _ in ()).throw(RuntimeError("private")),
    )
    with pytest.raises(DemoProcessRuntimeError, match="database check failed"):
        demo_process_database_check(broken, required_tables=("one",))


def test_loop_recovers_before_cycles_and_stops_with_durable_heartbeat() -> None:
    resource, heartbeats = _resource()
    order: list[str] = []
    times = iter(NOW + timedelta(seconds=index) for index in range(10))

    result = run_demo_process_loop(
        resource,
        recovery_probe=lambda: order.append("recovery") or {"status": "PASS"},
        cycle=lambda: order.append("cycle") or {"status": "WORK"},
        max_cycles=2,
        sleeper=lambda _seconds: order.append("sleep"),
        clock=lambda: next(times),
    )

    assert order == ["recovery", "cycle", "sleep", "cycle"]
    assert result["stop_reason"] == "MAX_CYCLES"
    assert result["completed_cycles"] == 2
    assert result["work_cycles"] == 2
    assert [record["status"] for record in heartbeats.records] == [
        "STARTING",
        "IDLE",
        "IDLE",
        "IDLE",
        "STOPPING",
        "STOPPED",
    ]


def test_loop_honors_shutdown_and_emits_error_on_invalid_cycle() -> None:
    resource, heartbeats = _resource()
    token = DemoProcessShutdownToken()
    token.request("SIGTERM")
    token.request("IGNORED")

    result = run_demo_process_loop(
        resource,
        recovery_probe=lambda: {"status": "PASS"},
        cycle=lambda: {"status": "IDLE"},
        shutdown_token=token,
        clock=lambda: NOW,
    )
    assert result["completed_cycles"] == 0
    assert result["stop_reason"] == "SIGTERM"

    resource, heartbeats = _resource()
    with pytest.raises(DemoProcessRuntimeError, match="cycle status"):
        run_demo_process_loop(
            resource,
            recovery_probe=lambda: {"status": "PASS"},
            cycle=lambda: {"status": "INVALID"},
            max_cycles=1,
            clock=lambda: NOW,
        )
    assert heartbeats.records[-1]["status"] == "ERROR"

    resource, heartbeats = _resource()
    with pytest.raises(DemoProcessRuntimeError, match="process loop failed"):
        run_demo_process_loop(
            resource,
            recovery_probe=lambda: {"status": "PASS"},
            cycle=lambda: (_ for _ in ()).throw(RuntimeError("private")),
            max_cycles=1,
            clock=lambda: NOW,
        )
    assert heartbeats.records[-1]["metadata"]["failure_type"] == "RuntimeError"


@pytest.mark.parametrize("max_cycles", (True, 0, 100_001))
def test_loop_rejects_invalid_cycle_bounds(max_cycles) -> None:
    with pytest.raises(DemoProcessRuntimeError, match="max_cycles"):
        run_demo_process_loop(
            _resource()[0],
            recovery_probe=lambda: {},
            cycle=lambda: {},
            max_cycles=max_cycles,
        )


def test_loop_rejects_malformed_probe_and_naive_clock() -> None:
    with pytest.raises(DemoProcessRuntimeError, match="recovery_probe"):
        run_demo_process_loop(
            _resource()[0],
            recovery_probe=lambda: None,  # type: ignore[return-value]
            cycle=lambda: {},
            max_cycles=1,
            clock=lambda: NOW,
        )
    with pytest.raises(DemoProcessRuntimeError, match="timezone-aware"):
        run_demo_process_loop(
            _resource()[0],
            recovery_probe=lambda: {},
            cycle=lambda: {},
            max_cycles=1,
            clock=lambda: datetime(2026, 10, 25),
        )


def test_shutdown_token_and_signal_handler_round_trip() -> None:
    token = DemoProcessShutdownToken()
    with pytest.raises(DemoProcessRuntimeError, match="reason_code"):
        token.request(" ")

    previous = install_demo_process_signal_handlers(token)
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert token.reason_code == "SIGTERM"
    finally:
        restore_demo_process_signal_handlers(previous)
