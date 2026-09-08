#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s59_ae_supervised_process_operator_control_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_supervised_process_operator_control_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    "scripts/smoke/run_s59_ae_supervised_process_operator_control_closure.py",
    "tests/test_ae_supervised_process_operator_control_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_policy.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_admission.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_command_preview.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_facade.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    "tests/test_s59_ae_supervised_process_operator_control_closure.py",
    "docs/README.md",
    "docs/slices/0581_ae_supervised_process_operator_control_boundary_audit.md",
    "docs/slices/0582_ae_supervised_process_control_policy_contract_schema.md",
    "docs/slices/0583_ae_supervised_process_operator_control_admission_state_machine.md",
    "docs/slices/0584_ae_supervised_process_operator_control_command_preview.md",
    "docs/slices/0585_ae_operator_control_service_api_facade.md",
    "docs/slices/0586_ae_operator_control_postgresql_smoke_evidence.md",
    "docs/slices/0587_ag_operator_control_facade_projection.md",
    "docs/slices/0588_ag_operator_control_operations_dashboard_integration.md",
    "docs/slices/0589_ag_to_ae_operator_control_postgresql_smoke_evidence.md",
    "docs/slices/0590_s59_ae_supervised_process_operator_control_closure.md",
)

TOKEN_CHECKS = (
    (
        "s59_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s59_ae_supervised_process_operator_control_closure.py",
    ),
    (
        "s59_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_supervised_process_operator_control_boundary_audit.py",
    ),
    (
        "ae_operator_control_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    ),
    (
        "ag_operator_control_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
    ),
    (
        "ag_automation_dashboard_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_artifact_retention_automation_operations_smoke.py",
    ),
    (
        "ae_operator_control_policy_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POLICY_SCHEMA_VERSION",
    ),
    (
        "ae_operator_control_request_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_REQUEST_SCHEMA_VERSION",
    ),
    (
        "ae_operator_control_admission_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_ADMISSION_SCHEMA_VERSION",
    ),
    (
        "ae_operator_control_command_preview_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_COMMAND_PREVIEW_SCHEMA_VERSION",
    ),
    (
        "ae_operator_control_facade_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_FACADE_SCHEMA_VERSION",
    ),
    (
        "ae_operator_control_policy_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_policy",
    ),
    (
        "ae_operator_control_request_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_request",
    ),
    (
        "ae_operator_control_admission_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_admission",
    ),
    (
        "ae_operator_control_command_preview_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_command_preview",
    ),
    (
        "ae_operator_control_facade_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_facade",
    ),
    (
        "ae_operator_control_restart_decomposition",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"restart_daemon"',
    ),
    (
        "ae_operator_control_policy_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-operator-control-policy"',
    ),
    (
        "ae_operator_control_preview_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-operator-control-preview"',
    ),
    (
        "ag_operator_control_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_operator_control_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_projection",
    ),
    (
        "ag_operator_control_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_daemon_operator_control_projection",
    ),
    (
        "ag_operator_control_policy_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-policy"',
    ),
    (
        "ag_operator_control_preview_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-preview"',
    ),
    (
        "ag_operator_control_no_direct_process",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_process_control_allowed": False',
    ),
    (
        "ag_operator_control_no_direct_daemon_process",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_daemon_process_control_allowed": False',
    ),
    (
        "ag_operator_control_no_direct_db",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_automation_operator_control_block",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"operator_control"',
    ),
    (
        "ag_automation_operator_control_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"operator_control_facade_status"',
    ),
    (
        "ae_operator_control_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE",
    ),
    (
        "ae_operator_control_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ae_operator_control_smoke_unchanged",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        "preview_route_kept_rows_unchanged",
    ),
    (
        "ag_operator_control_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE",
    ),
    (
        "ag_operator_control_smoke_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_operator_control_smoke_restart_ready",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        '"restart_daemon"',
    ),
    (
        "ag_operator_control_smoke_unchanged",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py",
        "preview_routes_kept_rows_unchanged",
    ),
    (
        "ag_automation_smoke_operator_control_ready",
        "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
        "operator_control_facade_status",
    ),
    (
        "s59_doc_index_0589",
        "docs/README.md",
        "Slice 0589",
    ),
    (
        "s59_doc_index_0590",
        "docs/README.md",
        "Slice 0590",
    ),
)

SLICE_DOCS = tuple(
    f"docs/slices/{number:04d}_"
    for number in range(581, 591)
)

REDACTION_SCAN_FILES = tuple(
    path
    for path in REQUIRED_FILES
    if path.startswith("docs/slices/058")
    or path.startswith("docs/slices/0590")
)


def run_s59_ae_supervised_process_operator_control_closure(
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
            value is True for key, value in redaction_summary.items()
            if key.endswith("_included")
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice_range": "0581-0590",
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
        "operator_control_boundary_audit": present.get(
            "s59_boundary_quality_gate_hook", False
        ),
        "policy_contract_schema": present.get(
            "ae_operator_control_policy_schema", False
        ),
        "admission_state_machine": present.get(
            "ae_operator_control_admission_builder", False
        ),
        "command_preview": present.get(
            "ae_operator_control_command_preview_builder", False
        ),
        "ae_service_api_facade": present.get(
            "ae_operator_control_preview_route", False
        ),
        "ae_postgresql_smoke": present.get(
            "ae_operator_control_smoke_opt_in", False
        ),
        "ag_facade_projection": present.get(
            "ag_operator_control_projection_builder", False
        ),
        "ag_dashboard_integration": present.get(
            "ag_automation_operator_control_summary", False
        ),
        "ag_to_ae_postgresql_smoke": present.get(
            "ag_operator_control_smoke_opt_in", False
        ),
        "closure_checkpoint": present.get("s59_closure_quality_gate_hook", False),
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
        "raw_artifact_payload_included": "raw_artifact_payload_included\": true"
        in scanned_text,
        "raw_execution_payload_included": "raw_execution_payload_included\": true"
        in scanned_text,
        "raw_supervisor_command_included": "raw_supervisor_command_included\": true"
        in scanned_text,
        "raw_supervisor_result_included": "raw_supervisor_result_included\": true"
        in scanned_text,
        "raw_supervised_process_snapshot_included": (
            "raw_supervised_process_snapshot_included\": true" in scanned_text
        ),
        "storage_path_included": "/data/nex-platform" in scanned_text,
        "storage_ref_included": "storage_ref" in scanned_text,
        "metadata_only_operator_control_boundary": (
            "metadata-only" in scanned_text or "metadata_only" in scanned_text
        ),
        "operator_control_policy_contract_ae_owned": (
            "AE-owned" in scanned_text and "operator-control policy" in scanned_text
        ),
        "operator_control_admission_preview_only": (
            "admission" in scanned_text and "preview-only" in scanned_text
        ),
        "operator_control_command_preview_only": (
            "command preview" in scanned_text and "preview-only" in scanned_text
        ),
        "ae_operator_control_facade_preview_only": (
            "facade" in scanned_text and "preview-only" in scanned_text
        ),
        "ag_operator_control_projection_read_only": (
            "AG" in scanned_text and "read-only" in scanned_text
        ),
        "ag_automation_dashboard_operator_control_preview_only": (
            "automation dashboard" in scanned_text and "preview-only" in scanned_text
        ),
        "protected_postgres_smoke_envs_required": (
            "NEX_AE_TEST_DATABASE_URL" in scanned_text
            and "POSTGRES_SMOKE=1" in scanned_text
        ),
        "real_test_db_smoke_evidence_referenced": "live_db=true" in scanned_text,
        "smoke_preview_kept_rows_unchanged": "unchanged=true" in scanned_text,
        "restart_decomposes_stop_then_start": (
            "stop-then-start" in scanned_text or "stop then start" in scanned_text
        ),
        "physical_delete_automation_disabled": (
            "physical_delete_automation_enabled" in scanned_text
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
            "s59_ae_supervised_process_operator_control_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            "boundary=ae_owned "
            "ag_projection=read_only "
            "dashboard=operator_control "
            "smoke=test_db_protected"
        )
    failed = ",".join(evidence.get("failed_checks", evidence["checks"].keys()))
    return (
        "s59_ae_supervised_process_operator_control_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed={failed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close the S59 AE supervised process operator-control track."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s59_ae_supervised_process_operator_control_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
