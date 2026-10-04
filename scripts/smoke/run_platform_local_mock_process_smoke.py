#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any, Mapping
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "dev"))

from nex_runtime.runtime_orchestrator import RuntimeOrchestrationError  # noqa: E402
from nex_runtime.runtime_profiles import runtime_profile_environment_overlay  # noqa: E402
from nex_runtime.service_endpoints import SERVICE_ENDPOINTS  # noqa: E402
from run_platform import build_platform_orchestrator  # noqa: E402


def run_platform_local_mock_process_smoke() -> dict[str, Any]:
    environment = _local_mock_environment()
    orchestrator = None
    running_status: dict[str, Any] | None = None
    stopped_status: dict[str, Any] | None = None
    endpoint_results: list[dict[str, Any]] = []
    failure_code = None
    try:
        orchestrator = build_platform_orchestrator(
            "local_mock", environ=environment, root=ROOT
        )
        running_status = orchestrator.start()
        endpoint_results = _probe_complete_topology(orchestrator.manifest)
        time.sleep(0.2)
        running_status = orchestrator.check_running()
    except RuntimeOrchestrationError as exc:
        failure_code = exc.failure_code
        running_status = dict(exc.status)
    except (OSError, TimeoutError, ValueError):
        failure_code = "platform_local_mock_probe_failed"
    finally:
        if orchestrator is not None:
            stopped_status = orchestrator.stop()

    running = running_status or {}
    stopped = stopped_status or {}
    checks = {
        "actual_thirteen_processes_started": (
            len(running.get("startup_order") or []) == 13
        ),
        "all_processes_reached_ready": (
            running.get("process_counts", {}).get("READY") == 13
        ),
        "five_api_health_probes_passed": (
            sum(item.get("kind") == "api" and item.get("ok") for item in endpoint_results)
            == 5
        ),
        "ae_web_probe_passed": any(
            item.get("kind") == "web" and item.get("ok") for item in endpoint_results
        ),
        "all_processes_remained_running": failure_code is None,
        "all_processes_stopped": (
            stopped.get("process_counts", {}).get("STOPPED") == 13
        ),
        "status_is_machine_readable_and_private": _status_is_private(
            {"running": running, "stopped": stopped}
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_local_mock_process_smoke.v1",
        "slice": "1320",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else (failure_code or "platform_local_mock_process_smoke_failed"),
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "actual_process_count": len(running.get("startup_order") or []),
        "http_probe_count": len(endpoint_results),
        "running_process_counts": running.get("process_counts") or {},
        "stopped_process_counts": stopped.get("process_counts") or {},
        "decision": {
            "postgres_contacted": False,
            "remote_provider_contacted": False,
            "rollback_runner": "scripts/dev/run_all_services.py",
            "next_slice": "1321",
        },
    }


def _local_mock_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(runtime_profile_environment_overlay("local_mock"))
    endpoint_urls = {
        service_id: f"http://127.0.0.1:{_free_port()}"
        for service_id in SERVICE_ENDPOINTS
    }
    for service_id, base_url in endpoint_urls.items():
        environment[SERVICE_ENDPOINTS[service_id][0]] = base_url
    environment["NEX_AE_WEB_BASE_URL"] = f"http://127.0.0.1:{_free_port()}"
    return environment


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _probe_complete_topology(manifest, *, opener=urlopen) -> list[dict[str, Any]]:
    results = []
    for process in manifest.processes:
        if process.kind not in {"api", "web"}:
            continue
        path = "/health" if process.kind == "api" else "/"
        url = f"http://{process.host}:{process.port}{path}"
        with opener(url, timeout=2.0) as response:
            body = response.read()
            ok = 200 <= int(response.status) < 400 and bool(body)
        results.append(
            {
                "process_id": process.process_id,
                "kind": process.kind,
                "ok": ok,
            }
        )
    return results


def _status_is_private(status: Mapping[str, Any]) -> bool:
    serialized = json.dumps(status, sort_keys=True).lower()
    return not any(
        token in serialized
        for token in ("command", "environment", "password", "api_key", "pid")
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_local_mock_process_smoke=fail issues={len(evidence.get('issues') or [])}"
    return (
        "platform_local_mock_process_smoke=pass "
        f"processes={evidence.get('actual_process_count')} "
        f"http={evidence.get('http_probe_count')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_local_mock_process_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
