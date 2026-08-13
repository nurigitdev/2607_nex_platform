#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import load_env_file  # noqa: E402
from run_ae_credential_login_postgres_smoke import (  # noqa: E402
    EMPLOYEE_ID_ENV as CREDENTIAL_EMPLOYEE_ID_ENV,
    PASSWORD_ENV as CREDENTIAL_PASSWORD_ENV,
    SMOKE_ENV as CREDENTIAL_SMOKE_ENV,
    SMOKE_PROFILE_ENV as CREDENTIAL_PROFILE_ENV,
    TENANT_ID_ENV as CREDENTIAL_TENANT_ID_ENV,
    run_ae_credential_login_postgres_smoke,
)
from run_ae_web_credential_login_browser_execution_readiness import (  # noqa: E402
    run_ae_web_credential_login_browser_execution_readiness,
)
from run_ae_web_credential_login_browser_harness_smoke import (  # noqa: E402
    run_ae_web_credential_login_browser_harness_smoke,
    safe_browser_config,
)
from run_ae_web_credential_login_browser_smoke_boundary import (  # noqa: E402
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    AE_WEB_URL_ENV,
    DEFAULT_PROFILE,
    EMPLOYEE_ID_ENV,
    OA_DATABASE_URL_ENV,
    PASSWORD_ENV,
    PROFILE_ENV,
    SMOKE_ENV as BROWSER_SMOKE_ENV,
    TENANT_ID_ENV,
    assert_boundary_evidence_redacted,
    run_ae_web_credential_login_browser_smoke_boundary,
)


SCHEMA_VERSION = "ae_web_credential_login_browser_live_smoke.v1"

SmokeRunner = Callable[[dict[str, str]], dict[str, Any]]

PROTECTED_ENV_KEYS = (
    AE_WEB_URL_ENV,
    AE_API_BASE_URL_ENV,
    AE_DATABASE_URL_ENV,
    OA_DATABASE_URL_ENV,
    TENANT_ID_ENV,
    EMPLOYEE_ID_ENV,
    PASSWORD_ENV,
    PROFILE_ENV,
    CREDENTIAL_TENANT_ID_ENV,
    CREDENTIAL_EMPLOYEE_ID_ENV,
    CREDENTIAL_PASSWORD_ENV,
    CREDENTIAL_PROFILE_ENV,
)


def run_ae_web_credential_login_browser_live_smoke(
    environ: dict[str, str] | None = None,
    *,
    readiness_runner: SmokeRunner = run_ae_web_credential_login_browser_execution_readiness,
    credential_runner: SmokeRunner = run_ae_credential_login_postgres_smoke,
    harness_runner: SmokeRunner = run_ae_web_credential_login_browser_harness_smoke,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(BROWSER_SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{BROWSER_SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    boundary = run_ae_web_credential_login_browser_smoke_boundary(
        env,
        browser_config=safe_browser_config(),
    )
    if boundary["status"] != "PASS":
        return _failure(
            "boundary_invalid",
            profile=profile,
            boundary=boundary,
            env=env,
        )

    readiness = readiness_runner(env)
    if readiness["status"] != "PASS":
        return _failure(
            "readiness_failed",
            profile=profile,
            boundary=boundary,
            readiness=readiness,
            env=env,
        )

    credential = credential_runner(_credential_environ(env))
    if credential["status"] != "PASS":
        return _failure(
            f"credential_postgres_{_status_label(credential)}",
            profile=profile,
            boundary=boundary,
            readiness=readiness,
            credential=credential,
            env=env,
        )

    harness = harness_runner(env)
    if harness["status"] != "PASS":
        return _failure(
            f"browser_harness_{_status_label(harness)}",
            profile=profile,
            boundary=boundary,
            readiness=readiness,
            credential=credential,
            harness=harness,
            env=env,
        )

    evidence = _pass_evidence(
        profile=profile,
        boundary=boundary,
        readiness=readiness,
        credential=credential,
        harness=harness,
    )
    assert_live_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _credential_environ(env: Mapping[str, str]) -> dict[str, str]:
    credential_env = dict(env)
    credential_env[CREDENTIAL_SMOKE_ENV] = "1"
    _copy_alias(credential_env, source=PROFILE_ENV, target=CREDENTIAL_PROFILE_ENV)
    _copy_alias(credential_env, source=TENANT_ID_ENV, target=CREDENTIAL_TENANT_ID_ENV)
    _copy_alias(
        credential_env,
        source=EMPLOYEE_ID_ENV,
        target=CREDENTIAL_EMPLOYEE_ID_ENV,
    )
    _copy_alias(credential_env, source=PASSWORD_ENV, target=CREDENTIAL_PASSWORD_ENV)
    return credential_env


def _copy_alias(env: dict[str, str], *, source: str, target: str) -> None:
    if source in env:
        env[target] = env[source]


def _pass_evidence(
    *,
    profile: str,
    boundary: Mapping[str, Any],
    readiness: Mapping[str, Any],
    credential: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> dict[str, Any]:
    credential_checks = _mapping(credential.get("checks"))
    db_observations = _mapping(credential.get("db_observations"))
    credential_observations = _mapping(credential.get("credential_login_observations"))
    harness_observations = _mapping(harness.get("harness"))
    harness_checks = _mapping(harness.get("checks"))
    checks = {
        "boundary_passed": boundary.get("status") == "PASS",
        "readiness_passed": readiness.get("status") == "PASS",
        "credential_postgres_smoke_passed": credential.get("status") == "PASS",
        "browser_harness_smoke_passed": harness.get("status") == "PASS",
        "actual_test_database_smoke_executed": True,
        "ae_test_database_connected": db_observations.get("ae_marker_rows") == 1,
        "oa_test_database_connected": (
            db_observations.get("oa_credential_count") == 1
            and db_observations.get("oa_session_count") == 1
        ),
        "oa_credential_login_proven": (
            credential_observations.get("password_verified") is True
        ),
        "password_verified": credential_observations.get("password_verified") is True,
        "ae_cookie_session_facade_proven": (
            credential_checks.get("cookie_set_after_login") is True
            and credential_checks.get("cookie_removed_after_logout") is True
        ),
        "route_guard_allowed": (
            credential_checks.get("protected_owner_scope_claim_derived") is True
            and harness_checks.get("route_guard_allowed") is True
        ),
        "logout_returns_anonymous": harness_checks.get("logout_returns_anonymous")
        is True,
        "db_session_revoked": (
            credential_checks.get("db_session_revoked") is True
            and db_observations.get("oa_session_status") == "REVOKED"
        ),
        "redacted_evidence": True,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise ValueError(f"AE Web browser live smoke pass evidence failed: {failed}")

    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "profile": profile,
        "services": ["nex-ae-web", "nex-ae-api", "nex-oa"],
        "source_smokes": {
            "boundary": {
                "schema_version": boundary.get("evidence_schema_version"),
                "status": boundary.get("status"),
            },
            "readiness": {
                "schema_version": readiness.get("readiness_schema_version"),
                "status": readiness.get("status"),
            },
            "credential_postgres": {
                "schema_version": credential.get("smoke_schema_version"),
                "status": credential.get("status"),
            },
            "browser_harness": {
                "schema_version": harness.get("smoke_schema_version"),
                "status": harness.get("status"),
            },
        },
        "activation": {
            "env": BROWSER_SMOKE_ENV,
            "enabled": True,
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        },
        "database_envs": _mapping(credential.get("database_envs")),
        "redacted_database_urls": _mapping(credential.get("redacted_database_urls")),
        "migrations": _mapping(credential.get("migrations")),
        "request_id": credential.get("request_id"),
        "trace_id": credential.get("trace_id"),
        "db_observations": {
            "ae_marker_rows": db_observations.get("ae_marker_rows"),
            "oa_credential_count": db_observations.get("oa_credential_count"),
            "oa_session_count": db_observations.get("oa_session_count"),
            "oa_session_status": db_observations.get("oa_session_status"),
            "oa_session_revoked_at_present": db_observations.get(
                "oa_session_revoked_at_present"
            ),
        },
        "credential_login_observations": {
            "ae_endpoint": credential_observations.get("ae_endpoint"),
            "oa_endpoint": credential_observations.get("oa_endpoint"),
            "oa_client_operations": list(
                credential_observations.get("oa_client_operations", [])
            ),
            "password_verified": credential_observations.get("password_verified")
            is True,
            "browser_cookie_value_kind": credential_observations.get(
                "browser_cookie_value_kind"
            ),
            "browser_cookie_material_in_evidence": credential_observations.get(
                "browser_cookie_material_in_evidence"
            )
            is True,
            "owner_scope_authority": credential_observations.get(
                "owner_scope_authority"
            ),
        },
        "browser_harness_observations": {
            "mode": harness_observations.get("mode"),
            "route_guard_status": harness_observations.get("route_guard_status"),
            "fetch_call_count": harness_observations.get("fetch_call_count"),
            "login_route": harness_observations.get("login_route"),
            "current_session_status": harness_observations.get(
                "current_session_status"
            ),
            "authenticated_session_status": harness_observations.get(
                "authenticated_session_status"
            ),
            "logout_session_status": harness_observations.get(
                "logout_session_status"
            ),
        },
        "execution_observations": {
            "actual_test_database_smoke_executed": True,
            "browser_harness_kind": "deterministic_fake_fetch",
            "browser_live_network_executed": False,
            "postgres_execution_runner": "run_ae_credential_login_postgres_smoke",
            "playwright_execution_status": "deferred_until_explicit_dependency_decision",
        },
        "checks": checks,
        "cleanup_observations": _mapping(credential.get("cleanup_observations")),
        "redaction": {
            "raw_password_in_evidence": False,
            "database_endpoint_in_evidence": False,
            "cookie_material_in_evidence": False,
            "token_material_in_evidence": False,
            "provider_endpoint_in_evidence": False,
        },
    }


def _failure(
    failure_code: str,
    *,
    profile: str,
    env: Mapping[str, str],
    boundary: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    credential: Mapping[str, Any] | None = None,
    harness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "profile": profile,
        "failure_code": failure_code,
        "source_smokes": {
            "boundary": _source_status(boundary, version_key="evidence_schema_version"),
            "readiness": _source_status(readiness, version_key="readiness_schema_version"),
            "credential_postgres": _source_status(
                credential,
                version_key="smoke_schema_version",
            ),
            "browser_harness": _source_status(
                harness,
                version_key="smoke_schema_version",
            ),
        },
        "checks": {
            "boundary_passed": _status(boundary) == "PASS",
            "readiness_passed": _status(readiness) == "PASS",
            "credential_postgres_smoke_passed": _status(credential) == "PASS",
            "browser_harness_smoke_passed": _status(harness) == "PASS",
            "actual_test_database_smoke_executed": _status(credential) == "PASS",
            "redacted_evidence": True,
        },
    }
    assert_live_smoke_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, default=str),
        env,
    )
    return evidence


def _source_status(
    evidence: Mapping[str, Any] | None,
    *,
    version_key: str,
) -> dict[str, Any]:
    if evidence is None:
        return {"status": "NOT_RUN"}
    source = {"status": evidence.get("status", "UNKNOWN")}
    if version_key in evidence:
        source["schema_version"] = evidence.get(version_key)
    if "failure_code" in evidence:
        source["failure_code"] = evidence.get("failure_code")
    return source


def _status(evidence: Mapping[str, Any] | None) -> str:
    if evidence is None:
        return "NOT_RUN"
    return str(evidence.get("status", "UNKNOWN"))


def _status_label(evidence: Mapping[str, Any]) -> str:
    return _status(evidence).lower()


def assert_live_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    assert_boundary_evidence_redacted(serialized_evidence, dict(environ))
    leaked = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked:
        raise ValueError(
            "AE Web credential-login browser live smoke evidence contains "
            f"unredacted environment value: {leaked[0]}"
        )


def _protected_env_value_leaked(serialized: str, value: str | None) -> bool:
    return bool(value and value not in {"1", DEFAULT_PROFILE} and value in serialized)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def write_live_smoke_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    assert_live_smoke_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_web_credential_login_browser_live_smoke=skipped reason={BROWSER_SMOKE_ENV}"
    if evidence["status"] == "PASS":
        db_observations = _mapping(evidence.get("db_observations"))
        database_envs = _mapping(evidence.get("database_envs"))
        browser_harness = _mapping(evidence.get("browser_harness_observations"))
        return (
            "ae_web_credential_login_browser_live_smoke=pass "
            f"profile={evidence['profile']} "
            f"ae_db={database_envs.get('ae')} "
            f"oa_db={database_envs.get('oa')} "
            f"route_guard={browser_harness.get('route_guard_status')} "
            f"oa_session_status={db_observations.get('oa_session_status')} "
            "live_db=true"
        )
    return (
        "ae_web_credential_login_browser_live_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected AE Web credential-login browser live smoke evidence."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_env_file(ROOT / ".env.local")
        evidence = run_ae_web_credential_login_browser_live_smoke()
        if args.output:
            write_live_smoke_evidence(args.output, evidence)
        print(
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
        return 1 if evidence["status"] == "FAIL" else 0
    except ValueError as exc:
        print(
            "ae_web_credential_login_browser_live_smoke=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
