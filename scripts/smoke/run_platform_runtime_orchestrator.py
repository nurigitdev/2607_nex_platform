#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.process_manifest import build_platform_runtime_manifest  # noqa: E402
from nex_runtime.runtime_orchestrator import RuntimeOrchestrator  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Handle:
    def __init__(self, process_id: str, stop_order: list[str]) -> None:
        self.process_id = process_id
        self.stop_order = stop_order
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def terminate(self) -> None:
        self.stop_order.append(self.process_id)
        self.exit_code = 0

    def wait(self, timeout=None) -> int:
        return 0 if self.exit_code is None else self.exit_code

    def kill(self) -> None:
        self.exit_code = -9


class _Launcher:
    def __init__(self) -> None:
        self.launch_order: list[str] = []
        self.stop_order: list[str] = []
        self.environment_values: list[str] = []

    def launch(self, process, *, environment):
        self.launch_order.append(process.process_id)
        self.environment_values.extend(environment.values())
        return _Handle(process.process_id, self.stop_order)


def run_platform_runtime_orchestrator() -> dict[str, Any]:
    manifest = build_platform_runtime_manifest(environ={}, python_executable="python")
    launcher = _Launcher()
    clock = _Clock()
    probe_attempts: dict[str, int] = {}

    def probe(request):
        probe_attempts[request.process_id] = probe_attempts.get(request.process_id, 0) + 1
        return probe_attempts[request.process_id] >= 2

    orchestrator = RuntimeOrchestrator(
        manifest,
        launcher=launcher,
        probe=probe,
        environ={"NEX_PRIVATE_VALUE": "must-not-appear"},
        sleeper=clock.sleep,
        clock=clock,
        poll_interval_seconds=0.01,
    )
    running = orchestrator.start()
    stopped = orchestrator.stop()
    serialized = json.dumps({"running": running, "stopped": stopped})
    checks = {
        "all_thirteen_processes_reach_ready": running["process_counts"]["READY"] == 13,
        "dependency_order_is_complete": len(running["startup_order"]) == 13,
        "network_processes_are_probe_gated": all(
            item["probe_attempts"] >= 2
            for item in running["processes"]
            if item["kind"] in {"api", "web"}
        ),
        "background_processes_are_stability_checked": all(
            item["probe_attempts"] == 2
            for item in running["processes"]
            if item["kind"] in {"worker", "daemon"}
        ),
        "shutdown_is_reverse_startup_order": (
            launcher.stop_order == list(reversed(launcher.launch_order))
        ),
        "all_processes_stop": stopped["process_counts"]["STOPPED"] == 13,
        "status_projection_is_private": (
            "must-not-appear" not in serialized
            and "command" not in serialized
            and "environment" not in serialized
            and "pid" not in serialized
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_runtime_orchestrator.v1",
        "slice": "1319",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_runtime_orchestrator_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "running_status": running,
        "stopped_status": stopped,
        "decision": {
            "actual_processes_spawned": False,
            "actual_local_mock_process_smoke": "1320",
            "rollback_runner": "scripts/dev/run_all_services.py",
            "next_slice": "1320",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_orchestrator=fail issues={len(evidence.get('issues') or [])}"
    running = evidence.get("running_status") or {}
    return (
        "platform_runtime_orchestrator=pass "
        f"ready={running.get('process_counts', {}).get('READY')} "
        f"started={len(running.get('startup_order') or [])} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_runtime_orchestrator()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
