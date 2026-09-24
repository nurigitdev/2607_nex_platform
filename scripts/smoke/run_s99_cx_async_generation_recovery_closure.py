#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_cx_async_generation_recovery_boundary_audit import (
    run_cx_async_generation_recovery_boundary_audit as run_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s99_cx_async_generation_recovery_closure.v1"
SLICE_RANGE = "0982-0991"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/async_generation_contracts.py",
    "services/nex-cx/nex_cx/generation_request_store.py",
    "services/nex-cx/nex_cx/async_generation.py",
    "services/nex-cx/nex_cx/async_generation_worker.py",
    "services/nex-cx/nex_cx/async_generation_recovery.py",
    "services/nex-cx/nex_cx/async_generation_operations.py",
    "services/nex-cx/nex_cx/async_generation_observability.py",
    "contracts/schemas/generation/cx_async_generation_job.v1.schema.json",
    "scripts/smoke/run_cx_async_generation_recovery_boundary_audit.py",
    "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
    "scripts/smoke/run_s99_cx_async_generation_recovery_closure.py",
    "tests/test_s99_cx_async_generation_recovery_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0982", "cx_async_generation_recovery_boundary_audit"),
            ("0983", "cx_async_generation_execution_job_contract"),
            ("0984", "cx_durable_private_generation_request_envelope"),
            ("0985", "cx_async_generation_idempotent_queue_admission"),
            ("0986", "cx_async_generation_mock_worker_execution"),
            ("0987", "cx_async_generation_retry_cancellation_recovery"),
            ("0988", "cx_async_generation_owner_operations_api"),
            ("0989", "cx_async_generation_contract_openapi_observability"),
            ("0990", "cx_async_generation_postgresql_recovery_smoke"),
            ("0991", "s99_cx_async_generation_recovery_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_cx_async_generation_recovery_boundary_audit.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_cx_async_generation_postgres_smoke.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s99_cx_async_generation_recovery_closure.py",
    ),
    (
        "job_contract",
        "services/nex-cx/nex_cx/async_generation_contracts.py",
        "cx.grounded-generation.execute",
    ),
    (
        "private_request_envelope",
        "services/nex-cx/nex_cx/generation_request_store.py",
        "cx_generation_request_envelope.v1",
    ),
    (
        "idempotent_admission",
        "services/nex-cx/nex_cx/async_generation.py",
        "def admit_async_generation",
    ),
    (
        "bounded_worker",
        "services/nex-cx/nex_cx/async_generation_worker.py",
        "class AsyncGenerationWorkerHandler",
    ),
    (
        "retry_recovery",
        "services/nex-cx/nex_cx/async_generation_recovery.py",
        "def recover_persisted_async_generation_job",
    ),
    (
        "owner_operations",
        "services/nex-cx/nex_cx/async_generation_operations.py",
        '"/api/v1/generation-jobs/{job_id}/cancel"',
    ),
    (
        "metadata_observability",
        "services/nex-cx/nex_cx/async_generation_observability.py",
        "cx.async_generation.cancelled",
    ),
    (
        "public_schema",
        "contracts/schemas/generation/cx_async_generation_job.v1.schema.json",
        "cx_async_generation_job.v1",
    ),
    (
        "openapi_operations",
        "contracts/openapi/nex-cx.openapi.yaml",
        "/api/v1/generation-jobs/{job_id}/cancel:",
    ),
    (
        "postgres_success",
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
        '"success_path_completed"',
    ),
    (
        "postgres_retry",
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
        '"retry_scheduled_then_completed"',
    ),
    (
        "postgres_recovery",
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
        '"expired_lease_requeued"',
    ),
    (
        "postgres_cancellation",
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
        '"queued_cancellation_persisted"',
    ),
    (
        "postgres_cleanup",
        "scripts/smoke/run_cx_async_generation_postgres_smoke.py",
        'checks["cleanup_verified"] = residue == 0',
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "0991_s99_cx_async_generation_recovery_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "metadata_job_and_private_request": (
        "job_contract",
        "private_request_envelope",
    ),
    "idempotent_durable_admission": ("idempotent_admission",),
    "bounded_worker_execution": ("bounded_worker",),
    "retry_cancellation_and_recovery": (
        "retry_recovery",
        "postgres_retry",
        "postgres_recovery",
        "postgres_cancellation",
    ),
    "owner_operations_boundary": ("owner_operations",),
    "contract_and_observability": (
        "metadata_observability",
        "public_schema",
        "openapi_operations",
    ),
    "protected_postgres_evidence": (
        "postgres_success",
        "postgres_retry",
        "postgres_recovery",
        "postgres_cancellation",
        "postgres_cleanup",
    ),
    "quality_and_documentation": (
        "quality_boundary",
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s99_cx_async_generation_recovery_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
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
            and boundary.get("next_slice") == "0991"
        ),
        "all_async_generation_components_closed": all(components.values()),
        "compatibility_and_storage_boundaries_preserved": (
            boundary_decision.get("sync_api_policy")
            == "preserve_existing_synchronous_route"
            and boundary_decision.get("request_storage_policy")
            == "owner_private_immutable_envelope"
            and boundary_decision.get("new_table_expected") is False
        ),
        "queue_and_worker_reuse_preserved": (
            boundary_decision.get("queue_policy")
            == "reuse_service_jobs_with_deterministic_idempotent_job"
            and boundary_decision.get("worker_policy")
            == "reuse_s98_bounded_worker_and_lease_reconciliation"
        ),
        "protected_postgres_slice_completed": (
            boundary_decision.get("postgres_required_slice") == "0990"
            and decision["postgres_smoke_target"]
            == "nex_cx_user@nex_cx_test"
            and decision["protected_postgres_check_count"] == 21
        ),
        "provider_scope_not_overclaimed": (
            boundary_decision.get("remote_provider_required_now") is False
            and decision["remote_provider_required"] is False
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "0982-0991",
                "checkpoint_gate": "0986",
                "full_gate": "0991",
            }
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0991",
        "slice_range": SLICE_RANGE,
        "requirement": "S99",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s99_cx_async_generation_recovery_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S100" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_ASYNC_GENERATION_RECOVERY_READY"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(
                boundary_summary.get("resolved_gap_count") or 0
            ),
            "protected_postgres_check_count": (
                21 if components["protected_postgres_evidence"] else 0
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S100",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_asynchronous_grounded_generation_execution_recovery",
        "sync_api_policy": "preserved",
        "queue_policy": "service_jobs_deterministic_idempotent_job",
        "request_storage_policy": "owner_private_immutable_envelope",
        "worker_policy": "s98_bounded_worker_and_lease_reconciliation",
        "recovery_policy": "bounded_retry_cancel_and_expired_lease_convergence",
        "observability_policy": "metadata_only_owner_safe_events",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "protected_postgres_check_count": 21,
        "new_table_added": False,
        "remote_provider_required": False,
        "remote_provider_live_evidence": "deferred_until_connectivity_available",
        "next_requirement_scope": "S100_pending_canonical_scope_review",
        "deferred_scope": [
            "live_remote_provider_async_smoke",
            "streaming_generation_transport",
            "multi_attempt_citation_repair",
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
        "s99_cx_async_generation_recovery_closure="
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
    evidence = run_s99_cx_async_generation_recovery_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
