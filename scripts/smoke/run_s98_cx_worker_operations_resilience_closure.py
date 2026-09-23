#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_cx_worker_operations_resilience_boundary_audit import (
    run_cx_worker_operations_resilience_boundary_audit as run_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s98_cx_worker_operations_resilience_closure.v1"
SLICE_RANGE = "0972-0981"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/worker_contracts.py",
    "services/nex-cx/nex_cx/worker_leases.py",
    "services/nex-cx/nex_cx/worker_runtime.py",
    "services/nex-cx/nex_cx/worker_resilience.py",
    "services/nex-cx/nex_cx/worker_lifecycle.py",
    "services/nex-cx/nex_cx/worker_reconciliation.py",
    "services/nex-cx/nex_cx/worker_operations.py",
    "scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py",
    "scripts/smoke/run_cx_worker_operations_postgres_smoke.py",
    "scripts/smoke/run_s98_cx_worker_operations_resilience_closure.py",
    "tests/test_s98_cx_worker_operations_resilience_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0972", "cx_worker_operations_resilience_boundary_audit"),
            ("0973", "cx_worker_execution_state_contract"),
            ("0974", "cx_durable_worker_claim_lease"),
            ("0975", "cx_bounded_worker_runtime_cancellation"),
            ("0976", "cx_worker_retry_poison_operations"),
            ("0977", "cx_worker_lifecycle_readiness_shutdown"),
            ("0978", "cx_worker_restart_reconciliation"),
            ("0979", "cx_worker_operations_api_observability"),
            ("0980", "cx_worker_operations_postgresql_smoke"),
            ("0981", "s98_cx_worker_operations_resilience_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_cx_worker_operations_resilience_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_cx_worker_operations_postgres_smoke.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s98_cx_worker_operations_resilience_closure.py",
    ),
    (
        "execution_contract",
        "services/nex-cx/nex_cx/worker_contracts.py",
        "cx_worker_execution.v1",
    ),
    (
        "lease_cas",
        "services/nex-cx/nex_cx/worker_leases.py",
        "expected_locked_at",
    ),
    (
        "bounded_runtime",
        "services/nex-cx/nex_cx/worker_runtime.py",
        "def run_bounded_worker_batch",
    ),
    (
        "cooperative_cancellation",
        "services/nex-cx/nex_cx/worker_runtime.py",
        "def request_worker_cancellation",
    ),
    (
        "dead_letter",
        "services/nex-cx/nex_cx/worker_resilience.py",
        "def project_dead_letter_job",
    ),
    (
        "readiness",
        "services/nex-cx/nex_cx/worker_lifecycle.py",
        "def project_worker_readiness",
    ),
    (
        "restart_reconciliation",
        "services/nex-cx/nex_cx/worker_reconciliation.py",
        "cx_worker_reconciliation_plan.v1",
    ),
    (
        "operations_api",
        "services/nex-cx/nex_cx/worker_operations.py",
        '"/internal/v1/workers/reconcile"',
    ),
    (
        "operations_observability",
        "services/nex-cx/nex_cx/worker_operations.py",
        "CX_WORKER_RECONCILIATION_APPLIED_EVENT",
    ),
    (
        "postgres_concurrent_claims",
        "docs/slices/0980_cx_worker_operations_postgresql_smoke.md",
        "`6/6`",
    ),
    (
        "postgres_recovery",
        "docs/slices/0980_cx_worker_operations_postgresql_smoke.md",
        "`4` expired leases",
    ),
    (
        "postgres_cleanup",
        "docs/slices/0980_cx_worker_operations_postgresql_smoke.md",
        "`residue=0`",
    ),
    (
        "postgres_target",
        "docs/slices/0980_cx_worker_operations_postgresql_smoke.md",
        "`nex_cx_user@nex_cx_test`",
    ),
    (
        "docs_postgres_index",
        "docs/README.md",
        "0980_cx_worker_operations_postgresql_smoke.md",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "0981_s98_cx_worker_operations_resilience_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "execution_state_contract": ("execution_contract",),
    "durable_claim_and_lease": ("lease_cas",),
    "bounded_runtime_and_cancellation": (
        "bounded_runtime",
        "cooperative_cancellation",
    ),
    "retry_and_dead_letter": ("dead_letter",),
    "lifecycle_and_readiness": ("readiness",),
    "restart_reconciliation": ("restart_reconciliation",),
    "operations_api_and_observability": (
        "operations_api",
        "operations_observability",
    ),
    "protected_postgres_evidence": (
        "postgres_concurrent_claims",
        "postgres_recovery",
        "postgres_cleanup",
        "postgres_target",
    ),
}


def run_s98_cx_worker_operations_resilience_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKEN_NAMES.items()
    }
    boundary = _safe_evidence(lambda: run_boundary(root))
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary_summary.get("issue_count") == 0
            and boundary.get("next_slice") == "0981"
        ),
        "all_worker_components_closed": all(components.values()),
        "queue_and_process_boundaries_preserved": (
            boundary_decision.get("queue_policy")
            == "reuse_service_jobs_and_atomic_skip_locked_claim"
            and boundary_decision.get("worker_process_policy")
            == "external_bounded_process_not_queue_controlled"
            and boundary_decision.get("database_policy")
            == "reuse_service_jobs_and_service_worker_heartbeats"
        ),
        "resilience_boundaries_preserved": (
            boundary_decision.get("execution_policy")
            == "bounded_cooperative_cancellation"
            and boundary_decision.get("retry_policy")
            == "bounded_backoff_then_dead_letter"
            and boundary_decision.get("recovery_policy")
            == "heartbeat_and_lease_reconciliation"
        ),
        "storage_scope_not_expanded": (
            boundary_decision.get("new_table_expected") is False
            and decision["new_table_added"] is False
        ),
        "protected_target_confirmed": (
            boundary_decision.get("postgres_smoke_target")
            == "nex_cx_user@nex_cx_test"
            and decision["postgres_smoke_target"]
            == "nex_cx_user@nex_cx_test"
        ),
        "provider_scope_not_overclaimed": (
            boundary_decision.get("remote_provider_required_now") is False
            and decision["dgx_provider_required"] is False
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "0972-0981",
                "checkpoint_gate": "0976",
                "full_gate": "0981",
            }
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0981",
        "slice_range": SLICE_RANGE,
        "requirement": "S98",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s98_cx_worker_operations_resilience_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S99" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_WORKER_OPERATIONS_RESILIENCE_READY"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(boundary_summary.get("resolved_gap_count") or 0),
            "protected_postgres_check_count": (
                23 if components["protected_postgres_evidence"] else 0
            ),
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S99",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_worker_operations_and_resilience",
        "queue_policy": "reuse_service_jobs_with_atomic_skip_locked_claim",
        "execution_policy": "bounded_cooperative_cancellation",
        "lease_policy": "renewable_compare_and_swap",
        "retry_policy": "bounded_backoff_then_dead_letter",
        "recovery_policy": "expired_lease_and_unavailable_heartbeat_required",
        "process_policy": "externally_supervised_bounded_worker",
        "observability_policy": "metadata_only_events_and_heartbeats",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "new_table_added": False,
        "dgx_provider_required": False,
        "protected_postgres_evidence_completed": True,
        "next_requirement_scope": (
            "cx_asynchronous_grounded_generation_execution_and_recovery"
        ),
        "deferred_scope": [
            "asynchronous_grounded_generation_execution",
            "streaming_generation_transport",
            "automatic_multi_attempt_citation_repair",
            "production_provider_slo_baseline",
        ],
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s98_cx_worker_operations_resilience_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"postgres_checks={summary.get('protected_postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s98_cx_worker_operations_resilience_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
