#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_permission_hybrid_retrieval_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0940_s94_cx_vector_storage_freshness_closure.md",
    "services/nex-cx/nex_cx/access_context.py",
    "services/nex-cx/nex_cx/api_ownership.py",
    "services/nex-cx/nex_cx/retrieval.py",
    "services/nex-cx/nex_cx/vector_retrieval_guard.py",
    "services/nex-cx/nex_cx/pgvector_store.py",
    "services/nex-cx/nex_cx/lexical_index.py",
    "services/nex-cx/nex_cx/retrieval_persistence.py",
    "database/nex-cx/migrations/0172_cx_retrieval_package_persistence.sql",
    "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0941_cx_permission_hybrid_retrieval_boundary_audit.md",
)
EVIDENCE_TOKENS = (
    EvidenceToken(
        "s94_handoff",
        "docs/slices/0940_s94_cx_vector_storage_freshness_closure.md",
        "READY_FOR_S95",
    ),
    EvidenceToken(
        "trusted_access_context",
        "services/nex-cx/nex_cx/access_context.py",
        'CX_ACCESS_CONTEXT_PROPAGATION_MODE = "trusted_service_asserted_subject"',
    ),
    EvidenceToken(
        "owner_visibility",
        "services/nex-cx/nex_cx/api_ownership.py",
        "def content_object_visible_to_owner",
    ),
    EvidenceToken(
        "scope_filter",
        "services/nex-cx/nex_cx/retrieval.py",
        "if _retrieval_document_visible(store, document_id, access_context)",
    ),
    EvidenceToken(
        "weighted_rrf",
        "services/nex-cx/nex_cx/retrieval.py",
        "def rank_weighted_rrf_candidates",
    ),
    EvidenceToken(
        "reranker_boundary",
        "services/nex-cx/nex_cx/retrieval.py",
        "def apply_rerank_scores",
    ),
    EvidenceToken(
        "fresh_vector_guard",
        "services/nex-cx/nex_cx/vector_retrieval_guard.py",
        "def search_fresh_vector_index",
    ),
    EvidenceToken(
        "pgvector_backend",
        "services/nex-cx/nex_cx/pgvector_store.py",
        "class PgVectorCxVectorStore",
    ),
    EvidenceToken(
        "query_tokenizer_alignment",
        "services/nex-cx/nex_cx/lexical_index.py",
        "def query_terms_for_lexical_index",
    ),
    EvidenceToken(
        "retrieval_persistence",
        "services/nex-cx/nex_cx/retrieval_persistence.py",
        "def build_retrieval_package_persistence_preview",
    ),
    EvidenceToken(
        "owner_lineage_migration",
        "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
        "CREATE OR REPLACE FUNCTION cx_apply_retrieval_owner_lineage()",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_permission_hybrid_retrieval_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0941_cx_permission_hybrid_retrieval_boundary_audit.md",
    ),
)


def run_cx_permission_hybrid_retrieval_boundary_audit(
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
    retrieval_source = _read_text(root / "services/nex-cx/nex_cx/retrieval.py")
    gap_checks = {
        "candidate_runtime_is_in_memory": "sorted(store.chunk_sets)" in retrieval_source,
        "lexical_score_is_not_bm25": (
            "matched_count / max(1, len(query_terms))" in retrieval_source
        ),
        "vector_candidates_are_process_local": (
            "store.get_embedding_vector(chunk_id)" in retrieval_source
        ),
        "permission_evidence_is_mock": (
            '"reason": "local_mock_service_scope"' in retrieval_source
            and '"policy_version": "local_mock_v1"' in retrieval_source
        ),
        "permission_snapshot_has_zero_filter_counts": (
            '"filtered_document_count": 0' in retrieval_source
            and '"filtered_chunk_count": 0' in retrieval_source
        ),
        "fresh_vector_guard_not_hybrid_wired": (
            "search_fresh_vector_index" not in retrieval_source
        ),
        "postgres_lexical_candidate_adapter_missing": (
            "PostgresLexicalCandidate" not in retrieval_source
        ),
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s94_handoff_bound": _group_present(tokens, "s94_handoff"),
        "owner_scope_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "trusted_access_context",
                "owner_visibility",
                "scope_filter",
            )
        ),
        "hybrid_ranking_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in ("weighted_rrf", "reranker_boundary")
        ),
        "fresh_pgvector_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in ("fresh_vector_guard", "pgvector_backend")
        ),
        "lexical_tokenizer_foundation_confirmed": _group_present(
            tokens, "query_tokenizer_alignment"
        ),
        "owner_scoped_package_persistence_confirmed": all(
            _group_present(tokens, group)
            for group in ("retrieval_persistence", "owner_lineage_migration")
        ),
        "implementation_gaps_confirmed": all(gap_checks.values()),
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
    issues.extend(
        {"category": "expected_gap_not_confirmed", "gap": name}
        for name, confirmed in gap_checks.items()
        if not confirmed
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0941",
        "requirement": "S95",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_permission_hybrid_retrieval_boundary_failed"
        ),
        "boundary_readiness": "GAPS_CONFIRMED" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 7,
            "gap_count": 7,
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": [
            "hybrid_candidates_are_process_local",
            "lexical_score_is_term_coverage_not_bm25",
            "vector_candidates_do_not_use_fresh_pgvector_guard",
            "permission_result_is_mock_metadata",
            "permission_snapshot_filter_counts_are_not_measured",
            "reranker_permission_continuity_is_not_explicitly_proven",
            "no_postgres_plus_live_embedding_reranker_hybrid_evidence",
        ],
        "slice_plan": [
            "0941_boundary_audit",
            "0942_permission_decision_snapshot_contract",
            "0943_owner_scoped_lexical_candidate_adapter",
            "0944_fresh_vector_candidate_adapter",
            "0945_permission_first_hybrid_orchestration",
            "0946_weighted_rrf_rerank_privacy_hardening",
            "0947_retrieval_package_api_persistence_wiring",
            "0948_retrieval_operations_observability",
            "0949_postgres_provider_live_smoke",
            "0950_s95_closure",
        ],
        "checks": checks,
        "gap_checks": gap_checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0942",
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "authorization_source": "trusted_service_asserted_oa_subject",
        "mvp_permission_model": "private_tenant_owner_exact_match",
        "eligible_content_state": "ACTIVE",
        "cross_owner_behavior": "not_found_before_candidate_generation",
        "permission_filter_order": [
            "authenticate_service",
            "resolve_tenant_subject",
            "filter_active_owner_content",
            "admit_fresh_indexes",
            "rank_bm25_and_vector",
            "rerank_authorized_candidates_only",
        ],
        "lexical_tokenizer": "mecab_ko_with_korean_mixed_v1_fallback",
        "hybrid_policy": "weighted_rrf_vector_0_7_bm25_0_3",
        "vector_backend": "owner_scoped_fresh_postgresql_pgvector",
        "reranker_input_policy": "authorized_candidate_text_only",
        "permission_snapshot_policy": "measured_and_hash_bound",
        "shared_acl_scope": "deferred_until_oa_claim_contract",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "remote_provider_required_now": False,
        "remote_provider_required_slice": "0949",
        "live_embedding_model": "Qwen3-Embedding-4B",
        "live_reranker_model": "Qwen3-Reranker-4B",
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
        "cx_permission_hybrid_retrieval_boundary="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"permission={decision.get('mvp_permission_model', 'unknown')} "
        f"remote_required_now={decision.get('remote_provider_required_now', True)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_permission_hybrid_retrieval_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
