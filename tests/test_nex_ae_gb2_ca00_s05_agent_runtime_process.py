from __future__ import annotations

import inspect
import json
from io import StringIO
from types import SimpleNamespace

import nex_ae_api.agent_runtime_process as process
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _sqlite_engine(*, current: bool = True, complete: bool = True):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = process.REQUIRED_TABLES if complete else {"schema_migrations"}
    with engine.begin() as connection:
        for table in sorted(tables - {"schema_migrations"}):
            connection.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
        connection.execute(
            text("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        )
        if current:
            for path in sorted(
                (process.ROOT / "database/nex-ae-api/migrations").glob("*.sql")
            ):
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": path.stem},
                )
    return engine


def _fake_process(*results: dict[str, object]):
    executions = iter(results)
    return SimpleNamespace(
        readiness=lambda: {
            "status": "PASS",
            "readiness_status": "READY",
        },
        run_once=lambda: next(executions),
        composition=SimpleNamespace(
            worker_config=SimpleNamespace(poll_interval_seconds=0.01)
        ),
    )


def test_source_check_uses_generic_product_factory_and_bounded_profile() -> None:
    result = process.build_source_check()
    source = inspect.getsource(process)

    assert result == {
        "schema_version": "ae_agent_runtime_process.v1",
        "status": "PASS",
        "process_id": "nex-ae-agent-runtime-worker",
        "service_id": "nex-ae-api",
        "module": "nex_ae_api.agent_runtime_process",
        "composition_factory": "build_installed_runtime_composition",
        "executor_kinds": [
            "DETERMINISTIC_AGGREGATE",
            "DETERMINISTIC_REPORT",
        ],
        "backend_profiles": ["NSL_V01_PROCESS_ISOLATED"],
        "database_environments": {
            "test": "NEX_AE_TEST_DATABASE_URL",
            "staging_live": "NEX_AE_DATABASE_URL",
            "production": "NEX_AE_DATABASE_URL",
        },
        "work_capability": "job_claiming",
        "runtime_ready": False,
        "content_included": False,
        "secret_included": False,
    }
    assert "build_installed_runtime_composition(" in source
    assert "nex_ae_api.demo_runtime" not in source
    assert "p8_demo" not in source


def test_installed_process_readiness_proves_db_dispatcher_worker_and_profile() -> None:
    engine = _sqlite_engine()
    installed = process.build_installed_agent_runtime_process(
        "test",
        environ={
            "NEX_AE_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "NEX_AE_AGENT_WORKER_ID": "ae-current-worker-1",
        },
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda value: sessionmaker(
            bind=value, autoflush=False, expire_on_commit=False
        ),
    )
    try:
        result = installed.readiness()
    finally:
        installed.close()

    assert result["status"] == "PASS"
    assert result["readiness_status"] == "READY"
    assert all(result["checks"].values())
    assert result["worker"]["in_process_package_status"] == "NOT_CONFIGURED"
    assert result["executor_kinds"] == [
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
    ]
    assert result["work_capability"] == "job_claiming"
    assert result["secret_included"] is False


def test_installed_process_delegates_cycle_and_disposes_engine() -> None:
    disposed: list[bool] = []
    installed = process.InstalledAgentRuntimeProcess(
        profile="test",
        database_environment="NEX_AE_TEST_DATABASE_URL",
        engine=SimpleNamespace(dispose=lambda: disposed.append(True)),
        sessions=SimpleNamespace(),
        composition=SimpleNamespace(
            run_cycle=lambda: {"status": "IDLE", "execution_count": 0}
        ),
    )

    assert installed.run_once() == {"status": "IDLE", "execution_count": 0}
    installed.close()
    assert disposed == [True]


@pytest.mark.parametrize(
    ("current", "complete", "failed_check"),
    (
        (False, True, "ae_migrations_current"),
        (True, False, "runtime_tables_present"),
    ),
)
def test_readiness_fails_closed_on_database_drift(
    current: bool, complete: bool, failed_check: str
) -> None:
    engine = _sqlite_engine(current=current, complete=complete)
    installed = process.build_installed_agent_runtime_process(
        "test",
        environ={"NEX_AE_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:"},
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda value: sessionmaker(bind=value),
    )
    try:
        result = installed.readiness()
    finally:
        installed.close()

    assert result["status"] == "FAIL"
    assert result["readiness_status"] == "NOT_READY"
    assert result["checks"][failed_check] is False


def test_local_mock_check_is_package_only_and_execution_is_rejected() -> None:
    assert process.build_live_check("local_mock")["runtime_ready"] is False

    with pytest.raises(process.AgentRuntimeProcessError, match="package admission"):
        process.build_installed_agent_runtime_process("local_mock", environ={})
    with pytest.raises(process.AgentRuntimeProcessError, match="unavailable"):
        process.build_installed_agent_runtime_process("production", environ={})


def test_protected_profile_selects_product_executor_composition(monkeypatch) -> None:
    engine = _sqlite_engine()
    product_profile = process.build_deterministic_component_executor_profile()
    observed = []
    monkeypatch.setattr(
        process,
        "build_product_runtime_executor_profile",
        lambda sessions, environ: observed.append((sessions, environ))
        or product_profile,
    )
    installed = process.build_installed_agent_runtime_process(
        "staging_live",
        environ={"NEX_AE_DATABASE_URL": "sqlite+pysqlite:///:memory:"},
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda value: sessionmaker(bind=value),
    )
    try:
        assert installed.profile == "staging_live"
        assert installed.database_environment == "NEX_AE_DATABASE_URL"
        assert installed.composition.executor_profile is product_profile
        assert len(observed) == 1
    finally:
        installed.close()


def test_installed_loop_reports_work_idle_and_bounded_stop() -> None:
    sleeps: list[float] = []
    installed = _fake_process(
        {"status": "WORK", "execution_count": 1, "failed_count": 0},
        {"status": "IDLE", "execution_count": 0, "failed_count": 0},
    )
    output = StringIO()

    result = process.run_installed_agent_runtime_process(
        installed,
        max_cycles=2,
        sleeper=sleeps.append,
        out=output,
    )

    assert result["status"] == "STOPPED"
    assert result["stop_reason"] == "MAX_CYCLES"
    assert result["completed_cycles"] == 2
    assert result["work_cycles"] == 1
    assert sleeps == [0.01]
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["state"] for record in records] == [
        "STARTED",
        "WORK",
        "STOPPED",
    ]


def test_installed_loop_honors_shutdown_and_rejects_bad_bounds() -> None:
    installed = _fake_process()

    stopped = process.run_installed_agent_runtime_process(
        installed,
        should_stop=lambda: True,
        out=StringIO(),
    )
    assert stopped["stop_reason"] == "SHUTDOWN_REQUESTED"
    assert stopped["completed_cycles"] == 0

    for value in (0, True, 100_001):
        with pytest.raises(process.AgentRuntimeProcessError, match="max_cycles"):
            process.run_installed_agent_runtime_process(
                installed, max_cycles=value, out=StringIO()
            )

    not_ready = SimpleNamespace(readiness=lambda: {"readiness_status": "NOT_READY"})
    with pytest.raises(process.AgentRuntimeProcessError, match="not ready"):
        process.run_installed_agent_runtime_process(not_ready, out=StringIO())


def test_builder_disposes_engine_and_sanitizes_database_failure() -> None:
    engine = _sqlite_engine()
    disposed: list[bool] = []
    original = engine.dispose

    def dispose() -> None:
        disposed.append(True)
        original()

    engine.dispose = dispose  # type: ignore[method-assign]

    with pytest.raises(process.AgentRuntimeProcessError, match="readiness failed"):
        process.build_installed_agent_runtime_process(
            "test",
            environ={"NEX_AE_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:"},
            engine_factory=lambda *_args, **_kwargs: engine,
            engine_checker=lambda _engine: False,
        )
    assert disposed == [True]


def test_builder_rejects_blank_worker_and_sanitizes_unexpected_failure() -> None:
    with pytest.raises(process.AgentRuntimeProcessError, match="worker_id"):
        process.build_installed_agent_runtime_process(
            "test",
            environ={
                "NEX_AE_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "NEX_AE_AGENT_WORKER_ID": "   ",
            },
        )

    engine = _sqlite_engine()
    disposed: list[bool] = []
    original = engine.dispose

    def dispose() -> None:
        disposed.append(True)
        original()

    engine.dispose = dispose  # type: ignore[method-assign]
    with pytest.raises(
        process.AgentRuntimeProcessError,
        match="installed AE Agent Runtime process is unavailable",
    ):
        process.build_installed_agent_runtime_process(
            "test",
            environ={"NEX_AE_TEST_DATABASE_URL": "sqlite+pysqlite:///:memory:"},
            engine_factory=lambda *_args, **_kwargs: engine,
            engine_checker=lambda _engine: True,
            session_factory_builder=lambda _engine: (_ for _ in ()).throw(
                RuntimeError("private builder detail")
            ),
        )
    assert disposed == [True]


def test_live_check_closes_installed_process() -> None:
    closed: list[bool] = []
    installed = SimpleNamespace(
        readiness=lambda: {"status": "PASS", "readiness_status": "READY"},
        close=lambda: closed.append(True),
    )

    result = process.build_live_check(
        "test",
        environ={},
        process_builder=lambda *_args, **_kwargs: installed,
    )

    assert result["readiness_status"] == "READY"
    assert closed == [True]


def test_live_run_restores_signal_handlers_and_closes_process(monkeypatch) -> None:
    closed: list[bool] = []
    restored: list[object] = []
    installed = _fake_process(
        {"status": "IDLE", "execution_count": 0, "failed_count": 0}
    )
    installed.close = lambda: closed.append(True)
    previous = {"SIGTERM": "previous"}
    monkeypatch.setattr(
        process,
        "install_agent_runtime_worker_signal_handlers",
        lambda _token: previous,
    )
    monkeypatch.setattr(
        process,
        "restore_agent_runtime_worker_signal_handlers",
        restored.append,
    )

    result = process.run_live(
        "test",
        environ={},
        max_cycles=1,
        process_builder=lambda *_args, **_kwargs: installed,
        out=StringIO(),
    )

    assert result["status"] == "STOPPED"
    assert restored == [previous]
    assert closed == [True]


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
                process.AgentRuntimeProcessError("bounded failure")
            ),
        )
        == 2
    )
    blocked = json.loads(output.getvalue())
    assert blocked["status"] == "BLOCKED"
    assert blocked["secret_included"] is False


def test_database_check_wraps_unavailable_schema() -> None:
    def sessions():
        raise RuntimeError("private connection detail")

    with pytest.raises(process.AgentRuntimeProcessError, match="database check"):
        process._database_readiness(sessions)  # type: ignore[arg-type]
