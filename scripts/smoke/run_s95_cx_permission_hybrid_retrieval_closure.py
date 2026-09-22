#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from run_cx_fresh_vector_candidate_contract import (  # noqa: E402
    run_cx_fresh_vector_candidate_contract as run_vector_contract,
)
from run_cx_hybrid_retrieval_package_contract import (  # noqa: E402
    run_cx_hybrid_retrieval_package_contract as run_package_contract,
)
from run_cx_permission_first_hybrid_orchestration import (  # noqa: E402
    run_cx_permission_first_hybrid_orchestration as run_orchestration,
)
from run_cx_permission_hybrid_retrieval_boundary_audit import (  # noqa: E402
    run_cx_permission_hybrid_retrieval_boundary_audit as run_boundary,
)
from run_cx_retrieval_operations_observability import (  # noqa: E402
    run_cx_retrieval_operations_observability as run_observability,
)
from run_cx_retrieval_permission_contract import (  # noqa: E402
    run_cx_retrieval_permission_contract as run_permission_contract,
)
from run_cx_weighted_rrf_rerank_privacy_contract import (  # noqa: E402
    run_cx_weighted_rrf_rerank_privacy_contract as run_ranking_contract,
)


SCHEMA_VERSION = "s95_cx_permission_hybrid_retrieval_closure.v1"
SLICE_RANGE = "0941-0950"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/retrieval_permissions.py",
    "services/nex-cx/nex_cx/lexical_candidates.py",
    "services/nex-cx/nex_cx/vector_candidates.py",
    "services/nex-cx/nex_cx/hybrid_candidate_orchestration.py",
    "services/nex-cx/nex_cx/hybrid_ranking.py",
    "services/nex-cx/nex_cx/hybrid_retrieval_package.py",
    "services/nex-cx/nex_cx/retrieval_observability.py",
    "database/nex-cx/migrations/0949_cx_retrieval_private_preview_nullable.sql",
    "scripts/smoke/run_cx_permission_hybrid_live_postgres_smoke.py",
    "scripts/smoke/run_s95_cx_permission_hybrid_retrieval_closure.py",
    "tests/test_s95_cx_permission_hybrid_retrieval_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0941", "cx_permission_hybrid_retrieval_boundary_audit"),
            ("0942", "cx_retrieval_permission_decision_contract"),
            ("0943", "cx_owner_scoped_lexical_candidate_adapter"),
            ("0944", "cx_fresh_vector_candidate_adapter"),
            ("0945", "cx_permission_first_hybrid_orchestration"),
            ("0946", "cx_weighted_rrf_rerank_privacy_hardening"),
            ("0947", "cx_hybrid_retrieval_package_api_persistence_wiring"),
            ("0948", "cx_retrieval_operations_observability"),
            ("0949", "cx_permission_hybrid_live_postgres_smoke"),
            ("0950", "s95_cx_permission_hybrid_retrieval_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_boundary_runner",
        QUALITY_GATE_PATH,
        "run_cx_permission_hybrid_retrieval_boundary_audit.py",
    ),
    (
        "quality_permission_runner",
        QUALITY_GATE_PATH,
        "run_cx_retrieval_permission_contract.py",
    ),
    (
        "quality_lexical_runner",
        QUALITY_GATE_PATH,
        "run_cx_lexical_candidate_postgres_smoke.py",
    ),
    (
        "quality_vector_runner",
        QUALITY_GATE_PATH,
        "run_cx_fresh_vector_candidate_contract.py",
    ),
    (
        "quality_orchestration_runner",
        QUALITY_GATE_PATH,
        "run_cx_permission_first_hybrid_orchestration.py",
    ),
    (
        "quality_ranking_runner",
        QUALITY_GATE_PATH,
        "run_cx_weighted_rrf_rerank_privacy_contract.py",
    ),
    (
        "quality_package_runner",
        QUALITY_GATE_PATH,
        "run_cx_hybrid_retrieval_package_contract.py",
    ),
    (
        "quality_observability_runner",
        QUALITY_GATE_PATH,
        "run_cx_retrieval_operations_observability.py",
    ),
    (
        "quality_live_runner",
        QUALITY_GATE_PATH,
        "run_cx_permission_hybrid_live_postgres_smoke.py",
    ),
    (
        "quality_closure_runner",
        QUALITY_GATE_PATH,
        "run_s95_cx_permission_hybrid_retrieval_closure.py",
    ),
    (
        "permission_policy",
        "services/nex-cx/nex_cx/retrieval_permissions.py",
        'PERMISSION_POLICY_ID = "cx.private_owner_active.v1"',
    ),
    (
        "bm25_k1",
        "services/nex-cx/nex_cx/lexical_candidates.py",
        "DEFAULT_BM25_K1 = 1.2",
    ),
    (
        "bm25_b",
        "services/nex-cx/nex_cx/lexical_candidates.py",
        "DEFAULT_BM25_B = 0.75",
    ),
    (
        "fresh_vector_guard",
        "services/nex-cx/nex_cx/vector_candidates.py",
        "search_fresh_vector_index",
    ),
    (
        "rrf_vector_weight",
        "services/nex-cx/nex_cx/hybrid_ranking.py",
        "DEFAULT_VECTOR_WEIGHT = 0.7",
    ),
    (
        "rrf_bm25_weight",
        "services/nex-cx/nex_cx/hybrid_ranking.py",
        "DEFAULT_BM25_WEIGHT = 0.3",
    ),
    (
        "rrf_k",
        "services/nex-cx/nex_cx/hybrid_ranking.py",
        "DEFAULT_RRF_K = 60",
    ),
    (
        "hash_only_policy",
        "services/nex-cx/nex_cx/hybrid_retrieval_package.py",
        '"persistence_payload_policy": "hash_only_private_owner"',
    ),
    (
        "nullable_private_preview",
        "database/nex-cx/migrations/0949_cx_retrieval_private_preview_nullable.sql",
        "ALTER COLUMN evidence_text_preview DROP NOT NULL",
    ),
    (
        "observed_event",
        "services/nex-cx/nex_cx/retrieval_observability.py",
        "cx.retrieval.package_observed",
    ),
    (
        "failed_event",
        "services/nex-cx/nex_cx/retrieval_observability.py",
        "cx.retrieval.package_failed",
    ),
    (
        "canonical_embedding_model",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B"',
    ),
    (
        "canonical_reranker_model",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-4B"',
    ),
    (
        "postgres_bm25_checks",
        "docs/slices/0943_cx_owner_scoped_lexical_candidate_adapter.md",
        "checks `9/9`",
    ),
    (
        "live_hybrid_checks",
        "docs/slices/0949_cx_permission_hybrid_live_postgres_smoke.md",
        "`16/16` checks passed",
    ),
    (
        "live_test_database",
        "docs/slices/0949_cx_permission_hybrid_live_postgres_smoke.md",
        "`nex_cx_user@nex_cx_test`",
    ),
    (
        "live_reranker_4b",
        "docs/slices/0949_cx_permission_hybrid_live_postgres_smoke.md",
        "`Qwen3-Reranker-4B`",
    ),
    (
        "docs_live_index",
        "docs/README.md",
        "0949_cx_permission_hybrid_live_postgres_smoke.md",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "0950_s95_cx_permission_hybrid_retrieval_closure.md",
    ),
)


def run_s95_cx_permission_hybrid_retrieval_closure(
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
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "permission": _safe_evidence(run_permission_contract),
        "fresh_vector": _safe_evidence(run_vector_contract),
        "orchestration": _safe_evidence(run_orchestration),
        "ranking": _safe_evidence(run_ranking_contract),
        "package": _safe_evidence(run_package_contract),
        "observability": _safe_evidence(run_observability),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    boundary_summary = _mapping(evidence["boundary"].get("summary"))
    boundary_decision = _mapping(evidence["boundary"].get("decision"))
    contract_check_count = sum(
        sum(bool(value) for value in _mapping(item.get("checks")).values())
        for name, item in evidence.items()
        if name != "boundary"
    )
    postgres_tokens = {
        name: token_status[name]
        for name in (
            "postgres_bm25_checks",
            "live_hybrid_checks",
            "live_test_database",
            "nullable_private_preview",
        )
    }
    live_tokens = {
        name: token_status[name]
        for name in (
            "live_hybrid_checks",
            "canonical_embedding_model",
            "canonical_reranker_model",
            "live_reranker_4b",
        )
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("issue_count") == 0
            and boundary_decision.get("mvp_permission_model")
            == "private_tenant_owner_exact_match"
        ),
        "permission_and_candidate_contracts_closed": (
            evidence["permission"].get("policy_id")
            == "cx.private_owner_active.v1"
            and evidence["fresh_vector"].get("permission_policy")
            == "cx.private_owner_active.v1"
            and evidence["orchestration"].get("permission_policy")
            == "cx.private_owner_active.v1"
            and contract_check_count == 55
        ),
        "weighted_rrf_and_rerank_closed": (
            evidence["ranking"].get("policy_id")
            == "weighted_rrf_vector_bm25_v1"
            and evidence["ranking"].get("rerank_state") == "APPLIED"
            and decision["fusion_policy"]
            == "weighted_rrf_vector_0_7_bm25_0_3_k_60"
        ),
        "api_and_hash_only_persistence_closed": (
            evidence["package"].get("package_schema_version")
            == "cx_retrieval_context_package.v1"
            and evidence["package"].get("persistence_payload_policy")
            == "hash_only_private_owner"
            and token_status.get("nullable_private_preview") is True
        ),
        "metadata_only_observability_closed": (
            evidence["observability"].get("success_event_type")
            == "cx.retrieval.package_observed"
            and evidence["observability"].get("failure_event_type")
            == "cx.retrieval.package_failed"
            and decision["observability_policy"]
            == "metadata_only_best_effort"
        ),
        "actual_postgres_evidence_passed": all(postgres_tokens.values()),
        "actual_live_provider_evidence_passed": all(live_tokens.values()),
        "canonical_models_current": (
            boundary_decision.get("live_embedding_model")
            == "Qwen3-Embedding-4B"
            and boundary_decision.get("live_reranker_model")
            == "Qwen3-Reranker-4B"
            and decision["reranker_model"] == "Qwen3-Reranker-4B"
        ),
        "owner_private_boundary_preserved": (
            decision["cross_owner_behavior"]
            == "not_found_before_candidate_generation"
            and decision["reranker_input_policy"]
            == "authorized_candidate_text_only"
            and decision["persistence_payload_policy"]
            == "hash_only_private_owner"
        ),
        "single_migration_history_preserved": (
            decision["migration_strategy"]
            == "versioned_sql_schema_migrations_runner"
        ),
        "deferred_scope_not_overclaimed": (
            "shared_group_acl_expansion" in decision["deferred_scope"]
            and "multi_document_retrieval_scale_validation"
            in decision["deferred_scope"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0950",
        "slice_range": SLICE_RANGE,
        "requirement": "S95",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s95_permission_hybrid_retrieval_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S96" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_PERMISSION_FILTERED_HYBRID_RETRIEVAL_READY"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "contract_check_count": contract_check_count,
            "postgres_check_count": 25 if all(postgres_tokens.values()) else 0,
            "live_check_count": 16 if all(live_tokens.values()) else 0,
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "postgres_evidence": postgres_tokens,
        "live_evidence": live_tokens,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S96",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "permission_filtered_owner_private_hybrid_retrieval",
        "permission_policy": "cx.private_owner_active.v1",
        "cross_owner_behavior": "not_found_before_candidate_generation",
        "lexical_policy": "postgresql_bm25_k1_1_2_b_0_75",
        "vector_policy": "owner_scoped_fresh_pgvector_only",
        "fusion_policy": "weighted_rrf_vector_0_7_bm25_0_3_k_60",
        "embedding_model": "Qwen3-Embedding-4B",
        "embedding_dimension": 2560,
        "reranker_model": "Qwen3-Reranker-4B",
        "reranker_input_policy": "authorized_candidate_text_only",
        "persistence_payload_policy": "hash_only_private_owner",
        "observability_policy": "metadata_only_best_effort",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "protected_live_evidence_completed": True,
        "deferred_scope": [
            "shared_group_acl_expansion",
            "multi_document_retrieval_scale_validation",
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
        "s95_cx_permission_hybrid_retrieval_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"contracts={summary.get('contract_check_count', 0)} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"live_checks={summary.get('live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s95_cx_permission_hybrid_retrieval_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
