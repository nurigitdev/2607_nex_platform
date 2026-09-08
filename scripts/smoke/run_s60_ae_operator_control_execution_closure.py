#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s60_ae_operator_control_execution_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_operator_control_execution_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
    "scripts/smoke/run_s60_ae_operator_control_execution_closure.py",
    "tests/test_ae_operator_control_execution_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_contract.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_state.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_persistence.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
    "tests/test_s60_ae_operator_control_execution_closure.py",
    "docs/README.md",
    "docs/slices/0591_ae_operator_control_execution_boundary_audit.md",
    "docs/slices/0592_ae_operator_control_execution_request_result_contract.md",
    "docs/slices/0593_ae_operator_control_execution_state_machine.md",
    "docs/slices/0594_ae_operator_control_execution_api_routes.md",
    "docs/slices/0595_ae_operator_control_execution_postgresql_smoke.md",
    "docs/slices/0596_ae_operator_control_execution_persistence_read_model_api.md",
    "docs/slices/0597_ag_operator_control_execution_projection_foundation.md",
    "docs/slices/0598_ag_operator_control_execution_route_wiring.md",
    "docs/slices/0599_ag_operator_control_execution_postgresql_smoke.md",
    "docs/slices/0600_s60_ae_operator_control_execution_closure.md",
)

TOKEN_CHECKS = (
    (
        "s60_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s60_ae_operator_control_execution_closure.py",
    ),
    (
        "s60_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_operator_control_execution_boundary_audit.py",
    ),
    (
        "ae_execution_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py",
    ),
    (
        "ag_execution_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
    ),
    (
        "ae_execution_request_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_REQUEST_SCHEMA_VERSION",
    ),
    (
        "ae_execution_result_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_RESULT_SCHEMA_VERSION",
    ),
    (
        "ae_execution_state_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_SCHEMA_VERSION",
    ),
    (
        "ae_execution_transition_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_STATE_TRANSITION_SCHEMA_VERSION",
    ),
    (
        "ae_execution_collection_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "ae_execution_detail_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_SCHEMA_VERSION",
    ),
    (
        "ae_execution_request_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_request",
    ),
    (
        "ae_execution_result_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_result",
    ),
    (
        "ae_execution_state_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_state",
    ),
    (
        "ae_execution_transition_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_state_transition",
    ),
    (
        "ae_execution_collection_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_collection",
    ),
    (
        "ae_execution_detail_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_detail",
    ),
    (
        "ae_execution_store",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionStore",
    ),
    (
        "ae_execution_store_record_state",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_execution_state",
    ),
    (
        "ae_execution_store_record_transition",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_execution_state_transition",
    ),
    (
        "ae_execution_state_table",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "ae_daemon_operator_control_execution_states",
    ),
    (
        "ae_execution_transition_table",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "ae_daemon_operator_control_execution_transitions",
    ),
    (
        "ae_execution_state_status_index",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "idx_ae_operator_control_execution_states_status",
    ),
    (
        "ae_execution_transition_state_index",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "idx_ae_operator_control_execution_transitions_state",
    ),
    (
        "ae_execution_post_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-operator-control-executions"',
    ),
    (
        "ae_execution_transition_post_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"scheduler-daemon-operator-control-execution-transitions"',
    ),
    (
        "ae_execution_collection_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "list_artifact_retention_scheduler_daemon_operator_control_executions",
    ),
    (
        "ae_execution_detail_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "get_artifact_retention_scheduler_daemon_operator_control_execution_detail",
    ),
    (
        "ae_persist_state_flag",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"persist_execution_state"',
    ),
    (
        "ae_persist_transition_flag",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"persist_transition"',
    ),
    (
        "ag_execution_collection_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_execution_detail_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_execution_collection_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_collection_projection",
    ),
    (
        "ag_execution_detail_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_detail_projection",
    ),
    (
        "ag_execution_collection_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "list_artifact_retention_scheduler_daemon_operator_control_executions",
    ),
    (
        "ag_execution_detail_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_scheduler_daemon_operator_control_execution_detail",
    ),
    (
        "ag_execution_collection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-executions"',
    ),
    (
        "ag_execution_read_only_guidance",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_execution_no_daemon_process_control",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_daemon_process_control_allowed": False',
    ),
    (
        "ag_execution_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_daemon_operator_control_execution_operations",
    ),
    (
        "ag_execution_detail_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_daemon_operator_control_execution_detail",
    ),
    (
        "ae_execution_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_POSTGRES_SMOKE",
    ),
    (
        "ae_execution_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_execution_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE",
    ),
    (
        "ag_execution_smoke_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_execution_smoke_scoped_rows",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
        "scoped_row_counts",
    ),
    (
        "ag_execution_smoke_cleanup",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py",
        "cleanup verification",
    ),
    (
        "s60_doc_index_0599",
        "docs/README.md",
        "Slice 0599",
    ),
    (
        "s60_doc_index_0600",
        "docs/README.md",
        "Slice 0600",
    ),
)

SLICE_DOCS = tuple(f"docs/slices/{number:04d}_" for number in range(591, 601))

REDACTION_SCAN_FILES = (
    "services/nex-ae-api/README.md",
    "services/nex-ag/README.md",
    "docs/slices/0591_ae_operator_control_execution_boundary_audit.md",
    "docs/slices/0592_ae_operator_control_execution_request_result_contract.md",
    "docs/slices/0593_ae_operator_control_execution_state_machine.md",
    "docs/slices/0594_ae_operator_control_execution_api_routes.md",
    "docs/slices/0595_ae_operator_control_execution_postgresql_smoke.md",
    "docs/slices/0596_ae_operator_control_execution_persistence_read_model_api.md",
    "docs/slices/0597_ag_operator_control_execution_projection_foundation.md",
    "docs/slices/0598_ag_operator_control_execution_route_wiring.md",
    "docs/slices/0599_ag_operator_control_execution_postgresql_smoke.md",
    "docs/slices/0600_s60_ae_operator_control_execution_closure.md",
)


def run_s60_ae_operator_control_execution_closure(
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
        "slice_range": "0591-0600",
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
        "execution_boundary_audit": present.get(
            "s60_boundary_quality_gate_hook", False
        ),
        "request_result_contract": present.get(
            "ae_execution_request_builder", False
        )
        and present.get("ae_execution_result_builder", False),
        "state_machine_and_transition": present.get(
            "ae_execution_state_builder", False
        )
        and present.get("ae_execution_transition_builder", False),
        "ae_execution_service_routes": present.get(
            "ae_execution_post_route", False
        )
        and present.get("ae_execution_transition_post_route", False),
        "ae_postgresql_smoke": present.get(
            "ae_execution_postgres_quality_gate_hook", False
        ),
        "ae_persistence_read_model": present.get("ae_execution_store", False)
        and present.get("ae_execution_collection_builder", False)
        and present.get("ae_execution_detail_builder", False),
        "ag_projection_foundation": present.get(
            "ag_execution_collection_projection_builder", False
        )
        and present.get("ag_execution_detail_projection_builder", False),
        "ag_route_wiring": present.get("ag_execution_collection_route", False)
        and present.get("ag_execution_collection_client_method", False),
        "ag_to_ae_postgresql_smoke": present.get(
            "ag_execution_postgres_quality_gate_hook", False
        )
        and present.get("ag_execution_smoke_scoped_rows", False),
        "closure_checkpoint": present.get("s60_closure_quality_gate_hook", False),
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
            re.search(r"slice-059[0-9]-[a-z0-9-]+", scanned_text)
        ),
        "raw_artifact_payload_included": "raw_artifact_payload_included\": true"
        in scanned_text,
        "raw_execution_payload_included": "raw_execution_payload_included\": true"
        in scanned_text,
        "raw_daemon_runtime_payload_included": (
            "raw_daemon_runtime_payload_included\": true" in scanned_text
        ),
        "raw_supervised_process_snapshot_included": (
            "raw_supervised_process_snapshot_included\": true" in scanned_text
        ),
        "storage_path_included": "/data/nex-platform" in scanned_text,
        "metadata_only_execution_boundary": (
            "metadata-only" in scanned_text or "metadata_only" in scanned_text
        ),
        "ae_execution_persistence_explicit": (
            "persist_execution_state=true" in scanned_text
            and "persist_transition=true" in scanned_text
        ),
        "ag_execution_projection_read_only": (
            "AG" in scanned_text and "read-only" in scanned_text
        ),
        "protected_postgres_smoke_envs_required": (
            "NEX_AE_TEST_DATABASE_URL" in scanned_text
            and "POSTGRES_SMOKE=1" in scanned_text
        ),
        "real_test_db_smoke_evidence_referenced": "live_db=true" in scanned_text,
        "scoped_db_write_select_cleanup": (
            "states=1" in scanned_text
            and "transitions=1" in scanned_text
            and "cleanup_states=1" in scanned_text
        ),
        "fake_dry_run_dispatch_only": (
            "fake_dry_run_supervisor_persistent_dispatch" in scanned_text
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
            "s60_ae_operator_control_execution_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            "boundary=ae_owned "
            "ag_projection=read_only "
            "persistence=explicit "
            "smoke=test_db_persisted_read_model"
        )
    failed = ",".join(evidence.get("failed_checks", evidence["checks"].keys()))
    return (
        "s60_ae_operator_control_execution_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed={failed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close the S60 AE operator-control execution track."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s60_ae_operator_control_execution_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
