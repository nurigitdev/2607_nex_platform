#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_identity_membership_lifecycle_boundary.v1"
SLICE_ID = "1212"
REQUIREMENT = "S122"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "s121_handoff",
        "scripts/smoke/run_s121_oa_current_state_reaudit_closure.py",
        '"next_requirement": "S122"',
    ),
    RequiredEvidence(
        "lifecycle_gap_audit",
        "services/nex-oa/nex_oa/identity_lifecycle_audit.py",
        '"subject_membership_status_transitions"',
    ),
    RequiredEvidence(
        "subject_registry",
        "services/nex-oa/nex_oa/subjects.py",
        'OA_SUBJECT_STATUSES = ("ACTIVE", "DISABLED", "DELETED")',
    ),
    RequiredEvidence(
        "membership_registry",
        "services/nex-oa/nex_oa/memberships.py",
        'OA_MEMBERSHIP_STATUSES = ("ACTIVE", "DISABLED")',
    ),
    RequiredEvidence(
        "session_registry",
        "services/nex-oa/nex_oa/sessions.py",
        "def revoke_session(",
    ),
    RequiredEvidence(
        "subject_migration",
        "database/nex-oa/migrations/0193_oa_subject_registry_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_subjects",
    ),
    RequiredEvidence(
        "membership_migration",
        "database/nex-oa/migrations/0242_oa_tenant_membership_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_tenant_memberships",
    ),
    RequiredEvidence(
        "session_migration",
        "database/nex-oa/migrations/0243_oa_user_session_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_user_sessions",
    ),
    RequiredEvidence(
        "slice_document",
        "docs/slices/1212_oa_identity_membership_lifecycle_boundary.md",
        "identity:lifecycle:write",
    ),
)


def run_oa_identity_membership_lifecycle_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    evidence = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in REQUIRED_EVIDENCE
    ]
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "direct_identity_states_reusable": all(
            _present(evidence, name)
            for name in ("subject_registry", "membership_registry")
        ),
        "durable_records_reusable": all(
            _present(evidence, name)
            for name in (
                "subject_migration",
                "membership_migration",
                "session_migration",
            )
        ),
        "s121_handoff_ready": _present(evidence, "s121_handoff"),
    }
    issues = [
        {"category": "evidence_missing", "name": item["name"], "path": item["path"]}
        for item in evidence
        if not item["present"]
    ]
    passed = all(checks.values()) and not issues
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_identity_membership_lifecycle_boundary_failed"
        ),
        "decision": {
            "owner": "nex-oa",
            "subject_states": ["ACTIVE", "DISABLED", "DELETED"],
            "membership_states": ["ACTIVE", "DISABLED"],
            "optimistic_revision_required": True,
            "terminal_subject_state": "DELETED",
            "session_revocation_on_disable_or_delete": True,
            "lifecycle_write_scope": "identity:lifecycle:write",
            "ensure_route_compatibility_preserved": True,
            "group_registry_deferred": True,
            "actual_test_database_evidence_required": True,
            "protected_live_provider_evidence_required": False,
            "new_table_required": True,
            "decision_status": "FROZEN",
        },
        "slice_plan": [
            "1212_boundary_audit",
            "1213_subject_lifecycle_domain",
            "1214_membership_lifecycle_domain",
            "1215_durable_lifecycle_repository",
            "1216_subject_lifecycle_api_checkpoint",
            "1217_membership_lifecycle_api",
            "1218_deprovision_session_cascade",
            "1219_contract_audit_privacy_hardening",
            "1220_postgresql_lifecycle_smoke",
            "1221_s122_closure_full_gate",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1216",
            "full_gate": "1221",
        },
        "deferred_scope": [
            "group_registry_and_group_membership",
            "external_identity_provider_lifecycle",
            "credential_hash_rotation_and_rehash",
            "service_token_and_jwks_hardening",
        ],
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _present(items: list[dict[str, Any]], name: str) -> bool:
    return any(item["name"] == name and item["present"] for item in items)


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "oa_identity_membership_lifecycle_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "oa_identity_membership_lifecycle_boundary=pass "
        f"scope={decision.get('lifecycle_write_scope')} "
        f"revision={decision.get('optimistic_revision_required')} "
        f"cascade={decision.get('session_revocation_on_disable_or_delete')} "
        f"postgres_required={decision.get('actual_test_database_evidence_required')} "
        f"live_provider_required={decision.get('protected_live_provider_evidence_required')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_identity_membership_lifecycle_boundary()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
