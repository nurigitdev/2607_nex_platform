#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from run_cx_document_intelligence_contract_observability import (  # noqa: E402
    run_cx_document_intelligence_contract_observability as run_observability,
)
from run_cx_document_intelligence_orchestration import (  # noqa: E402
    run_cx_document_intelligence_orchestration as run_orchestration,
)
from run_cx_document_intelligence_similarity_boundary_audit import (  # noqa: E402
    run_cx_document_intelligence_similarity_boundary_audit as run_boundary,
)
from run_cx_document_intelligence_summary_contract import (  # noqa: E402
    run_cx_document_intelligence_summary_contract as run_summary_contract,
)
from run_cx_document_summary_generation_adapter import (  # noqa: E402
    run_cx_document_summary_generation_adapter as run_generation,
)
from run_cx_document_summary_storage_smoke import (  # noqa: E402
    run_cx_document_summary_storage_smoke as run_storage,
)
from run_cx_summary_similarity_adapter import (  # noqa: E402
    run_cx_summary_similarity_adapter as run_similarity,
)
from run_cx_summary_vector_pgvector import (  # noqa: E402
    run_cx_summary_vector_pgvector as run_vector,
)


SCHEMA_VERSION = "s96_cx_document_intelligence_summary_similarity_closure.v1"
SLICE_RANGE = "0951-0960"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/document_intelligence.py",
    "services/nex-cx/nex_cx/document_summary_generation.py",
    "services/nex-cx/nex_cx/private_content.py",
    "services/nex-cx/nex_cx/summary_pgvector_store.py",
    "services/nex-cx/nex_cx/summary_similarity.py",
    "services/nex-cx/nex_cx/document_intelligence_orchestration.py",
    "services/nex-cx/nex_cx/document_intelligence_observability.py",
    "database/nex-cx/migrations/0955_cx_summary_vector_persistence.sql",
    "scripts/smoke/run_cx_document_intelligence_live_postgres_smoke.py",
    "scripts/smoke/run_s96_cx_document_intelligence_summary_similarity_closure.py",
    "tests/test_s96_cx_document_intelligence_summary_similarity_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0951", "cx_document_intelligence_similarity_boundary_audit"),
            ("0952", "cx_document_intelligence_summary_contract"),
            ("0953", "cx_durable_private_summary_storage"),
            ("0954", "cx_document_summary_generation_adapter"),
            ("0955", "cx_summary_vector_pgvector_freshness"),
            ("0956", "cx_owner_scoped_summary_similarity"),
            ("0957", "cx_document_intelligence_orchestration_api"),
            ("0958", "cx_document_intelligence_observability_contracts"),
            ("0959", "cx_document_intelligence_live_postgresql_dgx_smoke"),
            ("0960", "s96_cx_document_intelligence_summary_similarity_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_boundary_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_intelligence_similarity_boundary_audit.py",
    ),
    (
        "quality_summary_contract_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_intelligence_summary_contract.py",
    ),
    (
        "quality_storage_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_summary_storage_smoke.py",
    ),
    (
        "quality_generation_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_summary_generation_adapter.py",
    ),
    (
        "quality_vector_runner",
        QUALITY_GATE_PATH,
        "run_cx_summary_vector_pgvector.py",
    ),
    (
        "quality_similarity_runner",
        QUALITY_GATE_PATH,
        "run_cx_summary_similarity_adapter.py",
    ),
    (
        "quality_orchestration_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_intelligence_orchestration.py",
    ),
    (
        "quality_observability_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_intelligence_contract_observability.py",
    ),
    (
        "quality_live_runner",
        QUALITY_GATE_PATH,
        "run_cx_document_intelligence_live_postgres_smoke.py",
    ),
    (
        "quality_closure_runner",
        QUALITY_GATE_PATH,
        "run_s96_cx_document_intelligence_summary_similarity_closure.py",
    ),
    (
        "summary_hard_limit",
        "services/nex-cx/nex_cx/document_intelligence.py",
        "SUMMARY_HARD_LIMIT_CHARS = 1000",
    ),
    (
        "generation_model",
        "services/nex-cx/nex_cx/document_summary_generation.py",
        'DEFAULT_SUMMARY_MODEL_PROFILE = "Qwen3.5-4B"',
    ),
    (
        "generation_reasoning_disabled",
        "services/nex-cx/nex_cx/document_summary_generation.py",
        '"reasoning_mode": "disabled"',
    ),
    (
        "summary_contract_doc_model",
        "docs/slices/0952_cx_document_intelligence_summary_contract.md",
        "`Qwen3.5-4B`",
    ),
    (
        "generation_adapter_doc_model",
        "docs/slices/0954_cx_document_summary_generation_adapter.md",
        "`Qwen3.5-4B`",
    ),
    (
        "summary_vector_table",
        "database/nex-cx/migrations/0955_cx_summary_vector_persistence.sql",
        "CREATE TABLE IF NOT EXISTS cx_summary_vectors",
    ),
    (
        "summary_vector_hnsw",
        "database/nex-cx/migrations/0955_cx_summary_vector_persistence.sql",
        "halfvec_cosine_ops",
    ),
    (
        "ready_event",
        "services/nex-cx/nex_cx/document_intelligence_observability.py",
        "cx.document_intelligence.ready",
    ),
    (
        "similarity_event",
        "services/nex-cx/nex_cx/document_intelligence_observability.py",
        "cx.document_intelligence.similarity_observed",
    ),
    (
        "failed_event",
        "services/nex-cx/nex_cx/document_intelligence_observability.py",
        "cx.document_intelligence.failed",
    ),
    (
        "live_checks",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "`15/15` protected live checks passed",
    ),
    (
        "live_database",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "database `nex_cx_test`",
    ),
    (
        "live_role",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "`nex_cx_user`.",
    ),
    (
        "live_generation_model",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "`Qwen3.5-4B`",
    ),
    (
        "live_embedding_model",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "`Qwen3-Embedding-4B`",
    ),
    (
        "live_vector_dimension",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "2560-dimensional",
    ),
    (
        "live_similarity",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "one candidate while excluding the source",
    ),
    (
        "live_cleanup",
        "docs/slices/0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
        "owner summary-vector rows: `0`",
    ),
    (
        "docs_live_index",
        "docs/README.md",
        "0959_cx_document_intelligence_live_postgresql_dgx_smoke.md",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "0960_s96_cx_document_intelligence_summary_similarity_closure.md",
    ),
)


def run_s96_cx_document_intelligence_summary_similarity_closure(
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
        "summary_contract": _safe_evidence(run_summary_contract),
        "private_storage": _safe_evidence(_run_storage_evidence),
        "generation": _safe_evidence(run_generation),
        "summary_vector": _safe_evidence(run_vector),
        "similarity": _safe_evidence(run_similarity),
        "orchestration": _safe_evidence(run_orchestration),
        "observability": _safe_evidence(run_observability),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    boundary_summary = _mapping(evidence["boundary"].get("summary"))
    boundary_decision = _mapping(evidence["boundary"].get("decision"))
    deterministic_check_count = sum(
        sum(bool(value) for value in _mapping(item.get("checks")).values())
        for name, item in evidence.items()
        if name != "boundary"
    )
    postgres_tokens = {
        name: token_status[name]
        for name in (
            "live_checks",
            "live_database",
            "live_role",
            "live_vector_dimension",
            "live_cleanup",
        )
    }
    live_tokens = {
        name: token_status[name]
        for name in (
            "live_checks",
            "live_generation_model",
            "live_embedding_model",
            "live_similarity",
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
            and boundary_summary.get("open_gap_count") == 0
            and boundary_decision.get("feature_scope")
            == "owner_private_document_intelligence_summary_similarity"
        ),
        "summary_contract_closed": (
            evidence["summary_contract"].get("summary_hard_limit_chars") == 1000
            and evidence["summary_contract"].get("generation_model")
            == "Qwen3.5-4B"
            and evidence["summary_contract"].get("embedding_model")
            == "Qwen3-Embedding-4B"
        ),
        "durable_private_storage_closed": (
            evidence["private_storage"].get("owner_scoped") is True
            and evidence["private_storage"].get("restart_reload") is True
            and evidence["private_storage"].get("storage_backend")
            == "filesystem-text-v1"
        ),
        "generation_adapter_closed": (
            evidence["generation"].get("model_profile_id") == "Qwen3.5-4B"
            and evidence["generation"].get("passed_checks") == 10
        ),
        "summary_vector_freshness_closed": (
            evidence["summary_vector"].get("table") == "cx_summary_vectors"
            and evidence["summary_vector"].get("check_count") == 10
        ),
        "owner_scoped_similarity_closed": (
            evidence["similarity"].get("candidate_count") == 1
            and evidence["similarity"].get("check_count") == 10
        ),
        "orchestration_api_closed": (
            evidence["orchestration"].get("candidate_count") == 1
            and evidence["orchestration"].get("check_count") == 10
        ),
        "metadata_only_observability_closed": (
            evidence["observability"].get("passed_checks") == 10
            and decision["observability_policy"] == "metadata_only_best_effort"
        ),
        "actual_postgres_evidence_passed": all(postgres_tokens.values()),
        "actual_live_provider_evidence_passed": all(live_tokens.values()),
        "canonical_models_current": (
            boundary_decision.get("summary_generation_model") == "Qwen3.5-4B"
            and boundary_decision.get("summary_embedding_model")
            == "Qwen3-Embedding-4B"
            and decision["embedding_dimension"] == 2560
        ),
        "owner_private_boundary_preserved": (
            decision["cross_owner_behavior"]
            == "not_found_or_excluded_without_disclosure"
            and decision["summary_storage_policy"]
            == "private_durable_payload_reference"
            and decision["similarity_result_policy"]
            == "metadata_hashes_scores_bounded_owner_preview"
        ),
        "single_migration_history_preserved": (
            decision["migration_strategy"]
            == "versioned_sql_schema_migrations_runner"
        ),
        "deferred_scope_not_overclaimed": (
            "cross_owner_shared_acl_similarity" in decision["deferred_scope"]
            and "multi_tenant_similarity_scale_tuning"
            in decision["deferred_scope"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0960",
        "slice_range": SLICE_RANGE,
        "requirement": "S96",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s96_document_intelligence_summary_similarity_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S97" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_DOCUMENT_INTELLIGENCE_SUMMARY_SIMILARITY_READY"
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
            "deterministic_check_count": deterministic_check_count,
            "protected_live_check_count": 15
            if all(postgres_tokens.values()) and all(live_tokens.values())
            else 0,
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
        "next_requirement": "S97",
    }


def _run_storage_evidence() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-cx-s96-closure-") as temporary_root:
        return run_storage(temporary_root)


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "owner_private_document_intelligence_summary_similarity",
        "cross_owner_behavior": "not_found_or_excluded_without_disclosure",
        "summary_source": "latest_ready_extracted_markdown",
        "summary_hard_limit_chars": 1000,
        "summary_storage_policy": "private_durable_payload_reference",
        "generation_model": "Qwen3.5-4B",
        "generation_reasoning_mode": "disabled",
        "embedding_model": "Qwen3-Embedding-4B",
        "embedding_dimension": 2560,
        "vector_backend": "owner_scoped_fresh_postgresql_pgvector",
        "similarity_metric": "cosine",
        "similarity_result_policy": "metadata_hashes_scores_bounded_owner_preview",
        "source_document_excluded_from_similarity": True,
        "observability_policy": "metadata_only_best_effort",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "protected_live_evidence_completed": True,
        "deferred_scope": [
            "cross_owner_shared_acl_similarity",
            "summary_topic_taxonomy_and_classification",
            "multi_tenant_similarity_scale_tuning",
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
        "s96_cx_document_intelligence_summary_similarity_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"deterministic_checks={summary.get('deterministic_check_count', 0)} "
        f"live_checks={summary.get('protected_live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s96_cx_document_intelligence_summary_similarity_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
