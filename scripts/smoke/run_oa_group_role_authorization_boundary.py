#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_group_role_authorization_boundary.v1"
SLICE_ID = "1232"
REQUIREMENT = "S124"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "s123_handoff",
        "scripts/smoke/run_s123_oa_credential_session_security_closure.py",
        '"next_requirement": "S124"',
    ),
    RequiredEvidence(
        "group_gap_audit",
        "services/nex-oa/nex_oa/identity_lifecycle_audit.py",
        '"group_identity_lifecycle"',
    ),
    RequiredEvidence(
        "trust_scope_gap",
        "services/nex-oa/nex_oa/trust_coupling_audit.py",
        '"route_specific_service_authorization"',
    ),
    RequiredEvidence(
        "membership_grants",
        "services/nex-oa/nex_oa/memberships.py",
        'DEFAULT_MEMBERSHIP_ROLES = ("employee",)',
    ),
    RequiredEvidence(
        "session_claims",
        "services/nex-oa/nex_oa/sessions.py",
        '"roles": list(claims.roles)',
    ),
    RequiredEvidence(
        "membership_schema",
        "database/nex-oa/migrations/0242_oa_tenant_membership_foundation.sql",
        "roles JSONB NOT NULL DEFAULT '[]'::jsonb",
    ),
    RequiredEvidence(
        "slice_document",
        "docs/slices/1232_oa_group_role_authorization_boundary.md",
        "authorization:admin",
    ),
)


def run_oa_group_role_authorization_boundary(
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
    decision = _decision()
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "tenant_isolation_required": decision["tenant_isolation"] == "mandatory",
        "effective_grants_are_allow_only": (
            decision["grant_model"]["composition"] == "set_union"
            and decision["grant_model"]["explicit_deny_supported"] is False
        ),
        "authorization_changes_revoke_sessions": decision[
            "authorization_change_revokes_active_sessions"
        ],
        "admin_and_bootstrap_scopes_are_distinct": (
            decision["admin_scope"] == "authorization:admin"
            and decision["bootstrap_scope"] == "identity:bootstrap:write"
        ),
        "postgres_evidence_required": decision[
            "actual_test_database_evidence_required"
        ],
        "remote_provider_not_required": not decision[
            "protected_live_provider_evidence_required"
        ],
        "service_token_trust_deferred": decision[
            "signed_service_token_and_jwks_deferred"
        ],
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
        "failure_code": None if passed else "oa_group_role_authorization_boundary_failed",
        "decision": decision,
        "slice_plan": [
            "1232_boundary_and_policy",
            "1233_group_role_authorization_domain",
            "1234_authorization_persistence_migration",
            "1235_durable_authorization_repository",
            "1236_effective_grant_session_integration_checkpoint",
            "1237_group_role_admin_service_api",
            "1238_bootstrap_admin_scope_hardening",
            "1239_contract_openapi_privacy_hardening",
            "1240_postgresql_authorization_smoke",
            "1241_s124_closure_full_gate",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1236",
            "full_gate": "1241",
        },
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
    }


def _decision() -> dict[str, Any]:
    return {
        "owner": "nex-oa",
        "tenant_isolation": "mandatory",
        "admin_scope": "authorization:admin",
        "read_scope": "authorization:read",
        "bootstrap_scope": "identity:bootstrap:write",
        "grant_model": {
            "composition": "set_union",
            "sources": (
                "direct_membership_roles_and_scopes",
                "group_assigned_roles",
                "role_defined_scopes",
            ),
            "explicit_deny_supported": False,
            "unknown_role_fails_closed": True,
            "nested_groups_supported": False,
        },
        "mutation_requires_expected_revision": True,
        "authorization_change_revokes_active_sessions": True,
        "session_claims_are_issue_time_snapshot": True,
        "privacy_safe_authorization_events_required": True,
        "table_names": (
            "oa_roles",
            "oa_groups",
            "oa_group_members",
            "oa_group_roles",
            "oa_authz_events",
        ),
        "actual_test_database_evidence_required": True,
        "protected_live_provider_evidence_required": False,
        "signed_service_token_and_jwks_deferred": True,
        "decision_status": "FROZEN",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "oa_group_role_authorization_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    grant_model = decision.get("grant_model") or {}
    return (
        "oa_group_role_authorization_boundary=pass "
        f"grant={grant_model.get('composition')} "
        f"admin={decision.get('admin_scope')} "
        f"tables={len(decision.get('table_names') or ())} "
        f"postgres_required={decision.get('actual_test_database_evidence_required')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_group_role_authorization_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
