#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_vector_storage_freshness_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0930_s93_cx_durable_ingestion_closure.md",
    "services/nex-cx/nex_cx/private_content.py",
    "services/nex-cx/nex_cx/private_vector_store.py",
    "services/nex-cx/nex_cx/embedding_index.py",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/repository.py",
    "services/nex-cx/nex_cx/retrieval.py",
    "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
    ".env.example",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0931_cx_vector_storage_freshness_boundary_audit.md",
)
EVIDENCE_TOKENS = (
    EvidenceToken(
        "s93_handoff",
        "docs/slices/0930_s93_cx_durable_ingestion_closure.md",
        "READY_FOR_S94",
    ),
    EvidenceToken(
        "vector_port",
        "services/nex-cx/nex_cx/private_content.py",
        "class CxVectorStore(Protocol)",
    ),
    EvidenceToken(
        "filesystem_adapter",
        "services/nex-cx/nex_cx/private_vector_store.py",
        "class FileSystemCxVectorStore",
    ),
    EvidenceToken(
        "metadata_table",
        "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
        "CREATE TABLE IF NOT EXISTS cx_chunk_embeddings",
    ),
    EvidenceToken(
        "metadata_storage_uri",
        "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
        "embedding_storage_uri TEXT",
    ),
    EvidenceToken(
        "metadata_repository",
        "services/nex-cx/nex_cx/repository.py",
        "def save_chunk_embedding_index",
    ),
    EvidenceToken(
        "volatile_vectors",
        "services/nex-cx/nex_cx/ingestion.py",
        "embedding_vectors: dict[str, list[float]]",
    ),
    EvidenceToken(
        "runtime_direct_vector_write",
        "services/nex-cx/nex_cx/embedding_index.py",
        "private_vectors[chunk_id] = vector",
    ),
    EvidenceToken(
        "retrieval_presence_freshness",
        "services/nex-cx/nex_cx/retrieval.py",
        '"index_status": "READY" if embedding_index else "MISSING"',
    ),
    EvidenceToken(
        "vector_database_override",
        ".env.example",
        "NEX_CX_VECTOR_DATABASE_URL=",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_vector_storage_freshness_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0931_cx_vector_storage_freshness_boundary_audit.md",
    ),
)


def run_cx_vector_storage_freshness_boundary_audit(
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
    source = {
        path: _read_text(root / path)
        for path in (
            "services/nex-cx/nex_cx/embedding_index.py",
            "services/nex-cx/nex_cx/main.py",
            "services/nex-cx/nex_cx/private_vector_store.py",
        )
    }
    gap_checks = {
        "runtime_capability_not_wired": "build_private_vector_store" not in source[
            "services/nex-cx/nex_cx/embedding_index.py"
        ]
        and "build_private_vector_store" not in source[
            "services/nex-cx/nex_cx/main.py"
        ],
        "pgvector_adapter_missing": "PgVectorCxVectorStore" not in source[
            "services/nex-cx/nex_cx/private_vector_store.py"
        ],
        "freshness_contract_missing": "REBUILD_REQUIRED" not in source[
            "services/nex-cx/nex_cx/embedding_index.py"
        ],
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s93_handoff_bound": _group_present(tokens, "s93_handoff"),
        "private_vector_foundation_confirmed": all(
            _group_present(tokens, group)
            for group in ("vector_port", "filesystem_adapter")
        ),
        "metadata_persistence_confirmed": all(
            _group_present(tokens, group)
            for group in (
                "metadata_table",
                "metadata_storage_uri",
                "metadata_repository",
            )
        ),
        "volatile_vector_runtime_confirmed": all(
            _group_present(tokens, group)
            for group in ("volatile_vectors", "runtime_direct_vector_write")
        ),
        "presence_only_freshness_confirmed": _group_present(
            tokens, "retrieval_presence_freshness"
        ),
        "optional_vector_database_route_reserved": _group_present(
            tokens, "vector_database_override"
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
        "slice": "0931",
        "requirement": "S94",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_vector_storage_freshness_boundary_failed"
        ),
        "boundary_readiness": "GAPS_CONFIRMED" if passed else "AUDIT_FAILED",
        "decision": _boundary_decision(),
        "summary": {
            "foundation_count": 6,
            "gap_count": 6,
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "implementation_gaps": [
            "embedding_vectors_are_process_local",
            "pgvector_adapter_is_not_implemented",
            "embedding_runtime_does_not_use_private_vector_port",
            "freshness_fingerprint_and_state_contract_are_missing",
            "retrieval_treats_index_presence_as_ready",
            "no_postgres_plus_live_embedding_end_to_end_evidence",
        ],
        "slice_plan": [
            "0931_boundary_audit",
            "0932_embedding_profile_freshness_contract",
            "0933_vector_manifest_payload_persistence",
            "0934_owner_scoped_pgvector_adapter",
            "0935_atomic_private_vector_publish",
            "0936_stale_detection_reindex_reconciliation",
            "0937_retrieval_freshness_enforcement",
            "0938_protected_readiness_api_observability",
            "0939_postgres_remote_embedding_live_smoke",
            "0940_s94_closure",
        ],
        "checks": checks,
        "gap_checks": gap_checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0932",
    }


def _boundary_decision() -> dict[str, Any]:
    return {
        "metadata_system_of_record": "nex_cx_postgresql",
        "vector_payload_port": "CxVectorStore",
        "default_vector_payload_backend": "postgresql_pgvector",
        "vector_database_routing": (
            "NEX_CX_VECTOR_DATABASE_URL_or_primary_nex_cx_database"
        ),
        "fallback_backend": "filesystem_for_deterministic_local_regression",
        "manifest_table": "cx_vector_indexes",
        "payload_table": "cx_vectors",
        "freshness_states": [
            "BUILDING",
            "READY",
            "STALE",
            "REBUILD_REQUIRED",
            "FAILED",
        ],
        "retrieval_policy": "ready_and_compatible_indexes_only",
        "remote_embedding_required_now": False,
        "remote_embedding_required_slice": "0939",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "live_embedding_model": "Qwen3-Embedding-4B",
        "expected_live_dimension": 2560,
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
        "cx_vector_storage_freshness_boundary="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"foundations={summary.get('foundation_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"backend={decision.get('default_vector_payload_backend', 'unknown')} "
        f"remote_required_now={decision.get('remote_embedding_required_now', True)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_vector_storage_freshness_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
