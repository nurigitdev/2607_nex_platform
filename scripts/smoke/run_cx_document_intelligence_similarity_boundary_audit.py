#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_document_intelligence_similarity_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0950_s95_cx_permission_hybrid_retrieval_closure.md",
    "services/nex-cx/nex_cx/summaries.py",
    "services/nex-cx/nex_cx/summary_embeddings.py",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/ingestion_coordinator.py",
    "services/nex-cx/nex_cx/repository.py",
    "services/nex-cx/nex_cx/private_content.py",
    "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
    "scripts/smoke/run_protected_dgx_live_profile.py",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0951_cx_document_intelligence_similarity_boundary_audit.md",
)
EVIDENCE_TOKENS = (
    EvidenceToken(
        "s95_handoff",
        "docs/slices/0950_s95_cx_permission_hybrid_retrieval_closure.md",
        "READY_FOR_S96",
    ),
    EvidenceToken(
        "summary_limit",
        "services/nex-cx/nex_cx/summaries.py",
        "DEFAULT_SUMMARY_HARD_LIMIT_CHARS = 1000",
    ),
    EvidenceToken(
        "summary_prompt_registry",
        "services/nex-cx/nex_cx/summaries.py",
        "CX_DOCUMENT_SUMMARY_BINDING",
    ),
    EvidenceToken(
        "owner_authorization",
        "services/nex-cx/nex_cx/summaries.py",
        "authorize_cx_owner_request",
    ),
    EvidenceToken(
        "summary_embedding_provider",
        "services/nex-cx/nex_cx/summary_embeddings.py",
        "build_default_mo_embedding_client",
    ),
    EvidenceToken(
        "summary_metadata_table",
        "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
        "CREATE TABLE IF NOT EXISTS cx_document_summaries",
    ),
    EvidenceToken(
        "summary_embedding_metadata_table",
        "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
        "CREATE TABLE IF NOT EXISTS cx_document_summary_embeddings",
    ),
    EvidenceToken(
        "summary_repository",
        "services/nex-cx/nex_cx/repository.py",
        "def save_document_summary_record",
    ),
    EvidenceToken(
        "summary_embedding_repository",
        "services/nex-cx/nex_cx/repository.py",
        "def save_summary_embedding_record",
    ),
    EvidenceToken(
        "durable_ingestion_summary",
        "services/nex-cx/nex_cx/ingestion_coordinator.py",
        '"summary": lambda run:',
    ),
    EvidenceToken(
        "durable_ingestion_summary_embedding",
        "services/nex-cx/nex_cx/ingestion_coordinator.py",
        '"summary_embedding": lambda run:',
    ),
    EvidenceToken(
        "private_summary_capability",
        "services/nex-cx/nex_cx/private_content.py",
        '{"chunk_embedding", "summary_embedding"}',
    ),
    EvidenceToken(
        "generation_model",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_VLLM_MODEL": "Qwen3.5-4B"',
    ),
    EvidenceToken(
        "embedding_model",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B"',
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_document_intelligence_similarity_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0951_cx_document_intelligence_similarity_boundary_audit.md",
    ),
)


def run_cx_document_intelligence_similarity_boundary_audit(
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
    summary_source = _read_text(root / "services/nex-cx/nex_cx/summaries.py")
    embedding_source = _read_text(
        root / "services/nex-cx/nex_cx/summary_embeddings.py"
    )
    ingestion_source = _read_text(root / "services/nex-cx/nex_cx/ingestion.py")
    migration_source = _read_text(
        root / "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql"
    )
    gap_observations = {
        "summary_generation_is_local_mock": (
            'DEFAULT_SUMMARIZER_PROFILE = "mock-document-summary"' in summary_source
            and '"provider": "local_mock"' in summary_source
        ),
        "private_summary_text_is_process_local": (
            'summary_storage_uri": f"memory://' in summary_source
            and "self.summary_texts" in ingestion_source
        ),
        "summary_vector_is_process_local": (
            "self.summary_embedding_vectors" in ingestion_source
        ),
        "summary_pgvector_payload_missing": (
            "summary_embedding vector" not in migration_source.lower()
            and "halfvec" not in migration_source.lower()
        ),
        "owner_scoped_summary_similarity_missing": not (
            root / "services/nex-cx/nex_cx/summary_similarity.py"
        ).is_file(),
        "summary_similarity_freshness_guard_missing": (
            "search_summary_similarity" not in embedding_source
            and "freshness" not in embedding_source
        ),
        "document_intelligence_observability_missing": not (
            root / "services/nex-cx/nex_cx/document_intelligence_observability.py"
        ).is_file(),
    }
    resolution_checks = {
        "summary_generation_is_local_mock": (
            root / "services/nex-cx/nex_cx/document_summary_generation.py"
        ).is_file(),
        "private_summary_text_is_process_local": (
            root / "services/nex-cx/nex_cx/document_summary_storage.py"
        ).is_file(),
        "summary_vector_is_process_local": (
            root / "services/nex-cx/nex_cx/summary_pgvector_store.py"
        ).is_file(),
        "summary_pgvector_payload_missing": (
            root
            / "database/nex-cx/migrations/0955_cx_summary_vector_persistence.sql"
        ).is_file(),
        "owner_scoped_summary_similarity_missing": (
            root / "services/nex-cx/nex_cx/summary_similarity.py"
        ).is_file(),
        "summary_similarity_freshness_guard_missing": all(
            (
                (
                    root / "services/nex-cx/nex_cx/summary_pgvector_store.py"
                ).is_file(),
                (root / "services/nex-cx/nex_cx/summary_similarity.py").is_file(),
            )
        ),
        "document_intelligence_observability_missing": (
            root / "services/nex-cx/nex_cx/document_intelligence_observability.py"
        ).is_file(),
    }
    gap_checks = {
        name: gap_observations[name] or resolution_checks[name]
        for name in gap_observations
    }
    gap_states = {
        name: "RESOLVED" if resolution_checks[name] else "OPEN"
        for name in gap_observations
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s95_handoff_bound": _group_present(tokens, "s95_handoff"),
        "summary_contract_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "summary_limit",
                "summary_prompt_registry",
                "owner_authorization",
            )
        ),
        "summary_embedding_foundation_confirmed": _group_present(
            tokens, "summary_embedding_provider"
        ),
        "metadata_persistence_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "summary_metadata_table",
                "summary_embedding_metadata_table",
                "summary_repository",
                "summary_embedding_repository",
            )
        ),
        "durable_ingestion_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "durable_ingestion_summary",
                "durable_ingestion_summary_embedding",
            )
        ),
        "private_payload_boundary_confirmed": _group_present(
            tokens, "private_summary_capability"
        ),
        "provider_profiles_confirmed": all(
            _group_present(tokens, group)
            for group in ("generation_model", "embedding_model")
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
    issues.extend(
        {"category": "implementation_gap_unaccounted", "gap": name}
        for name, confirmed in gap_checks.items()
        if not confirmed
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "0951",
        "requirement": "S96",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "cx_document_intelligence_similarity_boundary_failed"
        ),
        "boundary_readiness": "BOUNDARY_CURRENT" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 8,
            "gap_count": 7,
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": [
            "summary_generation_is_local_mock",
            "private_summary_text_is_process_local",
            "summary_vector_is_process_local",
            "summary_pgvector_payload_missing",
            "owner_scoped_summary_similarity_missing",
            "summary_similarity_freshness_guard_missing",
            "document_intelligence_observability_missing",
        ],
        "slice_plan": [
            "0951_boundary_audit",
            "0952_document_intelligence_summary_contract",
            "0953_durable_private_summary_text_storage",
            "0954_generation_provider_summary_adapter",
            "0955_summary_vector_pgvector_freshness",
            "0956_owner_scoped_summary_similarity",
            "0957_document_intelligence_api_orchestration",
            "0958_operations_observability_contract_hardening",
            "0959_postgres_generation_embedding_live_smoke",
            "0960_s96_closure",
        ],
        "checks": checks,
        "gap_checks": gap_checks,
        "gap_observations": gap_observations,
        "gap_resolutions": resolution_checks,
        "gap_states": gap_states,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0952",
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "feature_scope": "owner_private_document_intelligence_summary_similarity",
        "summary_source": "latest_ready_extracted_markdown",
        "summary_hard_limit_chars": 1000,
        "summary_storage_policy": "private_durable_payload_reference",
        "summary_generation_model": "Qwen3.5-4B",
        "summary_embedding_model": "Qwen3-Embedding-4B",
        "summary_embedding_dimension": 2560,
        "similarity_backend": "owner_scoped_fresh_postgresql_pgvector",
        "similarity_metric": "cosine",
        "similarity_result_policy": "metadata_hashes_scores_bounded_preview",
        "cross_owner_behavior": "not_found_or_excluded_without_disclosure",
        "provider_execution_order": [
            "authorize_owner",
            "load_latest_ready_markdown",
            "generate_bounded_summary",
            "persist_private_summary",
            "embed_summary",
            "publish_fresh_summary_vector",
            "query_owner_scoped_similarity",
        ],
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "remote_provider_required_now": False,
        "remote_provider_required_slice": "0959",
        "deferred_scope": [
            "cross_owner_shared_acl_similarity",
            "summary_topic_taxonomy_and_classification",
            "multi_tenant_similarity_scale_tuning",
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
        "cx_document_intelligence_similarity_boundary="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"scope={decision.get('feature_scope', 'unknown')} "
        f"remote_required_now={decision.get('remote_provider_required_now', True)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_document_intelligence_similarity_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
