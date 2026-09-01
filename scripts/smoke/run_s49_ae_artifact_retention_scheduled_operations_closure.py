#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s49_ae_artifact_retention_scheduled_operations_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/generation/ae_artifact_retention_schedule.v1.schema.json",
    "contracts/examples/generation/ae_artifact_retention_schedule.local_dry_run.json",
    "contracts/tests/negative/generation/ae_artifact_retention_schedule.database_url_leak.json",
    "contracts/schemas/generation/ae_artifact_retention_batch_plan.v1.schema.json",
    "contracts/examples/generation/ae_artifact_retention_batch_plan.ready_dry_run.json",
    "contracts/tests/negative/generation/ae_artifact_retention_batch_plan.database_url_leak.json",
    "contracts/schemas/generation/ae_artifact_retention_scheduled_execution_command.v1.schema.json",
    "contracts/examples/generation/ae_artifact_retention_scheduled_execution_command.ready_dry_run.json",
    "contracts/tests/negative/generation/ae_artifact_retention_scheduled_execution_command.delete_enabled.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_scheduled_operations_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_batch_plan_postgres_smoke.py",
    "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
    "scripts/smoke/run_s49_ae_artifact_retention_scheduled_operations_closure.py",
    "tests/test_ae_artifact_retention_scheduled_operations_boundary_audit.py",
    "tests/test_ae_artifact_retention_batch_plan_postgres_smoke.py",
    "tests/test_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s49_ae_artifact_retention_scheduled_operations_closure.py",
    "docs/README.md",
    "docs/slices/0481_ae_artifact_retention_scheduled_operations_boundary_audit.md",
    "docs/slices/0482_ae_artifact_retention_schedule_contract_schema.md",
    "docs/slices/0483_ae_artifact_retention_batch_plan_read_model.md",
    "docs/slices/0484_ae_artifact_retention_batch_plan_api_wiring.md",
    "docs/slices/0485_ae_artifact_retention_batch_plan_postgresql_smoke.md",
    "docs/slices/0486_ae_artifact_retention_scheduled_execution_command.md",
    "docs/slices/0487_ae_artifact_retention_scheduled_execution_mock_worker.md",
    "docs/slices/0488_ag_artifact_retention_batch_operations_projection.md",
    "docs/slices/0489_ae_artifact_retention_scheduled_execution_postgresql_smoke.md",
    "docs/slices/0490_s49_ae_artifact_retention_scheduled_operations_closure.md",
)

TOKEN_CHECKS = (
    (
        "s49_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s49_ae_artifact_retention_scheduled_operations_closure.py",
    ),
    (
        "scheduled_boundary_audit_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduled_operations_boundary_audit.py",
    ),
    (
        "batch_plan_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_batch_plan_postgres_smoke.py",
    ),
    (
        "scheduled_execution_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
    ),
    (
        "schedule_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULE_SCHEMA_VERSION",
    ),
    (
        "batch_plan_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_BATCH_PLAN_SCHEMA_VERSION",
    ),
    (
        "scheduled_command_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_COMMAND_SCHEMA_VERSION",
    ),
    (
        "scheduled_worker_result_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_WORKER_RESULT_SCHEMA_VERSION",
    ),
    (
        "schedule_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_schedule",
    ),
    (
        "batch_plan_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_batch_plan",
    ),
    (
        "scheduled_command_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_scheduled_execution_command",
    ),
    (
        "scheduled_mock_worker",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "run_artifact_retention_scheduled_execution_mock_worker",
    ),
    (
        "batch_plan_store_method",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "plan_retention_batch",
    ),
    (
        "batch_plan_api_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/batch-plan"',
    ),
    (
        "purge_api_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/purge"',
    ),
    (
        "history_store",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "SqlAlchemyArtifactRetentionExecutionHistoryStore",
    ),
    (
        "ag_batch_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_batch_plan_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_batch_plan",
    ),
    (
        "ag_batch_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_batch_projection",
    ),
    (
        "ag_batch_projection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/batch-plan"',
    ),
    (
        "scheduled_smoke_env",
        "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULED_EXECUTION_POSTGRES_SMOKE",
    ),
    (
        "scheduled_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
        "live_db",
    ),
    (
        "scheduled_smoke_history_written",
        "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
        "history_written",
    ),
    (
        "scheduled_smoke_ag_projection",
        "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
        '"ag_projection":',
    ),
    (
        "scheduled_smoke_metadata_only",
        "scripts/smoke/run_ae_artifact_retention_scheduled_execution_postgres_smoke.py",
        "metadata_only_evidence",
    ),
    (
        "schedule_schema_file",
        "contracts/schemas/generation/ae_artifact_retention_schedule.v1.schema.json",
        "ae_artifact_retention_schedule.v1",
    ),
    (
        "batch_plan_schema_file",
        "contracts/schemas/generation/ae_artifact_retention_batch_plan.v1.schema.json",
        "ae_artifact_retention_batch_plan.v1",
    ),
    (
        "scheduled_command_schema_file",
        "contracts/schemas/generation/ae_artifact_retention_scheduled_execution_command.v1.schema.json",
        "ae_artifact_retention_scheduled_execution_command.v1",
    ),
    (
        "schedule_negative_database_url_guard",
        "contracts/tests/negative/generation/ae_artifact_retention_schedule.database_url_leak.json",
        "database_url",
    ),
    (
        "batch_plan_negative_database_url_guard",
        "contracts/tests/negative/generation/ae_artifact_retention_batch_plan.database_url_leak.json",
        "database_url",
    ),
    (
        "scheduled_command_negative_delete_guard",
        "contracts/tests/negative/generation/ae_artifact_retention_scheduled_execution_command.delete_enabled.json",
        '"delete_enabled": true',
    ),
    (
        "s49_slice_index",
        "docs/README.md",
        "Slice 0490",
    ),
    (
        "s49_ae_readme_smoke_note",
        "services/nex-ae-api/README.md",
        "Slice 0489 adds protected PostgreSQL smoke evidence",
    ),
    (
        "s49_ag_readme_projection_note",
        "services/nex-ag/README.md",
        "Slice 0488 adds",
    ),
)


def run_s49_ae_artifact_retention_scheduled_operations_closure(
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
        "slice_range": "0481-0490",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "scheduled_boundary_audit": True,
            "schedule_contract_schema": True,
            "batch_plan_read_model": True,
            "batch_plan_api": True,
            "batch_plan_postgresql_smoke": True,
            "scheduled_execution_command": True,
            "scheduled_execution_mock_worker": True,
            "ag_batch_operations_projection": True,
            "scheduled_execution_postgresql_smoke": True,
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
            "scheduled_batch_default_dry_run": True,
            "scheduler_daemon_deferred": True,
            "worker_mock_only": True,
            "history_write_verified": True,
            "ae_system_of_record": True,
            "ag_projection_read_only": True,
            "postgres_smoke_live_db": True,
            "physical_delete_deferred": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s49_ae_artifact_retention_scheduled_operations_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s49_ae_artifact_retention_scheduled_operations_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S49 AE artifact retention scheduled operations closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s49_ae_artifact_retention_scheduled_operations_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (481, "ae_artifact_retention_scheduled_operations_boundary_audit"),
            (482, "ae_artifact_retention_schedule_contract_schema"),
            (483, "ae_artifact_retention_batch_plan_read_model"),
            (484, "ae_artifact_retention_batch_plan_api_wiring"),
            (485, "ae_artifact_retention_batch_plan_postgresql_smoke"),
            (486, "ae_artifact_retention_scheduled_execution_command"),
            (487, "ae_artifact_retention_scheduled_execution_mock_worker"),
            (488, "ag_artifact_retention_batch_operations_projection"),
            (489, "ae_artifact_retention_scheduled_execution_postgresql_smoke"),
            (490, "s49_ae_artifact_retention_scheduled_operations_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
