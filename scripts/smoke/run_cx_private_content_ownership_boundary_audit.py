#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_private_content_ownership_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/0910_s91_cx_current_state_reaudit_closure.md",
    "services/nex-cx/nex_cx/ingestion.py",
    "services/nex-cx/nex_cx/repository.py",
    "services/nex-cx/nex_cx/main.py",
    "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
    "database/nex-cx/migrations/0194_cx_source_ownership_schema_migration.sql",
    "scripts/quality/run_quality_gate.sh",
    "docs/README.md",
    "docs/slices/0911_cx_private_content_ownership_boundary_audit.md",
)
EVIDENCE_TOKENS = (
    EvidenceToken(
        "s91_handoff",
        "docs/slices/0910_s91_cx_current_state_reaudit_closure.md",
        "READY_FOR_TARGETED_S92_REFACTORING",
    ),
    EvidenceToken(
        "private_source_text",
        "services/nex-cx/nex_cx/ingestion.py",
        "source_texts: dict[str, str]",
    ),
    EvidenceToken(
        "private_chunk_text",
        "services/nex-cx/nex_cx/ingestion.py",
        "chunk_texts: dict[str, str]",
    ),
    EvidenceToken(
        "private_chunk_vector",
        "services/nex-cx/nex_cx/ingestion.py",
        "embedding_vectors: dict[str, list[float]]",
    ),
    EvidenceToken(
        "private_summary_text",
        "services/nex-cx/nex_cx/ingestion.py",
        "summary_texts: dict[str, str]",
    ),
    EvidenceToken(
        "private_summary_vector",
        "services/nex-cx/nex_cx/ingestion.py",
        "summary_embedding_vectors: dict[str, list[float]]",
    ),
    EvidenceToken(
        "metadata_chunk_uri",
        "database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql",
        "embedding_storage_uri TEXT",
    ),
    EvidenceToken(
        "metadata_owner_columns",
        "database/nex-cx/migrations/0194_cx_source_ownership_schema_migration.sql",
        "owner_subject_ref_id TEXT",
    ),
    EvidenceToken(
        "runtime_singleton",
        "services/nex-cx/nex_cx/main.py",
        "DEFAULT_INGESTION_STORE.content_repository = CX_CONTENT_REPOSITORY",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_private_content_ownership_boundary_audit.py",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "0911_cx_private_content_ownership_boundary_audit.md",
    ),
)


def run_cx_private_content_ownership_boundary_audit(
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
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s91_handoff_bound": _group_present(tokens, "s91_handoff"),
        "volatile_private_payloads_inventoried": all(
            _group_present(tokens, group)
            for group in (
                "private_source_text",
                "private_chunk_text",
                "private_chunk_vector",
                "private_summary_text",
                "private_summary_vector",
            )
        ),
        "metadata_only_schema_evidenced": all(
            _group_present(tokens, group)
            for group in ("metadata_chunk_uri", "metadata_owner_columns")
        ),
        "runtime_refactor_trigger_evidenced": _group_present(
            tokens, "runtime_singleton"
        ),
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
        "slice": "0911",
        "requirement": "S92",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_private_content_ownership_boundary_failed"
        ),
        "boundary_readiness": "GAPS_CONFIRMED" if passed else "AUDIT_FAILED",
        "decision": {
            "public_postgres_policy": "metadata_hash_uri_dimension_only",
            "private_payload_owner": "cx_private_content_capability_ports",
            "first_adapter": "owner_scoped_local_filesystem",
            "future_adapter": "object_and_vector_storage",
            "access_context": "CxAccessContext",
            "runtime_composition": "app_factory_owned_dependencies",
            "migration_history": "versioned_sql_schema_migrations_runner",
            "dgx_live_provider_required": False,
            "new_table_required_in_slice": False,
            "existing_records_mutated_in_slice": False,
        },
        "summary": {
            "volatile_private_payload_count": 5,
            "adapter_required_payload_count": 4,
            "owner_lineage_target_count": 4,
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "private_payloads": [
            "source_text",
            "chunk_text",
            "chunk_embedding_vector",
            "summary_text",
            "summary_embedding_vector",
        ],
        "owner_lineage_targets": [
            "service_jobs",
            "cx_document_processing_runs",
            "cx_retrieval_packages",
            "generation_execution_state",
        ],
        "slice_plan": [
            "0911_boundary_audit",
            "0912_access_context_contract_resolver",
            "0913_central_authorization_enforcement",
            "0914_private_content_capability_ports",
            "0915_filesystem_private_text_adapter",
            "0916_private_vector_adapter_runtime_wiring",
            "0917_owner_scoped_lineage_persistence",
            "0918_api_contract_ownership_hardening",
            "0919_postgres_privacy_ownership_smoke",
            "0920_s92_closure",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": "0912",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(
        item.get("group") == group and item.get("present") is True
        for item in items
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    decision = evidence.get("decision") or {}
    return (
        "cx_private_content_ownership_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"private_payloads={summary.get('volatile_private_payload_count', 0)} "
        f"owner_targets={summary.get('owner_lineage_target_count', 0)} "
        f"dgx_required={decision.get('dgx_live_provider_required', False)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_private_content_ownership_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
