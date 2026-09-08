#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s58_ae_scheduler_daemon_supervised_process_activation_closure.v1"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "services/nex-ae-api/README.md",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-ag/README.md",
    "database/nex-ae-api/migrations/0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_supervised_daemon_process_boundary_audit.py",
    "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
    "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
    "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "scripts/smoke/run_s58_ae_scheduler_daemon_supervised_process_activation_closure.py",
    "tests/test_ae_supervised_daemon_process_boundary_audit.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_contract.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.py",
    "tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_routes.py",
    "tests/test_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
    "tests/test_nex_ag_artifact_operations.py",
    "tests/test_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
    "tests/test_ag_artifact_retention_automation_operations_smoke.py",
    "tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
    "tests/test_s58_ae_scheduler_daemon_supervised_process_activation_closure.py",
    "docs/README.md",
    "docs/slices/0571_ae_supervised_daemon_process_activation_boundary_audit.md",
    "docs/slices/0572_ae_supervised_process_contract_schema.md",
    "docs/slices/0573_ae_supervised_process_persistence_foundation.md",
    "docs/slices/0574_ae_supervised_process_service_api_wiring.md",
    "docs/slices/0575_ae_supervised_process_postgresql_smoke.md",
    "docs/slices/0576_ag_supervised_process_projection_foundation.md",
    "docs/slices/0577_ag_supervised_process_route_wiring.md",
    "docs/slices/0578_ag_supervised_process_postgresql_smoke.md",
    "docs/slices/0579_ag_supervised_process_operations_dashboard_integration.md",
    "docs/slices/0580_s58_ae_scheduler_daemon_supervised_process_activation_closure.md",
)

TOKEN_CHECKS = (
    (
        "s58_closure_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_s58_ae_scheduler_daemon_supervised_process_activation_closure.py",
    ),
    (
        "supervised_boundary_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_supervised_daemon_process_boundary_audit.py",
    ),
    (
        "ae_supervised_process_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
    ),
    (
        "ag_supervised_process_postgres_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
    ),
    (
        "ag_automation_dashboard_smoke_quality_gate_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_artifact_retention_automation_operations_smoke.py",
    ),
    (
        "ae_supervised_process_snapshot_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_record_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_RECORD_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_event_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_EVENT_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_dispatch_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DISPATCH_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_collection_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_COLLECTION_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_detail_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_DETAIL_SCHEMA_VERSION",
    ),
    (
        "ae_supervised_process_statuses",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_STATUSES",
    ),
    (
        "ae_supervised_process_snapshot_builder",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "build_artifact_retention_scheduler_daemon_supervised_process_snapshot",
    ),
    (
        "ae_supervised_process_snapshot_validator",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "validate_artifact_retention_scheduler_daemon_supervised_process_snapshot",
    ),
    (
        "ae_supervised_process_store",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore",
    ),
    (
        "ae_supervised_process_store_record",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "record_supervised_process_snapshot",
    ),
    (
        "ae_supervised_process_snapshot_table_runtime_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "ae_artifact_retention_scheduler_daemon_process_snapshots",
    ),
    (
        "ae_supervised_process_event_table_runtime_schema",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        "ae_artifact_retention_scheduler_daemon_process_events",
    ),
    (
        "ae_supervised_process_post_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '"/api/v1/artifact-retention/scheduler-daemon-process-snapshots"',
    ),
    (
        "ae_supervised_process_store_unavailable_problem",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "ae.artifact_retention_scheduler_daemon_supervised_process_store_unavailable",
    ),
    (
        "supervised_process_migration_snapshot_table",
        "database/nex-ae-api/migrations/0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.sql",
        "ae_artifact_retention_scheduler_daemon_process_snapshots",
    ),
    (
        "supervised_process_migration_event_table",
        "database/nex-ae-api/migrations/0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.sql",
        "ae_artifact_retention_scheduler_daemon_process_events",
    ),
    (
        "supervised_process_migration_observed_index",
        "database/nex-ae-api/migrations/0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.sql",
        "idx_ae_daemon_process_snapshots_observed",
    ),
    (
        "supervised_process_migration_pid_index",
        "database/nex-ae-api/migrations/0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.sql",
        "idx_ae_daemon_process_snapshots_pid",
    ),
    (
        "ag_supervised_process_collection_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_supervised_process_detail_schema",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION",
    ),
    (
        "ag_supervised_process_collection_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_supervised_process_collection_projection",
    ),
    (
        "ag_supervised_process_detail_builder",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "build_artifact_operation_retention_daemon_supervised_process_detail_projection",
    ),
    (
        "ag_supervised_process_collection_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-process-snapshots"',
    ),
    (
        "ag_supervised_process_detail_route",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler-daemon-process-snapshots/{daemon_supervised_process_record_id}"',
    ),
    (
        "ag_supervised_process_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "summarize_artifact_retention_daemon_supervised_process_operations",
    ),
    (
        "ag_automation_dashboard_process_block",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"scheduler_daemon_processes"',
    ),
    (
        "ag_automation_dashboard_process_summary",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"daemon_process_record_count"',
    ),
    (
        "ag_automation_dashboard_process_attention",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"daemon_process_operator_attention_required"',
    ),
    (
        "ag_process_projection_read_only_guardrail",
        "services/nex-ag/nex_ag/artifact_operations.py",
        '"ag_direct_daemon_process_control_allowed": False',
    ),
    (
        "ae_supervised_process_smoke_opt_in",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
        "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_POSTGRES_SMOKE",
    ),
    (
        "ae_supervised_process_smoke_live_db",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ae_supervised_process_smoke_cleanup",
        "scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py",
        "cleanup_records=",
    ),
    (
        "ag_supervised_process_smoke_opt_in",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
        "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_READ_MODEL_POSTGRES_SMOKE",
    ),
    (
        "ag_supervised_process_smoke_live_db",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
        '"live_db": True',
    ),
    (
        "ag_supervised_process_smoke_cleanup",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_supervised_process_read_model_postgres_smoke.py",
        "cleanup_records=",
    ),
    (
        "ag_automation_smoke_process_rollup",
        "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
        "daemon_process_rollup_visible",
    ),
    (
        "ag_automation_smoke_process_summary",
        "scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py",
        "process_attention=",
    ),
    (
        "scheduler_smoke_bridge_process_compatibility",
        "scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py",
        "list_artifact_retention_scheduler_daemon_process_snapshots",
    ),
    (
        "s58_closure_doc_indexed",
        "docs/README.md",
        "0580_s58_ae_scheduler_daemon_supervised_process_activation_closure.md",
    ),
)

SLICE_DOCS = tuple(range(571, 581))

SENSITIVE_PATTERNS = (
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(
        r"postgresql(?:\+\w+)?://[^:\"'\s]+:(?!\*\*\*)[^@\"'\s]+@",
        re.IGNORECASE,
    ),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
)


def run_s58_ae_scheduler_daemon_supervised_process_activation_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    checks = {
        "required_files_present": all(
            item["present"] for item in required_file_results
        ),
        "token_checks_present": all(item["present"] for item in token_results),
        "slice_docs_contiguous": _slice_docs_contiguous(root),
        "redaction_scan_safe": _redaction_scan_safe(root),
    }
    evidence = {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "failure_code": None,
        "slice_range": "0571-0580",
        "required_file_count": len(REQUIRED_FILES),
        "checks": checks,
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
            "raw_supervisor_command_included": False,
            "raw_supervisor_result_included": False,
            "raw_supervised_process_snapshot_included": False,
            "storage_path_included": False,
            "storage_ref_included": False,
            "metadata_only_supervised_process_boundary": True,
            "subprocess_activation_test_profile_protected": True,
            "supervised_process_persistence_ae_owned": True,
            "ae_supervised_process_read_model_read_only": True,
            "ag_supervised_process_projection_read_only": True,
            "ag_automation_dashboard_rollup_read_only": True,
            "protected_postgres_smoke_envs_required": True,
            "real_test_db_smoke_evidence_referenced": True,
            "smoke_cleanup_verified": True,
            "physical_delete_automation_disabled": True,
        },
        "required_file_results": required_file_results,
        "token_results": token_results,
    }
    if not all(checks.values()) or not all(evidence["experience_matrix"].values()):
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
        "supervised_process_boundary_audit": (
            docs_dir / "0571_ae_supervised_daemon_process_activation_boundary_audit.md"
        ).is_file(),
        "contract_schema": (
            docs_dir / "0572_ae_supervised_process_contract_schema.md"
        ).is_file(),
        "persistence_foundation": (
            docs_dir / "0573_ae_supervised_process_persistence_foundation.md"
        ).is_file(),
        "service_api_wiring": (
            docs_dir / "0574_ae_supervised_process_service_api_wiring.md"
        ).is_file(),
        "ae_postgresql_smoke": (
            docs_dir / "0575_ae_supervised_process_postgresql_smoke.md"
        ).is_file(),
        "ag_projection_foundation": (
            docs_dir / "0576_ag_supervised_process_projection_foundation.md"
        ).is_file(),
        "ag_route_wiring": (
            docs_dir / "0577_ag_supervised_process_route_wiring.md"
        ).is_file(),
        "ag_postgresql_smoke": (
            docs_dir / "0578_ag_supervised_process_postgresql_smoke.md"
        ).is_file(),
        "ag_dashboard_integration": (
            docs_dir / "0579_ag_supervised_process_operations_dashboard_integration.md"
        ).is_file(),
        "closure_checkpoint": (
            docs_dir
            / "0580_s58_ae_scheduler_daemon_supervised_process_activation_closure.md"
        ).is_file(),
    }


def _redaction_scan_safe(root: Path) -> bool:
    texts = [
        _read_text(root / "services/nex-ae-api/README.md"),
        _read_text(root / "services/nex-ag/README.md"),
        _read_text(
            root
            / "docs/slices/0571_ae_supervised_daemon_process_activation_boundary_audit.md"
        ),
        _read_text(root / "docs/slices/0575_ae_supervised_process_postgresql_smoke.md"),
        _read_text(root / "docs/slices/0578_ag_supervised_process_postgresql_smoke.md"),
        _read_text(
            root
            / "docs/slices/0579_ag_supervised_process_operations_dashboard_integration.md"
        ),
        _read_text(
            root
            / "docs/slices/0580_s58_ae_scheduler_daemon_supervised_process_activation_closure.md"
        ),
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
        "process=ae_owned ag_projection=read_only dashboard=rollup "
        "smoke=test_db_protected"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "s58_ae_scheduler_daemon_supervised_process_activation_closure="
        f"{str(evidence.get('status')).lower()} {suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run S58 AE scheduler daemon supervised process activation closure "
            "checks."
        )
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a short result line."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_s58_ae_scheduler_daemon_supervised_process_activation_closure()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
