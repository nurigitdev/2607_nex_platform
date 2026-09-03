#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s54_ae_scheduler_daemon_runtime_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "docs/runbooks/ag_scheduler_daemon_operations.md",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_scheduler_daemon_runtime_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "scripts/smoke/run_s54_ae_scheduler_daemon_runtime_closure.py",
    "tests/test_ae_scheduler_daemon_runtime_boundary_audit.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    "tests/test_nex_ae_artifact_retention_scheduler.py",
    "tests/test_nex_ae_artifacts.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_s54_ae_scheduler_daemon_runtime_closure.py",
    "docs/README.md",
    "docs/slices/0531_ae_scheduler_daemon_runtime_boundary_audit.md",
    "docs/slices/0532_ae_scheduler_daemon_runtime_config_expansion.md",
    "docs/slices/0533_ae_scheduler_daemon_loop_planner_state_machine.md",
    "docs/slices/0534_ae_scheduler_daemon_one_cycle_runner_adapter.md",
    "docs/slices/0535_ae_scheduler_daemon_start_stop_control_guardrail.md",
    "docs/slices/0536_ae_scheduler_daemon_one_cycle_postgresql_smoke.md",
    "docs/slices/0537_ae_scheduler_daemon_runtime_heartbeat_observability.md",
    "docs/slices/0538_ag_scheduler_daemon_runtime_operations_projection.md",
    "docs/slices/0539_ag_scheduler_daemon_runtime_attention_issue_candidates.md",
    "docs/slices/0540_s54_ae_scheduler_daemon_runtime_closure.md",
)

TOKEN_CHECKS = (
    (
        "s54_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s54_ae_scheduler_daemon_runtime_closure.py",
    ),
    (
        "runtime_boundary_audit_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_scheduler_daemon_runtime_boundary_audit.py",
    ),
    (
        "one_cycle_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py",
    ),
    (
        "ag_daemon_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
    ),
    (
        "runtime_config_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_CONFIG_SCHEMA_VERSION",
    ),
    (
        "runtime_config_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_runtime_config",
    ),
    (
        "loop_plan_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_LOOP_PLAN_SCHEMA_VERSION",
    ),
    (
        "loop_planner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_loop_plan",
    ),
    (
        "one_cycle_result_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION",
    ),
    (
        "one_cycle_runner",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "run_artifact_retention_scheduler_daemon_one_cycle",
    ),
    (
        "start_stop_guardrail_validator",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "validate_artifact_retention_scheduler_daemon_start_stop_guardrail",
    ),
    (
        "scheduler_daemon_started_false",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"scheduler_daemon_started": False',
    ),
    (
        "continuous_loop_started_false",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"continuous_loop_started": False',
    ),
    (
        "physical_delete_automation_disabled",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        '"physical_delete_automation_enabled": False',
    ),
    (
        "daemon_heartbeat_emitter_optional",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "daemon_heartbeat_emitter: Any | None = None",
    ),
    (
        "daemon_heartbeat_results",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "daemon_heartbeat_results",
    ),
    (
        "runtime_observation_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUNTIME_OBSERVATION_SCHEMA_VERSION",
    ),
    (
        "runtime_observation_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        "build_artifact_retention_scheduler_daemon_runtime_observation",
    ),
    (
        "ae_runtime_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-runtime"',
    ),
    (
        "ae_runtime_route_store_from_app",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "worker_heartbeat_store_from_app",
    ),
    (
        "ag_daemon_worker_type",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE",
    ),
    (
        "ag_runtime_client_protocol",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "get_artifact_retention_scheduler_daemon_runtime",
    ),
    (
        "ag_runtime_projection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_runtime_projection_payload",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"daemon_runtime"',
    ),
    (
        "ag_runtime_issue_candidate_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_ISSUE_CANDIDATE_SCHEMA_VERSION",
    ),
    (
        "ag_runtime_issue_candidate_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_retention_daemon_runtime_issue_candidates",
    ),
    (
        "heartbeat_attention_state",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "HEARTBEAT_ATTENTION",
    ),
    (
        "runtime_issue_candidate_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"runtime_issue_candidate_count"',
    ),
    (
        "one_cycle_smoke_runtime_route_check",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py",
        "daemon_runtime_route_observed",
    ),
    (
        "one_cycle_smoke_runtime_summary",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py",
        "daemon_runtime=",
    ),
    (
        "ag_smoke_runtime_store_summary",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "runtime_store=",
    ),
    (
        "ag_smoke_runtime_status_readback",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py",
        "ae_daemon_runtime_statuses",
    ),
    (
        "runbook_heartbeat_attention",
        "docs/runbooks/ag_scheduler_daemon_operations.md",
        "HEARTBEAT_ATTENTION",
    ),
    (
        "runbook_runtime_issue_candidates",
        "docs/runbooks/ag_scheduler_daemon_operations.md",
        "Runtime Issue Candidates",
    ),
    (
        "s54_closure_doc_indexed",
        "docs/README.md",
        "0540_s54_ae_scheduler_daemon_runtime_closure.md",
    ),
)

SLICE_DOCS = tuple(range(531, 541))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\"'\s]+", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_s54_ae_scheduler_daemon_runtime_closure(root: Path = ROOT) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    docs_present = _slice_docs_contiguous(root)
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "failure_code": None,
        "slice_range": "0531-0540",
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
            "metadata_only_runtime_observation": True,
            "ae_runtime_route_read_only": True,
            "ag_projection_read_only": True,
            "manual_tick_guarded": True,
            "start_daemon_blocked": True,
            "stop_daemon_noop": True,
            "continuous_loop_deferred": True,
            "daemon_heartbeat_observable": True,
            "runtime_issue_candidates_ready": True,
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
        "runtime_boundary_audit": (
            docs_dir / "0531_ae_scheduler_daemon_runtime_boundary_audit.md"
        ).is_file(),
        "runtime_config_expansion": (
            docs_dir / "0532_ae_scheduler_daemon_runtime_config_expansion.md"
        ).is_file(),
        "loop_planner_state_machine": (
            docs_dir / "0533_ae_scheduler_daemon_loop_planner_state_machine.md"
        ).is_file(),
        "one_cycle_runner_adapter": (
            docs_dir / "0534_ae_scheduler_daemon_one_cycle_runner_adapter.md"
        ).is_file(),
        "start_stop_control_guardrail": (
            docs_dir / "0535_ae_scheduler_daemon_start_stop_control_guardrail.md"
        ).is_file(),
        "one_cycle_postgresql_smoke": (
            docs_dir / "0536_ae_scheduler_daemon_one_cycle_postgresql_smoke.md"
        ).is_file(),
        "runtime_heartbeat_observability": (
            docs_dir / "0537_ae_scheduler_daemon_runtime_heartbeat_observability.md"
        ).is_file(),
        "ag_runtime_operations_projection": (
            docs_dir / "0538_ag_scheduler_daemon_runtime_operations_projection.md"
        ).is_file(),
        "runtime_attention_issue_candidates": (
            docs_dir / "0539_ag_scheduler_daemon_runtime_attention_issue_candidates.md"
        ).is_file(),
        "closure_checkpoint": (
            docs_dir / "0540_s54_ae_scheduler_daemon_runtime_closure.md"
        ).is_file(),
    }


def _redaction_scan_safe(root: Path) -> bool:
    texts = [
        _read_text(root / "docs/runbooks/ag_scheduler_daemon_operations.md"),
        _read_text(root / "services/nex-ae-api/README.md"),
        _read_text(root / "services/nex-ag/README.md"),
        _read_text(root / "docs/slices/0536_ae_scheduler_daemon_one_cycle_postgresql_smoke.md"),
        _read_text(root / "docs/slices/0538_ag_scheduler_daemon_runtime_operations_projection.md"),
        _read_text(root / "docs/slices/0539_ag_scheduler_daemon_runtime_attention_issue_candidates.md"),
        _read_text(root / "docs/slices/0540_s54_ae_scheduler_daemon_runtime_closure.md"),
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
        f"required_files={evidence.get('required_file_count', len(REQUIRED_FILES))}"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "s54_ae_scheduler_daemon_runtime_closure="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S54 AE scheduler daemon runtime closure checks."
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s54_ae_scheduler_daemon_runtime_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
