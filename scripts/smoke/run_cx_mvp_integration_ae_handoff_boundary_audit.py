#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_mvp_integration_ae_handoff_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0991_s99_cx_async_generation_recovery_closure.md",
    "services/nex-cx/nex_cx/ingestion_coordinator.py",
    "services/nex-cx/nex_cx/hybrid_retrieval_package.py",
    "services/nex-cx/nex_cx/vector_index_publish.py",
    "services/nex-cx/nex_cx/async_generation_worker.py",
    "services/nex-cx/nex_cx/generation_read_model.py",
    "services/nex-cx/nex_cx/main.py",
    "docs/development_process.md",
    "docs/slices/0992_cx_mvp_integration_ae_handoff_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s99_handoff",
        "docs/slices/0991_s99_cx_async_generation_recovery_closure.md",
        "READY_FOR_S100",
    ),
    EvidenceToken(
        "durable_ingestion",
        "services/nex-cx/nex_cx/ingestion_coordinator.py",
        "def build_default_ingestion_step_handlers",
    ),
    EvidenceToken(
        "hardened_retrieval",
        "services/nex-cx/nex_cx/hybrid_retrieval_package.py",
        "class PermissionFilteredHybridPackageRuntime",
    ),
    EvidenceToken(
        "atomic_vector_publish",
        "services/nex-cx/nex_cx/vector_index_publish.py",
        "def publish_vector_index",
    ),
    EvidenceToken(
        "async_generation_worker",
        "services/nex-cx/nex_cx/async_generation_worker.py",
        "class AsyncGenerationWorkerHandler",
    ),
    EvidenceToken(
        "restart_safe_generation_read",
        "services/nex-cx/nex_cx/generation_read_model.py",
        "class GenerationReadModel",
    ),
    EvidenceToken(
        "production_bootstrap",
        "services/nex-cx/nex_cx/main.py",
        "register_async_generation_operations_routes",
    ),
    EvidenceToken(
        "tiered_gate",
        "docs/development_process.md",
        "Checkpoint Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0992_cx_mvp_integration_ae_handoff_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "mvp_lifecycle_contract_missing": (
        "services/nex-cx/nex_cx/mvp_integration.py"
    ),
    "production_hybrid_retrieval_composition_missing": (
        "services/nex-cx/nex_cx/hybrid_retrieval_runtime.py"
    ),
    "durable_ingestion_vector_publish_missing": (
        "services/nex-cx/nex_cx/mvp_ingestion_indexing.py"
    ),
    "ae_generation_handoff_projection_missing": (
        "services/nex-cx/nex_cx/generation_handoff.py"
    ),
    "bounded_citation_repair_missing": (
        "services/nex-cx/nex_cx/citation_repair.py"
    ),
    "production_runtime_composition_missing": (
        "services/nex-cx/nex_cx/mvp_runtime.py"
    ),
    "integration_contract_openapi_missing": (
        "contracts/schemas/generation/cx_generation_handoff.v1.schema.json"
    ),
    "postgres_dgx_e2e_evidence_missing": (
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py"
    ),
}

GAP_SLICES = {
    "mvp_lifecycle_contract_missing": "0993",
    "production_hybrid_retrieval_composition_missing": "0994",
    "durable_ingestion_vector_publish_missing": "0995",
    "ae_generation_handoff_projection_missing": "0996",
    "bounded_citation_repair_missing": "0997",
    "production_runtime_composition_missing": "0998",
    "integration_contract_openapi_missing": "0999",
    "postgres_dgx_e2e_evidence_missing": "1000",
}


def run_cx_mvp_integration_ae_handoff_boundary_audit(
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
        "s99_handoff_bound": _group_present(tokens, "s99_handoff"),
        "lifecycle_foundations_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "durable_ingestion",
                "hardened_retrieval",
                "atomic_vector_publish",
                "async_generation_worker",
                "restart_safe_generation_read",
            )
        ),
        "production_bootstrap_confirmed": _group_present(
            tokens, "production_bootstrap"
        ),
        "tiered_quality_cadence_confirmed": _group_present(
            tokens, "tiered_gate"
        ),
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
        "1001",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0992",
        "requirement": "S100",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_CURRENT" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 8,
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
            "0992_boundary_audit",
            "0993_mvp_lifecycle_contract",
            "0994_production_hybrid_retrieval_composition",
            "0995_durable_ingestion_vector_publish",
            "0996_ae_generation_handoff_projection",
            "0997_bounded_citation_repair",
            "0998_production_runtime_composition",
            "0999_contract_openapi_observability",
            "1000_postgres_dgx_e2e_smoke",
            "1001_s100_closure",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_mvp_integration_and_ae_handoff_closure",
        "public_choreography_policy": (
            "preserve_explicit_upload_retrieval_generation_job_apis"
        ),
        "retrieval_policy": "production_bootstrap_uses_permission_hardened_runtime",
        "ingestion_index_policy": (
            "durable_ingestion_publishes_fresh_owner_scoped_pgvector_index"
        ),
        "handoff_policy": "owner_safe_pollable_generation_result_projection",
        "citation_repair_policy": (
            "one_bounded_repair_attempt_same_retrieval_package"
        ),
        "storage_policy": "metadata_in_postgresql_private_payloads_outside_rows",
        "new_table_expected": False,
        "postgres_required_now": False,
        "postgres_live_required_slice": "1000",
        "remote_provider_required_now": False,
        "remote_provider_required_slice": "1000",
        "remote_provider_path": "cx_to_mo_capability_alias_only",
        "quality_cadence": {
            "slice_gate": "0992-1001",
            "checkpoint_gate": "0996",
            "full_gate": "1001",
        },
        "deferred_scope": [
            "streaming_transport",
            "shared_group_acl",
            "multi_document_scale_tuning",
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
        "cx_mvp_integration_ae_handoff_boundary="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"scope={decision.get('feature_scope', 'unknown')} "
        f"live_required_slice={decision.get('remote_provider_required_slice', 'none')} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_mvp_integration_ae_handoff_boundary_audit()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
