#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from nex_runtime.process_manifest import build_platform_runtime_manifest  # noqa: E402
from nex_runtime.runtime_process_adapters import (  # noqa: E402
    build_runtime_process_environment,
)
from nex_runtime.runtime_profiles import SIGNED_TRUST_ENV_NAMES  # noqa: E402
from nex_runtime.service_endpoints import SERVICE_ENDPOINTS  # noqa: E402
from nex_runtime.topology import RuntimeProcess  # noqa: E402
from platform_test_migrations import (  # noqa: E402
    PlatformMigrationReadinessError,
    run_platform_test_migration_readiness,
)


SMOKE_ENV = "NEX_PLATFORM_TEST_PROFILE_STARTUP_SMOKE"
API_READY_TIMEOUT_SECONDS = 30.0
BACKGROUND_STABILITY_SECONDS = 0.5


class PlatformTestProfileStartupError(RuntimeError):
    def __init__(self, failure_code: str, process_id: str | None = None) -> None:
        self.failure_code = failure_code
        self.process_id = process_id
        super().__init__(failure_code)


def run_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    popen: Callable[..., Any] = subprocess.Popen,
    readiness_probe: Callable[[RuntimeProcess], Mapping[str, Any] | None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    port_allocator: Callable[[], int] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "platform_test_profile_startup_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    allocate = port_allocator or _free_port
    try:
        configured = _startup_environment(env, allocate)
        migration = run_platform_test_migration_readiness(configured)
        manifest = build_platform_runtime_manifest(
            "test", environ=configured, python_executable=sys.executable
        )
        child_environment = build_runtime_process_environment(
            manifest, environ=configured
        )
        probe = readiness_probe or _http_readiness_probe
        api_results = []
        background_results = []
        for process in manifest.processes:
            if process.kind == "api":
                api_results.append(
                    _start_api(
                        process,
                        environment=child_environment,
                        popen=popen,
                        readiness_probe=probe,
                        sleeper=sleeper,
                        clock=clock,
                    )
                )
            elif process.kind in {"worker", "daemon"}:
                background_results.append(
                    _start_background(
                        process,
                        environment=child_environment,
                        popen=popen,
                        sleeper=sleeper,
                        clock=clock,
                    )
                )
    except PlatformMigrationReadinessError as exc:
        return _failure(exc.failure_code, exc.service_id)
    except PlatformTestProfileStartupError as exc:
        return _failure(exc.failure_code, exc.process_id)
    except Exception as exc:
        return _failure("test_profile_startup_failed", exc.__class__.__name__)

    return {
        "schema_version": "platform_test_profile_startup_smoke.v1",
        "status": "PASS",
        "profile": "test",
        "migration_count": sum(
            item.migration_count for item in migration.services
        ),
        "api_count": len(api_results),
        "background_count": len(background_results),
        "ready_process_count": len(api_results) + len(background_results),
        "work_claiming_enabled": False,
        "remote_provider_required": False,
        "slice": "1327",
        "requirement": "S133",
        "next_slice": "1328",
    }


def _startup_environment(
    environ: Mapping[str, str],
    port_allocator: Callable[[], int],
) -> dict[str, str]:
    env = dict(environ)
    env["NEX_PROFILE"] = "test"
    for environment_name, _ in SERVICE_ENDPOINTS.values():
        env[environment_name] = f"http://127.0.0.1:{port_allocator()}"
    env["NEX_AE_WEB_BASE_URL"] = f"http://127.0.0.1:{port_allocator()}"
    for name in SIGNED_TRUST_ENV_NAMES:
        env.setdefault(name, "s133-startup-evidence-not-for-route-use")
    return env


def _start_api(
    process: RuntimeProcess,
    *,
    environment: Mapping[str, str],
    popen: Callable[..., Any],
    readiness_probe: Callable[[RuntimeProcess], Mapping[str, Any] | None],
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, str]:
    handle = _spawn(process, environment=environment, popen=popen)
    try:
        deadline = clock() + API_READY_TIMEOUT_SECONDS
        while clock() < deadline:
            if handle.poll() is not None:
                raise PlatformTestProfileStartupError(
                    "api_exited_before_ready", process.process_id
                )
            payload = readiness_probe(process)
            if payload is not None:
                if (
                    payload.get("service_id") != process.owner
                    or payload.get("readiness_status") != "READY"
                ):
                    raise PlatformTestProfileStartupError(
                        "api_readiness_invalid", process.process_id
                    )
                return {"process_id": process.process_id, "state": "READY"}
            sleeper(0.1)
        raise PlatformTestProfileStartupError(
            "api_readiness_timeout", process.process_id
        )
    finally:
        _stop_process(handle)


def _start_background(
    process: RuntimeProcess,
    *,
    environment: Mapping[str, str],
    popen: Callable[..., Any],
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, str]:
    handle = _spawn(process, environment=environment, popen=popen)
    try:
        deadline = clock() + BACKGROUND_STABILITY_SECONDS
        while clock() < deadline:
            if handle.poll() is not None:
                raise PlatformTestProfileStartupError(
                    "background_exited_before_ready", process.process_id
                )
            sleeper(0.05)
        return {"process_id": process.process_id, "state": "READY"}
    finally:
        _stop_process(handle)


def _spawn(
    process: RuntimeProcess,
    *,
    environment: Mapping[str, str],
    popen: Callable[..., Any],
) -> Any:
    try:
        return popen(
            process.command,
            cwd=ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise PlatformTestProfileStartupError(
            "process_launch_failed", process.process_id
        ) from exc


def _stop_process(handle: Any) -> None:
    if handle.poll() is not None:
        return
    handle.terminate()
    try:
        handle.wait(timeout=10.0)
    except (subprocess.TimeoutExpired, TimeoutError):
        handle.kill()
        handle.wait(timeout=None)


def _http_readiness_probe(process: RuntimeProcess) -> Mapping[str, Any] | None:
    if process.host is None or process.port is None:
        return None
    try:
        with urlopen(
            f"http://{process.host}:{process.port}/ready",
            timeout=1.0,
        ) as response:
            if int(getattr(response, "status", 0)) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, Mapping) else None
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _failure(failure_code: str, process_id: str | None) -> dict[str, Any]:
    return {
        "schema_version": "platform_test_profile_startup_smoke.v1",
        "status": "FAIL",
        "failure_code": failure_code,
        "process_id": process_id,
    }


def summary_line(report: Mapping[str, Any]) -> str:
    if report.get("status") == "SKIPPED":
        return "platform_test_profile_startup=skip"
    if report.get("status") != "PASS":
        return (
            "platform_test_profile_startup=fail "
            f"process={report.get('process_id') or 'none'} "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_test_profile_startup=pass "
        f"apis={report.get('api_count')} "
        f"background={report.get('background_count')} "
        f"ready={report.get('ready_process_count')} next={report.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = run_smoke()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
