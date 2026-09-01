#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s51_ae_artifact_retention_automation_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_automation_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
    "scripts/smoke/run_ae_artifact_retention_physical_purge_postgres_smoke.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "scripts/smoke/run_s51_ae_artifact_retention_automation_closure.py",
    "tests/test_ae_artifact_retention_automation_boundary_audit.py",
    "tests/test_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
    "tests/test_ae_artifact_retention_physical_purge_postgres_smoke.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s51_ae_artifact_retention_automation_closure.py",
    "docs/README.md",
    "docs/slices/0501_ae_artifact_retention_automation_boundary_audit.md",
    "docs/slices/0502_ae_retention_scheduler_runtime_config_expansion.md",
    "docs/slices/0503_ae_retention_scheduler_tick_planner_foundation.md",
    "docs/slices/0504_ae_retention_scheduler_tick_jobqueue_admission.md",
    "docs/slices/0505_ae_artifact_retention_scheduler_tick_postgresql_smoke.md",
    "docs/slices/0506_ae_artifact_retention_execute_mode_safety_hardening.md",
    "docs/slices/0507_ae_artifact_retention_physical_purge_adapter.md",
    "docs/slices/0508_ae_artifact_retention_physical_purge_postgresql_smoke.md",
    "docs/slices/0509_ag_artifact_retention_automation_operations_projection.md",
    "docs/slices/0510_s51_ae_artifact_retention_automation_closure.md",
)

TOKEN_CHECKS = (
    (
        "s51_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s51_ae_artifact_retention_automation_closure.py",
    ),
    (
        "s51_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_automation_boundary_audit.py",
    ),
    (
        "scheduler_tick_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
    ),
    (
        "physical_purge_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_physical_purge_postgres_smoke.py",
    ),
    (
        "ag_automation_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_artifact_retention_automation_operations_smoke.py",
    ),
    (
        "scheduler_config_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_scheduler_config",
    ),
    (
        "scheduler_tick_plan_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION",
    ),
    (
        "scheduler_tick_enqueue_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ENQUEUE_RESULT_SCHEMA_VERSION",
    ),
    (
        "scheduler_tick_planner",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_scheduler_tick_plan",
    ),
    (
        "scheduler_tick_jobqueue_admission",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "enqueue_artifact_retention_scheduler_tick_job",
    ),
    (
        "scheduler_tick_default_interval",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ARTIFACT_RETENTION_SCHEDULER_TICK_INTERVAL_SECONDS = 900",
    ),
    (
        "scheduler_tick_default_jitter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ARTIFACT_RETENTION_SCHEDULER_TICK_JITTER_SECONDS = 60",
    ),
    (
        "scheduler_tick_window_enforced",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"scheduler_tick_batch_window_enforced": True',
    ),
    (
        "scheduler_tick_trigger_type",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"trigger_type": "scheduler_tick"',
    ),
    (
        "operator_approval_schema",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_OPERATOR_APPROVAL_SCHEMA_VERSION",
    ),
    (
        "operator_approval_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_operator_approval",
    ),
    (
        "operator_approval_required_reason",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        'ARTIFACT_RETENTION_OPERATOR_APPROVAL_REQUIRED_REASON = "operator_approval_required"',
    ),
    (
        "execute_requires_operator_approval",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"execute_requires_operator_approval": True',
    ),
    (
        "execute_requires_storage_guard",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"execute_requires_storage_mutation_enabled": True',
    ),
    (
        "execute_requires_database_guard",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"execute_requires_database_row_delete_enabled": True',
    ),
    (
        "physical_delete_automation_disabled",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "physical_purge_adapter",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "delete_artifact_retention_physical_records",
    ),
    (
        "ae_ag_direct_database_write_disallowed",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ae_ag_direct_job_enqueue_disallowed",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "ag_automation_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_automation_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_automation_projection",
    ),
    (
        "ag_automation_summary_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_automation_operations",
    ),
    (
        "ag_automation_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/automation"',
    ),
    (
        "ag_automation_direct_database_write_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_automation_direct_job_enqueue_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "ag_automation_physical_delete_disabled",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "scheduler_tick_smoke_env_guard",
        "scripts/smoke/run_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE",
    ),
    (
        "scheduler_tick_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
        "live_db",
    ),
    (
        "scheduler_tick_smoke_sqlalchemy_queue",
        "scripts/smoke/run_ae_artifact_retention_scheduler_tick_postgres_smoke.py",
        "SqlAlchemyJobQueue",
    ),
    (
        "physical_purge_smoke_env_guard",
        "scripts/smoke/run_ae_artifact_retention_physical_purge_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE",
    ),
    (
        "physical_purge_smoke_approval_block",
        "scripts/smoke/run_ae_artifact_retention_physical_purge_postgres_smoke.py",
        "operator_approval_required",
    ),
    (
        "physical_purge_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_physical_purge_postgres_smoke.py",
        "live_db",
    ),
    (
        "ae_ag_smoke_env_guard",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE",
    ),
    (
        "ae_ag_smoke_ag_automation",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        '"ag_automation"',
    ),
    (
        "ae_ag_smoke_automation_summary",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "automation=",
    ),
    (
        "s51_slice_index",
        "docs/README.md",
        "Slice 0510",
    ),
    (
        "s51_ae_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0510 closes S51",
    ),
    (
        "s51_ag_readme_closure_note",
        "services/nex-ag/README.md",
        "Slice 0510 closes S51",
    ),
)


def run_s51_ae_artifact_retention_automation_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
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
        "slice_range": "0501-0510",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "automation_boundary_audit": True,
            "scheduler_runtime_config_expansion": True,
            "scheduler_tick_planner": True,
            "scheduler_tick_jobqueue_admission": True,
            "scheduler_tick_postgresql_smoke": True,
            "execute_mode_operator_approval": True,
            "physical_purge_adapter": True,
            "physical_purge_postgresql_smoke": True,
            "ag_automation_operations_projection": True,
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
            "raw_download_content_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "scheduler_daemon_default_disabled": True,
            "first_automation_path_dry_run_tick_admission": True,
            "physical_delete_automation_disabled": True,
            "execute_requires_operator_approval": True,
            "delete_storage_database_guards_required": True,
            "common_job_backed": True,
            "sqlalchemy_queue_backed": True,
            "ae_system_of_record": True,
            "ag_projection_read_only": True,
            "ag_dispatch_api_mediated": True,
            "protected_postgres_smoke_envs_required": True,
            "real_test_db_smoke_evidence_referenced": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s51_ae_artifact_retention_automation_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s51_ae_artifact_retention_automation_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S51 AE artifact retention automation closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s51_ae_artifact_retention_automation_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (501, "ae_artifact_retention_automation_boundary_audit"),
            (502, "ae_retention_scheduler_runtime_config_expansion"),
            (503, "ae_retention_scheduler_tick_planner_foundation"),
            (504, "ae_retention_scheduler_tick_jobqueue_admission"),
            (505, "ae_artifact_retention_scheduler_tick_postgresql_smoke"),
            (506, "ae_artifact_retention_execute_mode_safety_hardening"),
            (507, "ae_artifact_retention_physical_purge_adapter"),
            (508, "ae_artifact_retention_physical_purge_postgresql_smoke"),
            (509, "ag_artifact_retention_automation_operations_projection"),
            (510, "s51_ae_artifact_retention_automation_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
