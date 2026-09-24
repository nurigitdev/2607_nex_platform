#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_async_generation_recovery_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0981_s98_cx_worker_operations_resilience_closure.md",
    "services/nex-cx/nex_cx/generation.py",
    "services/nex-cx/nex_cx/generation_runtime.py",
    "services/nex-cx/nex_cx/generation_read_model.py",
    "services/nex-cx/nex_cx/worker_runtime.py",
    "services/nex-cx/nex_cx/worker_reconciliation.py",
    "services/_shared/nex_runtime/jobs.py",
    "services/nex-cx/nex_cx/private_content.py",
    "docs/development_process.md",
    "docs/slices/0982_cx_async_generation_recovery_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s98_handoff",
        "docs/slices/0981_s98_cx_worker_operations_resilience_closure.md",
        "READY_FOR_S99",
    ),
    EvidenceToken(
        "sync_generation_runtime",
        "services/nex-cx/nex_cx/generation_runtime.py",
        "class GroundedGenerationRuntime",
    ),
    EvidenceToken(
        "owner_private_output",
        "services/nex-cx/nex_cx/generation_runtime.py",
        "persist_generation_output",
    ),
    EvidenceToken(
        "restart_safe_read_model",
        "services/nex-cx/nex_cx/generation_read_model.py",
        "class GenerationReadModel",
    ),
    EvidenceToken(
        "bounded_worker",
        "services/nex-cx/nex_cx/worker_runtime.py",
        "def run_bounded_worker_batch",
    ),
    EvidenceToken(
        "worker_reconciliation",
        "services/nex-cx/nex_cx/worker_reconciliation.py",
        "def apply_worker_reconciliation_plan",
    ),
    EvidenceToken(
        "atomic_job_claim",
        "services/_shared/nex_runtime/jobs.py",
        "FOR UPDATE SKIP LOCKED",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0982_cx_async_generation_recovery_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "async_execution_contract_missing": (
        "services/nex-cx/nex_cx/async_generation_contracts.py"
    ),
    "durable_private_request_envelope_missing": (
        "services/nex-cx/nex_cx/generation_request_store.py"
    ),
    "idempotent_queue_admission_missing": (
        "services/nex-cx/nex_cx/async_generation.py"
    ),
    "async_generation_worker_missing": (
        "services/nex-cx/nex_cx/async_generation_worker.py"
    ),
    "generation_retry_recovery_missing": (
        "services/nex-cx/nex_cx/async_generation_recovery.py"
    ),
    "owner_scoped_operations_api_missing": (
        "services/nex-cx/nex_cx/async_generation_operations.py"
    ),
    "async_contract_openapi_missing": (
        "contracts/schemas/generation/cx_async_generation_job.v1.schema.json"
    ),
    "postgres_recovery_evidence_missing": (
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py"
    ),
}

GAP_SLICES = {
    "async_execution_contract_missing": "0983",
    "durable_private_request_envelope_missing": "0984",
    "idempotent_queue_admission_missing": "0985",
    "async_generation_worker_missing": "0986",
    "generation_retry_recovery_missing": "0987",
    "owner_scoped_operations_api_missing": "0988",
    "async_contract_openapi_missing": "0989",
    "postgres_recovery_evidence_missing": "0990",
}


def run_cx_async_generation_recovery_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
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
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s98_handoff_bound": _group_present(tokens, "s98_handoff"),
        "durable_generation_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "sync_generation_runtime",
                "owner_private_output",
                "restart_safe_read_model",
            )
        ),
        "worker_resilience_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "bounded_worker",
                "worker_reconciliation",
                "atomic_job_claim",
            )
        ),
        "tiered_quality_cadence_confirmed": _group_present(tokens, "tiered_gate"),
        "implementation_gaps_accounted_for": len(gap_states) == 8,
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
    next_slice = next(
        (GAP_SLICES[name] for name, state in gap_states.items() if state == "OPEN"),
        "0991",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0982",
        "requirement": "S99",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_CURRENT" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 7,
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": list(gap_states),
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "0982_boundary_audit",
            "0983_async_execution_job_contract",
            "0984_durable_private_request_envelope",
            "0985_idempotent_queue_admission",
            "0986_mock_provider_worker_execution",
            "0987_retry_cancellation_crash_recovery",
            "0988_owner_scoped_operations_api",
            "0989_contract_openapi_observability",
            "0990_postgres_recovery_smoke",
            "0991_s99_closure",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_asynchronous_grounded_generation_execution_recovery",
        "queue_policy": "reuse_service_jobs_with_deterministic_idempotent_job",
        "request_storage_policy": "owner_private_immutable_envelope",
        "worker_policy": "reuse_s98_bounded_worker_and_lease_reconciliation",
        "sync_api_policy": "preserve_existing_synchronous_route",
        "new_table_expected": False,
        "postgres_required_now": False,
        "postgres_required_slice": "0990",
        "remote_provider_required_now": False,
        "remote_provider_evidence": "deferred_until_connectivity_available",
        "quality_cadence": {
            "slice_gate": "0982-0991",
            "checkpoint_gate": "0986",
            "full_gate": "0991",
        },
        "deferred_scope": [
            "live_remote_provider_smoke",
            "streaming_transport",
            "multi_attempt_citation_repair",
            "production_provider_slo_baselines",
        ],
    }


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    return any(item["group"] == group and item["present"] for item in tokens)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    summary = result.get("summary", {})
    decision = result.get("decision", {})
    return (
        "cx_async_generation_recovery_boundary="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"scope={decision.get('feature_scope', 'unknown')} "
        f"remote_required_now={decision.get('remote_provider_required_now', False)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_async_generation_recovery_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
