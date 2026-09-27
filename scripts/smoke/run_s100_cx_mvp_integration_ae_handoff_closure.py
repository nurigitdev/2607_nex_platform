#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_cx_mvp_integration_ae_handoff_boundary_audit import (
    run_cx_mvp_integration_ae_handoff_boundary_audit as run_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s100_cx_mvp_integration_ae_handoff_closure.v1"
SLICE_RANGE = "0992-1001"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/mvp_integration.py",
    "services/nex-cx/nex_cx/hybrid_retrieval_runtime.py",
    "services/nex-cx/nex_cx/mvp_ingestion_indexing.py",
    "services/nex-cx/nex_cx/generation_handoff.py",
    "services/nex-cx/nex_cx/citation_repair.py",
    "services/nex-cx/nex_cx/mvp_runtime.py",
    "services/nex-cx/nex_cx/generation_handoff_observability.py",
    "contracts/schemas/generation/cx_generation_handoff.v1.schema.json",
    "scripts/smoke/run_cx_mvp_integration_ae_handoff_boundary_audit.py",
    "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
    "scripts/smoke/run_s100_cx_mvp_integration_ae_handoff_closure.py",
    "tests/test_s100_cx_mvp_integration_ae_handoff_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0992", "cx_mvp_integration_ae_handoff_boundary_audit"),
            ("0993", "cx_mvp_lifecycle_contract"),
            ("0994", "cx_production_hybrid_retrieval_composition"),
            ("0995", "cx_durable_ingestion_vector_publish"),
            ("0996", "cx_ae_generation_handoff_projection"),
            ("0997", "cx_bounded_citation_repair"),
            ("0998", "cx_production_runtime_composition"),
            ("0999", "cx_handoff_contract_openapi_observability"),
            ("1000", "cx_mvp_integration_live_postgres_smoke"),
            ("1001", "s100_cx_mvp_integration_ae_handoff_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_cx_mvp_integration_ae_handoff_boundary_audit.py",
    ),
    (
        "quality_live",
        QUALITY_GATE_PATH,
        "run_cx_mvp_integration_live_postgres_smoke.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s100_cx_mvp_integration_ae_handoff_closure.py",
    ),
    (
        "lifecycle_contract",
        "services/nex-cx/nex_cx/mvp_integration.py",
        "CX_MVP_INTEGRATION_SCHEMA_VERSION",
    ),
    (
        "permission_hardened_retrieval",
        "services/nex-cx/nex_cx/hybrid_retrieval_runtime.py",
        "def build_permission_hardened_hybrid_runtime",
    ),
    (
        "durable_vector_publish",
        "services/nex-cx/nex_cx/mvp_ingestion_indexing.py",
        "class MvpIngestionVectorIndexer",
    ),
    (
        "ae_handoff",
        "services/nex-cx/nex_cx/generation_handoff.py",
        "PRESENT_GENERATION_TO_OWNER",
    ),
    (
        "citation_repair",
        "services/nex-cx/nex_cx/citation_repair.py",
        "def generate_with_bounded_citation_repair",
    ),
    (
        "production_composition",
        "services/nex-cx/nex_cx/mvp_runtime.py",
        "def build_cx_mvp_runtime",
    ),
    (
        "handoff_observability",
        "services/nex-cx/nex_cx/generation_handoff_observability.py",
        "cx.generation_handoff.observed",
    ),
    (
        "handoff_schema",
        "contracts/schemas/generation/cx_generation_handoff.v1.schema.json",
        "cx_generation_handoff.v1",
    ),
    (
        "openapi_v1",
        "contracts/openapi/nex-cx.openapi.yaml",
        "version: 1.0.0",
    ),
    (
        "live_database_identity",
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
        '"test_database_identity"',
    ),
    (
        "live_provider_path",
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
        '"provider_path": "cx_to_mo_capability_alias_only"',
    ),
    (
        "live_provider_models",
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
        '"provider_models_frozen"',
    ),
    (
        "live_owner_isolation",
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
        '"cross_owner_handoff_hidden"',
    ),
    (
        "live_private_metadata",
        "scripts/smoke/run_cx_mvp_integration_live_postgres_smoke.py",
        '"metadata_rows_exclude_private_text"',
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1001_s100_cx_mvp_integration_ae_handoff_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "lifecycle_contract": ("lifecycle_contract",),
    "production_retrieval_and_indexing": (
        "permission_hardened_retrieval",
        "durable_vector_publish",
    ),
    "ae_handoff_and_citation_repair": ("ae_handoff", "citation_repair"),
    "production_runtime_composition": ("production_composition",),
    "contract_and_observability": (
        "handoff_observability",
        "handoff_schema",
        "openapi_v1",
    ),
    "protected_postgres_and_dgx_evidence": (
        "live_database_identity",
        "live_provider_path",
        "live_provider_models",
    ),
    "ownership_and_private_storage": (
        "live_owner_isolation",
        "live_private_metadata",
    ),
    "quality_and_documentation": (
        "quality_boundary",
        "quality_live",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s100_cx_mvp_integration_ae_handoff_closure(
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
            and boundary.get("next_slice") == "1001"
        ),
        "all_mvp_components_closed": all(components.values()),
        "public_choreography_preserved": (
            boundary_decision.get("public_choreography_policy")
            == "preserve_explicit_upload_retrieval_generation_job_apis"
            and boundary_decision.get("handoff_policy")
            == "owner_safe_pollable_generation_result_projection"
        ),
        "private_storage_boundary_preserved": (
            boundary_decision.get("storage_policy")
            == "metadata_in_postgresql_private_payloads_outside_rows"
            and boundary_decision.get("new_table_expected") is False
        ),
        "live_provider_boundary_completed": (
            boundary_decision.get("remote_provider_path")
            == "cx_to_mo_capability_alias_only"
            and decision["protected_live_check_count"] == 11
            and decision["provider_models"]
            == {
                "embedding": "Qwen3-Embedding-4B",
                "reranking": "Qwen3-Reranker-4B",
                "generation": "Qwen3.5-4B",
            }
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "0992-1001",
                "checkpoint_gate": "0996",
                "full_gate": "1001",
            }
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1001",
        "slice_range": SLICE_RANGE,
        "requirement": "S100",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s100_cx_mvp_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S101" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_MVP_INTEGRATION_AE_HANDOFF_READY"
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
            "protected_live_check_count": (
                11 if components["protected_postgres_and_dgx_evidence"] else 0
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
        "next_requirement": "S101",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "cx_mvp_integration_and_ae_handoff",
        "public_choreography_policy": "explicit_owner_scoped_job_apis",
        "retrieval_policy": "permission_hardened_weighted_hybrid_with_rerank",
        "citation_repair_policy": "one_bounded_attempt_same_retrieval_package",
        "storage_policy": "postgres_metadata_external_owner_private_payloads",
        "provider_path": "cx_to_mo_capability_alias_only",
        "provider_models": {
            "embedding": "Qwen3-Embedding-4B",
            "reranking": "Qwen3-Reranker-4B",
            "generation": "Qwen3.5-4B",
        },
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "protected_live_check_count": 11,
        "new_table_added": False,
        "next_requirement_scope": "S101_pending_canonical_scope_review",
        "deferred_scope": [
            "streaming_transport",
            "shared_group_acl",
            "multi_document_scale_tuning",
            "production_provider_slo_baselines",
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
        "s100_cx_mvp_integration_ae_handoff_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"live_checks={summary.get('protected_live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s100_cx_mvp_integration_ae_handoff_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
