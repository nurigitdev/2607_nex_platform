#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from nex_runtime.postgres_orchestration import (  # noqa: E402
    POSTGRES_SERVICE_ORDER,
    build_platform_postgres_restart_evidence,
    build_postgres_phase_evidence,
)
from nex_runtime.postgres_pool_lifecycle import (  # noqa: E402
    PlatformPostgresPoolLifecycle,
)
from nex_runtime.postgres_restart_coordinator import (  # noqa: E402
    PlatformPostgresRestartCoordinator,
    PostgresRestartCoordinatorError,
)
from nex_runtime.postgres_restoration import (  # noqa: E402
    PlatformPostgresRestorationStore,
    PostgresRestorationError,
)
from nex_runtime.process_manifest import build_platform_runtime_manifest  # noqa: E402
from nex_runtime.runtime_orchestrator import (  # noqa: E402
    RuntimeOrchestrator,
    SubprocessRuntimeLauncher,
)
from nex_runtime.runtime_profiles import SIGNED_TRUST_ENV_NAMES  # noqa: E402
from nex_runtime.service_endpoints import SERVICE_ENDPOINTS  # noqa: E402
from platform_test_migrations import (  # noqa: E402
    PlatformMigrationReadinessError,
    run_platform_test_migration_readiness,
)


SMOKE_ENV = "NEX_PLATFORM_POSTGRES_RESTART_SMOKE"
EXPECTED_PROCESS_COUNT = 13


def run_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    port_allocator=None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "platform_postgres_restart_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    allocate = port_allocator or _free_port
    run_id = f"s133-{uuid4().hex}"
    coordinator: PlatformPostgresRestartCoordinator | None = None
    store: PlatformPostgresRestorationStore | None = None
    migrations = []
    runtimes: list[RuntimeOrchestrator] = []
    written = False
    cleaned = False
    stopped = False
    failure_code: str | None = None
    failure_service: str | None = None
    try:
        configured = _restart_environment(env, allocate)

        def migration_gate():
            result = run_platform_test_migration_readiness(configured)
            migrations.append(result)
            return result

        def pool_factory():
            return PlatformPostgresPoolLifecycle.build(configured)

        def runtime_factory():
            manifest = build_platform_runtime_manifest(
                "test", environ=configured, python_executable=sys.executable
            )
            runtime = RuntimeOrchestrator(
                manifest,
                launcher=SubprocessRuntimeLauncher(ROOT),
                environ=configured,
            )
            runtimes.append(runtime)
            return runtime

        coordinator = PlatformPostgresRestartCoordinator(
            migration_gate=migration_gate,
            pool_factory=pool_factory,
            runtime_factory=runtime_factory,
        )
        store = PlatformPostgresRestorationStore.build(configured)

        first = coordinator.start()
        _require_ready_runtime(runtimes[-1], generation=1)
        store.write(run_id)
        written = True
        coordinator.check_running()

        second = coordinator.restart()
        _require_ready_runtime(runtimes[-1], generation=2)
        restored = store.restore(run_id)
        coordinator.check_running()

        final = coordinator.stop()
        stopped = True
        cleaned_result = store.cleanup(run_id)
        cleaned = True
        absence = store.confirm_absence(run_id)
        evidence = _build_success_evidence()
    except (
        PlatformMigrationReadinessError,
        PostgresRestartCoordinatorError,
        PostgresRestorationError,
    ) as exc:
        failure_code = exc.failure_code
        failure_service = getattr(exc, "service_id", None)
    except Exception as exc:
        failure_code = "platform_postgres_restart_failed"
        failure_service = exc.__class__.__name__
    finally:
        if coordinator is not None and not stopped:
            try:
                if coordinator.public_status()["state"] == "RUNNING":
                    coordinator.stop()
            except PostgresRestartCoordinatorError:
                pass
        if store is not None and written and not cleaned:
            try:
                store.cleanup(run_id)
                store.confirm_absence(run_id)
            except PostgresRestorationError:
                pass

    if failure_code is not None:
        return _failure(failure_code, failure_service)

    migration_count = sum(item.migration_count for item in migrations[-1].services)
    return {
        "schema_version": "platform_postgres_restart_smoke.v1",
        "status": "PASS",
        "profile": "test",
        "service_count": restored.service_count,
        "process_count": EXPECTED_PROCESS_COUNT,
        "process_generation_count": len(runtimes),
        "pool_count_per_generation": first["active_engine_count"],
        "fresh_pool_count": second["fresh_engine_count"],
        "migration_gate_count": second["migration_gate_count"],
        "migration_count_per_generation": migration_count,
        "restart_count": final["restart_count"],
        "restored_count": restored.record_count,
        "cleaned_count": cleaned_result.record_count,
        "absence_count": absence.record_count,
        "shutdown_order": final["last_shutdown_order"],
        "evidence_record_count": evidence.to_public_projection()["record_count"],
        "work_claiming_enabled": False,
        "remote_provider_required": False,
        "slice": "1330",
        "requirement": "S133",
        "next_slice": "1331",
    }


def _restart_environment(environ: Mapping[str, str], port_allocator) -> dict[str, str]:
    env = dict(environ)
    env["NEX_PROFILE"] = "test"
    for environment_name, _ in SERVICE_ENDPOINTS.values():
        env[environment_name] = f"http://127.0.0.1:{port_allocator()}"
    env["NEX_AE_WEB_BASE_URL"] = f"http://127.0.0.1:{port_allocator()}"
    for name in SIGNED_TRUST_ENV_NAMES:
        env.setdefault(name, "s133-restart-evidence-not-for-route-use")
    return env


def _require_ready_runtime(runtime: RuntimeOrchestrator, *, generation: int) -> None:
    status = runtime.public_status()
    if (
        status.get("state") != "RUNNING"
        or status.get("process_counts", {}).get("READY") != EXPECTED_PROCESS_COUNT
    ):
        raise ValueError(f"runtime_generation_{generation}_not_ready")


def _build_success_evidence():
    records = []
    phase_codes = (
        ("CONFIGURATION", 0, "test_database_targets_valid"),
        ("MIGRATION", 0, "migration_heads_current"),
        ("POOL_READINESS", 0, "generation_1_pools_ready"),
        ("STARTUP", 0, "generation_1_processes_ready"),
        ("SHUTDOWN", 0, "generation_1_processes_stopped"),
        ("MIGRATION", 1, "restart_migration_heads_current"),
        ("POOL_READINESS", 1, "generation_2_fresh_pools_ready"),
        ("STARTUP", 1, "generation_2_processes_ready"),
        ("RESTART", 1, "fresh_runtime_restart_completed"),
        ("RESTORATION", 1, "durable_sentinel_restored"),
        ("SHUTDOWN", 1, "generation_2_processes_stopped"),
        ("CLEANUP", 1, "durable_sentinel_cleanup_confirmed"),
    )
    for service_id in POSTGRES_SERVICE_ORDER:
        for phase, iteration, code in phase_codes:
            records.append(
                build_postgres_phase_evidence(
                    service_id=service_id,
                    phase=phase,
                    status="PASSED",
                    restart_iteration=iteration,
                    evidence_codes=(code,),
                )
            )
    return build_platform_postgres_restart_evidence(
        run_id="s133-protected-restart-smoke",
        state="PASSED",
        records=records,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _failure(failure_code: str, service_id: str | None) -> dict[str, Any]:
    return {
        "schema_version": "platform_postgres_restart_smoke.v1",
        "status": "FAIL",
        "failure_code": failure_code,
        "service_id": service_id,
    }


def summary_line(report: Mapping[str, Any]) -> str:
    status = report.get("status")
    if status == "SKIPPED":
        return "platform_postgres_restart=skip"
    if status != "PASS":
        return (
            "platform_postgres_restart=fail "
            f"service={report.get('service_id') or 'none'} "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_postgres_restart=pass "
        f"services={report.get('service_count')} "
        f"processes={report.get('process_count')}x{report.get('process_generation_count')} "
        f"pools={report.get('pool_count_per_generation')}+{report.get('fresh_pool_count')} "
        f"restored={report.get('restored_count')} "
        f"next={report.get('next_slice')}"
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
