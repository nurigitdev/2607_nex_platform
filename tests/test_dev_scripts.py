from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_all_services
import run_service


def test_run_service_main_invokes_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    fake_uvicorn = SimpleNamespace(
        run=lambda app_path, **kwargs: calls.append({"app_path": app_path, **kwargs})
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(sys, "argv", ["run_service.py", "nex-oa", "--port", "9101"])
    monkeypatch.chdir(tmp_path)

    assert run_service.main() == 0

    assert calls == [
        {
            "app_path": "nex_oa.main:app",
            "host": "127.0.0.1",
            "port": 9101,
            "reload": False,
            "reload_dirs": None,
        }
    ]


def test_run_service_main_uses_default_port_and_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    fake_uvicorn = SimpleNamespace(
        run=lambda app_path, **kwargs: calls.append({"app_path": app_path, **kwargs})
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(sys, "argv", ["run_service.py", "nex-mo", "--reload"])

    assert run_service.main() == 0

    assert calls[0]["port"] == 8105
    assert calls[0]["reload"] is True
    assert calls[0]["reload_dirs"]


class FakeProcess:
    def __init__(self, pid: int, poll_values: list[int | None]) -> None:
        self.pid = pid
        self.poll_values = poll_values
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self) -> int | None:
        if self.poll_values:
            return self.poll_values.pop(0)
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> None:
        self.waited = True

    def kill(self) -> None:
        self.killed = True


class StuckProcess(FakeProcess):
    def wait(self, timeout: int) -> None:
        self.waited = True
        raise run_all_services.subprocess.TimeoutExpired("cmd", timeout)


def test_wait_for_processes_returns_first_exit_code() -> None:
    process = FakeProcess(pid=1, poll_values=[7])

    assert run_all_services._wait_for_processes([process]) == 7


def test_wait_for_processes_sleeps_until_process_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    process = FakeProcess(pid=1, poll_values=[None, 8])
    monkeypatch.setattr(run_all_services.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert run_all_services._wait_for_processes([process]) == 8
    assert sleeps == [0.5]


def test_terminate_processes_terminates_running_processes() -> None:
    process = FakeProcess(pid=1, poll_values=[None, None, 0])

    run_all_services._terminate_processes([process])

    assert process.terminated is True
    assert process.waited is True
    assert process.killed is False


def test_terminate_processes_kills_stuck_processes() -> None:
    process = StuckProcess(pid=1, poll_values=[None, None, None])

    run_all_services._terminate_processes([process])

    assert process.terminated is True
    assert process.waited is True
    assert process.killed is True


def test_handle_stop_signal_raises_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        run_all_services._handle_stop_signal(15, None)


def test_run_all_services_main_starts_services_and_returns_wait_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes: list[FakeProcess] = []
    popen_calls: list[list[str]] = []

    def fake_popen(args: list[str], cwd: Path, text: bool) -> FakeProcess:
        popen_calls.append(args)
        process = FakeProcess(pid=100 + len(processes), poll_values=[0])
        processes.append(process)
        return process

    monkeypatch.setattr(run_all_services.signal, "signal", lambda signum, handler: None)
    monkeypatch.setattr(run_all_services.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_all_services, "SERVICES", ["nex-oa", "nex-mo"])
    monkeypatch.setattr(run_all_services, "_wait_for_processes", lambda started: 3)

    assert run_all_services.main() == 3
    assert len(processes) == 2
    assert popen_calls[0][-1] == "nex-oa"
    assert popen_calls[1][-1] == "nex-mo"


def test_run_all_services_main_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(pid=200, poll_values=[None, 0])

    def fake_popen(args: list[str], cwd: Path, text: bool) -> FakeProcess:
        return process

    def raise_keyboard_interrupt(started: list[FakeProcess]) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_all_services.signal, "signal", lambda signum, handler: None)
    monkeypatch.setattr(run_all_services.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_all_services, "SERVICES", ["nex-oa"])
    monkeypatch.setattr(run_all_services, "_wait_for_processes", raise_keyboard_interrupt)

    assert run_all_services.main() == 130
    assert process.terminated is True
