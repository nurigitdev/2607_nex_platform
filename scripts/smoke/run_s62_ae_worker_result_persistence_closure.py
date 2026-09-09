#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s62_ae_worker_result_persistence_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
    "scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_s62_ae_worker_result_persistence_closure.py",
    "tests/test_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py",
    "tests/test_ae_operator_control_execution_worker_result_postgres_smoke.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
    "tests/test_s62_ae_worker_result_persistence_closure.py",
    "docs/README.md",
    "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
    "docs/slices/0612_ae_worker_result_persistence_schema_store.md",
    "docs/slices/0613_ae_worker_result_route_persistence_wiring.md",
    "docs/slices/0614_ae_worker_result_postgresql_smoke.md",
    "docs/slices/0615_ae_worker_result_read_model_api.md",
    "docs/slices/0616_ag_worker_result_projection_foundation.md",
    "docs/slices/0617_ag_worker_result_route_dashboard_wiring.md",
    "docs/slices/0618_ag_worker_result_postgresql_smoke.md",
    "docs/slices/0619_ag_worker_result_diagnostics_rollup.md",
    "docs/slices/0620_s62_ae_worker_result_persistence_closure.md",
)

TOKEN_CHECKS = (
    (
        "s62_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s62_ae_worker_result_persistence_closure.py",
    ),
    (
        "s62_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py",
    ),
    (
        "ae_worker_result_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_operator_control_execution_worker_result_postgres_smoke.py",
    ),
    (
        "ag_worker_result_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
    ),
    (
        "ag_operations_smoke_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_artifact_retention_automation_operations_smoke.py",
    ),
    (
        "ae_worker_result_record_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_RECORD_SCHEMA_VERSION",
    ),
    (
        "ae_worker_result_collection_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "ae_worker_result_detail_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_SCHEMA_VERSION",
    ),
    (
        "ae_worker_result_table_constant",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        'AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_TABLE = "ae_op_exec_worker_results"',
    ),
    (
        "ae_worker_result_store",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore",
    ),
    (
        "ae_worker_result_safe_summary_token",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "safe_summary",
    ),
    (
        "ae_worker_result_command_hash_token",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "operator_control_execution_worker_command_hash",
    ),
    (
        "ae_worker_result_transition_hash_token",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "operator_control_execution_worker_transition_plan_hash",
    ),
    (
        "ae_worker_result_migration_table",
        "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ae_op_exec_worker_results",
    ),
    (
        "ae_worker_result_migration_observed_index",
        "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
        "idx_ae_op_worker_results_observed",
    ),
    (
        "ae_worker_result_migration_state_index",
        "database/nex-ae-api/migrations/0612_ae_worker_result_persistence.sql",
        "idx_ae_op_worker_results_state",
    ),
    (
        "ae_worker_result_route_persist_flag",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "persist_worker_result",
    ),
    (
        "ae_worker_result_collection_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"scheduler-daemon-operator-control-execution-worker-results"',
    ),
    (
        "ae_worker_result_collection_callable",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "list_artifact_retention_scheduler_daemon_operator_control_execution_worker_results",
    ),
    (
        "ae_worker_result_detail_callable",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "get_artifact_retention_scheduler_daemon_operator_control_execution_worker_result",
    ),
    (
        "ae_worker_result_postgres_opt_in",
        "scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py",
        "NEX_AE_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_POSTGRES_SMOKE",
    ),
    (
        "ae_worker_result_postgres_live_db",
        "scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ae_worker_result_postgres_cleanup",
        "scripts/smoke/run_ae_operator_control_execution_worker_result_postgres_smoke.py",
        "cleanup verification",
    ),
    (
        "ag_worker_result_collection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_COLLECTION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_worker_result_detail_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DETAIL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_worker_result_diagnostics_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_DIAGNOSTICS_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_worker_result_collection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_worker_result_collection_projection",
    ),
    (
        "ag_worker_result_detail_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_worker_result_detail_projection",
    ),
    (
        "ag_worker_result_diagnostics_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_worker_result_diagnostics_projection",
    ),
    (
        "ag_worker_result_diagnostics_helper",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "diagnose_artifact_retention_daemon_operator_control_execution_worker_results",
    ),
    (
        "ag_worker_result_collection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-execution-worker-results"',
    ),
    (
        "ag_worker_result_diagnostics_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-execution-worker-result-diagnostics"',
    ),
    (
        "ag_worker_result_read_only_guardrail",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_worker_result_no_job_enqueue_guardrail",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "ag_worker_result_postgres_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
        "WORKER_RESULT_READ_MODEL_POSTGRES_SMOKE",
    ),
    (
        "ag_worker_result_postgres_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_worker_result_postgres_read_statuses",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke.py",
        "ag_worker_result_collection_status",
    ),
    (
        "s62_doc_index_0619",
        "docs/README.md",
        "Slice 0619",
    ),
    (
        "s62_doc_index_0620",
        "docs/README.md",
        "Slice 0620",
    ),
)

SLICE_DOCS = tuple(f"docs/slices/{number:04d}_" for number in range(611, 621))

REDACTION_SCAN_FILES = (
    "services/nex-ae-api/README.md",
    "services/nex-ag/README.md",
    "docs/slices/0611_ae_worker_result_persistence_boundary_audit.md",
    "docs/slices/0612_ae_worker_result_persistence_schema_store.md",
    "docs/slices/0613_ae_worker_result_route_persistence_wiring.md",
    "docs/slices/0614_ae_worker_result_postgresql_smoke.md",
    "docs/slices/0615_ae_worker_result_read_model_api.md",
    "docs/slices/0616_ag_worker_result_projection_foundation.md",
    "docs/slices/0617_ag_worker_result_route_dashboard_wiring.md",
    "docs/slices/0618_ag_worker_result_postgresql_smoke.md",
    "docs/slices/0619_ag_worker_result_diagnostics_rollup.md",
    "docs/slices/0620_s62_ae_worker_result_persistence_closure.md",
)


def run_s62_ae_worker_result_persistence_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    redaction_summary = _redaction_summary(root)
    checks = {
        "required_files_present": all(
            item["present"] for item in required_file_results
        ),
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
        "redaction_scan_safe": not any(
            value is True
            for key, value in redaction_summary.items()
            if key.endswith("_included")
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice_range": "0611-0620",
        "result_table": "ae_op_exec_worker_results",
        "result_table_length": len("ae_op_exec_worker_results"),
        "new_tables_in_slice_0620": False,
        "required_file_count": len(REQUIRED_FILES),
        "token_check_count": len(TOKEN_CHECKS),
        "checks": checks,
        "experience_matrix": _experience_matrix(token_results),
        "redaction_summary": redaction_summary,
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    if status != "PASS":
        evidence["failure_code"] = "closure_checks_failed"
        evidence["failed_checks"] = [
            key for key, passed in checks.items() if not passed
        ]
    return evidence


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": relative_path,
            "present": (root / relative_path).is_file(),
        }
        for relative_path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        text = _read_text(root / relative_path)
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in text,
            }
        )
    return results


def _slice_docs_contiguous(root: Path) -> bool:
    docs_dir = root / "docs" / "slices"
    if not docs_dir.is_dir():
        return False
    existing = {path.name for path in docs_dir.glob("*.md")}
    return all(
        any(name.startswith(prefix.split("/")[-1]) for name in existing)
        for prefix in SLICE_DOCS
    )


def _experience_matrix(token_results: list[dict[str, Any]]) -> dict[str, bool]:
    present = {item["check_id"]: item["present"] for item in token_results}
    return {
        "worker_result_boundary_audit": present.get(
            "s62_boundary_quality_gate_hook", False
        )
        and present.get("ae_worker_result_table_constant", False),
        "ae_schema_store_foundation": present.get(
            "ae_worker_result_migration_table", False
        )
        and present.get("ae_worker_result_store", False),
        "explicit_route_persistence": present.get(
            "ae_worker_result_route_persist_flag", False
        )
        and present.get("ae_worker_result_collection_route", False),
        "ae_read_model_api": present.get(
            "ae_worker_result_collection_callable", False
        )
        and present.get("ae_worker_result_detail_callable", False),
        "ae_postgresql_smoke": present.get(
            "ae_worker_result_postgres_quality_gate_hook", False
        )
        and present.get("ae_worker_result_postgres_live_db", False),
        "ag_projection_foundation": present.get(
            "ag_worker_result_collection_builder", False
        )
        and present.get("ag_worker_result_detail_builder", False),
        "ag_route_dashboard_wiring": present.get(
            "ag_worker_result_collection_route", False
        )
        and present.get("ag_operations_smoke_quality_gate_hook", False),
        "ag_postgresql_smoke": present.get(
            "ag_worker_result_postgres_quality_gate_hook", False
        )
        and present.get("ag_worker_result_postgres_live_db", False),
        "ag_diagnostics_rollup": present.get(
            "ag_worker_result_diagnostics_schema", False
        )
        and present.get("ag_worker_result_diagnostics_route", False)
        and present.get("ag_worker_result_diagnostics_helper", False),
        "closure_checkpoint": present.get("s62_closure_quality_gate_hook", False),
    }


def _redaction_summary(root: Path) -> dict[str, bool]:
    scanned_text = "\n".join(_read_text(root / path) for path in REDACTION_SCAN_FILES)
    return {
        "database_url_included": bool(
            re.search(r"postgresql(?:\+psycopg)?://[^*\s]+:[^*\s]+@", scanned_text)
        ),
        "service_token_included": "Bearer " in scanned_text,
        "provider_api_key_included": "ed6@c496em" in scanned_text,
        "shared_password_included": "nuri1004" in scanned_text,
        "raw_prompt_included": "SECRET_SYSTEM_PROMPT" in scanned_text,
        "raw_generation_output_included": "RAW_GENERATION_OUTPUT" in scanned_text,
        "raw_source_document_text_included": "RAW_SOURCE_DOCUMENT_TEXT" in scanned_text,
        "idempotency_key_included": bool(
            re.search(r"slice-06(?:1[1-9]|20)-[a-z0-9-]+", scanned_text)
        ),
        "raw_artifact_payload_included": "raw_artifact_payload_included\": true"
        in scanned_text,
        "raw_execution_payload_included": "raw_execution_payload_included\": true"
        in scanned_text,
        "raw_worker_command_included": "raw_worker_command_included\": true"
        in scanned_text,
        "raw_supervisor_result_included": "raw_supervisor_result_included\": true"
        in scanned_text,
        "raw_daemon_runtime_payload_included": (
            "raw_daemon_runtime_payload_included\": true" in scanned_text
        ),
        "raw_supervised_process_snapshot_included": (
            "raw_supervised_process_snapshot_included\": true" in scanned_text
        ),
        "storage_path_included": "/data/nex-platform" in scanned_text,
        "explicit_persist_flag_documented": "persist_worker_result=true"
        in scanned_text,
        "safe_summary_hash_boundary_documented": (
            "safe summary" in scanned_text and "hashes" in scanned_text
        ),
        "ae_worker_result_postgres_test_db_smoke": (
            "ae_operator_control_execution_worker_result_postgres_smoke=pass"
            in scanned_text
            and "cleanup_results=1" in scanned_text
            and "live_db=true" in scanned_text
        ),
        "ag_worker_result_postgres_test_db_smoke": (
            "ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_read_model_postgres_smoke=pass"
            in scanned_text
            and "cleanup_results=1" in scanned_text
            and "live_db=true" in scanned_text
        ),
        "ag_read_only_documented": (
            "AG remains read-only" in scanned_text
            or "AG still does not connect to or mutate" in scanned_text
        ),
        "diagnostics_metadata_only": "Diagnostics are read-only and metadata-only"
        in scanned_text,
        "protected_postgres_smoke_envs_required": (
            "NEX_AE_TEST_DATABASE_URL" in scanned_text
            and "POSTGRES_SMOKE=1" in scanned_text
        ),
        "physical_delete_automation_disabled": (
            "physical deletion" in scanned_text
            or "physical delete automation" in scanned_text
        ),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "s62_ae_worker_result_persistence_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            "boundary=ae_owned "
            f"table={evidence['result_table']} "
            "ag_projection=read_only "
            "diagnostics=metadata_only "
            "smoke=test_db_result_read_model"
        )
    failed = ",".join(evidence.get("failed_checks", evidence["checks"].keys()))
    return (
        "s62_ae_worker_result_persistence_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed={failed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close the S62 AE worker result persistence/read-model track."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s62_ae_worker_result_persistence_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
