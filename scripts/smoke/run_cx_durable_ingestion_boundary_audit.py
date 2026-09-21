#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_durable_ingestion_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0920_s92_cx_private_content_ownership_closure.md",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/processing.py",
    "services/nex-cx/nex_cx/main.py",
    "services/_shared/nex_runtime/jobs.py",
    "database/nex-cx/migrations/0182_cx_processing_run_step_persistence.sql",
    "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0921_cx_durable_ingestion_boundary_audit.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s92_handoff",
        "docs/slices/0920_s92_cx_private_content_ownership_closure.md",
        "READY_FOR_S93",
    ),
    EvidenceToken(
        "volatile_documents",
        "services/nex-cx/nex_cx/ingestion.py",
        "documents: dict[str, dict[str, Any]]",
    ),
    EvidenceToken(
        "volatile_ingestion_jobs",
        "services/nex-cx/nex_cx/ingestion.py",
        "jobs: dict[str, dict[str, Any]]",
    ),
    EvidenceToken(
        "durable_job_queue",
        "services/nex-cx/nex_cx/processing.py",
        "run_cx_document_processing_worker_once",
    ),
    EvidenceToken(
        "durable_job_table",
        "services/_shared/nex_runtime/jobs.py",
        "INSERT INTO service_jobs",
    ),
    EvidenceToken(
        "processing_run_persistence",
        "database/nex-cx/migrations/0182_cx_processing_run_step_persistence.sql",
        "cx_document_processing_runs",
    ),
    EvidenceToken(
        "owner_lineage",
        "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
        "ck_cx_proc_runs_owner_lineage",
    ),
    EvidenceToken(
        "runtime_singleton",
        "services/nex-cx/nex_cx/main.py",
        "DEFAULT_INGESTION_STORE",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_durable_ingestion_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0921_cx_durable_ingestion_boundary_audit.md",
    ),
)


def run_cx_durable_ingestion_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": relative_path, "present": (root / relative_path).is_file()}
        for relative_path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s92_handoff_bound": _group_present(tokens, "s92_handoff"),
        "volatile_ingestion_state_confirmed": all(
            _group_present(tokens, group)
            for group in ("volatile_documents", "volatile_ingestion_jobs")
        ),
        "durable_queue_reuse_confirmed": all(
            _group_present(tokens, group)
            for group in ("durable_job_queue", "durable_job_table")
        ),
        "durable_result_lineage_confirmed": all(
            _group_present(tokens, group)
            for group in ("processing_run_persistence", "owner_lineage")
        ),
        "composition_refactor_trigger_confirmed": _group_present(
            tokens, "runtime_singleton"
        ),
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0921",
        "requirement": "S93",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_durable_ingestion_boundary_failed",
        "boundary_readiness": "GAPS_CONFIRMED" if passed else "AUDIT_FAILED",
        "decision": {
            "execution_queue": "existing_service_jobs_job_queue",
            "orchestration_system_of_record": "cx_ingest_runs",
            "orchestration_table_name_length": len("cx_ingest_runs"),
            "checkpoint_granularity": "pipeline_step",
            "private_payload_policy": "s92_capability_ports_only",
            "worker_model": "bounded_claim_execute_checkpoint",
            "recovery_model": "lease_expiry_and_checkpoint_resume",
            "database_smoke_target": "actual_nex_cx_test",
            "dgx_live_provider_required": False,
            "new_table_required_in_slice": False,
            "existing_records_mutated_in_slice": False,
        },
        "summary": {
            "volatile_state_count": 2,
            "durable_foundation_count": 3,
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "durability_gaps": [
            "ingestion_run_state_is_process_local",
            "step_checkpoint_is_not_claimable_after_restart",
            "worker_lease_and_stale_recovery_are_not_ingestion_specific",
            "upload_admission_and_processing_queue_are_not_one_durable_transaction",
        ],
        "slice_plan": [
            "0921_boundary_audit",
            "0922_orchestration_state_transition_contract",
            "0923_durable_run_repository_and_migration",
            "0924_durable_ingestion_admission",
            "0925_checkpointed_step_coordinator",
            "0926_worker_retry_and_recovery",
            "0927_restart_hydration_and_read_model",
            "0928_protected_api_contract_observability",
            "0929_postgres_smoke_and_privacy_runbook",
            "0930_s93_closure",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0922",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(
        item.get("group") == group and item.get("present") is True
        for item in items
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    decision = evidence.get("decision") or {}
    return (
        "cx_durable_ingestion_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"volatile={summary.get('volatile_state_count', 0)} "
        f"durable={summary.get('durable_foundation_count', 0)} "
        f"table={decision.get('orchestration_system_of_record', 'unknown')} "
        f"dgx_required={decision.get('dgx_live_provider_required', False)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_durable_ingestion_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
