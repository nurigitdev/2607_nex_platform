from __future__ import annotations

from io import StringIO
import json

import pytest

import run_background_process as runner


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


def test_default_output_stop_signal_and_run_mode(monkeypatch, capsys) -> None:
    runner._STOP_REQUESTED = False
    runner._handle_stop_signal(15, object())
    assert runner.run_background_process_shell(
        "nex-cx-ingestion-worker", "local_mock"
    ) == 0
    assert '"state": "STOPPED"' in capsys.readouterr().out
    runner._STOP_REQUESTED = False

    observed: list[tuple[str, str, float]] = []

    def fake_shell(process_id, profile, *, poll_interval_seconds, out):
        observed.append((process_id, profile, poll_interval_seconds))
        return 0

    monkeypatch.setattr(runner, "run_background_process_shell", fake_shell)
    assert runner.main(
        ["nex-cx-ingestion-worker", "--poll-interval-seconds", "0.5"]
    ) == 0
    assert observed == [("nex-cx-ingestion-worker", "local_mock", 0.5)]


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
