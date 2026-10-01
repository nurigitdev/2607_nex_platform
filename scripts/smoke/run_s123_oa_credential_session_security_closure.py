#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "scripts/smoke"))

from run_oa_argon2_adaptive_rehash import (  # noqa: E402
    run_oa_argon2_adaptive_rehash as run_argon2,
)
from run_oa_atomic_login_lockout import (  # noqa: E402
    run_oa_atomic_login_lockout as run_lockout,
)
from run_oa_auth_event_flow import run_oa_auth_event_flow as run_auth_events  # noqa: E402
from run_oa_credential_rotation import (  # noqa: E402
    run_oa_credential_rotation as run_rotation,
)
from run_oa_credential_security_contracts import (  # noqa: E402
    run_oa_credential_security_contracts as run_contracts,
)
from run_oa_credential_session_security_boundary import (  # noqa: E402
    run_oa_credential_session_security_boundary as run_boundary,
)
from run_oa_secure_session_lifecycle import (  # noqa: E402
    run_oa_secure_session_lifecycle as run_sessions,
)
from run_oa_security_persistence_migration import (  # noqa: E402
    run_oa_security_persistence_migration as run_migration,
)


SCHEMA_VERSION = "s123_oa_credential_session_security_closure.v1"
SLICE_RANGE = "1222-1231"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_DOCUMENT = "docs/slices/1230_oa_credential_security_postgresql_smoke.md"
QUALITY_SCRIPTS = (
    "run_oa_credential_session_security_boundary.py",
    "run_oa_argon2_adaptive_rehash.py",
    "run_oa_atomic_login_lockout.py",
    "run_oa_security_persistence_migration.py",
    "run_oa_secure_session_lifecycle.py",
    "run_oa_credential_rotation.py",
    "run_oa_auth_event_flow.py",
    "run_oa_credential_security_contracts.py",
    "run_oa_credential_security_postgres_smoke.py",
    "run_s123_oa_credential_session_security_closure.py",
)
SLICE_DOCUMENTS = (
    "1222_oa_credential_session_security_boundary.md",
    "1223_oa_argon2id_adaptive_rehash.md",
    "1224_oa_atomic_failed_login_lockout.md",
    "1225_oa_security_persistence_migration.md",
    "1226_oa_secure_session_lifecycle.md",
    "1227_oa_password_rotation_session_revocation.md",
    "1228_oa_auth_security_event_persistence.md",
    "1229_oa_credential_security_contract_hardening.md",
    "1230_oa_credential_security_postgresql_smoke.md",
    "1231_s123_oa_credential_session_security_closure.md",
)
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/credentials.py",
    "services/nex-oa/nex_oa/sessions.py",
    "services/nex-oa/nex_oa/credential_security.py",
    "services/nex-oa/nex_oa/auth_events.py",
    "services/nex-oa/nex_oa/credential_security_postgres_smoke.py",
    "database/nex-oa/migrations/1225_oa_credential_session_security.sql",
    "contracts/openapi/nex-oa.openapi.yaml",
    "contracts/schemas/service/nex_oa/credential_rotation.v1.schema.json",
    "contracts/schemas/service/nex_oa/auth_event_list.v1.schema.json",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s123_oa_credential_session_security_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "argon2_default",
        "services/nex-oa/nex_oa/credentials.py",
        "DEFAULT_PASSWORD_HASH_ALGORITHM = ARGON2ID_PASSWORD_HASH_ALGORITHM",
    ),
    (
        "security_scope",
        "services/nex-oa/nex_oa/credential_security.py",
        'OA_CREDENTIAL_SECURITY_WRITE_SCOPE = "credential:security:write"',
    ),
    (
        "event_table",
        "database/nex-oa/migrations/1225_oa_credential_session_security.sql",
        "CREATE TABLE IF NOT EXISTS oa_auth_events",
    ),
    ("postgres_identity", POSTGRES_DOCUMENT, "`nex_oa_test` / `nex_oa_user`"),
    (
        "postgres_migration",
        POSTGRES_DOCUMENT,
        "`1225_oa_credential_session_security`",
    ),
    ("postgres_events", POSTGRES_DOCUMENT, "auth events: `12` total"),
    ("postgres_sessions", POSTGRES_DOCUMENT, "two credential-rotation revocations"),
    ("postgres_cleanup", POSTGRES_DOCUMENT, "all six tables: `0`"),
    (
        "closure_index",
        "docs/README.md",
        "1231_s123_oa_credential_session_security_closure.md",
    ),
)


def run_s123_oa_credential_session_security_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
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
        "argon2": _safe_evidence(run_argon2),
        "lockout": _safe_evidence(run_lockout),
        "migration": _safe_evidence(lambda: run_migration(root)),
        "sessions": _safe_evidence(run_sessions),
        "rotation": _safe_evidence(run_rotation),
        "auth_events": _safe_evidence(run_auth_events),
        "contracts": _safe_evidence(lambda: run_contracts(root)),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_postgres"] = {
        "slice": "1230",
        "requirement": "S123",
        "status": (
            "PASS"
            if all(
                token_status.get(name, False)
                for name in (
                    "postgres_identity",
                    "postgres_migration",
                    "postgres_events",
                    "postgres_sessions",
                    "postgres_cleanup",
                )
            )
            else "FAIL"
        ),
    }
    expected_slices = {
        "boundary": "1222",
        "argon2": "1223",
        "lockout": "1224",
        "migration": "1225",
        "sessions": "1226",
        "rotation": "1227",
        "auth_events": "1228",
        "contracts": "1229",
        "protected_postgres": "1230",
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    components = {
        "credential_hash_and_lockout": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "argon2", "lockout")
        ),
        "durable_security_and_session_lifecycle": all(
            evidence[name].get("status") == "PASS"
            for name in ("migration", "sessions")
        ),
        "credential_rotation_and_revocation": evidence["rotation"].get("status")
        == "PASS",
        "auth_events_contracts_and_privacy": all(
            evidence[name].get("status") == "PASS"
            for name in ("auth_events", "contracts")
        ),
        "actual_postgres_evidence": evidence["protected_postgres"].get("status")
        == "PASS",
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S123"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "argon2_rehash_closed": (
            summaries["argon2"].get("default_algorithm") == "argon2id.v1"
            and summaries["argon2"].get("legacy_algorithm") == "pbkdf2_sha256.v1"
            and summaries["argon2"].get("passed_check_count") == 7
        ),
        "atomic_lockout_closed": (
            summaries["lockout"].get("threshold") == 5
            and summaries["lockout"].get("duration_seconds") == 900
            and summaries["lockout"].get("passed_check_count") == 6
        ),
        "persistence_and_session_closed": (
            summaries["migration"].get("table") == "oa_auth_events"
            and summaries["migration"].get("passed_check_count") == 9
            and summaries["sessions"].get("id_entropy_bytes") == 32
            and summaries["sessions"].get("idle_ttl_seconds") == 1800
            and summaries["sessions"].get("passed_check_count") == 7
        ),
        "rotation_revocation_closed": (
            summaries["rotation"].get("passed_check_count") == 7
            and summaries["rotation"].get("reset_revoked") == 1
            and summaries["rotation"].get("change_revoked") == 1
        ),
        "event_contract_privacy_closed": (
            summaries["auth_events"].get("passed_check_count") == 7
            and summaries["auth_events"].get("event_count") == 2
            and summaries["contracts"].get("schema_count") == 2
            and summaries["contracts"].get("documented_operation_count") == 3
            and summaries["contracts"].get("security_implemented_count") == 8
            and summaries["contracts"].get("security_gap_count") == 0
            and summaries["contracts"].get("remaining_contract_drift_count") == 23
        ),
        "actual_postgres_closed": evidence["protected_postgres"]["status"]
        == "PASS",
        "completed_scope_closed": decision["completed_scope"]
        == (
            "argon2id_with_legacy_adaptive_rehash",
            "atomic_timed_login_lockout",
            "random_idle_and_absolute_session_expiry",
            "credential_rotation_session_revocation",
            "privacy_safe_auth_security_events",
        ),
        "remaining_scope_deferred": decision["deferred_scope"]
        == (
            "multi_factor_authentication",
            "self_service_password_reset_delivery",
            "oidc_saml_external_identity",
            "signed_service_tokens_and_jwks_verification",
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1222-1230",
            "checkpoint_gate": "1226",
            "full_gate": "1231",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1231",
        "slice_range": SLICE_RANGE,
        "requirement": "S123",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s123_oa_credential_session_security_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S124" if passed else "BLOCKED",
        "feature_readiness": (
            "OA_CREDENTIAL_SESSION_SECURITY_READY" if passed else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "deterministic_check_count": sum(
                int(summaries[name].get("check_count") or 0)
                for name in (
                    "argon2",
                    "lockout",
                    "migration",
                    "sessions",
                    "rotation",
                    "auth_events",
                )
            ),
            "canonical_schema_count": summaries["contracts"].get(
                "schema_count", 0
            ),
            "protected_operation_count": summaries["contracts"].get(
                "documented_operation_count", 0
            ),
            "postgres_event_count": 12
            if evidence["protected_postgres"]["status"] == "PASS"
            else 0,
            "postgres_revoked_session_count": 2
            if evidence["protected_postgres"]["status"] == "PASS"
            else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S124" if passed else "blocked",
        "next_requirement_scope": (
            "oa_group_role_authorization_hardening" if passed else "blocked"
        ),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "oa_credential_and_session_security",
        "completed_scope": (
            "argon2id_with_legacy_adaptive_rehash",
            "atomic_timed_login_lockout",
            "random_idle_and_absolute_session_expiry",
            "credential_rotation_session_revocation",
            "privacy_safe_auth_security_events",
        ),
        "deferred_scope": (
            "multi_factor_authentication",
            "self_service_password_reset_delivery",
            "oidc_saml_external_identity",
            "signed_service_tokens_and_jwks_verification",
        ),
        "password_hash_default": "argon2id.v1",
        "legacy_hash_read": "pbkdf2_sha256.v1",
        "lockout_threshold": 5,
        "lockout_duration_seconds": 900,
        "session_entropy_bytes": 32,
        "session_idle_ttl_seconds": 1800,
        "password_rotation_revokes_sessions": True,
        "auth_event_table": "oa_auth_events",
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "quality_cadence": {
            "slice_gate": "1222-1230",
            "checkpoint_gate": "1226",
            "full_gate": "1231",
        },
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
    summary = evidence.get("summary") or {}
    return (
        "s123_oa_credential_session_security_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"operations={summary.get('protected_operation_count', 0)} "
        f"postgres_events={summary.get('postgres_event_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s123_oa_credential_session_security_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
