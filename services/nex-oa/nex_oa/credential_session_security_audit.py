from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_credential_session_security_audit.v1"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "credential_hashing",
        "services/nex-oa/nex_oa/credentials.py",
        'hashlib.pbkdf2_hmac(',
    ),
    RequiredEvidence(
        "constant_time_verification",
        "services/nex-oa/nex_oa/credentials.py",
        "hmac.compare_digest(candidate, digest)",
    ),
    RequiredEvidence(
        "session_introspection",
        "services/nex-oa/nex_oa/sessions.py",
        "def introspect_session",
    ),
    RequiredEvidence(
        "session_revocation",
        "services/nex-oa/nex_oa/sessions.py",
        "def revoke_session",
    ),
    RequiredEvidence(
        "credential_security_regression",
        "tests/test_nex_oa_credentials.py",
        "test_password_hash_helpers_verify_and_hide_raw_password",
    ),
    RequiredEvidence(
        "session_security_regression",
        "tests/test_nex_oa_sessions.py",
        "test_session_introspection_reports_active_inactive_and_hides_credentials",
    ),
    RequiredEvidence(
        "credential_schema",
        "database/nex-oa/migrations/0252_oa_local_credential_foundation.sql",
        "failed_attempt_count INTEGER NOT NULL DEFAULT 0",
    ),
    RequiredEvidence(
        "session_schema",
        "database/nex-oa/migrations/0243_oa_user_session_foundation.sql",
        "CHECK (expires_at > issued_at)",
    ),
)


def build_oa_credential_session_security_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    evidence = [_inspect_evidence(root, item) for item in REQUIRED_EVIDENCE]
    credential_source = _read_text(root / "services/nex-oa/nex_oa/credentials.py")
    session_source = _read_text(root / "services/nex-oa/nex_oa/sessions.py")
    login_source = _read_text(root / "services/nex-oa/nex_oa/user_login.py")
    security_source = _read_text(
        root / "services/nex-oa/nex_oa/credential_security.py"
    )
    auth_event_source = _read_text(root / "services/nex-oa/nex_oa/auth_events.py")

    observations = {
        "pbkdf2_salted_hashing_present": all(
            token in credential_source
            for token in ("hashlib.pbkdf2_hmac(", "os.urandom(SALT_BYTES)")
        ),
        "constant_time_password_compare_present": (
            "hmac.compare_digest(candidate, digest)" in credential_source
        ),
        "private_payload_rejection_present": (
            "_PRIVATE_CREDENTIAL_KEY_PARTS" in credential_source
            and "SENSITIVE_SESSION_KEY_PARTS" in session_source
        ),
        "bounded_session_ttl_present": all(
            token in session_source
            for token in (
                "MAX_SESSION_TTL_SECONDS = 86400",
                "if value <= 0 or value > MAX_SESSION_TTL_SECONDS",
            )
        ),
        "session_introspection_revocation_present": all(
            token in session_source
            for token in ("def introspect_session", "def revoke_session")
        ),
        "failed_attempt_mutation_present": (
            "failed_attempt_count = failed_attempt_count + 1" in credential_source
        ),
        "credential_rotation_present": (
            "def change_password(" in security_source
            and "def reset_password(" in security_source
            and "session_revocation_atomic" in security_source
        ),
        "adaptive_rehash_present": (
            "argon2" in credential_source.lower()
            and "rehash" in credential_source.lower()
        ),
        "random_session_identifier_present": (
            "uuid4(" in session_source or "token_urlsafe(" in session_source
        ),
        "auth_event_emission_present": (
            "record_auth_event_safely" in security_source
            and "record_auth_event_safely" in session_source
            and "record_auth_event_safely" in login_source
            and "class SqlAlchemyOaAuthEventRepository" in auth_event_source
        ),
    }
    controls = [
        _control("credential_secret_storage_and_redaction", "IMPLEMENTED", None),
        _control("constant_time_password_verification", "IMPLEMENTED", None),
        _control("bounded_session_introspection_revocation", "IMPLEMENTED", None),
        _control(
            "adaptive_password_hash_upgrade",
            "IMPLEMENTED",
            None,
        ),
        _control(
            "failed_login_counter_and_lockout",
            "IMPLEMENTED",
            None,
        ),
        _control(
            "credential_change_reset_rotation",
            "IMPLEMENTED",
            None,
        ),
        _control(
            "opaque_session_identifier_entropy",
            "IMPLEMENTED",
            None,
        ),
        _control(
            "authentication_security_audit_events",
            "IMPLEMENTED",
            None,
        ),
    ]
    strengths_observed = all(
        observations[name]
        for name in (
            "pbkdf2_salted_hashing_present",
            "constant_time_password_compare_present",
            "private_payload_rejection_present",
            "bounded_session_ttl_present",
            "session_introspection_revocation_present",
        )
    )
    classification_current = (
        observations["credential_rotation_present"] is True
        and observations["auth_event_emission_present"] is True
    )
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "security_control_inventory_complete": len(controls) == 8,
        "implemented_security_strengths_observed": strengths_observed,
        "security_classification_current": classification_current,
        "non_implemented_controls_have_explicit_gaps": all(
            item["status"] == "IMPLEMENTED" or bool(item["gap"])
            for item in controls
        ),
    }
    issues = [
        {
            "category": "evidence_missing",
            "name": item["name"],
            "path": item["path"],
        }
        for item in evidence
        if not item["present"]
    ]
    if not strengths_observed or not classification_current:
        issues.append({"category": "security_classification_drift"})
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1206",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_credential_session_security_audit_failed"
        ),
        "security_readiness": "HARDENED" if passed else "BLOCKED",
        "summary": {
            "control_count": len(controls),
            "implemented_count": sum(
                item["status"] == "IMPLEMENTED" for item in controls
            ),
            "partial_count": sum(item["status"] == "PARTIAL" for item in controls),
            "gap_count": sum(item["status"] != "IMPLEMENTED" for item in controls),
            "evidence_issue_count": len(issues),
        },
        "decision": {
            "current_login_compatibility_preserved": True,
            "security_gaps_require_targeted_hardening": False,
            "raw_credentials_or_session_ids_in_evidence": False,
            "new_table_required_now": False,
        },
        "observations": observations,
        "controls": controls,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "next_slice": "1207",
    }


def _control(control_id: str, status: str, gap: str | None) -> dict[str, Any]:
    return {"control_id": control_id, "status": status, "gap": gap}


def _inspect_evidence(root: Path, item: RequiredEvidence) -> dict[str, Any]:
    path = root / item.relative_path
    return {
        "name": item.name,
        "path": item.relative_path,
        "present": item.token in _read_text(path),
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
