#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ag_audit_integrity_evidence_boundary_audit.v1"
SLICE_ID = "0861"
REQUIREMENT = "S87"
BOUNDARY = "existing_audit_event_and_evidence_export_integrity_hardening"
MAX_IDENTIFIER_LENGTH = 30
SOURCE_TABLES = ("service_operational_events", "ag_ev_exports")


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
        "s86_closure",
        "scripts/smoke/run_s86_ag_recovery_notification_live_delivery_closure.py",
    ),
    RequiredPath(
        "operational_event_runtime",
        "services/_shared/nex_runtime/operational_events.py",
    ),
    RequiredPath(
        "evidence_export_runtime",
        "services/nex-ag/nex_ag/operator_reviews.py",
    ),
    RequiredPath("operations_runtime", "services/nex-ag/nex_ag/operations.py"),
    RequiredPath(
        "operational_event_migration",
        "database/nex-ag/migrations/0085_service_operational_events_foundation.sql",
    ),
    RequiredPath(
        "evidence_export_migration",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
    ),
    RequiredPath(
        "evidence_export_schema",
        "contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/0861_ag_audit_integrity_evidence_boundary_audit.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s86_closed",
        "scripts/smoke/run_s86_ag_recovery_notification_live_delivery_closure.py",
        "s86_ag_recovery_notification_live_delivery_closure.v1",
    ),
    TokenRequirement(
        "event_validation",
        "services/_shared/nex_runtime/operational_events.py",
        "def validate_operational_event",
    ),
    TokenRequirement(
        "event_redaction",
        "services/_shared/nex_runtime/operational_events.py",
        "def redact_operational_details",
    ),
    TokenRequirement(
        "event_sql_store",
        "services/_shared/nex_runtime/operational_events.py",
        "class SqlAlchemyOperationalEventStore",
    ),
    TokenRequirement(
        "export_manifest",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "def evidence_manifest",
    ),
    TokenRequirement(
        "export_hash",
        "services/nex-ag/nex_ag/operator_reviews.py",
        "evidence_hash = sha256_json(manifest)",
    ),
    TokenRequirement(
        "zip_manifest_format",
        "services/nex-ag/nex_ag/operator_reviews.py",
        '"zip_manifest"',
    ),
    TokenRequirement(
        "trace_index",
        "database/nex-ag/migrations/0626_ag_redacted_evidence_export_persistence.sql",
        "idx_ag_ev_exports_trace_time",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_ag_audit_integrity_evidence_boundary_audit.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "0861_ag_audit_integrity_evidence_boundary_audit.md",
    ),
)


def run_ag_audit_integrity_evidence_boundary_audit(
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
        for name in SOURCE_TABLES
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s86_closed": _group_present(tokens, "s86_closed"),
        "event_validation_reusable": all(
            _group_present(tokens, group)
            for group in ("event_validation", "event_redaction", "event_sql_store")
        ),
        "evidence_export_reusable": all(
            _group_present(tokens, group)
            for group in ("export_manifest", "export_hash", "zip_manifest_format")
        ),
        "trace_lookup_supported": _group_present(tokens, "trace_index"),
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
        "failure_code": None
        if passed
        else "ag_audit_integrity_evidence_boundary_failed",
        "boundary": BOUNDARY,
        "decision": {
            "audit_owner": "nex-ag",
            "event_source_table": SOURCE_TABLES[0],
            "evidence_source_table": SOURCE_TABLES[1],
            "new_table_required": False,
            "new_migration_required": False,
            "verification_mode": "read_only_deterministic",
            "manifest_hash_algorithm": "sha256_canonical_json",
            "event_ordering": ["created_at", "event_id"],
            "external_signature_service_required": False,
        },
        "implementation_gaps": [
            "audit_event_integrity_report",
            "trace_correlation_continuity_report",
            "verifiable_evidence_package_manifest",
            "protected_integrity_export_api",
            "operations_integrity_projection",
            "postgres_integrity_smoke",
        ],
        "deferred_scope": [
            "external_notary_or_signature_service",
            "cross_database_distributed_transaction",
            "retention_archive_and_physical_purge_s89",
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
            "ag_audit_integrity_evidence_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "ag_audit_integrity_evidence_boundary=pass "
        f"tables={len(SOURCE_TABLES)} "
        f"new_table={decision.get('new_table_required')} "
        f"mode={decision.get('verification_mode')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_audit_integrity_evidence_boundary_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
