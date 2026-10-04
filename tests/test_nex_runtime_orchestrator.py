from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import nex_runtime.runtime_process_adapters as runtime_adapters
from nex_runtime.runtime_orchestrator import (
    RuntimeOrchestrationError,
    RuntimeOrchestrator,
    RuntimeProbeRequest,
    SubprocessRuntimeLauncher,
    probe_http_runtime_process,
)
from nex_runtime.topology import (
    PlatformRuntimeManifest,
    RuntimeEndpoint,
    RuntimeModes,
    RuntimeProbe,
    RuntimeProcess,
)


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class Handle:
    def __init__(self, process_id: str, log: list[str], *, exit_code=None, hang=False):
        self.process_id = process_id
        self.log = log
        self.exit_code = exit_code
        self.hang = hang
        self.killed = False

    def poll(self):
        return self.exit_code

    def terminate(self) -> None:
        self.log.append(f"terminate:{self.process_id}")
        if not self.hang:
            self.exit_code = -15

    def wait(self, timeout=None) -> int:
        if self.hang and not self.killed:
            raise TimeoutError
        return 0 if self.exit_code is None else self.exit_code

    def kill(self) -> None:
        self.log.append(f"kill:{self.process_id}")
        self.killed = True
        self.exit_code = -9


class Launcher:
    def __init__(self, *, fail_on=None, exit_on=None, hang_on=None):
        self.fail_on = fail_on
        self.exit_on = exit_on
        self.hang_on = hang_on
        self.launches: list[str] = []
        self.environments: list[dict[str, str]] = []
        self.log: list[str] = []
        self.handles: dict[str, Handle] = {}

    def launch(self, process, *, environment):
        if process.process_id == self.fail_on:
            raise OSError("private launch detail")
        self.launches.append(process.process_id)
        self.environments.append(dict(environment))
        handle = Handle(
            process.process_id,
            self.log,
            exit_code=7 if process.process_id == self.exit_on else None,
            hang=process.process_id == self.hang_on,
        )
        self.handles[process.process_id] = handle
        return handle


def process(process_id: str, *, dependency=None, kind="api", probe=True):
    network = kind in {"api", "web"}
    return RuntimeProcess(
        process_id,
        process_id,
        kind,
        ("python", "secret-command.py"),
        host="127.0.0.1" if network else None,
        port=8100 + len(process_id) if network else None,
        dependencies=(dependency,) if dependency else (),
        liveness_probe=RuntimeProbe("/health", 0.5) if network and probe else None,
        readiness_probe=RuntimeProbe("/ready", 0.75) if network and probe else None,
        environment_names=("NEX_SECRET",),
    )


def manifest(*, profile="local_mock", timeout=1.0, processes=None):
    selected = processes or (
        process("root"),
        process("child", dependency="root"),
        process("worker", dependency="child", kind="worker"),
    )
    modes = (
        RuntimeModes("memory", "mock", "test_mock", "memory")
        if profile == "local_mock"
        else RuntimeModes("postgres", "mock", "signed", "api")
    )
    return PlatformRuntimeManifest(
        "platform_runtime_manifest.v1",
        profile,
        modes,
        (),
        selected,
        startup_timeout_seconds=timeout,
        shutdown_timeout_seconds=0.5,
    )


def orchestrator(value, launcher, probe=lambda request: True):
    clock = Clock()
    return RuntimeOrchestrator(
        value,
        launcher=launcher,
        probe=probe,
        environ={"NEX_SECRET": "never-project-me"},
        sleeper=clock.sleep,
        clock=clock,
        poll_interval_seconds=0.1,
    )


def test_start_waits_for_probes_and_stop_reverses_start_order() -> None:
    launcher = Launcher()
    attempts: dict[str, int] = {}

    def probe(request):
        attempts[request.process_id] = attempts.get(request.process_id, 0) + 1
        return attempts[request.process_id] >= 2

    runner = orchestrator(manifest(), launcher, probe)
    status = runner.start()

    assert status["state"] == "RUNNING"
    assert status["startup_order"] == ["root", "child", "worker"]
    assert status["process_counts"]["READY"] == 3
    assert {item["probe_mode"] for item in status["processes"][:2]} == {"liveness"}
    assert status["processes"][2]["probe_attempts"] == 2
    assert launcher.environments[0]["NEX_PROFILE"] == "local_mock"
    assert "never-project-me" not in str(status)
    assert "secret-command.py" not in str(status)

    stopped = runner.stop()
    assert stopped["state"] == "STOPPED"
    assert stopped["process_counts"]["STOPPED"] == 3
    assert launcher.log == ["terminate:worker", "terminate:child", "terminate:root"]


def test_manifest_endpoints_are_projected_to_child_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEX_EXISTING_VALUE", "preserved")
    selected = replace(
        manifest(processes=(process("root"),)),
        endpoints=(
            RuntimeEndpoint("nex-oa", "http://127.0.0.1:19001"),
            RuntimeEndpoint("nex-ae-web", "http://127.0.0.1:19002"),
            RuntimeEndpoint("custom", "http://127.0.0.1:19003"),
        ),
    )
    launcher = Launcher()
    clock = Clock()
    runner = RuntimeOrchestrator(
        selected,
        launcher=launcher,
        probe=lambda request: True,
        sleeper=clock.sleep,
        clock=clock,
    )

    runner.start()

    environment = launcher.environments[0]
    assert environment["NEX_OA_BASE_URL"] == "http://127.0.0.1:19001"
    assert environment["NEX_AE_WEB_BASE_URL"] == "http://127.0.0.1:19002"
    assert environment["NEX_EXISTING_VALUE"] == "preserved"
    assert "custom" not in str(environment)
    runner.stop()


def test_protected_profile_uses_readiness_probe() -> None:
    launcher = Launcher()
    requests = []
    runner = orchestrator(
        manifest(profile="test", processes=(process("root"),)),
        launcher,
        lambda request: requests.append(request) or True,
    )

    assert runner.start()["processes"][0]["probe_mode"] == "readiness"
    assert requests[0].url.endswith("/ready")
    runner.stop()


def test_startup_timeout_fails_closed_and_redacts_probe_details() -> None:
    launcher = Launcher()
    runner = orchestrator(
        manifest(timeout=0.15, processes=(process("root"),)),
        launcher,
        lambda request: False,
    )

    with pytest.raises(RuntimeOrchestrationError) as raised:
        runner.start()

    assert raised.value.failure_code == "runtime_startup_timeout"
    assert raised.value.status["state"] == "FAILED"
    assert raised.value.status["processes"][0]["state"] == "FAILED"
    assert "secret" not in str(raised.value.status).lower()
    assert runner.stop()["state"] == "FAILED"


@pytest.mark.parametrize(
    ("launcher", "failure_code"),
    [
        (Launcher(fail_on="root"), "runtime_process_launch_failed"),
        (Launcher(exit_on="root"), "runtime_process_exited_before_ready"),
    ],
)
def test_launch_and_early_exit_failures_are_normalized(launcher, failure_code) -> None:
    runner = orchestrator(manifest(processes=(process("root"),)), launcher)

    with pytest.raises(RuntimeOrchestrationError) as raised:
        runner.start()

    assert raised.value.failure_code == failure_code
    assert raised.value.status["failure_code"] == failure_code


def test_missing_root_probe_and_invalid_orchestrator_state_fail_closed() -> None:
    runner = orchestrator(
        manifest(processes=(process("root", probe=False),)), Launcher()
    )
    with pytest.raises(RuntimeOrchestrationError) as raised:
        runner.start()
    assert raised.value.failure_code == "runtime_process_probe_missing"

    successful = orchestrator(manifest(processes=(process("root"),)), Launcher())
    with pytest.raises(RuntimeOrchestrationError, match="check_state_invalid"):
        successful.check_running()
    successful.start()
    assert successful.check_running()["state"] == "RUNNING"
    with pytest.raises(RuntimeOrchestrationError, match="start_state_invalid"):
        successful.start()
    successful.stop()


def test_running_process_exit_triggers_reverse_cleanup() -> None:
    launcher = Launcher()
    runner = orchestrator(manifest(), launcher)
    runner.start()
    launcher.handles["child"].exit_code = 9

    with pytest.raises(RuntimeOrchestrationError) as raised:
        runner.check_running()

    assert raised.value.failure_code == "runtime_process_exited_while_running"
    child = next(
        item for item in raised.value.status["processes"] if item["process_id"] == "child"
    )
    assert child["state"] == "FAILED"
    assert child["exit_code"] == 9
    assert launcher.log == ["terminate:worker", "terminate:root"]


def test_shutdown_kills_process_that_does_not_terminate() -> None:
    launcher = Launcher(hang_on="root")
    runner = orchestrator(manifest(processes=(process("root"),)), launcher)
    runner.start()

    status = runner.stop()

    assert launcher.log == ["terminate:root", "kill:root"]
    assert status["processes"][0]["exit_code"] == -9
    assert runner.stop() == status


def test_constructor_and_http_probe_defensive_paths() -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        RuntimeOrchestrator(manifest(), launcher=Launcher(), poll_interval_seconds=0)

    request = RuntimeProbeRequest("root", "liveness", "http://root/health", 1.0)

    class Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    assert probe_http_runtime_process(request, opener=lambda *args, **kwargs: Response(204))
    assert not probe_http_runtime_process(
        request, opener=lambda *args, **kwargs: Response(500)
    )
    assert not probe_http_runtime_process(
        request, opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )


def test_subprocess_launcher_uses_no_shell_and_suppresses_child_output(monkeypatch) -> None:
    calls = []
    sentinel = SimpleNamespace()
    monkeypatch.setattr(
        runtime_adapters.subprocess,
        "Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)) or sentinel,
    )
    selected = process("root")

    result = SubprocessRuntimeLauncher(Path("/repo")).launch(
        selected, environment={"NEX_PROFILE": "local_mock"}
    )

    assert result is sentinel
    assert calls[0][0] == (selected.command,)
    assert calls[0][1]["cwd"] == Path("/repo")
    assert calls[0][1]["stdin"] is runtime_adapters.subprocess.DEVNULL
    assert "shell" not in calls[0][1]
