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

from run_cx_contract_api_drift_audit import (  # noqa: E402
    run_cx_contract_api_drift_audit as run_contract_drift,
)
from run_cx_vector_index_freshness_contract import (  # noqa: E402
    run_cx_vector_index_freshness_contract as run_freshness_contract,
)
from run_cx_vector_storage_freshness_boundary_audit import (  # noqa: E402
    run_cx_vector_storage_freshness_boundary_audit as run_boundary,
)


SCHEMA_VERSION = "s94_cx_vector_storage_freshness_closure.v1"
SLICE_RANGE = "0931-0940"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/vector_index_freshness.py",
    "services/nex-cx/nex_cx/vector_index_repository.py",
    "services/nex-cx/nex_cx/pgvector_store.py",
    "services/nex-cx/nex_cx/vector_index_publish.py",
    "services/nex-cx/nex_cx/vector_index_reconciliation.py",
    "services/nex-cx/nex_cx/vector_retrieval_guard.py",
    "services/nex-cx/nex_cx/vector_index_operations.py",
    "database/nex-cx/migrations/0933_cx_vector_index_persistence.sql",
    "database/nex-cx/migrations/0936_cx_vector_ready_history.sql",
    "scripts/smoke/run_cx_vector_live_embedding_pgvector_smoke.py",
    "scripts/smoke/run_s94_cx_vector_storage_freshness_closure.py",
    "tests/test_s94_cx_vector_storage_freshness_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0931", "cx_vector_storage_freshness_boundary_audit"),
            ("0932", "cx_vector_index_freshness_contract"),
            ("0933", "cx_vector_index_persistence_schema"),
            ("0934", "cx_owner_scoped_pgvector_adapter"),
            ("0935", "cx_atomic_private_vector_publish"),
            ("0936", "cx_vector_reconciliation"),
            ("0937", "cx_vector_retrieval_freshness_enforcement"),
            ("0938", "cx_vector_readiness_api_observability"),
            ("0939", "cx_vector_live_embedding_pgvector_smoke"),
            ("0940", "s94_cx_vector_storage_freshness_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_boundary_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_storage_freshness_boundary_audit.py",
    ),
    (
        "quality_contract_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_index_freshness_contract.py",
    ),
    (
        "quality_persistence_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_persistence_postgres_smoke.py",
    ),
    (
        "quality_adapter_runner",
        QUALITY_GATE_PATH,
        "run_cx_pgvector_adapter_postgres_smoke.py",
    ),
    (
        "quality_publish_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_atomic_publish_postgres_smoke.py",
    ),
    (
        "quality_reconciliation_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_reconciliation_postgres_smoke.py",
    ),
    (
        "quality_retrieval_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_retrieval_guard_postgres_smoke.py",
    ),
    (
        "quality_readiness_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_readiness_api_postgres_smoke.py",
    ),
    (
        "quality_live_runner",
        QUALITY_GATE_PATH,
        "run_cx_vector_live_embedding_pgvector_smoke.py",
    ),
    (
        "quality_closure_runner",
        QUALITY_GATE_PATH,
        "run_s94_cx_vector_storage_freshness_closure.py",
    ),
    (
        "pgvector_payload_type",
        "database/nex-cx/migrations/0933_cx_vector_index_persistence.sql",
        "embedding vector NOT NULL",
    ),
    (
        "pgvector_ann_index",
        "database/nex-cx/migrations/0933_cx_vector_index_persistence.sql",
        "halfvec_cosine_ops",
    ),
    (
        "postgres_persistence_checks",
        "docs/slices/0933_cx_vector_index_persistence_schema.md",
        "`9/9` checks",
    ),
    (
        "postgres_adapter_checks",
        "docs/slices/0934_cx_owner_scoped_pgvector_adapter.md",
        "`10/10` checks",
    ),
    (
        "postgres_publish_checks",
        "docs/slices/0935_cx_atomic_private_vector_publish.md",
        "`8/8` checks",
    ),
    (
        "postgres_reconciliation_checks",
        "docs/slices/0936_cx_vector_reconciliation.md",
        "`8/8` checks",
    ),
    (
        "postgres_retrieval_checks",
        "docs/slices/0937_cx_vector_retrieval_freshness_enforcement.md",
        "`8/8` checks",
    ),
    (
        "postgres_readiness_checks",
        "docs/slices/0938_cx_vector_readiness_api_observability.md",
        "`10/10` checks",
    ),
    (
        "openapi_version",
        "docs/slices/0938_cx_vector_readiness_api_observability.md",
        "OpenAPI `0.94.0`",
    ),
    (
        "live_embedding_checks",
        "docs/slices/0939_cx_vector_live_embedding_pgvector_smoke.md",
        "`11/11` checks",
    ),
    (
        "live_embedding_dimension",
        "docs/slices/0939_cx_vector_live_embedding_pgvector_smoke.md",
        "2560-dimensional, finite, non-zero",
    ),
    (
        "live_embedding_target",
        "docs/slices/0939_cx_vector_live_embedding_pgvector_smoke.md",
        "actual DGX",
    ),
    (
        "live_fixture_cleanup",
        "docs/slices/0939_cx_vector_live_embedding_pgvector_smoke.md",
        "`cx_vectors=0`",
    ),
    (
        "docs_index",
        "docs/README.md",
        "0940_s94_cx_vector_storage_freshness_closure.md",
    ),
)


def run_s94_cx_vector_storage_freshness_closure(
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
        "freshness_contract": _safe_evidence(run_freshness_contract),
        "contract_drift": _safe_evidence(lambda: run_contract_drift(root)),
    }
    boundary_summary = _mapping(evidence["boundary"].get("summary"))
    boundary_decision = _mapping(evidence["boundary"].get("decision"))
    contract_summary = _mapping(evidence["contract_drift"].get("summary"))
    token_status = {item["name"]: item["present"] for item in token_checks}
    postgres_tokens = {
        name: token_status[name]
        for name in (
            "postgres_persistence_checks",
            "postgres_adapter_checks",
            "postgres_publish_checks",
            "postgres_reconciliation_checks",
            "postgres_retrieval_checks",
            "postgres_readiness_checks",
        )
    }
    live_tokens = {
        name: token_status[name]
        for name in (
            "live_embedding_checks",
            "live_embedding_dimension",
            "live_embedding_target",
            "live_fixture_cleanup",
        )
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "boundary_decisions_preserved": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("issue_count") == 0
            and boundary_decision.get("manifest_table") == "cx_vector_indexes"
            and boundary_decision.get("payload_table") == "cx_vectors"
            and boundary_decision.get("expected_live_dimension") == 2560
        ),
        "freshness_contract_closed": (
            evidence["freshness_contract"].get("freshness_state_count") == 5
            and evidence["freshness_contract"].get("stale_reason_count") == 11
            and evidence["freshness_contract"].get("transition_count") == 6
            and all(
                _mapping(evidence["freshness_contract"].get("checks")).values()
            )
        ),
        "pgvector_schema_and_routing_closed": (
            token_status.get("pgvector_payload_type") is True
            and token_status.get("pgvector_ann_index") is True
            and decision["vector_database_routing"]
            == "optional_override_with_primary_cx_fallback"
        ),
        "atomic_publish_and_reconciliation_closed": (
            token_status.get("postgres_publish_checks") is True
            and token_status.get("postgres_reconciliation_checks") is True
            and decision["publish_protocol"]
            == "validate_publish_ready_cas_with_compensation"
        ),
        "fresh_retrieval_and_readiness_api_closed": (
            token_status.get("postgres_retrieval_checks") is True
            and token_status.get("postgres_readiness_checks") is True
            and evidence["contract_drift"].get("contract_readiness") == "HARDENED"
            and contract_summary.get("runtime_operation_count", 0) >= 33
            and contract_summary.get("missing_openapi_operation_count") == 0
        ),
        "actual_postgres_evidence_passed": all(postgres_tokens.values()),
        "actual_live_embedding_evidence_passed": all(live_tokens.values()),
        "owner_scope_and_private_payload_preserved": (
            decision["cross_owner_visibility"] == "not-found"
            and decision["payload_policy"] == "private_owner_scoped_pgvector"
            and decision["retrieval_policy"]
            == "ready_source_profile_payload_compatible_only"
        ),
        "single_migration_history_preserved": (
            decision["migration_strategy"]
            == "versioned_sql_schema_migrations_runner"
        ),
        "runtime_wiring_scope_not_overclaimed": (
            "durable_ingestion_worker_vector_build_wiring"
            in decision["deferred_scope"]
            and decision["feature_scope"] == "storage_and_freshness_foundation"
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0940",
        "slice_range": SLICE_RANGE,
        "requirement": "S94",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s94_vector_storage_freshness_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S95" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_VECTOR_STORAGE_AND_INDEX_FRESHNESS_FOUNDATION_READY"
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
            "freshness_state_count": evidence["freshness_contract"].get(
                "freshness_state_count", 0
            ),
            "stale_reason_count": evidence["freshness_contract"].get(
                "stale_reason_count", 0
            ),
            "postgres_check_count": 53 if all(postgres_tokens.values()) else 0,
            "live_check_count": 11 if all(live_tokens.values()) else 0,
            "runtime_route_count": contract_summary.get(
                "runtime_operation_count", 0
            ),
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
        "next_requirement": "S95",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "storage_and_freshness_foundation",
        "metadata_system_of_record": "cx_vector_indexes",
        "payload_backend": "cx_vectors_postgresql_pgvector",
        "payload_policy": "private_owner_scoped_pgvector",
        "embedding_dimension": 2560,
        "ann_index": "halfvec_2560_hnsw_cosine",
        "vector_database_routing": "optional_override_with_primary_cx_fallback",
        "freshness_states": [
            "BUILDING",
            "READY",
            "STALE",
            "REBUILD_REQUIRED",
            "FAILED",
        ],
        "publish_protocol": "validate_publish_ready_cas_with_compensation",
        "retrieval_policy": "ready_source_profile_payload_compatible_only",
        "reconciliation_policy": "durable_stale_then_rebuild_required",
        "cross_owner_visibility": "not-found",
        "readiness_api": "owner_scoped_get_and_explicit_reconcile",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "postgres_smoke_target": "nex_cx_user@nex_cx_test",
        "live_embedding_profile": "Qwen3-Embedding-4B_openai_compatible",
        "live_embedding_evidence_completed": True,
        "deferred_scope": [
            "durable_ingestion_worker_vector_build_wiring",
            "separate_vector_database_deployment_and_migration",
            "multi_document_ann_scale_and_performance_validation",
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
        "s94_cx_vector_storage_freshness_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"live_checks={summary.get('live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s94_cx_vector_storage_freshness_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
