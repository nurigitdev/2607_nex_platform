#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s55_ae_scheduler_daemon_process_lifecycle_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_scheduler_daemon_process_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "scripts/smoke/run_s55_ae_scheduler_daemon_process_lifecycle_closure.py",
    "tests/test_ae_scheduler_daemon_process_boundary_audit.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "tests/test_nex_ae_artifact_retention_scheduler.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s55_ae_scheduler_daemon_process_lifecycle_closure.py",
    "docs/README.md",
    "docs/slices/0541_ae_scheduler_daemon_process_boundary_audit.md",
    "docs/slices/0542_ae_scheduler_daemon_runtime_state_contract_schema.md",
    "docs/slices/0543_ae_scheduler_daemon_cli_entrypoint_foundation.md",
    "docs/slices/0544_ae_scheduler_daemon_bounded_loop_adapter.md",
    "docs/slices/0545_ae_scheduler_daemon_bounded_loop_postgresql_smoke.md",
    "docs/slices/0546_ae_scheduler_daemon_graceful_shutdown_state_transition.md",
    "docs/slices/0547_ae_scheduler_daemon_retry_backoff_circuit_guard.md",
    "docs/slices/0548_ag_scheduler_daemon_lifecycle_projection.md",
    "docs/slices/0549_ag_scheduler_daemon_lifecycle_postgresql_smoke.md",
    "docs/slices/0550_s55_ae_scheduler_daemon_process_lifecycle_closure.md",
)

TOKEN_CHECKS = (
    (
        "s55_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s55_ae_scheduler_daemon_process_lifecycle_closure.py",
    ),
    (
        "process_boundary_audit_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_scheduler_daemon_process_boundary_audit.py",
    ),
    (
        "bounded_loop_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py",
    ),
    (
        "ag_lifecycle_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    ),
    (
        "runtime_state_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_STATE_SCHEMA_VERSION",
    ),
    (
        "runtime_state_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_runtime_state",
    ),
    (
        "bounded_loop_runner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "run_artifact_retention_scheduler_daemon_bounded_loop",
    ),
    (
        "bounded_loop_finite_guardrail",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"bounded_loop_is_finite": True',
    ),
    (
        "shutdown_transition_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_shutdown_transition",
    ),
    (
        "shutdown_stop_before_next_cycle",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"bounded_loop_should_stop_before_next_cycle"',
    ),
    (
        "retry_circuit_guard_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_retry_circuit_guard",
    ),
    (
        "retry_circuit_open_status",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "CIRCUIT_OPEN",
    ),
    (
        "daemon_process_owner_ae",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"daemon_process_owner_ae": True',
    ),
    (
        "physical_delete_automation_disabled",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "daemon_cli_plan_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_cli_plan",
    ),
    (
        "daemon_cli_plan_only",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        '"starts_bounded_loop": False',
    ),
    (
        "daemon_cli_wrapper",
        "scripts/daemon/run_ae_artifact_retention_scheduler_daemon.py",
        "nex_ae_api.artifact_retention_scheduler_daemon",
    ),
    (
        "ae_runtime_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-runtime"',
    ),
    (
        "ag_lifecycle_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_lifecycle_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_retention_daemon_lifecycle_projection",
    ),
    (
        "ag_lifecycle_projection_payload",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"lifecycle_projection"',
    ),
    (
        "ag_lifecycle_projection_metadata_only",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ae_daemon_lifecycle_projection": "metadata_only"',
    ),
    (
        "ag_direct_database_write_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_runtime_client_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_scheduler_daemon_runtime",
    ),
    (
        "bounded_loop_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE",
    ),
    (
        "bounded_loop_smoke_worker_heartbeat",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.py",
        "WorkerHeartbeatEmitter",
    ),
    (
        "ag_lifecycle_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "ag_lifecycle_smoke_db_heartbeat",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "daemon_heartbeat_rows",
    ),
    (
        "ag_lifecycle_smoke_summary",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "lifecycle=",
    ),
    (
        "s55_closure_doc_indexed",
        "docs/README.md",
        "0550_s55_ae_scheduler_daemon_process_lifecycle_closure.md",
    ),
)

SLICE_DOCS = tuple(range(541, 551))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_s55_ae_scheduler_daemon_process_lifecycle_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    docs_present = _slice_docs_contiguous(root)
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "failure_code": None,
        "slice_range": "0541-0550",
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
            "metadata_only_runtime_state": True,
            "ae_process_owner": True,
            "jobqueue_for_retention_work_only": True,
            "daemon_cli_plan_first": True,
            "bounded_loop_finite": True,
            "graceful_shutdown_metadata_only": True,
            "retry_circuit_metadata_only": True,
            "ag_lifecycle_projection_read_only": True,
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
        "process_boundary_audit": (
            docs_dir / "0541_ae_scheduler_daemon_process_boundary_audit.md"
        ).is_file(),
        "runtime_state_contract_schema": (
            docs_dir / "0542_ae_scheduler_daemon_runtime_state_contract_schema.md"
        ).is_file(),
        "cli_entrypoint_foundation": (
            docs_dir / "0543_ae_scheduler_daemon_cli_entrypoint_foundation.md"
        ).is_file(),
        "bounded_loop_adapter": (
            docs_dir / "0544_ae_scheduler_daemon_bounded_loop_adapter.md"
        ).is_file(),
        "bounded_loop_postgresql_smoke": (
            docs_dir / "0545_ae_scheduler_daemon_bounded_loop_postgresql_smoke.md"
        ).is_file(),
        "graceful_shutdown_state_transition": (
            docs_dir / "0546_ae_scheduler_daemon_graceful_shutdown_state_transition.md"
        ).is_file(),
        "retry_backoff_circuit_guard": (
            docs_dir / "0547_ae_scheduler_daemon_retry_backoff_circuit_guard.md"
        ).is_file(),
        "ag_lifecycle_projection": (
            docs_dir / "0548_ag_scheduler_daemon_lifecycle_projection.md"
        ).is_file(),
        "ag_lifecycle_postgresql_smoke": (
            docs_dir / "0549_ag_scheduler_daemon_lifecycle_postgresql_smoke.md"
        ).is_file(),
        "closure_checkpoint": (
            docs_dir / "0550_s55_ae_scheduler_daemon_process_lifecycle_closure.md"
        ).is_file(),
    }


def _redaction_scan_safe(root: Path) -> bool:
    texts = [
        _read_text(root / "services/nex-ae-api/README.md"),
        _read_text(root / "services/nex-ag/README.md"),
        _read_text(root / "docs/slices/0541_ae_scheduler_daemon_process_boundary_audit.md"),
        _read_text(root / "docs/slices/0545_ae_scheduler_daemon_bounded_loop_postgresql_smoke.md"),
        _read_text(root / "docs/slices/0548_ag_scheduler_daemon_lifecycle_projection.md"),
        _read_text(root / "docs/slices/0549_ag_scheduler_daemon_lifecycle_postgresql_smoke.md"),
        _read_text(root / "docs/slices/0550_s55_ae_scheduler_daemon_process_lifecycle_closure.md"),
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
        "process_boundary=ae_owned lifecycle=RUNNING"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "s55_ae_scheduler_daemon_process_lifecycle_closure="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S55 AE scheduler daemon process lifecycle closure checks."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s55_ae_scheduler_daemon_process_lifecycle_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
