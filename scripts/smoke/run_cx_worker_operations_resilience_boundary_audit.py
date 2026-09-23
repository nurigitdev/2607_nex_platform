#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_worker_operations_resilience_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0970_s97_cx_grounded_generation_runtime_closure.md",
    "services/_shared/nex_runtime/jobs.py",
    "services/_shared/nex_runtime/worker_runner.py",
    "services/_shared/nex_runtime/worker_heartbeats.py",
    "services/nex-cx/nex_cx/ingestion_worker.py",
    "services/nex-cx/nex_cx/ingestion_read_model.py",
    "services/nex-cx/nex_cx/ingestion_operations.py",
    "docs/development_process.md",
    "docs/slices/0972_cx_worker_operations_resilience_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s97_handoff",
        "docs/slices/0970_s97_cx_grounded_generation_runtime_closure.md",
        "READY_FOR_S98",
    ),
    EvidenceToken(
        "atomic_claim",
        "services/_shared/nex_runtime/jobs.py",
        "FOR UPDATE SKIP LOCKED",
    ),
    EvidenceToken(
        "retry_policy",
        "services/_shared/nex_runtime/jobs.py",
        "def plan_job_retry",
    ),
    EvidenceToken(
        "dead_letter_replay",
        "services/_shared/nex_runtime/jobs.py",
        "def plan_dead_letter_replay",
    ),
    EvidenceToken(
        "bounded_runner",
        "services/_shared/nex_runtime/worker_runner.py",
        "def run_worker_batch",
    ),
    EvidenceToken(
        "runner_heartbeat",
        "services/_shared/nex_runtime/worker_runner.py",
        "WorkerHeartbeatEmitter",
    ),
    EvidenceToken(
        "lifecycle_statuses",
        "services/_shared/nex_runtime/worker_heartbeats.py",
        "STOPPING = \"STOPPING\"",
    ),
    EvidenceToken(
        "ingestion_lease_recovery",
        "services/nex-cx/nex_cx/ingestion_worker.py",
        "def recover_expired_ingestion_job",
    ),
    EvidenceToken(
        "restart_plan",
        "services/nex-cx/nex_cx/ingestion_read_model.py",
        "def build_ingestion_restart_plan",
    ),
    EvidenceToken(
        "recovery_route",
        "services/nex-cx/nex_cx/ingestion_operations.py",
        '"/internal/v1/ingestion/jobs/{job_id}/recover-expired-lease"',
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0972_cx_worker_operations_resilience_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "worker_execution_contract_missing": (
        "services/nex-cx/nex_cx/worker_contracts.py"
    ),
    "durable_claim_lease_controls_missing": (
        "services/nex-cx/nex_cx/worker_leases.py"
    ),
    "bounded_cancellation_runtime_missing": (
        "services/nex-cx/nex_cx/worker_runtime.py"
    ),
    "retry_poison_operations_missing": (
        "services/nex-cx/nex_cx/worker_resilience.py"
    ),
    "worker_lifecycle_shutdown_missing": (
        "services/nex-cx/nex_cx/worker_lifecycle.py"
    ),
    "restart_reconciliation_missing": (
        "services/nex-cx/nex_cx/worker_reconciliation.py"
    ),
    "worker_operations_api_missing": (
        "services/nex-cx/nex_cx/worker_operations.py"
    ),
    "postgres_concurrency_recovery_evidence_missing": (
        "scripts/smoke/run_cx_worker_operations_postgres_smoke.py"
    ),
}

GAP_SLICES = {
    "worker_execution_contract_missing": "0973",
    "durable_claim_lease_controls_missing": "0974",
    "bounded_cancellation_runtime_missing": "0975",
    "retry_poison_operations_missing": "0976",
    "worker_lifecycle_shutdown_missing": "0977",
    "restart_reconciliation_missing": "0978",
    "worker_operations_api_missing": "0979",
    "postgres_concurrency_recovery_evidence_missing": "0980",
}


def run_cx_worker_operations_resilience_boundary_audit(
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
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    gap_checks = {
        name: state in {"OPEN", "RESOLVED"}
        for name, state in gap_states.items()
    }
    next_slice = next(
        (
            GAP_SLICES[name]
            for name, state in gap_states.items()
            if state == "OPEN"
        ),
        "0981",
    )
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s97_handoff_bound": _group_present(tokens, "s97_handoff"),
        "jobqueue_resilience_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in ("atomic_claim", "retry_policy", "dead_letter_replay")
        ),
        "worker_runtime_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "bounded_runner",
                "runner_heartbeat",
                "lifecycle_statuses",
            )
        ),
        "cx_ingestion_recovery_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "ingestion_lease_recovery",
                "restart_plan",
                "recovery_route",
            )
        ),
        "tiered_quality_cadence_confirmed": _group_present(
            tokens, "tiered_gate"
        ),
        "implementation_gaps_accounted_for": all(gap_checks.values()),
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
        "slice": "0972",
        "requirement": "S98",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_worker_operations_resilience_boundary_failed"
        ),
        "boundary_readiness": "BOUNDARY_CURRENT" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 6,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": list(gap_states),
        "slice_plan": [
            "0972_boundary_audit",
            "0973_worker_execution_state_contract",
            "0974_durable_claim_lease_concurrency",
            "0975_bounded_runner_cancellation",
            "0976_retry_backoff_poison_operations",
            "0977_heartbeat_readiness_graceful_shutdown",
            "0978_restart_recovery_reconciliation",
            "0979_operations_api_observability",
            "0980_postgres_concurrency_recovery_smoke",
            "0981_s98_closure",
        ],
        "checks": checks,
        "gap_checks": gap_checks,
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_worker_operations_and_resilience",
        "queue_policy": "reuse_service_jobs_and_atomic_skip_locked_claim",
        "worker_process_policy": "external_bounded_process_not_queue_controlled",
        "execution_policy": "bounded_cooperative_cancellation",
        "concurrency_policy": "database_claim_plus_workload_lease",
        "retry_policy": "bounded_backoff_then_dead_letter",
        "recovery_policy": "heartbeat_and_lease_reconciliation",
        "observability_policy": "metadata_only_events_logs_heartbeats",
        "database_policy": "reuse_service_jobs_and_service_worker_heartbeats",
        "new_table_expected": False,
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "postgres_required_now": False,
        "postgres_required_slice": "0980",
        "remote_provider_required_now": False,
        "remote_provider_required_requirement": "async_grounded_generation",
        "quality_cadence": {
            "slice_gate": "0972-0981",
            "checkpoint_gate": "0976",
            "full_gate": "0981",
        },
        "deferred_scope": [
            "asynchronous_grounded_generation_execution",
            "streaming_generation_transport",
            "automatic_multi_attempt_citation_repair",
            "production_provider_slo_baseline",
        ],
    }


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    matches = [item["present"] for item in tokens if item["group"] == group]
    return bool(matches) and all(matches)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(result: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    decision = result.get("decision") or {}
    return (
        "cx_worker_operations_resilience_boundary="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"scope={decision.get('feature_scope', 'unknown')} "
        f"postgres_required_now={decision.get('postgres_required_now', True)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_worker_operations_resilience_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
