from __future__ import annotations

from io import StringIO
import json

import pytest

import run_platform as command
from nex_runtime.runtime_orchestrator import RuntimeOrchestrationError


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class Orchestrator:
    def __init__(self, *, start_error=False, check_error=False):
        self.start_error = start_error
        self.check_error = check_error
        self.check_count = 0
        self.stop_count = 0
        self.manifest = command.build_platform_runtime_manifest(environ={})

    def start(self):
        status = self._status("RUNNING")
        if self.start_error:
            raise RuntimeOrchestrationError("start_failed", status)
        return status

    def check_running(self):
        self.check_count += 1
        status = self._status("RUNNING")
        if self.check_error:
            raise RuntimeOrchestrationError("check_failed", status)
        return status

    def stop(self):
        self.stop_count += 1
        return self._status("STOPPED")

    @staticmethod
    def _status(state):
        return {
            "schema_version": "platform_runtime_orchestration_status.v1",
            "profile": "local_mock",
            "state": state,
        }


def test_finite_platform_session_checks_runtime_and_stops() -> None:
    clock = Clock()
    runner = Orchestrator()
    output = StringIO()

    assert command.run_platform_session(
        runner,
        run_seconds=0.5,
        out=output,
        sleeper=clock.sleep,
        clock=clock,
    ) == 0

    assert runner.check_count == 2
    assert runner.stop_count == 1
    assert [json.loads(line)["state"] for line in output.getvalue().splitlines()] == [
        "RUNNING",
        "STOPPED",
    ]


@pytest.mark.parametrize(("start_error", "check_error"), [(True, False), (False, True)])
def test_orchestration_error_returns_safe_failure(start_error, check_error) -> None:
    clock = Clock()
    runner = Orchestrator(start_error=start_error, check_error=check_error)
    output = StringIO()

    assert command.run_platform_session(
        runner,
        run_seconds=0.1,
        out=output,
        sleeper=clock.sleep,
        clock=clock,
    ) == 1

    assert runner.stop_count == 1
    assert "failed" not in output.getvalue()


def test_keyboard_interrupt_and_invalid_duration_paths() -> None:
    runner = Orchestrator()
    with pytest.raises(ValueError, match="non-negative"):
        command.run_platform_session(runner, run_seconds=-1, out=StringIO())

    assert command.run_platform_session(
        runner,
        run_seconds=None,
        out=StringIO(),
        sleeper=lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    ) == 130


def test_build_orchestrator_and_main_config_projection(monkeypatch, capsys) -> None:
    built = command.build_platform_orchestrator(
        "local_mock",
        environ={},
        launcher=object(),
    )
    assert built.manifest.profile == "local_mock"

    runner = Orchestrator()
    monkeypatch.setattr(command, "build_platform_orchestrator", lambda profile: runner)
    output = StringIO()
    assert command.main(["--check-config"], out=output) == 0
    assert json.loads(output.getvalue())["profile"] == "local_mock"

    monkeypatch.setattr(command, "run_platform_session", lambda *args, **kwargs: 17)
    assert command.main(["--run-seconds", "0"], out=StringIO()) == 17

    monkeypatch.setattr(
        command,
        "build_platform_orchestrator",
        lambda profile: (_ for _ in ()).throw(ValueError("private")),
    )
    output = StringIO()
    assert command.main([], out=output) == 2
    assert json.loads(output.getvalue())["failure_code"] == "ValueError"


def test_stop_signal_is_normalized_to_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        command._handle_stop_signal(15, object())
