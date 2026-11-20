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
    heartbeat_statuses: list[str] = []
    finalization_flags: list[bool] = []

    def run_once(*, finalize_lifecycle: bool = True):
        finalization_flags.append(finalize_lifecycle)
        return next(executions)

    return SimpleNamespace(
        readiness=lambda: {
            "status": "PASS",
            "readiness_status": "READY",
        },
        run_once=run_once,
        composition=SimpleNamespace(
            worker_config=SimpleNamespace(poll_interval_seconds=0.01),
            heartbeat_emitter=SimpleNamespace(
                safe_emit=lambda **values: heartbeat_statuses.append(values["status"])
            ),
        ),
        heartbeat_statuses=heartbeat_statuses,
        finalization_flags=finalization_flags,
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
            run_cycle=lambda **_values: {"status": "IDLE", "execution_count": 0}
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
    product_skill_runtime = SimpleNamespace()
    observed = []
    monkeypatch.setattr(
        process,
        "build_installed_product_skill_runtime",
        lambda sessions, environ: product_skill_runtime,
    )
    monkeypatch.setattr(
        process,
        "build_product_runtime_executor_profile",
        lambda sessions, environ, **values: (
            observed.append((sessions, environ, values)) or product_profile
        ),
    )
    monkeypatch.setattr(
        process,
        "build_activated_m1_product_planning_composition",
        lambda **values: SimpleNamespace(
            assignment_handler=None,
            runtime_registry=SimpleNamespace(identities=()),
            environ=values["environ"],
        ),
    )
    installed = process.build_installed_agent_runtime_process(
        "staging_live",
        environ={
            "NEX_AE_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                process.ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            ),
        },
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda value: sessionmaker(bind=value),
    )
    try:
        assert installed.profile == "staging_live"
        assert installed.database_environment == "NEX_AE_DATABASE_URL"
        assert installed.composition.executor_profile is product_profile
        assert installed.composition.product_planning is not None
        assert installed.composition.product_planning.assignment_handler is None
        assert not hasattr(installed, "mybee_product_consumer")
        assert len(observed) == 1
        assert observed[0][2]["runtime"] is product_skill_runtime
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
    assert installed.heartbeat_statuses == [process.STOPPED]
    assert installed.finalization_flags == [False, False]
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [record["state"] for record in records] == [
        "STARTED",
        "WORK",
        "STOPPED",
    ]


def test_installed_loop_reports_bounded_result_settlement_failures() -> None:
    installed = _fake_process(
        {
            "status": "WORK",
            "execution_count": 1,
            "failed_count": 2,
            "result_closure": {
                "candidate_count": 1,
                "finalized_count": 0,
                "published_count": 0,
                "replayed_count": 0,
                "failed_count": 1,
                "failures": [
                    {
                        "tenant_id": "protected-tenant",
                        "agent_execution_id": "protected-execution",
                        "error_code": "ae.workspace_result_lineage_invalid",
                        "retryable": False,
                    }
                ],
            },
            "background_result_closure": {
                "candidate_count": 1,
                "finalized_count": 1,
                "published_count": 0,
                "replayed_count": 0,
                "failed_count": 1,
                "failures": [
                    {
                        "tenant_id": "protected-tenant",
                        "agent_execution_id": "protected-execution",
                        "error_code": "ae.wc_work_result_http_failed",
                        "retryable": True,
                    }
                ],
            },
        }
    )
    output = StringIO()

    process.run_installed_agent_runtime_process(
        installed,
        max_cycles=1,
        out=output,
    )

    work = json.loads(output.getvalue().splitlines()[1])
    assert work["ia_result_settlement"] == {
        "candidate_count": 1,
        "finalized_count": 0,
        "published_count": 0,
        "replayed_count": 0,
        "failed_count": 1,
        "failures": [
            {
                "error_code": "ae.workspace_result_lineage_invalid",
                "retryable": False,
            }
        ],
        "content_included": False,
    }
    assert work["background_result_settlement"]["failures"] == [
        {
            "error_code": "ae.wc_work_result_http_failed",
            "retryable": True,
        }
    ]
    assert "tenant_id" not in str(work)


def test_installed_loop_honors_shutdown_and_rejects_bad_bounds() -> None:
    installed = _fake_process()

    stopped = process.run_installed_agent_runtime_process(
        installed,
        should_stop=lambda: True,
        out=StringIO(),
    )
    assert stopped["stop_reason"] == "SHUTDOWN_REQUESTED"
    assert stopped["completed_cycles"] == 0
    assert installed.heartbeat_statuses == [process.STOPPED]
    assert installed.finalization_flags == []

    for value in (0, True, 100_001):
        with pytest.raises(process.AgentRuntimeProcessError, match="max_cycles"):
            process.run_installed_agent_runtime_process(
                installed, max_cycles=value, out=StringIO()
            )

    not_ready = SimpleNamespace(
        readiness=lambda: {
            "readiness_status": "NOT_READY",
            "checks": {
                "database_connected": True,
                "package_readiness_satisfied": False,
            },
        }
    )
    with pytest.raises(
        process.AgentRuntimeProcessError,
        match="failed_checks=package_readiness_satisfied",
    ):
        process.run_installed_agent_runtime_process(not_ready, out=StringIO())

    missing_contract = SimpleNamespace(
        readiness=lambda: {"readiness_status": "NOT_READY"}
    )
    with pytest.raises(
        process.AgentRuntimeProcessError,
        match="failed_checks=readiness_contract_unavailable",
    ):
        process.run_installed_agent_runtime_process(missing_contract, out=StringIO())


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


def test_database_check_wraps_unavailable_schema() -> None:
    def sessions():
        raise RuntimeError("private connection detail")

    with pytest.raises(process.AgentRuntimeProcessError, match="database check"):
        process._database_readiness(sessions)  # type: ignore[arg-type]
