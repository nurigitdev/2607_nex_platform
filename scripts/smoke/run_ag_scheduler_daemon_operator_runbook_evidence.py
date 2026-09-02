#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_scheduler_daemon_operator_runbook_evidence.v1"
RUNBOOK_PATH = "docs/runbooks/ag_scheduler_daemon_operations.md"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "services/nex-ae-api/README.md",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_scheduler_daemon_operations_boundary_audit.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "scripts/smoke/run_ag_scheduler_daemon_operator_runbook_evidence.py",
    "tests/test_ag_scheduler_daemon_operations_boundary_audit.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "tests/test_ag_scheduler_daemon_operator_runbook_evidence.py",
    "tests/test_nex_ag_artifact_operations.py",
    "docs/README.md",
    RUNBOOK_PATH,
    "docs/slices/0521_ag_scheduler_daemon_operations_boundary_audit.md",
    "docs/slices/0522_ag_ae_scheduler_daemon_client_adapter.md",
    "docs/slices/0523_ag_scheduler_daemon_operations_projection.md",
    "docs/slices/0524_ag_scheduler_daemon_operations_route.md",
    "docs/slices/0525_ag_scheduler_daemon_manual_tick_guardrail.md",
    "docs/slices/0526_ag_to_ae_scheduler_daemon_postgresql_smoke.md",
    "docs/slices/0527_ag_scheduler_daemon_dashboard_rollup.md",
    "docs/slices/0528_ag_scheduler_daemon_attention_classification.md",
    "docs/slices/0529_ag_scheduler_daemon_operator_runbook_evidence.md",
)

TOKEN_CHECKS = (
    (
        "runbook_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_scheduler_daemon_operator_runbook_evidence.py",
    ),
    (
        "daemon_attention_classifier",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "classify_artifact_retention_daemon_attention",
    ),
    (
        "daemon_attention_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION",
    ),
    (
        "automation_attention_rollup",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"daemon_attention_reason_codes"',
    ),
    (
        "automation_smoke_attention_summary",
        "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
        "daemon_attention=",
    ),
    (
        "protected_daemon_postgres_env_guard",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "runbook_manual_tick_route",
        RUNBOOK_PATH,
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
    ),
    (
        "runbook_protected_smoke_guard",
        RUNBOOK_PATH,
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE",
    ),
    (
        "runbook_ready_attention",
        RUNBOOK_PATH,
        "daemon_attention_status=READY",
    ),
    (
        "runbook_lease_attention",
        RUNBOOK_PATH,
        "LEASE_ATTENTION",
    ),
    (
        "runbook_queue_attention",
        RUNBOOK_PATH,
        "QUEUE_ATTENTION",
    ),
    (
        "runbook_batch_window_attention",
        RUNBOOK_PATH,
        "BATCH_WINDOW_ATTENTION",
    ),
    (
        "runbook_dispatch_attention",
        RUNBOOK_PATH,
        "DISPATCH_ATTENTION",
    ),
    (
        "runbook_control_policy_blocked",
        RUNBOOK_PATH,
        "CONTROL_POLICY_BLOCKED",
    ),
    (
        "runbook_redaction_guardrail",
        RUNBOOK_PATH,
        "Do not store raw service tokens, DB URLs, local storage paths",
    ),
    (
        "slice_0529_indexed",
        "docs/README.md",
        "0529_ag_scheduler_daemon_operator_runbook_evidence.md",
    ),
)

SLICE_DOCS = tuple(range(521, 530))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_ag_scheduler_daemon_operator_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    runbook_text = _read_text(root / RUNBOOK_PATH)
    quality_gate_text = _read_text(root / "scripts/quality/run_quality_gate.sh")
    status = "PASS" if _all_present(required_file_results, token_results) else "FAIL"
    evidence = {
        "runbook_evidence_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None if status == "PASS" else "runbook_checks_failed",
        "runbook": RUNBOOK_PATH,
        "slice_range": "0521-0530",
        "checks": {
            "required_files_present": all(
                item["present"] for item in required_file_results
            ),
            "token_checks_present": all(item["present"] for item in token_results),
            "slice_docs_contiguous": _slice_docs_contiguous(root),
            "quality_gate_hooked": (
                "run_ag_scheduler_daemon_operator_runbook_evidence.py"
                in quality_gate_text
            ),
            "runbook_redacted": _is_text_redacted(runbook_text),
        },
        "operator_runbook_matrix": {
            "protected_postgres_smoke_documented": (
                "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE"
                in runbook_text
            ),
            "manual_tick_guardrail_documented": (
                '"confirm_dispatch":true' in runbook_text
                and "confirm_worker_run=true" in runbook_text
            ),
            "attention_states_documented": all(
                token in runbook_text
                for token in (
                    "READY",
                    "LEASE_ATTENTION",
                    "QUEUE_ATTENTION",
                    "BATCH_WINDOW_ATTENTION",
                    "DISPATCH_ATTENTION",
                    "CONTROL_POLICY_BLOCKED",
                )
            ),
            "ae_owns_control_and_persistence": (
                "AE remains the system of record" in runbook_text
            ),
            "ag_read_only_dashboard": (
                "AG dashboard is metadata-only" in runbook_text
            ),
        },
        "redaction_summary": {
            "database_url_included": re.search(
                r"postgresql(?:\+\w+)?://[^\"'\s]+", runbook_text, re.IGNORECASE
            )
            is not None,
            "service_token_included": re.search(
                r"Bearer\s+(?!<redacted)[^\s]+", runbook_text, re.IGNORECASE
            )
            is not None,
            "provider_api_key_included": "ed6@c496em" in runbook_text,
            "storage_path_included": "/data/nex-platform" in runbook_text,
            "raw_artifact_payload_included": "raw_artifact_payload" in runbook_text,
            "raw_execution_payload_included": "raw_execution_payload" in runbook_text,
            "metadata_only": "metadata-only" in runbook_text,
            "protected_smoke_envs_required": (
                "protected smoke is opt-in" in runbook_text
            ),
        },
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    evidence["checks"]["runbook_matrix_ready"] = all(
        evidence["operator_runbook_matrix"].values()
    )
    evidence["checks"]["redaction_summary_safe"] = not any(
        value
        for key, value in evidence["redaction_summary"].items()
        if key
        in {
            "database_url_included",
            "service_token_included",
            "provider_api_key_included",
            "storage_path_included",
            "raw_artifact_payload_included",
            "raw_execution_payload_included",
        }
    )
    if not all(evidence["checks"].values()):
        evidence["status"] = "FAIL"
        evidence["failure_code"] = "runbook_checks_failed"
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


def _all_present(
    required_file_results: list[dict[str, Any]],
    token_results: list[dict[str, Any]],
) -> bool:
    return all(item["present"] for item in required_file_results) and all(
        item["present"] for item in token_results
    )


def _is_text_redacted(text: str) -> bool:
    return not any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


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
        f"runbook={evidence.get('runbook')} "
        f"required_files={evidence.get('required_file_count', len(REQUIRED_FILES))}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ag_scheduler_daemon_operator_runbook_evidence="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG scheduler daemon operator runbook evidence checks."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_scheduler_daemon_operator_runbook_evidence()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
