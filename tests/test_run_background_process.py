from __future__ import annotations

from io import StringIO
import json

import pytest

from nex_runtime import background_process as runner


class Engine:
    def __init__(self, *, fail_dispose=False):
        self.fail_dispose = fail_dispose
        self.dispose_count = 0

    def dispose(self):
        self.dispose_count += 1
        if self.fail_dispose:
            raise RuntimeError("private")


def test_all_background_modules_are_importable_in_local_mock() -> None:
    for process_id in runner.BACKGROUND_MODULES:
        metadata = runner.background_process_metadata(process_id, "local_mock")
        assert metadata["lifecycle_ready"] is True
        assert metadata["work_claiming_enabled"] is False


def test_background_shell_starts_and_stops_cooperatively() -> None:
    output = StringIO()
    stops = iter((False, True))
    sleeps: list[float] = []

    assert runner.run_background_process_shell(
        "nex-cx-ingestion-worker",
        "local_mock",
        should_stop=lambda: next(stops),
        sleeper=sleeps.append,
        out=output,
    ) == 0

    states = [json.loads(line)["state"] for line in output.getvalue().splitlines()]
    assert states == ["STARTED", "STOPPED"]
    assert sleeps == [0.25]


def test_check_mode_and_fail_closed_paths() -> None:
    output = StringIO()
    assert runner.main(
        ["nex-ag-dispatch-daemon", "--profile", "local_mock", "--check"],
        out=output,
    ) == 0
    assert json.loads(output.getvalue())["process_id"] == "nex-ag-dispatch-daemon"

    blocked = StringIO()
    assert runner.main(
        ["nex-ag-dispatch-daemon", "--profile", "test", "--check"],
        out=blocked,
    ) == 2
    assert json.loads(blocked.getvalue())["status"] == "BLOCKED"

    with pytest.raises(ValueError, match="unsupported background process"):
        runner.background_process_metadata("unknown", "local_mock")

    with pytest.raises(ValueError, match="profile is not enabled"):
        runner.background_process_metadata(
            "nex-ag-dispatch-daemon", "production"
        )


def test_protected_metadata_uses_worker_pool_and_disposes() -> None:
    engine = Engine()
    metadata = runner.background_process_metadata(
        "nex-cx-ingestion-worker",
        "test",
        environ={
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
            )
        },
        engine_factory=lambda *args, **kwargs: engine,
        engine_checker=lambda value: value is engine,
    )

    assert metadata["persistence_mode"] == "postgres"
    assert metadata["pool_workload"] == "worker"
    assert metadata["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert metadata["work_claiming_enabled"] is False
    assert engine.dispose_count == 1
    assert "secret" not in str(metadata)


@pytest.mark.parametrize("failure", ["build", "check"])
def test_protected_persistence_failure_is_normalized(failure) -> None:
    engine = Engine()

    def build(*args, **kwargs):
        if failure == "build":
            raise RuntimeError("private")
        return engine

    with pytest.raises(ValueError, match="persistence unavailable"):
        runner.prepare_background_process(
            "nex-ag-dispatch-daemon",
            "test",
            environ={
                "NEX_AG_TEST_DATABASE_URL": (
                    "postgresql://nex_ag_user:secret@localhost/nex_ag_test"
                )
            },
            engine_factory=build,
            engine_checker=lambda value: failure != "check",
        )
    assert engine.dispose_count == (0 if failure == "build" else 1)


def test_resource_close_is_idempotent_and_normalizes_failure() -> None:
    resource = runner.BackgroundProcessResource({}, Engine())
    resource.close()
    resource.close()

    failing = runner.BackgroundProcessResource({}, Engine(fail_dispose=True))
    with pytest.raises(ValueError, match="disposal failed"):
        failing.close()


def test_failed_readiness_ignores_cleanup_dispose_error() -> None:
    with pytest.raises(ValueError, match="persistence unavailable"):
        runner.prepare_background_process(
            "nex-cx-remediation-worker",
            "test",
            environ={
                "NEX_CX_TEST_DATABASE_URL": (
                    "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
                )
            },
            engine_factory=lambda *args, **kwargs: Engine(fail_dispose=True),
            engine_checker=lambda engine: False,
        )


def test_default_output_stop_signal_and_run_mode(monkeypatch, capsys) -> None:
    runner._STOP_REQUESTED = False
    runner._handle_stop_signal(15, object())
    assert runner.run_background_process_shell(
        "nex-cx-ingestion-worker", "local_mock"
    ) == 0
    assert '"state": "STOPPED"' in capsys.readouterr().out
    runner._STOP_REQUESTED = False

    observed: list[tuple[str, str, float]] = []

    def fake_shell(
        process_id,
        profile,
        *,
        poll_interval_seconds,
        out,
        enable_work_claiming,
    ):
        observed.append((process_id, profile, poll_interval_seconds))
        assert enable_work_claiming is True
        return 0

    monkeypatch.setattr(runner, "run_background_process_shell", fake_shell)
    assert runner.main(
        ["nex-cx-ingestion-worker", "--poll-interval-seconds", "0.5"]
    ) == 0
    assert observed == [("nex-cx-ingestion-worker", "local_mock", 0.5)]


def test_shell_holds_and_disposes_protected_resource(monkeypatch) -> None:
    engine = Engine()
    resource = runner.BackgroundProcessResource(
        {
            "process_id": "worker",
            "profile": "test",
            "work_claiming_enabled": False,
        },
        engine,
    )
    monkeypatch.setattr(
        runner, "prepare_background_process", lambda *args, **kwargs: resource
    )
    output = StringIO()

    assert runner.run_background_process_shell(
        "nex-cx-ingestion-worker",
        "test",
        should_stop=lambda: True,
        out=output,
    ) == 0

    assert engine.dispose_count == 1
    assert [json.loads(line)["state"] for line in output.getvalue().splitlines()] == [
        "STARTED",
        "STOPPED",
    ]


def test_import_path_configuration_adds_missing_paths(monkeypatch) -> None:
    monkeypatch.setattr(runner.sys, "path", [])
    runner._configure_import_path("nex-cx")

    assert str(runner.SHARED_PATH) in runner.sys.path
    assert str(runner.ROOT / "services" / "nex-cx") in runner.sys.path


def test_non_positive_poll_interval_is_rejected() -> None:
    output = StringIO()
    assert runner.main(
        [
            "nex-cx-ingestion-worker",
            "--profile",
            "local_mock",
            "--poll-interval-seconds",
            "0",
        ],
        out=output,
    ) == 2
    assert "poll interval must be positive" in output.getvalue()


def test_ingestion_shell_executes_recovery_and_work_cycle(monkeypatch) -> None:
    class WorkProcess:
        def __init__(self):
            self.results = iter(
                (
                    {"status": "SUCCEEDED", "job_id": "job-1349"},
                    {"status": "IDLE", "job_id": None},
                )
            )
            self.closed = False

        def metadata(self):
            return {
                "process_id": "nex-cx-ingestion-worker",
                "work_claiming_enabled": True,
            }

        def startup(self):
            return {"recovered_lease_count": 1}

        def run_once(self):
            return next(self.results)

        def close(self):
            self.closed = True

    process = WorkProcess()
    monkeypatch.setattr(
        runner,
        "_build_ingestion_work_process",
        lambda profile: process,
    )
    output = StringIO()
    stops = iter((False, False, True))
    sleeps: list[float] = []

    assert runner.run_background_process_shell(
        "nex-cx-ingestion-worker",
        "test",
        should_stop=lambda: next(stops),
        sleeper=sleeps.append,
        out=output,
        enable_work_claiming=True,
    ) == 0

    states = [json.loads(line)["state"] for line in output.getvalue().splitlines()]
    assert states == ["STARTED", "RECOVERED", "WORK", "STOPPED"]
    assert sleeps == [0.25, 0.25]
    assert process.closed is True


def test_ingestion_work_process_builder_normalizes_profile_error() -> None:
    with pytest.raises(ValueError, match="profile is not enabled"):
        runner._build_ingestion_work_process("production")


def test_database_environment_and_required_url_helpers() -> None:
    assert runner._database_environment("nex-ae-api", "test") == (
        "NEX_AE_TEST_DATABASE_URL"
    )
    assert runner._database_environment("nex-ae-api", "local_mock") == (
        "NEX_AE_DATABASE_URL"
    )
    assert runner._required_database_url("DATABASE_URL", {"DATABASE_URL": " db "}) == (
        "db"
    )
    with pytest.raises(ValueError, match="DATABASE_URL"):
        runner._required_database_url("DATABASE_URL", {})


def test_signal_handler_installation_and_source_wrapper(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(runner.signal, "signal", lambda *args: calls.append(args))
    runner.install_signal_handlers()

    import run_background_process as source_wrapper

    assert len(calls) == 2
    assert source_wrapper.main is runner.main
    assert source_wrapper.BACKGROUND_MODULES is runner.BACKGROUND_MODULES
