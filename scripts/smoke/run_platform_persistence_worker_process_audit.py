#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_persistence_worker_process_audit.v1"
SERVICES = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")
SERVICE_PACKAGES = {
    "nex-oa": "nex_oa",
    "nex-ag": "nex_ag",
    "nex-ae-api": "nex_ae_api",
    "nex-cx": "nex_cx",
    "nex-mo": "nex_mo",
}
WORKER_RUNTIME_PATHS = (
    "services/nex-ae-api/nex_ae_api/async_artifact_render_worker.py",
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ag/nex_ag/remediation_execution_status_sync_worker.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_daemon.py",
    "services/nex-cx/nex_cx/async_generation_worker.py",
    "services/nex-cx/nex_cx/ingestion_worker.py",
    "services/nex-cx/nex_cx/remediation_execution_worker.py",
)


def run_platform_persistence_worker_process_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    migration_counts = {
        service_id: len(
            tuple((root / "database" / service_id / "migrations").glob("*.sql"))
        )
        for service_id in SERVICES
    }
    main_sources = {
        service_id: _read_text(
            root
            / "services"
            / service_id
            / SERVICE_PACKAGES[service_id]
            / "main.py"
        )
        for service_id in SERVICES
    }
    migration_runner = _read_text(root / "scripts/db/run_migrations.py")
    persistence_runtime = _read_text(
        root / "services/_shared/nex_runtime/persistence.py"
    )
    database_runtime = _read_text(root / "services/_shared/nex_runtime/database.py")
    all_services_runner = _read_text(root / "scripts/dev/run_all_services.py")
    ae_web_server = root / "apps/nex-ae-web/scripts/serve.mjs"
    daemon_wrapper = root / "scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py"
    present_worker_runtimes = [
        path for path in WORKER_RUNTIME_PATHS if (root / path).is_file()
    ]
    executable_worker_runtimes = [
        path
        for path in present_worker_runtimes
        if "def main(" in _read_text(root / path)
        or "if __name__" in _read_text(root / path)
    ]

    checks = {
        "all_services_attach_persistence_runtime": all(
            "attach_service_persistence_runtime" in source
            and "SERVICE_PERSISTENCE" in source
            for source in main_sources.values()
        ),
        "all_services_expose_local_job_control": all(
            "register_service_job_control_routes" in source
            and "job_queue=SERVICE_PERSISTENCE.job_queue" in source
            for source in main_sources.values()
        ),
        "all_services_own_sql_migrations": all(
            count > 0 for count in migration_counts.values()
        ),
        "migration_runner_supports_all_test_profile": all(
            token in migration_runner
            for token in (
                '"test": TEST_DATABASE_ENVS',
                'group.add_argument("--all"',
                "for service_id in selected_services(args)",
            )
        ),
        "postgres_runtime_separates_api_and_worker_pools": all(
            token in persistence_runtime
            for token in (
                'workload="api"',
                'workload="worker"',
                "api_session_factory",
                "worker_session_factory",
            )
        )
        and 'DATABASE_WORKLOADS = ("api", "worker")' in database_runtime,
        "backend_runner_lists_all_api_services": all(
            f'"{service_id}"' in all_services_runner for service_id in SERVICES
        ),
        "worker_and_daemon_runtime_modules_are_present": (
            len(present_worker_runtimes) == len(WORKER_RUNTIME_PATHS)
        ),
        "ae_web_has_standalone_server": ae_web_server.is_file(),
        "ae_daemon_has_executable_wrapper": daemon_wrapper.is_file(),
    }
    issues = [name for name, passed in checks.items() if not passed]
    process_gaps = {
        "migration_before_start": "run_migrations.py" not in all_services_runner,
        "readiness_wait": all(
            token not in all_services_runner
            for token in ("/ready", "readiness", "healthcheck")
        ),
        "ae_web_process": "nex-ae-web" not in all_services_runner,
        "worker_or_daemon_process": all(
            token not in all_services_runner for token in ("worker", "daemon")
        ),
        "automatic_restart_policy": all(
            token not in all_services_runner for token in ("restart", "backoff")
        ),
    }
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1309",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None
        if not issues
        else "platform_persistence_worker_process_audit_failed",
        "checks": checks,
        "issues": issues,
        "findings": {
            "service_count": len(SERVICES),
            "migration_counts": migration_counts,
            "migration_total": sum(migration_counts.values()),
            "worker_runtime_module_count": len(present_worker_runtimes),
            "executable_worker_runtime_count": len(executable_worker_runtimes),
            "backend_api_process_count": len(SERVICES),
            "integrated_ae_web_process_count": 0
            if process_gaps["ae_web_process"]
            else 1,
            "integrated_worker_daemon_process_count": 0
            if process_gaps["worker_or_daemon_process"]
            else len(present_worker_runtimes),
            "process_orchestration_gaps": process_gaps,
            "platform_restart_smoke_present": False,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "platform-runtime",
                "gap": "publish one typed process manifest covering five APIs, AE Web, workers, and daemons",
                "target_requirement": "S132",
            },
            {
                "priority": "P0",
                "owner": "platform-runtime/database",
                "gap": "orchestrate test migrations, readiness waits, ordered shutdown, restart, and durable reload evidence",
                "target_requirement": "S133",
            },
            {
                "priority": "P1",
                "owner": "service-workers",
                "gap": "add canonical executable entrypoints for worker modules that currently expose callable runners only",
                "target_requirement": "S132/S133",
            },
        ],
        "decision": {
            "service_local_databases_remain_canonical": True,
            "api_and_worker_database_pools_remain_separate": True,
            "existing_individual_restart_smokes_are_retained": True,
            "current_run_all_services_is_release_orchestration": False,
            "database_or_provider_mutation_performed": False,
            "next_slice": "1310",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_persistence_worker_process=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    gaps = findings.get("process_orchestration_gaps") or {}
    return (
        "platform_persistence_worker_process=pass "
        f"services={findings.get('service_count', 0)} "
        f"migrations={findings.get('migration_total', 0)} "
        f"worker_runtimes={findings.get('worker_runtime_module_count', 0)} "
        f"process_gaps={sum(bool(value) for value in gaps.values())} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_persistence_worker_process_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
