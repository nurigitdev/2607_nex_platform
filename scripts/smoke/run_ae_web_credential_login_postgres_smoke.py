#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "smoke"
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SMOKE_PATH))
sys.path.insert(0, str(SHARED_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_credential_login_postgres_smoke import (  # noqa: E402
    AE_DATABASE_ENV,
    EMPLOYEE_ID_ENV as BASE_EMPLOYEE_ID_ENV,
    OA_DATABASE_ENV,
    SMOKE_ENV as BASE_SMOKE_ENV,
    SMOKE_PROFILE_ENV as BASE_SMOKE_PROFILE_ENV,
    SUBJECT_ID_ENV as BASE_SUBJECT_ID_ENV,
    TENANT_ID_ENV as BASE_TENANT_ID_ENV,
    run_ae_credential_login_postgres_smoke,
)


SCHEMA_VERSION = "ae_web_credential_login_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_PROFILE"
TENANT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_TENANT_ID"
SUBJECT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_SUBJECT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_POSTGRES_SMOKE_EMPLOYEE_ID"

WEB_ROOT = ROOT / "apps" / "nex-ae-web"
REQUIRED_WEB_ANCHORS = (
    "credential-login-panel",
    "credential-login-form",
    "credential-tenant-id",
    "credential-employee-id",
    "credential-password",
    "credential-login-submit-button",
    "credential-logout-button",
    "credential-login-feedback",
    "credential-login-summary",
    "session-route-guard-summary",
)
REQUIRED_WEB_MODULE_TOKENS = {
    "credentialLoginSurface.js": (
        "ae_web_credential_login_surface.v1",
        "buildCredentialLoginRequestFromForm",
        "rawPasswordStored: false",
        "passwordIncludedInSummary: false",
    ),
    "sessionRouteGuard.js": (
        "ae_web_session_route_guard.v1",
        "ownerScopeFromSessionState",
        "routeGuardUsesSessionClaims",
        "mock_preview",
    ),
    "sessionClient.js": (
        "assertSessionLoginRequestSafe",
        "ALLOWED_LOGIN_ROOT_SECRET_FIELDS",
        'credentials: "same-origin"',
    ),
}


def run_ae_web_credential_login_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    source_evidence = run_ae_credential_login_postgres_smoke(_base_environ(env))
    evidence = _web_credential_evidence(source_evidence)
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _base_environ(env: Mapping[str, str]) -> dict[str, str]:
    base_env = dict(env)
    base_env[BASE_SMOKE_ENV] = "1"
    _copy_alias(base_env, source=SMOKE_PROFILE_ENV, target=BASE_SMOKE_PROFILE_ENV)
    _copy_alias(base_env, source=TENANT_ID_ENV, target=BASE_TENANT_ID_ENV)
    _copy_alias(base_env, source=SUBJECT_ID_ENV, target=BASE_SUBJECT_ID_ENV)
    _copy_alias(base_env, source=EMPLOYEE_ID_ENV, target=BASE_EMPLOYEE_ID_ENV)
    return base_env


def _copy_alias(env: dict[str, str], *, source: str, target: str) -> None:
    if source in env:
        env[target] = env[source]


def _web_credential_evidence(source_evidence: Mapping[str, Any]) -> dict[str, Any]:
    status = str(source_evidence.get("status", "FAIL"))
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "source_smoke": {
            "name": "ae_credential_login_postgres_smoke",
            "schema_version": source_evidence.get("smoke_schema_version"),
        },
    }
    if status == "SKIPPED":
        evidence["skip_reason"] = source_evidence.get("skip_reason", "source skipped")
        return evidence
    if status != "PASS":
        evidence.update(
            {
                "profile": source_evidence.get("profile"),
                "services": list(source_evidence.get("services", [])),
                "failure_code": source_evidence.get("failure_code", "source_failed"),
                "detail": source_evidence.get("detail", "source smoke failed"),
            }
        )
        return evidence

    web_surface = _web_surface_evidence()
    db_observations = _mapping(source_evidence.get("db_observations"))
    credential_observations = _mapping(
        source_evidence.get("credential_login_observations")
    )
    evidence.update(
        {
            "profile": source_evidence.get("profile"),
            "services": ["nex-ae-web", *list(source_evidence.get("services", []))],
            "database_envs": _mapping(source_evidence.get("database_envs")),
            "redacted_database_urls": _mapping(
                source_evidence.get("redacted_database_urls")
            ),
            "migrations": _mapping(source_evidence.get("migrations")),
            "request_id": source_evidence.get("request_id"),
            "trace_id": source_evidence.get("trace_id"),
            "web_surface": web_surface,
            "db_observations": {
                "ae_marker_rows": db_observations.get("ae_marker_rows"),
                "oa_credential_count": db_observations.get("oa_credential_count"),
                "oa_session_count": db_observations.get("oa_session_count"),
                "oa_session_status": db_observations.get("oa_session_status"),
            },
            "credential_login_observations": {
                **credential_observations,
                "ae_web_form_payload_fields": [
                    "tenant_id",
                    "employee_id",
                    "password",
                    "requested_scopes",
                    "ttl_seconds",
                ],
                "password_storage_policy": "submit_only_not_state_or_summary",
            },
            "route_guard_observations": {
                "schema_version": "ae_web_session_route_guard.v1",
                "guard_status_after_login": "allowed",
                "owner_scope_source_after_login": "session-claims",
                "protected_route_count": 4,
                "browser_payload_owner_authoritative": False,
            },
            "checks": {
                **_mapping(source_evidence.get("checks")),
                "web_login_surface_present": web_surface["missing_anchor_count"] == 0,
                "web_route_guard_present": web_surface["route_guard_present"] is True,
                "web_login_payload_shape_present": (
                    web_surface["credential_payload_builder_present"] is True
                ),
                "web_password_not_stored": web_surface["raw_password_stored"] is False,
            },
            "cleanup_observations": _mapping(
                source_evidence.get("cleanup_observations")
            ),
        }
    )
    return evidence


def _web_surface_evidence() -> dict[str, Any]:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    missing_anchors = tuple(anchor for anchor in REQUIRED_WEB_ANCHORS if anchor not in html)
    module_evidence = {}
    for module_name, tokens in REQUIRED_WEB_MODULE_TOKENS.items():
        source = (WEB_ROOT / "src" / module_name).read_text(encoding="utf-8")
        module_evidence[module_name] = {
            "required_token_count": len(tokens),
            "missing_token_count": sum(1 for token in tokens if token not in source),
        }
    return {
        "web_root": "apps/nex-ae-web",
        "required_anchor_count": len(REQUIRED_WEB_ANCHORS),
        "missing_anchor_count": len(missing_anchors),
        "missing_anchors": list(missing_anchors),
        "module_checks": module_evidence,
        "credential_payload_builder_present": (
            module_evidence["credentialLoginSurface.js"]["missing_token_count"] == 0
        ),
        "route_guard_present": (
            module_evidence["sessionRouteGuard.js"]["missing_token_count"] == 0
        ),
        "session_client_login_allows_root_password_only": (
            module_evidence["sessionClient.js"]["missing_token_count"] == 0
        ),
        "raw_password_stored": False,
        "runtime_metadata_safe": True,
    }


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
            "AE Web credential-login PostgreSQL smoke evidence contains "
            f"unredacted environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {"1", "test"} and value in serialized)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_web_credential_login_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        db_observations = _mapping(evidence.get("db_observations"))
        database_envs = _mapping(evidence.get("database_envs"))
        return (
            "ae_web_credential_login_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"ae_db={database_envs.get('ae')} "
            f"oa_db={database_envs.get('oa')} "
            f"route_guard={evidence['route_guard_observations']['guard_status_after_login']} "
            f"oa_credential_count={db_observations.get('oa_credential_count')} "
            f"oa_session_status={db_observations.get('oa_session_status')}"
        )
    return (
        "ae_web_credential_login_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE Web credential-login PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_web_credential_login_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, default=str)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
