#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_credential_session_security_boundary.v1"
SLICE_ID = "1222"
REQUIREMENT = "S123"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "s122_handoff",
        "scripts/smoke/run_s122_oa_identity_membership_lifecycle_closure.py",
        '"next_requirement": "S123"',
    ),
    RequiredEvidence(
        "security_gap_audit",
        "services/nex-oa/nex_oa/credential_session_security_audit.py",
        '"failed_login_counter_and_lockout"',
    ),
    RequiredEvidence(
        "credential_registry",
        "services/nex-oa/nex_oa/credentials.py",
        "class SqlAlchemyOaCredentialRegistry",
    ),
    RequiredEvidence(
        "session_registry",
        "services/nex-oa/nex_oa/sessions.py",
        "class SqlAlchemyOaSessionRegistry",
    ),
    RequiredEvidence(
        "credential_schema",
        "database/nex-oa/migrations/0252_oa_local_credential_foundation.sql",
        "failed_attempt_count INTEGER NOT NULL DEFAULT 0",
    ),
    RequiredEvidence(
        "session_schema",
        "database/nex-oa/migrations/0243_oa_user_session_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_user_sessions",
    ),
    RequiredEvidence(
        "slice_document",
        "docs/slices/1222_oa_credential_session_security_boundary.md",
        "credential:security:write",
    ),
)


def run_oa_credential_session_security_boundary(
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
        "argon2id_is_default": decision["password_hash"]["default"] == "argon2id.v1",
        "pbkdf2_compatibility_retained": decision["password_hash"]["legacy_read"]
        == "pbkdf2_sha256.v1",
        "lockout_is_bounded": decision["lockout"]["threshold"] == 5
        and decision["lockout"]["duration_seconds"] == 900,
        "session_expiry_is_bounded": decision["session"]["absolute_ttl_seconds"]
        == 3600
        and decision["session"]["idle_ttl_seconds"] == 1800,
        "postgres_evidence_required": decision["actual_test_database_evidence_required"],
        "remote_provider_not_required": not decision[
            "protected_live_provider_evidence_required"
        ],
        "service_trust_deferred": decision["signed_service_token_and_jwks_deferred"],
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
        "failure_code": None if passed else "oa_credential_session_boundary_failed",
        "decision": decision,
        "slice_plan": [
            "1222_boundary_and_policy",
            "1223_argon2id_and_adaptive_rehash",
            "1224_atomic_failed_login_lockout",
            "1225_security_persistence_migration",
            "1226_secure_session_lifecycle_checkpoint",
            "1227_password_rotation_and_session_revocation",
            "1228_auth_security_events",
            "1229_contract_audit_privacy",
            "1230_postgresql_security_smoke",
            "1231_s123_closure_full_gate",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1226",
            "full_gate": "1231",
        },
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
    }


def _decision() -> dict[str, Any]:
    return {
        "owner": "nex-oa",
        "credential_write_scope": "credential:security:write",
        "password_hash": {
            "default": "argon2id.v1",
            "legacy_read": "pbkdf2_sha256.v1",
            "login_time_rehash": True,
        },
        "lockout": {
            "threshold": 5,
            "duration_seconds": 900,
            "atomic_update": True,
            "enumeration_safe_failure": True,
        },
        "session": {
            "identifier": "secrets.token_urlsafe",
            "absolute_ttl_seconds": 3600,
            "maximum_ttl_seconds": 86400,
            "idle_ttl_seconds": 1800,
            "rotation_restores_revoked_session": False,
        },
        "password_change_revokes_active_sessions": True,
        "password_reset_requires_change": True,
        "safe_auth_events_required": True,
        "actual_test_database_evidence_required": True,
        "protected_live_provider_evidence_required": False,
        "signed_service_token_and_jwks_deferred": True,
        "decision_status": "FROZEN",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"oa_credential_session_security_boundary=fail issues={len(evidence.get('issues') or [])}"
    decision = evidence.get("decision") or {}
    return (
        "oa_credential_session_security_boundary=pass "
        f"hash={decision.get('password_hash', {}).get('default')} "
        f"lockout={decision.get('lockout', {}).get('threshold')}/"
        f"{decision.get('lockout', {}).get('duration_seconds')} "
        f"idle_ttl={decision.get('session', {}).get('idle_ttl_seconds')} "
        f"postgres_required={decision.get('actual_test_database_evidence_required')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_credential_session_security_boundary()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
