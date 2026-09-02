#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s52_ae_scheduler_daemon_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0513_ae_artifact_retention_scheduler_lease.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "scripts/smoke/run_s52_ae_scheduler_daemon_closure.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_boundary_audit.py",
    "tests/test_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "tests/test_nex_ae_artifact_retention_scheduler.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_s52_ae_scheduler_daemon_closure.py",
    "docs/README.md",
    "docs/slices/0511_ae_scheduler_daemon_boundary_audit_refactoring_checkpoint.md",
    "docs/slices/0512_ae_scheduler_lease_lock_contract_foundation.md",
    "docs/slices/0513_ae_scheduler_lease_repository_adapter.md",
    "docs/slices/0514_ae_scheduler_tick_once_runtime_wiring.md",
    "docs/slices/0515_ae_scheduler_tick_once_postgresql_smoke.md",
    "docs/slices/0516_ae_scheduler_daemon_config_control_contract.md",
    "docs/slices/0517_ae_scheduler_daemon_dispatch_facade.md",
    "docs/slices/0518_ae_scheduler_daemon_service_api_wiring.md",
    "docs/slices/0519_ae_scheduler_daemon_postgresql_smoke.md",
    "docs/slices/0520_s52_ae_scheduler_daemon_closure.md",
)

TOKEN_CHECKS = (
    (
        "s52_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s52_ae_scheduler_daemon_closure.py",
    ),
    (
        "daemon_boundary_audit_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_boundary_audit.py",
    ),
    (
        "tick_once_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py",
    ),
    (
        "daemon_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
    ),
    (
        "lease_request_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION",
    ),
    (
        "lease_sqlalchemy_store",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "SqlAlchemyArtifactRetentionSchedulerLeaseStore",
    ),
    (
        "lease_table_sql_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "artifact_retention_scheduler_lease_table_sql",
    ),
    (
        "lease_migration_table",
        "database/nex-ae-api/migrations/0513_ae_artifact_retention_scheduler_lease.sql",
        "ae_artifact_retention_scheduler_leases",
    ),
    (
        "tick_once_runner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "run_artifact_retention_scheduler_tick_once",
    ),
    (
        "daemon_config_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONFIG_SCHEMA_VERSION",
    ),
    (
        "daemon_control_plan_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_PLAN_SCHEMA_VERSION",
    ),
    (
        "daemon_dispatch_result_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION",
    ),
    (
        "daemon_config_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_config",
    ),
    (
        "daemon_control_plan_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_control_plan",
    ),
    (
        "daemon_dispatch_facade",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "dispatch_artifact_retention_scheduler_daemon_control",
    ),
    (
        "manual_tick_once_action",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_MANUAL_TICK_ONCE",
    ),
    (
        "start_daemon_action",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "ARTIFACT_RETENTION_SCHEDULER_DAEMON_CONTROL_ACTION_START_DAEMON",
    ),
    (
        "daemon_start_block_reason",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "daemon_disabled_by_policy",
    ),
    (
        "daemon_auto_start_guard",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"daemon_auto_start_allowed": False',
    ),
    (
        "scheduler_daemon_started_false",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"scheduler_daemon_started": False',
    ),
    (
        "continuous_loop_started_false",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"continuous_loop_started": False',
    ),
    (
        "physical_delete_automation_disabled",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "daemon_config_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-config"',
    ),
    (
        "daemon_controls_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-controls"',
    ),
    (
        "daemon_route_lease_store_injection",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "retention_scheduler_lease_store",
    ),
    (
        "daemon_route_default_lease_store",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_default_artifact_retention_scheduler_lease_store",
    ),
    (
        "daemon_route_run_worker_guard",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        'run_worker=payload.get("run_worker") is True',
    ),
    (
        "daemon_smoke_env_guard",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "daemon_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "live_db",
    ),
    (
        "daemon_smoke_controls_route",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "/api/v1/artifact-retention/scheduler-daemon-controls",
    ),
    (
        "daemon_smoke_lease_readback",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "_scheduler_once_lease_observation",
    ),
    (
        "daemon_smoke_job_readback",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "_job_observation",
    ),
    (
        "daemon_smoke_history_readback",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "history_rows",
    ),
    (
        "daemon_smoke_cleanup_lease",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "cleanup_leases",
    ),
    (
        "tick_once_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py",
        "live_db",
    ),
    (
        "tick_once_smoke_sqlalchemy_queue",
        "scripts/smoke/run_ae_artifact_retention_scheduler_tick_once_postgres_smoke.py",
        "SqlAlchemyJobQueue",
    ),
    (
        "s52_slice_index",
        "docs/README.md",
        "Slice 0520",
    ),
    (
        "s52_ae_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0520 closes S52",
    ),
    (
        "s52_ag_readme_boundary_note",
        "services/nex-ag/README.md",
        "Slice 0519 proves that boundary against PostgreSQL",
    ),
)


def run_s52_ae_scheduler_daemon_closure(root: Path = ROOT) -> dict[str, Any]:
    missing_files = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not (root / relative_path).is_file()
    ]
    token_results = [
        {
            "check_id": check_id,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for check_id, relative_path, token in TOKEN_CHECKS
    ]
    checks = {
        "required_files_present": not missing_files,
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "closure_checks_failed",
        "slice_range": "0511-0520",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "daemon_boundary_audit": True,
            "lease_lock_contract_foundation": True,
            "lease_repository_adapter": True,
            "manual_tick_once_runtime": True,
            "tick_once_postgresql_smoke": True,
            "daemon_config_control_contract": True,
            "daemon_dispatch_facade": True,
            "daemon_service_api_wiring": True,
            "daemon_postgresql_smoke": True,
            "closure_checkpoint": True,
        },
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "scheduler_daemon_default_disabled": True,
            "continuous_loop_deferred": True,
            "manual_once_runner": True,
            "lease_required_before_tick": True,
            "sqlalchemy_lease_store_backed": True,
            "common_job_backed": True,
            "route_control_ae_owned": True,
            "ag_projection_read_only": True,
            "protected_postgres_smoke_envs_required": True,
            "real_test_db_smoke_evidence_referenced": True,
            "physical_delete_automation_disabled": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s52_ae_scheduler_daemon_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s52_ae_scheduler_daemon_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S52 AE scheduler daemon closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s52_ae_scheduler_daemon_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (511, "ae_scheduler_daemon_boundary_audit_refactoring_checkpoint"),
            (512, "ae_scheduler_lease_lock_contract_foundation"),
            (513, "ae_scheduler_lease_repository_adapter"),
            (514, "ae_scheduler_tick_once_runtime_wiring"),
            (515, "ae_scheduler_tick_once_postgresql_smoke"),
            (516, "ae_scheduler_daemon_config_control_contract"),
            (517, "ae_scheduler_daemon_dispatch_facade"),
            (518, "ae_scheduler_daemon_service_api_wiring"),
            (519, "ae_scheduler_daemon_postgresql_smoke"),
            (520, "s52_ae_scheduler_daemon_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
