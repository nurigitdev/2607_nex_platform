#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s61_ae_operator_control_execution_worker_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    "scripts/smoke/run_s61_ae_operator_control_execution_worker_closure.py",
    "tests/test_ae_operator_control_execution_worker_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_contract.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_adapter.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    "tests/test_s61_ae_operator_control_execution_worker_closure.py",
    "docs/README.md",
    "docs/slices/0601_ae_operator_control_execution_worker_boundary_audit.md",
    "docs/slices/0602_ae_execution_worker_plan_command_contract.md",
    "docs/slices/0603_ae_execution_worker_state_transition_hardening.md",
    "docs/slices/0604_ae_fake_dry_run_execution_worker_adapter.md",
    "docs/slices/0605_ae_execution_worker_service_api_wiring.md",
    "docs/slices/0606_ae_execution_worker_postgresql_smoke.md",
    "docs/slices/0607_ag_worker_execution_projection_foundation.md",
    "docs/slices/0608_ag_worker_execution_route_wiring.md",
    "docs/slices/0609_ag_worker_execution_postgresql_smoke.md",
    "docs/slices/0610_s61_ae_operator_control_execution_worker_closure.md",
)

TOKEN_CHECKS = (
    (
        "s61_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s61_ae_operator_control_execution_worker_closure.py",
    ),
    (
        "s61_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_operator_control_execution_worker_boundary_audit.py",
    ),
    (
        "ae_worker_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    ),
    (
        "ag_worker_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
    ),
    (
        "ae_worker_plan_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PLAN_SCHEMA_VERSION",
    ),
    (
        "ae_worker_command_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_COMMAND_SCHEMA_VERSION",
    ),
    (
        "ae_worker_transition_plan_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_TRANSITION_PLAN_SCHEMA_VERSION",
    ),
    (
        "ae_worker_result_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_RESULT_SCHEMA_VERSION",
    ),
    (
        "ae_worker_plan_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_worker_plan",
    ),
    (
        "ae_worker_command_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_worker_command",
    ),
    (
        "ae_worker_transition_plan_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_worker_transition_plan",
    ),
    (
        "ae_worker_result_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_operator_control_execution_worker_result",
    ),
    (
        "ae_worker_runner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "run_artifact_retention_scheduler_daemon_operator_control_execution_worker",
    ),
    (
        "ae_worker_mode",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "fake_dry_run_supervisor_persistent_dispatch_worker",
    ),
    (
        "ae_worker_performed_metadata",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"worker_execution_performed": command["command_status"] == "READY"',
    ),
    (
        "ae_worker_subprocess_guardrail",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"subprocess_started": False',
    ),
    (
        "ae_worker_transition_persistence_guardrail",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"transition_persistence_performed": False',
    ),
    (
        "ae_worker_state_table",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "ae_daemon_operator_control_execution_states",
    ),
    (
        "ae_worker_transition_table",
        "database/nex-ae-api/migrations/0596_ae_operator_control_execution_persistence.sql",
        "ae_daemon_operator_control_execution_transitions",
    ),
    (
        "ae_worker_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"scheduler-daemon-operator-control-execution-workers"',
    ),
    (
        "ae_worker_route_callable",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "run_artifact_retention_scheduler_daemon_operator_control_execution_worker_route",
    ),
    (
        "ae_worker_state_id_input",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"operator_control_execution_state_id"',
    ),
    (
        "ag_worker_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_worker_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_operator_control_execution_worker_projection",
    ),
    (
        "ag_worker_client_method",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "run_artifact_retention_scheduler_daemon_operator_control_execution_worker",
    ),
    (
        "ag_worker_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-operator-control-execution-workers"',
    ),
    (
        "ag_worker_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_daemon_operator_control_execution_worker_result",
    ),
    (
        "ag_worker_read_only_guidance",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_worker_no_job_enqueue",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "ag_worker_no_physical_delete",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "ae_worker_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE",
    ),
    (
        "ae_worker_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ae_worker_smoke_transition_count",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "scoped_row_counts",
    ),
    (
        "ag_worker_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE",
    ),
    (
        "ag_worker_smoke_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_worker_smoke_no_transition_row",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        '"execution_transitions": 0',
    ),
    (
        "ag_worker_smoke_cleanup",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_worker_postgres_smoke.py",
        "cleanup verification",
    ),
    (
        "s61_doc_index_0609",
        "docs/README.md",
        "Slice 0609",
    ),
    (
        "s61_doc_index_0610",
        "docs/README.md",
        "Slice 0610",
    ),
)

SLICE_DOCS = tuple(f"docs/slices/{number:04d}_" for number in range(601, 611))

REDACTION_SCAN_FILES = (
    "services/nex-ae-api/README.md",
    "services/nex-ag/README.md",
    "docs/slices/0601_ae_operator_control_execution_worker_boundary_audit.md",
    "docs/slices/0602_ae_execution_worker_plan_command_contract.md",
    "docs/slices/0603_ae_execution_worker_state_transition_hardening.md",
    "docs/slices/0604_ae_fake_dry_run_execution_worker_adapter.md",
    "docs/slices/0605_ae_execution_worker_service_api_wiring.md",
    "docs/slices/0606_ae_execution_worker_postgresql_smoke.md",
    "docs/slices/0607_ag_worker_execution_projection_foundation.md",
    "docs/slices/0608_ag_worker_execution_route_wiring.md",
    "docs/slices/0609_ag_worker_execution_postgresql_smoke.md",
    "docs/slices/0610_s61_ae_operator_control_execution_worker_closure.md",
)


def run_s61_ae_operator_control_execution_worker_closure(
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
        "slice_range": "0601-0610",
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
        "worker_boundary_audit": present.get("s61_boundary_quality_gate_hook", False),
        "plan_command_contract": present.get("ae_worker_plan_builder", False)
        and present.get("ae_worker_command_builder", False),
        "transition_plan_contract": present.get(
            "ae_worker_transition_plan_builder", False
        ),
        "fake_dry_run_worker_adapter": present.get("ae_worker_runner", False)
        and present.get("ae_worker_mode", False),
        "ae_worker_service_route": present.get("ae_worker_route", False)
        and present.get("ae_worker_route_callable", False),
        "ae_postgresql_smoke": present.get(
            "ae_worker_postgres_quality_gate_hook", False
        )
        and present.get("ae_worker_smoke_live_db", False),
        "ag_projection_foundation": present.get(
            "ag_worker_projection_builder", False
        )
        and present.get("ag_worker_summary", False),
        "ag_route_wiring": present.get("ag_worker_route", False)
        and present.get("ag_worker_client_method", False),
        "ag_to_ae_postgresql_smoke": present.get(
            "ag_worker_postgres_quality_gate_hook", False
        )
        and present.get("ag_worker_smoke_no_transition_row", False),
        "closure_checkpoint": present.get("s61_closure_quality_gate_hook", False),
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
            re.search(r"slice-060[1-9]-[a-z0-9-]+", scanned_text)
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
        "metadata_only_worker_boundary": (
            "metadata-only" in scanned_text or "metadata_only" in scanned_text
        ),
        "worker_result_persistence_deferred": (
            "does not persist a transition row by itself" in scanned_text
            and "without adding worker-result persistence" in scanned_text
        ),
        "ae_worker_postgres_test_db_smoke": (
            "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_POSTGRES_SMOKE=1"
            in scanned_text
            and "transitions=1" in scanned_text
            and "cleanup_transitions=1" in scanned_text
        ),
        "ag_worker_projection_read_only": (
            "AG remains read/projection-only" in scanned_text
            or ("AG" in scanned_text and "read-only" in scanned_text)
        ),
        "ag_worker_no_transition_persistence": (
            "transitions=0" in scanned_text and "cleanup_transitions=0" in scanned_text
        ),
        "protected_postgres_smoke_envs_required": (
            "NEX_AE_TEST_DATABASE_URL" in scanned_text
            and "POSTGRES_SMOKE=1" in scanned_text
        ),
        "real_test_db_smoke_evidence_referenced": "live_db=true" in scanned_text,
        "scoped_db_write_select_cleanup": (
            "states=1" in scanned_text and "cleanup_states=1" in scanned_text
        ),
        "fake_dry_run_worker_only": (
            "fake_dry_run_supervisor_persistent_dispatch_worker" in scanned_text
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
            "s61_ae_operator_control_execution_worker_closure=pass "
            f"slice_range={evidence['slice_range']} "
            f"required_files={evidence['required_file_count']} "
            "boundary=ae_owned "
            "worker=fake_dry_run "
            "ag_projection=read_only "
            "smoke=test_db_worker_route"
        )
    failed = ",".join(evidence.get("failed_checks", evidence["checks"].keys()))
    return (
        "s61_ae_operator_control_execution_worker_closure=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed={failed}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close the S61 AE operator-control execution worker track."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s61_ae_operator_control_execution_worker_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
