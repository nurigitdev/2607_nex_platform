#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "cx_current_state_reaudit_boundary.v1"
SLICE_ID = "0901"
REQUIREMENT = "S91"
BOUNDARY = "cx_current_state_reaudit_and_refactoring_checkpoint"


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    RequiredPath(
        "s90_closure",
        "scripts/smoke/run_s90_ag_mvp_acceptance_cx_transition_closure.py",
    ),
    RequiredPath("cx_readme", "services/nex-cx/README.md"),
    RequiredPath("cx_runtime", "services/nex-cx/nex_cx/main.py"),
    RequiredPath("cx_repository", "services/nex-cx/nex_cx/repository.py"),
    RequiredPath("cx_ingestion", "services/nex-cx/nex_cx/ingestion.py"),
    RequiredPath("cx_processing", "services/nex-cx/nex_cx/processing.py"),
    RequiredPath("cx_retrieval", "services/nex-cx/nex_cx/retrieval.py"),
    RequiredPath("cx_generation", "services/nex-cx/nex_cx/generation.py"),
    RequiredPath(
        "cx_persistence_audit",
        "services/nex-cx/nex_cx/persistence_audit.py",
    ),
    RequiredPath(
        "cx_latest_migration",
        "database/nex-cx/migrations/0355_cx_repair_attempt_lineage_persistence_foundation.sql",
    ),
    RequiredPath("cx_openapi", "contracts/openapi/nex-cx.openapi.yaml"),
    RequiredPath(
        "service_requirements",
        "docs/30_service_specific_requirement_partition.md",
    ),
    RequiredPath("testing_strategy", "docs/34_testing_strategy_v0_1_detail.md"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0901_cx_current_state_reaudit_boundary.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s90_handoff",
        "scripts/smoke/run_s90_ag_mvp_acceptance_cx_transition_closure.py",
        '"next_requirement": "S91"',
    ),
    TokenRequirement(
        "cx_app",
        "services/nex-cx/nex_cx/main.py",
        "app = build_service_app(SERVICE_SPEC)",
    ),
    TokenRequirement(
        "repository",
        "services/nex-cx/nex_cx/repository.py",
        "class SqlAlchemyCxContentRepository",
    ),
    TokenRequirement(
        "ingestion",
        "services/nex-cx/nex_cx/ingestion.py",
        "class ContentIngestionStore",
    ),
    TokenRequirement(
        "processing",
        "services/nex-cx/nex_cx/processing.py",
        "def run_document_processing_pipeline",
    ),
    TokenRequirement(
        "retrieval",
        "services/nex-cx/nex_cx/retrieval.py",
        "def build_retrieval_context_package",
    ),
    TokenRequirement(
        "generation",
        "services/nex-cx/nex_cx/generation.py",
        "def create_generation",
    ),
    TokenRequirement(
        "persistence_audit",
        "services/nex-cx/nex_cx/persistence_audit.py",
        "def build_cx_persistence_gap_audit",
    ),
    TokenRequirement(
        "cx_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "CX-FR-008",
    ),
    TokenRequirement(
        "coverage_policy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Branch coverage",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_cx_current_state_reaudit_boundary.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0901_cx_current_state_reaudit_boundary.md",
    ),
)


def run_cx_current_state_reaudit_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in TOKEN_REQUIREMENTS
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s90_handoff_ready": _group_present(tokens, "s90_handoff"),
        "cx_runtime_reusable": all(
            _group_present(tokens, group)
            for group in (
                "cx_app",
                "repository",
                "ingestion",
                "processing",
                "retrieval",
                "generation",
            )
        ),
        "audit_inputs_reusable": all(
            _group_present(tokens, group)
            for group in (
                "persistence_audit",
                "cx_requirements",
                "coverage_policy",
            )
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
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_current_state_reaudit_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-cx",
            "audit_scope": "cx_fr_001_through_008",
            "repository_state_is_primary_evidence": True,
            "legacy_gap_documents_are_advisory": True,
            "refactor_before_feature_when_needed": True,
            "actual_test_database_evidence_required": True,
            "live_provider_evidence_is_supplementary": True,
            "new_table_required": False,
            "existing_cx_records_mutated": False,
            "next_requirement": "S92",
            "decision_status": "FROZEN",
        },
        "audit_surfaces": [
            "source_and_content_ownership",
            "private_payload_storage",
            "extraction_and_chunking",
            "lexical_and_vector_indexes",
            "retrieval_and_context_packages",
            "grounded_generation_and_recovery",
            "database_migrations_and_indexes",
            "contracts_operations_and_privacy",
        ],
        "deferred_scope": [
            "new_end_user_feature_development",
            "production_object_storage_activation",
            "external_vector_database_selection",
            "production_load_and_disaster_recovery_certification",
        ],
        "slice_plan": [
            "0901_boundary_audit",
            "0902_srs_capability_traceability_inventory",
            "0903_persistence_gap_rebaseline",
            "0904_private_payload_storage_decision",
            "0905_ownership_permission_enforcement_audit",
            "0906_runtime_coupling_refactoring_checkpoint",
            "0907_database_migration_drift_audit",
            "0908_contract_api_drift_audit",
            "0909_postgres_reaudit_privacy_runbook",
            "0910_s91_closure_s92_handoff",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    return any(
        item.get("group") == group and item.get("present") is True
        for item in items
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "cx_current_state_reaudit_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "cx_current_state_reaudit_boundary=pass "
        f"scope={decision.get('audit_scope')} "
        f"owner={decision.get('owner')} "
        f"new_table={decision.get('new_table_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_current_state_reaudit_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
