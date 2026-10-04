from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import subprocess
import time
from typing import Any

from .runtime_process_adapters import (
    RuntimeProcessHandle,
    RuntimeProcessLauncher,
    RuntimeProbeRequest,
    SubprocessRuntimeLauncher,
    build_runtime_process_environment,
    probe_http_runtime_process,
)
from .topology import PlatformRuntimeManifest, RuntimeProcess, validate_runtime_manifest
from .topology_graph import RuntimeStartupPlan, build_runtime_startup_plan


PROCESS_STATES = ("PENDING", "STARTING", "READY", "FAILED", "STOPPED")


@dataclass
class RuntimeProcessState:
    process_id: str
    owner: str
    kind: str
    state: str = "PENDING"
    probe_mode: str | None = None
    probe_attempts: int = 0
    exit_code: int | None = None
    failure_code: str | None = None


class RuntimeOrchestrationError(RuntimeError):
    def __init__(self, failure_code: str, status: Mapping[str, Any]) -> None:
        self.failure_code = failure_code
        self.status = dict(status)
        super().__init__(failure_code)


class RuntimeOrchestrator:
    def __init__(
        self,
        manifest: PlatformRuntimeManifest,
        *,
        launcher: RuntimeProcessLauncher,
        probe: Callable[[RuntimeProbeRequest], bool] = probe_http_runtime_process,
        environ: Mapping[str, str] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        validate_runtime_manifest(manifest)
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.manifest = manifest
        self.plan: RuntimeStartupPlan = build_runtime_startup_plan(manifest)
        self.launcher = launcher
        self.probe = probe
        self.sleeper = sleeper
        self.clock = clock
        self.poll_interval_seconds = poll_interval_seconds
        self.environment = build_runtime_process_environment(
            manifest, environ=environ
        )
        self._processes = {item.process_id: item for item in manifest.processes}
        self._states = {
            item.process_id: RuntimeProcessState(item.process_id, item.owner, item.kind)
            for item in manifest.processes
        }
        self._handles: dict[str, RuntimeProcessHandle] = {}
        self._started_process_ids: list[str] = []
        self._state = "NEW"
        self._failure_code: str | None = None

    def start(self) -> dict[str, Any]:
        if self._state != "NEW":
            raise RuntimeOrchestrationError(
                "runtime_orchestrator_start_state_invalid", self.public_status()
            )
        self._state = "STARTING"
        deadline = self.clock() + self.manifest.startup_timeout_seconds
        try:
            for layer in self.plan.layers:
                for process_id in layer:
                    self._launch_process(process_id)
                self._wait_until_layer_ready(layer, deadline=deadline)
        except _RuntimeStartFailure as exc:
            self._failure_code = exc.failure_code
            self._state = "FAILED"
            self._stop_handles(preserve_failed=True)
            raise RuntimeOrchestrationError(
                exc.failure_code, self.public_status()
            ) from exc
        self._state = "RUNNING"
        return self.public_status()

    def stop(self) -> dict[str, Any]:
        self._stop_handles(preserve_failed=self._state == "FAILED")
        if self._state != "FAILED":
            self._state = "STOPPED"
        return self.public_status()

    def check_running(self) -> dict[str, Any]:
        if self._state != "RUNNING":
            raise RuntimeOrchestrationError(
                "runtime_orchestrator_check_state_invalid", self.public_status()
            )
        for process_id in self._started_process_ids:
            exit_code = self._handles[process_id].poll()
            if exit_code is None:
                continue
            state = self._states[process_id]
            state.exit_code = exit_code
            self._fail_process(process_id, "runtime_process_exited_while_running")
            self._failure_code = "runtime_process_exited_while_running"
            self._state = "FAILED"
            self._stop_handles(preserve_failed=True)
            raise RuntimeOrchestrationError(
                self._failure_code, self.public_status()
            )
        return self.public_status()

    def public_status(self) -> dict[str, Any]:
        records = [
            self._states[item.process_id] for item in self.manifest.processes
        ]
        counts = {
            state: sum(record.state == state for record in records)
            for state in PROCESS_STATES
        }
        return {
            "schema_version": "platform_runtime_orchestration_status.v1",
            "profile": self.manifest.profile,
            "state": self._state,
            "failure_code": self._failure_code,
            "process_counts": counts,
            "startup_order": list(self._started_process_ids),
            "processes": [
                {
                    "process_id": record.process_id,
                    "owner": record.owner,
                    "kind": record.kind,
                    "state": record.state,
                    "probe_mode": record.probe_mode,
                    "probe_attempts": record.probe_attempts,
                    "exit_code": record.exit_code,
                    "failure_code": record.failure_code,
                }
                for record in records
            ],
        }

    def _launch_process(self, process_id: str) -> None:
        process = self._processes[process_id]
        state = self._states[process_id]
        state.state = "STARTING"
        try:
            handle = self.launcher.launch(
                process,
                environment=self.environment,
            )
        except OSError as exc:
            self._fail_process(process_id, "runtime_process_launch_failed")
            raise _RuntimeStartFailure("runtime_process_launch_failed") from exc
        self._handles[process_id] = handle
        self._started_process_ids.append(process_id)

    def _wait_until_layer_ready(
        self,
        layer: tuple[str, ...],
        *,
        deadline: float,
    ) -> None:
        pending = set(layer)
        background_observations = {process_id: 0 for process_id in layer}
        while True:
            for process_id in tuple(pending):
                handle = self._handles[process_id]
                exit_code = handle.poll()
                if exit_code is not None:
                    state = self._states[process_id]
                    state.exit_code = exit_code
                    self._fail_process(process_id, "runtime_process_exited_before_ready")
                    raise _RuntimeStartFailure(
                        "runtime_process_exited_before_ready"
                    )
                process = self._processes[process_id]
                if process.kind in {"api", "web"}:
                    ready = self._probe_process(process)
                else:
                    background_observations[process_id] += 1
                    self._states[process_id].probe_attempts += 1
                    ready = background_observations[process_id] >= 2
                if ready:
                    self._states[process_id].state = "READY"
                    pending.remove(process_id)
            if not pending:
                return
            if self.clock() >= deadline:
                failed_process_id = next(
                    process_id for process_id in layer if process_id in pending
                )
                self._fail_process(failed_process_id, "runtime_startup_timeout")
                raise _RuntimeStartFailure("runtime_startup_timeout")
            self.sleeper(self.poll_interval_seconds)

    def _probe_process(self, process: RuntimeProcess) -> bool:
        probe_mode = "liveness" if self.manifest.profile == "local_mock" else "readiness"
        probe = (
            process.liveness_probe
            if probe_mode == "liveness"
            else process.readiness_probe
        )
        if process.host is None or process.port is None or probe is None:
            self._fail_process(process.process_id, "runtime_process_probe_missing")
            raise _RuntimeStartFailure("runtime_process_probe_missing")
        state = self._states[process.process_id]
        state.probe_mode = probe_mode
        state.probe_attempts += 1
        request = RuntimeProbeRequest(
            process_id=process.process_id,
            mode=probe_mode,
            url=f"http://{process.host}:{process.port}{probe.path}",
            timeout_seconds=probe.timeout_seconds,
        )
        return bool(self.probe(request))

    def _fail_process(self, process_id: str, failure_code: str) -> None:
        state = self._states[process_id]
        state.state = "FAILED"
        state.failure_code = failure_code

    def _stop_handles(self, *, preserve_failed: bool) -> None:
        if not self._handles:
            return
        deadline = self.clock() + self.manifest.shutdown_timeout_seconds
        for process_id in reversed(self._started_process_ids):
            handle = self._handles[process_id]
            if handle.poll() is not None:
                continue
            handle.terminate()
        for process_id in reversed(self._started_process_ids):
            handle = self._handles[process_id]
            try:
                exit_code = handle.wait(timeout=max(0.0, deadline - self.clock()))
            except (subprocess.TimeoutExpired, TimeoutError):
                handle.kill()
                exit_code = handle.wait(timeout=None)
            state = self._states[process_id]
            state.exit_code = exit_code
            if not (preserve_failed and state.state == "FAILED"):
                state.state = "STOPPED"
        self._handles.clear()


class _RuntimeStartFailure(RuntimeError):
    def __init__(self, failure_code: str) -> None:
        self.failure_code = failure_code
        super().__init__(failure_code)
