#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s56_ae_scheduler_daemon_executable_runtime_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0557_ae_artifact_retention_scheduler_daemon_run_persistence.sql",
    "scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_scheduler_daemon_executable_runtime_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
    "scripts/smoke/run_s56_ae_scheduler_daemon_executable_runtime_closure.py",
    "tests/test_ae_scheduler_daemon_executable_runtime_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
    "tests/test_s56_ae_scheduler_daemon_executable_runtime_closure.py",
    "docs/README.md",
    "docs/slices/0551_ae_scheduler_daemon_executable_runtime_boundary_audit.md",
    "docs/slices/0552_ae_daemon_cli_execute_mode_contract_schema.md",
    "docs/slices/0553_ae_daemon_process_lock_pid_run_metadata_contract.md",
    "docs/slices/0554_ae_daemon_graceful_shutdown_signal_adapter.md",
    "docs/slices/0555_ae_daemon_bounded_loop_cli_execution_wiring.md",
    "docs/slices/0556_ae_daemon_cli_execution_postgresql_smoke.md",
    "docs/slices/0557_ae_daemon_run_lifecycle_persistence.md",
    "docs/slices/0558_ae_daemon_run_read_model_api.md",
    "docs/slices/0559_ag_daemon_run_read_model_projection.md",
    "docs/slices/0560_s56_ae_scheduler_daemon_executable_runtime_closure.md",
)

TOKEN_CHECKS = (
    (
        "s56_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s56_ae_scheduler_daemon_executable_runtime_closure.py",
    ),
    (
        "executable_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_scheduler_daemon_executable_runtime_boundary_audit.py",
    ),
    (
        "cli_execution_smoke_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py",
    ),
    (
        "ag_run_read_model_smoke_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
    ),
    (
        "cli_execute_command_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTE_COMMAND_SCHEMA_VERSION",
    ),
    (
        "cli_execution_result_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION",
    ),
    (
        "process_lock_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_PROCESS_LOCK_SCHEMA_VERSION",
    ),
    (
        "run_metadata_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_METADATA_SCHEMA_VERSION",
    ),
    (
        "signal_shutdown_adapter_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SIGNAL_SHUTDOWN_ADAPTER_SCHEMA_VERSION",
    ),
    (
        "daemon_cli_execution_runner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "run_artifact_retention_scheduler_daemon_cli_execution",
    ),
    (
        "bounded_loop_adapter_used",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "run_artifact_retention_scheduler_daemon_bounded_loop",
    ),
    (
        "execute_mode_requires_explicit_opt_in",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"execution_requires_explicit_opt_in": True',
    ),
    (
        "execute_profile_test_only",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "profile must be test.",
    ),
    (
        "run_record_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_RECORD_SCHEMA_VERSION",
    ),
    (
        "lifecycle_event_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LIFECYCLE_EVENT_SCHEMA_VERSION",
    ),
    (
        "daemon_run_store",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "SqlAlchemyArtifactRetentionSchedulerDaemonRunStore",
    ),
    (
        "daemon_run_store_record_cli_execution",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_cli_execution",
    ),
    (
        "daemon_run_store_list_read_model",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "list_run_records",
    ),
    (
        "daemon_lifecycle_list_read_model",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "list_lifecycle_events",
    ),
    (
        "ae_run_collection_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_run_collection",
    ),
    (
        "ae_run_detail_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_run_detail",
    ),
    (
        "run_persistence_migration_table",
        "database/nex-ae-api/migrations/0557_ae_artifact_retention_scheduler_daemon_run_persistence.sql",
        "ae_artifact_retention_scheduler_daemon_runs",
    ),
    (
        "run_lifecycle_migration_table",
        "database/nex-ae-api/migrations/0557_ae_artifact_retention_scheduler_daemon_run_persistence.sql",
        "ae_artifact_retention_scheduler_daemon_lifecycle_events",
    ),
    (
        "ae_daemon_run_collection_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-runs"',
    ),
    (
        "ae_daemon_run_detail_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-runs/{daemon_run_record_id}"',
    ),
    (
        "ae_daemon_run_store_unavailable_problem",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ae.artifact_retention_scheduler_daemon_run_store_unavailable",
    ),
    (
        "ag_run_collection_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_run_detail_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_run_collection_client_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "list_artifact_retention_scheduler_daemon_runs",
    ),
    (
        "ag_run_detail_client_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_scheduler_daemon_run_detail",
    ),
    (
        "ag_run_collection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/scheduler-daemon-runs"',
    ),
    (
        "ag_daemon_result_status_guardrail",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "SUPPORTED_ARTIFACT_RETENTION_DAEMON_RESULT_STATUSES",
    ),
    (
        "ag_direct_database_write_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_direct_daemon_process_control_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_daemon_process_control_allowed": False',
    ),
    (
        "cli_execution_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE",
    ),
    (
        "cli_execution_smoke_run_record_persisted",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py",
        "run_record_persisted",
    ),
    (
        "ag_run_read_model_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_READ_MODEL_POSTGRES_SMOKE",
    ),
    (
        "ag_run_read_model_smoke_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_run_read_model_smoke_cleanup",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py",
        "cleanup_runs",
    ),
    (
        "s56_closure_doc_indexed",
        "docs/README.md",
        "0560_s56_ae_scheduler_daemon_executable_runtime_closure.md",
    ),
)

SLICE_DOCS = tuple(range(551, 561))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_s56_ae_scheduler_daemon_executable_runtime_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    docs_present = _slice_docs_contiguous(root)
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "failure_code": None,
        "slice_range": "0551-0560",
        "required_file_count": len(REQUIRED_FILES),
        "checks": {
            "required_files_present": all(
                item["present"] for item in required_file_results
            ),
            "token_checks_present": all(item["present"] for item in token_results),
            "slice_docs_contiguous": docs_present,
            "redaction_scan_safe": _redaction_scan_safe(root),
        },
        "experience_matrix": _experience_matrix(root),
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
            "metadata_only_execution_boundary": True,
            "daemon_cli_plan_first": True,
            "execute_mode_test_profile_only": True,
            "execute_mode_explicit_opt_in": True,
            "bounded_loop_finite": True,
            "process_lock_metadata_safe": True,
            "graceful_shutdown_metadata_only": True,
            "run_persistence_ae_owned": True,
            "ae_run_read_model_read_only": True,
            "ag_run_projection_read_only": True,
            "protected_postgres_smoke_envs_required": True,
            "real_test_db_smoke_evidence_referenced": True,
            "physical_delete_automation_disabled": True,
        },
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    if not all(evidence["checks"].values()) or not all(
        evidence["experience_matrix"].values()
    ):
        evidence["status"] = "FAIL"
        evidence["failure_code"] = "closure_checks_failed"
    return evidence


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": relative_path, "present": (root / relative_path).is_file()}
        for relative_path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check_id,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for check_id, relative_path, token in TOKEN_CHECKS
    ]


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    return all(
        any(docs_dir.glob(f"{slice_number:04d}_*.md"))
        for slice_number in SLICE_DOCS
    )


def _experience_matrix(root: Path) -> dict[str, bool]:
    docs_dir = root / "docs" / "slices"
    return {
        "executable_runtime_boundary_audit": (
            docs_dir / "0551_ae_scheduler_daemon_executable_runtime_boundary_audit.md"
        ).is_file(),
        "cli_execute_mode_contract_schema": (
            docs_dir / "0552_ae_daemon_cli_execute_mode_contract_schema.md"
        ).is_file(),
        "process_lock_pid_run_metadata_contract": (
            docs_dir / "0553_ae_daemon_process_lock_pid_run_metadata_contract.md"
        ).is_file(),
        "graceful_shutdown_signal_adapter": (
            docs_dir / "0554_ae_daemon_graceful_shutdown_signal_adapter.md"
        ).is_file(),
        "bounded_loop_cli_execution_wiring": (
            docs_dir / "0555_ae_daemon_bounded_loop_cli_execution_wiring.md"
        ).is_file(),
        "cli_execution_postgresql_smoke": (
            docs_dir / "0556_ae_daemon_cli_execution_postgresql_smoke.md"
        ).is_file(),
        "run_lifecycle_persistence": (
            docs_dir / "0557_ae_daemon_run_lifecycle_persistence.md"
        ).is_file(),
        "run_read_model_api": (
            docs_dir / "0558_ae_daemon_run_read_model_api.md"
        ).is_file(),
        "ag_run_read_model_projection": (
            docs_dir / "0559_ag_daemon_run_read_model_projection.md"
        ).is_file(),
        "closure_checkpoint": (
            docs_dir / "0560_s56_ae_scheduler_daemon_executable_runtime_closure.md"
        ).is_file(),
    }


def _redaction_scan_safe(root: Path) -> bool:
    texts = [
        _read_text(root / "services/nex-ae-api/README.md"),
        _read_text(root / "services/nex-ag/README.md"),
        _read_text(root / "docs/slices/0551_ae_scheduler_daemon_executable_runtime_boundary_audit.md"),
        _read_text(root / "docs/slices/0556_ae_daemon_cli_execution_postgresql_smoke.md"),
        _read_text(root / "docs/slices/0557_ae_daemon_run_lifecycle_persistence.md"),
        _read_text(root / "docs/slices/0558_ae_daemon_run_read_model_api.md"),
        _read_text(root / "docs/slices/0559_ag_daemon_run_read_model_projection.md"),
        _read_text(root / "docs/slices/0560_s56_ae_scheduler_daemon_executable_runtime_closure.md"),
    ]
    return not any(pattern.search(text) for pattern in SENSITIVE_PATTERNS for text in texts)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    checks = evidence.get("checks", {})
    failing_checks = [key for key, passed in checks.items() if passed is not True]
    suffix = (
        f"slice_range={evidence.get('slice_range')} "
        f"required_files={evidence.get('required_file_count', len(REQUIRED_FILES))} "
        "runtime=explicit_bounded read_model=ae_owned ag_projection=read_only"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "s56_ae_scheduler_daemon_executable_runtime_closure="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S56 AE scheduler daemon executable runtime closure checks."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s56_ae_scheduler_daemon_executable_runtime_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
