#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s53_ag_scheduler_daemon_operations_closure.v1"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "services/nex-ae-api/README.md",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_scheduler_daemon_operations_boundary_audit.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "scripts/smoke/run_ag_scheduler_daemon_operator_runbook_evidence.py",
    "scripts/smoke/run_s53_ag_scheduler_daemon_operations_closure.py",
    "tests/test_ag_scheduler_daemon_operations_boundary_audit.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "tests/test_ag_scheduler_daemon_operator_runbook_evidence.py",
    "tests/test_s53_ag_scheduler_daemon_operations_closure.py",
    "tests/test_nex_ag_artifact_operations.py",
    "docs/README.md",
    "docs/runbooks/ag_scheduler_daemon_operations.md",
    "docs/slices/0521_ag_scheduler_daemon_operations_boundary_audit.md",
    "docs/slices/0522_ag_ae_scheduler_daemon_client_adapter.md",
    "docs/slices/0523_ag_scheduler_daemon_operations_projection.md",
    "docs/slices/0524_ag_scheduler_daemon_operations_route.md",
    "docs/slices/0525_ag_scheduler_daemon_manual_tick_guardrail.md",
    "docs/slices/0526_ag_to_ae_scheduler_daemon_postgresql_smoke.md",
    "docs/slices/0527_ag_scheduler_daemon_dashboard_rollup.md",
    "docs/slices/0528_ag_scheduler_daemon_attention_classification.md",
    "docs/slices/0529_ag_scheduler_daemon_operator_runbook_evidence.md",
    "docs/slices/0530_s53_ag_scheduler_daemon_operations_closure.md",
)

TOKEN_CHECKS = (
    (
        "s53_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s53_ag_scheduler_daemon_operations_closure.py",
    ),
    (
        "s53_boundary_audit_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_scheduler_daemon_operations_boundary_audit.py",
    ),
    (
        "s53_runbook_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_scheduler_daemon_operator_runbook_evidence.py",
    ),
    (
        "ag_daemon_client_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_scheduler_daemon_config",
    ),
    (
        "ag_daemon_dispatch_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "dispatch_artifact_retention_scheduler_daemon_control",
    ),
    (
        "ag_daemon_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_daemon_attention_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION",
    ),
    (
        "ag_daemon_attention_classifier",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "classify_artifact_retention_daemon_attention",
    ),
    (
        "ag_daemon_projection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_projection",
    ),
    (
        "ag_daemon_operations_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/scheduler-daemon"',
    ),
    (
        "ag_daemon_manual_tick_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once"',
    ),
    (
        "manual_tick_confirmation_required",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "confirm_dispatch",
    ),
    (
        "start_daemon_blocked",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"start_daemon_allowed": False',
    ),
    (
        "continuous_loop_blocked",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"continuous_loop_allowed": False',
    ),
    (
        "ag_direct_database_write_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_database_write_allowed": False',
    ),
    (
        "ag_direct_job_enqueue_disallowed",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_job_enqueue_allowed": False',
    ),
    (
        "automation_dashboard_daemon_rollup",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler_daemon"',
    ),
    (
        "automation_dashboard_daemon_attention",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"daemon_attention_status"',
    ),
    (
        "automation_smoke_attention_summary",
        "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
        "daemon_attention=",
    ),
    (
        "ag_to_ae_daemon_postgres_guard",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "runbook_protected_smoke_opt_in",
        "docs/runbooks/ag_scheduler_daemon_operations.md",
        "The protected smoke is opt-in",
    ),
    (
        "runbook_attention_states",
        "docs/runbooks/ag_scheduler_daemon_operations.md",
        "LEASE_ATTENTION",
    ),
    (
        "runbook_metadata_only",
        "docs/runbooks/ag_scheduler_daemon_operations.md",
        "AG dashboard is metadata-only",
    ),
    (
        "s53_closure_doc_indexed",
        "docs/README.md",
        "0530_s53_ag_scheduler_daemon_operations_closure.md",
    ),
)

SLICE_DOCS = tuple(range(521, 531))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_s53_ag_scheduler_daemon_operations_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    docs_present = _slice_docs_contiguous(root)
    status = (
        "PASS"
        if all(item["present"] for item in required_file_results)
        and all(item["present"] for item in token_results)
        and docs_present
        else "FAIL"
    )
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "closure_checks_failed",
        "slice_range": "0521-0530",
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
            "metadata_only_dashboard": True,
            "ag_projection_read_only": True,
            "route_control_ae_owned": True,
            "manual_tick_guarded": True,
            "start_daemon_deferred": True,
            "continuous_loop_deferred": True,
            "attention_classification_ready": True,
            "operator_runbook_evidence_ready": True,
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
        "operations_boundary_audit": (
            docs_dir / "0521_ag_scheduler_daemon_operations_boundary_audit.md"
        ).is_file(),
        "ae_daemon_client_adapter": (
            docs_dir / "0522_ag_ae_scheduler_daemon_client_adapter.md"
        ).is_file(),
        "daemon_operations_projection": (
            docs_dir / "0523_ag_scheduler_daemon_operations_projection.md"
        ).is_file(),
        "daemon_operations_route": (
            docs_dir / "0524_ag_scheduler_daemon_operations_route.md"
        ).is_file(),
        "manual_tick_guardrail": (
            docs_dir / "0525_ag_scheduler_daemon_manual_tick_guardrail.md"
        ).is_file(),
        "ag_to_ae_daemon_postgresql_smoke": (
            docs_dir / "0526_ag_to_ae_scheduler_daemon_postgresql_smoke.md"
        ).is_file(),
        "daemon_dashboard_rollup": (
            docs_dir / "0527_ag_scheduler_daemon_dashboard_rollup.md"
        ).is_file(),
        "daemon_attention_classification": (
            docs_dir / "0528_ag_scheduler_daemon_attention_classification.md"
        ).is_file(),
        "operator_runbook_evidence": (
            docs_dir / "0529_ag_scheduler_daemon_operator_runbook_evidence.md"
        ).is_file(),
        "closure_checkpoint": (
            docs_dir / "0530_s53_ag_scheduler_daemon_operations_closure.md"
        ).is_file(),
    }


def _redaction_scan_safe(root: Path) -> bool:
    texts = [
        _read_text(root / "docs/runbooks/ag_scheduler_daemon_operations.md"),
        _read_text(root / "docs/slices/0529_ag_scheduler_daemon_operator_runbook_evidence.md"),
        _read_text(root / "docs/slices/0530_s53_ag_scheduler_daemon_operations_closure.md"),
    ]
    return not any(pattern.search(text) for pattern in SENSITIVE_PATTERNS for text in texts)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    checks = evidence.get("checks", {})
    failing_checks = [
        key for key, passed in checks.items() if passed is not True
    ]
    suffix = (
        f"slice_range={evidence.get('slice_range')} "
        f"required_files={evidence.get('required_file_count', len(REQUIRED_FILES))}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "s53_ag_scheduler_daemon_operations_closure="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S53 AG scheduler daemon operations closure checks."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s53_ag_scheduler_daemon_operations_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
