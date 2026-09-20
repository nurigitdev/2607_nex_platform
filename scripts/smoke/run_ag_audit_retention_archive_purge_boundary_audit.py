#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_audit_retention_archive_purge_boundary_audit.v1"
SLICE_ID = "0881"
REQUIREMENT = "S89"
BOUNDARY = "ag_audit_evidence_retention_archive_and_guarded_purge"
MAX_IDENTIFIER_LENGTH = 30
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")
PROPOSED_RECEIPT_TABLE = "ag_ret_archives"


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
        "s88_closure",
        "scripts/smoke/run_s88_ag_resilience_performance_closure.py",
    ),
    RequiredPath(
        "event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
    ),
    RequiredPath(
        "export_migration",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
    ),
    RequiredPath(
        "event_store",
        "services/_shared/nex_runtime/operational_events.py",
    ),
    RequiredPath(
        "export_store",
        "services/nex-ag/nex_ag/operator_reviews.py",
    ),
    RequiredPath(
        "service_log_retention_reference",
        "services/nex-ag/nex_ag/service_log_retention.py",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0881_ag_audit_retention_archive_purge_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s88_closed",
        "scripts/smoke/run_s88_ag_resilience_performance_closure.py",
        "s88_ag_resilience_performance_closure.v1",
    ),
    TokenRequirement(
        "event_source",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
        "CREATE TABLE IF NOT EXISTS service_operational_events",
    ),
    TokenRequirement(
        "export_source",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "CREATE TABLE IF NOT EXISTS ag_ev_exports",
    ),
    TokenRequirement(
        "event_store",
        "services/_shared/nex_runtime/operational_events.py",
        "class SqlAlchemyOperationalEventStore",
    ),
    TokenRequirement(
        "export_delete",
        "services/nex-ag/nex_ag/operator_reviews.py",
        'text("DELETE FROM ag_ev_exports WHERE export_id = :export_id")',
    ),
    TokenRequirement(
        "retention_reference",
        "services/nex-ag/nex_ag/service_log_retention.py",
        "def purge_logs",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_audit_retention_archive_purge_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0881_ag_audit_retention_archive_purge_boundary_audit.md",
    ),
)


def run_ag_audit_retention_archive_purge_boundary_audit(
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
    identifiers = [
        {
            "name": name,
            "length": len(name),
            "within_limit": len(name) <= MAX_IDENTIFIER_LENGTH,
        }
        for name in (*SOURCE_TABLES, PROPOSED_RECEIPT_TABLE)
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s88_closed": _group_present(tokens, "s88_closed"),
        "source_tables_reusable": all(
            _group_present(tokens, group)
            for group in ("event_source", "export_source")
        ),
        "source_stores_reusable": all(
            _group_present(tokens, group)
            for group in ("event_store", "export_delete")
        ),
        "retention_pattern_available": _group_present(
            tokens, "retention_reference"
        ),
        "identifier_lengths_safe": all(
            item["within_limit"] for item in identifiers
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
    issues.extend(
        {"category": "identifier_too_long", "identifier": item["name"]}
        for item in identifiers
        if not item["within_limit"]
    )
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "ag_audit_retention_archive_purge_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-ag",
            "source_tables": list(SOURCE_TABLES),
            "source_rows_are_archive_payload": False,
            "metadata_only_manifest_allows_purge": False,
            "physical_purge_requires_sealed_archive_receipt": True,
            "archive_payload_authority": "external_injected_adapter",
            "archive_receipt_authority": "nex-ag",
            "proposed_receipt_table": PROPOSED_RECEIPT_TABLE,
            "new_table_required": True,
            "direct_delete_api_must_not_be_operator_exposed": True,
            "dry_run_default": True,
            "explicit_execute_confirmation_required": True,
            "decision_status": "CONFIRMATION_REQUIRED",
        },
        "current_risks": [
            "evidence_export_store_has_immediate_delete_without_archive_receipt",
            "operational_event_store_has_no_retention_candidate_or_purge_contract",
            "no_durable_archive_receipt_or_purge_tombstone_exists",
            "no_source_specific_retention_policy_is_frozen",
        ],
        "implementation_gaps": [
            "validated_retention_archive_policy",
            "bounded_retention_candidate_read_model",
            "archive_receipt_persistence_and_sealing",
            "guarded_idempotent_physical_purge",
            "lifecycle_operations_projection",
            "contract_and_index_hardening",
            "postgres_archive_purge_smoke",
        ],
        "deferred_scope": [
            "production_object_storage_provider_selection",
            "cross_service_retention_orchestration",
            "legal_hold_case_management",
            "ag_mvp_acceptance_and_cx_transition_s90",
        ],
        "required_paths": paths,
        "required_tokens": tokens,
        "identifiers": identifiers,
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
            "ag_audit_retention_archive_purge_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "ag_audit_retention_archive_purge_boundary=pass "
        f"sources={len(decision.get('source_tables') or [])} "
        f"receipt_table={decision.get('proposed_receipt_table')} "
        f"decision={decision.get('decision_status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_audit_retention_archive_purge_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
