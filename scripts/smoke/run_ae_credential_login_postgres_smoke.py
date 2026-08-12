#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_oa_auth_postgres_smoke import (  # noqa: E402
    DEFAULT_PROFILE,
    EMPLOYEE_ID_ENV as BASE_EMPLOYEE_ID_ENV,
    SMOKE_ENV as BASE_SMOKE_ENV,
    SMOKE_PROFILE_ENV as BASE_SMOKE_PROFILE_ENV,
    SUBJECT_ID_ENV as BASE_SUBJECT_ID_ENV,
    TENANT_ID_ENV as BASE_TENANT_ID_ENV,
    run_ae_oa_auth_postgres_smoke,
)


SCHEMA_VERSION = "ae_credential_login_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_PROFILE"
TENANT_ID_ENV = "NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_TENANT_ID"
SUBJECT_ID_ENV = "NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_SUBJECT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_CREDENTIAL_LOGIN_POSTGRES_SMOKE_EMPLOYEE_ID"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"


def run_ae_credential_login_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    base_evidence = run_ae_oa_auth_postgres_smoke(_base_environ(env))
    evidence = _credential_evidence(base_evidence)
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _base_environ(env: Mapping[str, str]) -> dict[str, str]:
    base_env = dict(env)
    base_env[BASE_SMOKE_ENV] = "1"
    _copy_alias(
        base_env,
        source=SMOKE_PROFILE_ENV,
        target=BASE_SMOKE_PROFILE_ENV,
        default=DEFAULT_PROFILE,
    )
    _copy_alias(base_env, source=TENANT_ID_ENV, target=BASE_TENANT_ID_ENV)
    _copy_alias(base_env, source=SUBJECT_ID_ENV, target=BASE_SUBJECT_ID_ENV)
    _copy_alias(base_env, source=EMPLOYEE_ID_ENV, target=BASE_EMPLOYEE_ID_ENV)
    return base_env


def _copy_alias(
    env: dict[str, str],
    *,
    source: str,
    target: str,
    default: str | None = None,
) -> None:
    if source in env:
        env[target] = env[source]
    elif target not in env and default is not None:
        env[target] = default


def _credential_evidence(base_evidence: Mapping[str, Any]) -> dict[str, Any]:
    status = str(base_evidence.get("status", "FAIL"))
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "source_smoke": {
            "name": "ae_oa_auth_postgres_smoke",
            "schema_version": base_evidence.get("smoke_schema_version"),
        },
    }
    if status == "SKIPPED":
        evidence["skip_reason"] = base_evidence.get("skip_reason", "source skipped")
        return evidence
    if status != "PASS":
        evidence.update(
            {
                "profile": base_evidence.get("profile"),
                "services": list(base_evidence.get("services", [])),
                "failure_code": base_evidence.get("failure_code", "source_failed"),
                "detail": base_evidence.get("detail", "source smoke failed"),
            }
        )
        return evidence

    checks = _mapping(base_evidence.get("checks"))
    db_observations = _mapping(base_evidence.get("db_observations"))
    auth_observations = _mapping(base_evidence.get("auth_observations"))
    adapter_observations = _mapping(base_evidence.get("adapter_observations"))
    evidence.update(
        {
            "profile": base_evidence.get("profile"),
            "services": list(base_evidence.get("services", [])),
            "database_envs": _mapping(base_evidence.get("database_envs")),
            "redacted_database_urls": _mapping(
                base_evidence.get("redacted_database_urls")
            ),
            "migrations": _mapping(base_evidence.get("migrations")),
            "request_id": base_evidence.get("request_id"),
            "trace_id": base_evidence.get("trace_id"),
            "db_observations": {
                "ae_marker_rows": db_observations.get("ae_marker_rows"),
                "oa_membership_count": db_observations.get("oa_membership_count"),
                "oa_credential_count": db_observations.get("oa_credential_count"),
                "oa_session_count": db_observations.get("oa_session_count"),
                "oa_session_status": db_observations.get("oa_session_status"),
                "oa_session_revoked_at_present": db_observations.get(
                    "oa_session_revoked_at_present"
                ),
            },
            "credential_login_observations": {
                "ae_endpoint": "POST /api/v1/auth/session/login",
                "oa_endpoint": "POST /internal/v1/auth/user-login",
                "oa_client_operations": list(
                    adapter_observations.get("oa_client_operations", [])
                ),
                "password_verified": checks.get("login_password_verified") is True,
                "browser_cookie_value_kind": "opaque_oa_session_id",
                "browser_cookie_material_in_evidence": auth_observations.get(
                    "browser_cookie_material_in_evidence"
                )
                is True,
                "owner_scope_authority": auth_observations.get(
                    "owner_scope_authority"
                ),
            },
            "checks": {
                key: checks.get(key) is True
                for key in (
                    "ae_runtime_mode",
                    "oa_runtime_mode",
                    "credential_status_ok",
                    "login_status_ok",
                    "login_password_verified",
                    "cookie_set_after_login",
                    "cookie_removed_after_logout",
                    "protected_owner_scope_claim_derived",
                    "credential_persisted",
                    "session_persisted",
                    "db_session_revoked",
                    "raw_payload_absent",
                )
            },
            "cleanup_observations": _mapping(
                base_evidence.get("cleanup_observations")
            ),
        }
    )
    return evidence


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    protected_env_keys = (
        AE_DATABASE_ENV,
        OA_DATABASE_ENV,
        TENANT_ID_ENV,
        SUBJECT_ID_ENV,
        EMPLOYEE_ID_ENV,
        BASE_TENANT_ID_ENV,
        BASE_SUBJECT_ID_ENV,
        BASE_EMPLOYEE_ID_ENV,
    )
    leaked = [
        key
        for key in protected_env_keys
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE credential-login PostgreSQL smoke evidence contains unredacted "
            f"environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {DEFAULT_PROFILE, "1"} and value in serialized)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_credential_login_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        db_observations = _mapping(evidence.get("db_observations"))
        database_envs = _mapping(evidence.get("database_envs"))
        return (
            "ae_credential_login_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"ae_db={database_envs.get('ae')} "
            f"oa_db={database_envs.get('oa')} "
            f"oa_credential_count={db_observations.get('oa_credential_count')} "
            f"oa_session_status={db_observations.get('oa_session_status')}"
        )
    return (
        "ae_credential_login_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE credential-login PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_credential_login_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, default=str)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
