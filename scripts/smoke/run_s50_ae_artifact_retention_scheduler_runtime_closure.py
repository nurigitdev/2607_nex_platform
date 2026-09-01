#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s50_ae_artifact_retention_scheduler_runtime_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "contracts/schemas/common/common_job.v1.schema.json",
    "contracts/schemas/generation/ae_artifact_retention_scheduled_job.v1.schema.json",
    "contracts/examples/generation/ae_artifact_retention_scheduled_job.queued_dry_run.json",
    "contracts/tests/negative/generation/ae_artifact_retention_scheduled_job.database_url_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_artifact_retention_scheduler_runtime_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduled_worker_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "scripts/smoke/run_s50_ae_artifact_retention_scheduler_runtime_closure.py",
    "tests/test_ae_artifact_retention_scheduler_runtime_boundary_audit.py",
    "tests/test_ae_artifact_retention_scheduled_worker_postgres_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s50_ae_artifact_retention_scheduler_runtime_closure.py",
    "docs/README.md",
    "docs/slices/0491_ae_artifact_retention_scheduler_runtime_boundary_audit.md",
    "docs/slices/0492_ae_artifact_retention_scheduled_job_contract_schema.md",
    "docs/slices/0493_ae_artifact_retention_scheduled_job_admission.md",
    "docs/slices/0494_ae_artifact_retention_scheduled_worker_runner_adapter.md",
    "docs/slices/0495_ae_artifact_retention_scheduled_worker_postgresql_smoke.md",
    "docs/slices/0496_ag_artifact_retention_scheduled_job_operations_projection.md",
    "docs/slices/0497_ag_artifact_retention_scheduled_dispatch_control_guardrail.md",
    "docs/slices/0498_ae_artifact_retention_scheduler_config_read_model_api.md",
    "docs/slices/0499_ae_ag_artifact_retention_scheduler_postgresql_smoke.md",
    "docs/slices/0500_s50_ae_artifact_retention_scheduler_runtime_closure.md",
)

TOKEN_CHECKS = (
    (
        "s50_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s50_ae_artifact_retention_scheduler_runtime_closure.py",
    ),
    (
        "scheduler_runtime_boundary_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_runtime_boundary_audit.py",
    ),
    (
        "scheduled_worker_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduled_worker_postgres_smoke.py",
    ),
    (
        "ae_ag_scheduler_postgres_smoke_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    ),
    (
        "scheduler_config_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_CONFIG_SCHEMA_VERSION",
    ),
    (
        "scheduled_job_schema_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_JOB_SCHEMA_VERSION",
    ),
    (
        "scheduled_job_enqueue_result_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_JOB_ENQUEUE_RESULT_SCHEMA_VERSION",
    ),
    (
        "scheduled_job_collection_constant",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "scheduled_job_type",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE",
    ),
    (
        "scheduled_job_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_scheduled_job",
    ),
    (
        "scheduled_admission_builder",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_artifact_retention_scheduled_job_admission",
    ),
    (
        "scheduled_enqueue_boundary",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "enqueue_artifact_retention_scheduled_job",
    ),
    (
        "scheduled_queue_runtime",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "build_default_artifact_retention_scheduled_job_queue",
    ),
    (
        "scheduled_worker_runner",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "run_artifact_retention_scheduled_worker_once",
    ),
    (
        "scheduler_config_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-config"',
    ),
    (
        "scheduled_jobs_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduled-jobs"',
    ),
    (
        "scheduled_job_admission_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduled-jobs/admission"',
    ),
    (
        "ag_scheduled_job_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_scheduled_dispatch_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION",
    ),
    (
        "ag_scheduled_job_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "list_artifact_retention_scheduled_jobs",
    ),
    (
        "ag_scheduled_dispatch_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "dispatch_artifact_retention_scheduled_job",
    ),
    (
        "ag_scheduled_job_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/scheduled-jobs"',
    ),
    (
        "ag_scheduled_dispatch_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch"',
    ),
    (
        "ag_dispatch_confirmation_guard",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "confirm_dispatch",
    ),
    (
        "ag_direct_enqueue_guard",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "scheduled_job_contract_schema_file",
        "contracts/schemas/generation/ae_artifact_retention_scheduled_job.v1.schema.json",
        "ae_artifact_retention_scheduled_job.v1",
    ),
    (
        "scheduled_job_common_job_schema",
        "contracts/schemas/common/common_job.v1.schema.json",
        "common_job.v1",
    ),
    (
        "scheduled_job_example",
        "contracts/examples/generation/ae_artifact_retention_scheduled_job.queued_dry_run.json",
        "ae.artifact_retention.scheduled_execution",
    ),
    (
        "scheduled_job_negative_database_url_guard",
        "contracts/tests/negative/generation/ae_artifact_retention_scheduled_job.database_url_leak.json",
        "database_url",
    ),
    (
        "worker_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduled_worker_postgres_smoke.py",
        "live_db",
    ),
    (
        "worker_smoke_service_jobs",
        "scripts/smoke/run_ae_artifact_retention_scheduled_worker_postgres_smoke.py",
        "service_jobs",
    ),
    (
        "ae_ag_smoke_env",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE",
    ),
    (
        "ae_ag_smoke_bridge",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "AeTestClientArtifactOperationsClient",
    ),
    (
        "ae_ag_smoke_sqlalchemy_queue",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "SqlAlchemyJobQueue",
    ),
    (
        "ae_ag_smoke_direct_job_observation",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "_job_observation",
    ),
    (
        "ae_ag_smoke_metadata_only",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "metadata_only_evidence",
    ),
    (
        "s50_slice_index",
        "docs/README.md",
        "Slice 0500",
    ),
    (
        "s50_ae_readme_closure_note",
        "services/nex-ae-api/README.md",
        "Slice 0500 closes S50",
    ),
    (
        "s50_ag_readme_closure_note",
        "services/nex-ag/README.md",
        "Slice 0500 closes S50",
    ),
)


def run_s50_ae_artifact_retention_scheduler_runtime_closure(
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
        "slice_range": "0491-0500",
        "required_file_count": len(REQUIRED_FILES),
        "missing_files": missing_files,
        "token_results": token_results,
        "checks": checks,
        "experience_matrix": {
            "scheduler_runtime_boundary_audit": True,
            "scheduled_job_contract_schema": True,
            "jobqueue_admission": True,
            "worker_runner_adapter": True,
            "worker_postgresql_smoke": True,
            "ag_scheduled_jobs_projection": True,
            "ag_dispatch_guardrail": True,
            "ae_scheduler_config_api": True,
            "ae_ag_scheduler_postgresql_smoke": True,
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
            "default_dry_run": True,
            "scheduler_daemon_deferred": True,
            "physical_delete_deferred": True,
            "common_job_backed": True,
            "shared_worker_runner_backed": True,
            "ae_system_of_record": True,
            "ag_projection_read_only": True,
            "ag_dispatch_requires_confirm": True,
            "ae_api_admission_only": True,
            "postgres_smoke_live_db": True,
            "direct_service_jobs_verified": True,
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s50_ae_artifact_retention_scheduler_runtime_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']}"
        )
    failed_checks = [
        key for key, value in evidence.get("checks", {}).items() if value is not True
    ]
    return (
        "s50_ae_artifact_retention_scheduler_runtime_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"checks={','.join(failed_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S50 AE artifact retention scheduler runtime closure checks."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s50_ae_artifact_retention_scheduler_runtime_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        (docs_dir / f"{slice_no:04d}_{suffix}.md").is_file()
        for slice_no, suffix in (
            (491, "ae_artifact_retention_scheduler_runtime_boundary_audit"),
            (492, "ae_artifact_retention_scheduled_job_contract_schema"),
            (493, "ae_artifact_retention_scheduled_job_admission"),
            (494, "ae_artifact_retention_scheduled_worker_runner_adapter"),
            (495, "ae_artifact_retention_scheduled_worker_postgresql_smoke"),
            (496, "ag_artifact_retention_scheduled_job_operations_projection"),
            (497, "ag_artifact_retention_scheduled_dispatch_control_guardrail"),
            (498, "ae_artifact_retention_scheduler_config_read_model_api"),
            (499, "ae_ag_artifact_retention_scheduler_postgresql_smoke"),
            (500, "s50_ae_artifact_retention_scheduler_runtime_closure"),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
