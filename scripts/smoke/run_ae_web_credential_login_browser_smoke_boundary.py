#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "ae_web_credential_login_browser_smoke_boundary.v1"
SMOKE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE"
PROFILE_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
AE_WEB_URL_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_WEB_URL"
AE_API_BASE_URL_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_AE_API_BASE_URL"
AE_DATABASE_URL_ENV = "NEX_AE_TEST_DATABASE_URL"
OA_DATABASE_URL_ENV = "NEX_OA_TEST_DATABASE_URL"
TENANT_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_TENANT_ID"
EMPLOYEE_ID_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_EMPLOYEE_ID"
PASSWORD_ENV = "NEX_AE_WEB_CREDENTIAL_LOGIN_BROWSER_SMOKE_PASSWORD"


@dataclass(frozen=True)
class EnvSpec:
    name: str
    scope: str
    purpose: str


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    proof: str
    service_boundary: str


REQUIRED_ENV_SPECS = (
    EnvSpec(AE_WEB_URL_ENV, "operator-only", "AE Web URL served for browser smoke."),
    EnvSpec(
        AE_API_BASE_URL_ENV,
        "operator-only",
        "AE API base URL used by the browser credential-login profile.",
    ),
    EnvSpec(
        AE_DATABASE_URL_ENV,
        "server-only",
        "AE test database URL for migration/readback proof.",
    ),
    EnvSpec(
        OA_DATABASE_URL_ENV,
        "server-only",
        "OA test database URL for credential/session proof.",
    ),
    EnvSpec(TENANT_ID_ENV, "operator-only", "Smoke tenant/organization subject."),
    EnvSpec(EMPLOYEE_ID_ENV, "operator-only", "Smoke employee login identifier."),
    EnvSpec(
        PASSWORD_ENV,
        "operator-secret",
        "Smoke employee password typed into the browser login form.",
    ),
)

REQUIRED_PHASES = (
    PhaseSpec(
        "static_shell_ready",
        "AE Web shell serves the credential-login form and diagnostics anchors.",
        "nex-ae-web",
    ),
    PhaseSpec(
        "browser_runtime_config_guard",
        "Browser config is fetch-mode, same-origin safe, and secret-free.",
        "nex-ae-web",
    ),
    PhaseSpec(
        "ae_auth_facade_ready",
        "AE auth facade responds before browser login checks start.",
        "nex-ae-api",
    ),
    PhaseSpec(
        "postgres_migration_current",
        "AE/OA test schemas are migrated/current before credential execution.",
        "nex-ae-api,nex-oa",
    ),
    PhaseSpec(
        "oa_credential_seed_available",
        "Smoke tenant and employee credential exist in OA test persistence.",
        "nex-oa",
    ),
    PhaseSpec(
        "credential_form_fill_submit",
        "Browser fills tenant, employee id, and password, then submits login.",
        "nex-ae-web,nex-ae-api",
    ),
    PhaseSpec(
        "browser_session_current_readback",
        "Browser reads an active same-origin user session after login.",
        "nex-ae-web,nex-ae-api,nex-oa",
    ),
    PhaseSpec(
        "authenticated_route_guard",
        "AE Web route guard reports allowed protected routes from session claims.",
        "nex-ae-web",
    ),
    PhaseSpec(
        "logout_revocation_readback",
        "Browser logout revokes the OA-backed session and returns anonymous state.",
        "nex-ae-web,nex-ae-api,nex-oa",
    ),
    PhaseSpec(
        "evidence_redaction_check",
        "Evidence excludes DB URLs, passwords, cookies, tokens, and provider endpoints.",
        "operator",
    ),
)

REQUIRED_BROWSER_ROUTES = (
    "/api/v1/auth/session",
    "/api/v1/auth/session/login",
    "/api/v1/auth/session/logout",
)

BROWSER_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "config_schema_version",
        "client_mode",
        "ae_api_base_path",
        "ae_base_url",
        "features",
        "session_route",
        "login_route",
        "logout_route",
    }
)

FORBIDDEN_BROWSER_CONFIG_TOKENS = (
    "api_key",
    "apikey",
    "cookie",
    "database",
    "db_url",
    "password",
    "provider",
    "secret",
    "service_token",
    "source_storage",
    "storage_path",
    "storage_uri",
    "token",
)

PROTECTED_ENV_KEYS = tuple(spec.name for spec in REQUIRED_ENV_SPECS) + (PROFILE_ENV,)


def run_ae_web_credential_login_browser_smoke_boundary(
    environ: dict[str, str] | None = None,
    *,
    browser_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    enabled = env.get(SMOKE_ENV) == "1"
    issues = _configuration_issues(env, enabled=enabled)
    issues.extend(_browser_config_issues(browser_config))
    status = "FAIL" if issues else "PASS" if enabled else "SKIPPED"
    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "evidence_generated_at": _utc_now(),
        "status": status,
        "activation": {
            "env": SMOKE_ENV,
            "enabled": enabled,
            "profile_env": PROFILE_ENV,
            "requested_profile": env.get(PROFILE_ENV, DEFAULT_PROFILE),
            "required_profile": DEFAULT_PROFILE,
        },
        "boundary": {
            "type": "protected_ae_web_credential_login_browser_smoke",
            "live_network_allowed": enabled,
            "actual_execution_in_this_runner": False,
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
            "next_execution_slice": "Slice 0263",
        },
        "required_env": _required_env_evidence(env),
        "browser_runtime_contract": {
            "provided": browser_config is not None,
            "allowed_top_level_keys": sorted(BROWSER_ALLOWED_TOP_LEVEL_KEYS),
            "observed_top_level_keys": sorted(browser_config or {}),
            "forbidden_key_tokens": sorted(FORBIDDEN_BROWSER_CONFIG_TOKENS),
            "same_origin_credentials": "required",
            "password_in_browser_config": False,
            "service_credentials_in_browser": False,
            "database_endpoints_in_browser": False,
            "provider_endpoints_in_browser": False,
            "cookie_material_in_browser_config": False,
        },
        "browser_routes": list(REQUIRED_BROWSER_ROUTES),
        "required_phases": [
            {
                "name": phase.name,
                "proof": phase.proof,
                "service_boundary": phase.service_boundary,
            }
            for phase in REQUIRED_PHASES
        ],
        "evidence_requirements": {
            "must_attempt_postgresql_connections": [
                AE_DATABASE_URL_ENV,
                OA_DATABASE_URL_ENV,
            ],
            "must_prove_oa_credential_login": True,
            "must_prove_ae_cookie_session_facade": True,
            "must_prove_browser_route_guard_allowed": True,
            "must_fail_instead_of_silent_skip_when_enabled": True,
            "may_skip_by_default_in_quality_gate": True,
            "redacted_fields_only": True,
        },
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "policy": "protected DB/API/Web credential values are excluded from evidence",
            "checked_env_keys": [key for key in PROTECTED_ENV_KEYS if env.get(key)],
        },
    }
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    assert_boundary_evidence_redacted(serialized, env)
    return evidence


def _configuration_issues(
    env: dict[str, str],
    *,
    enabled: bool,
) -> list[dict[str, str]]:
    if not enabled:
        return []

    issues: list[dict[str, str]] = []
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        issues.append(
            {
                "error_code": "profile_not_allowed",
                "detail": f"{PROFILE_ENV} must be {DEFAULT_PROFILE}.",
                "env": PROFILE_ENV,
            }
        )
    for spec in REQUIRED_ENV_SPECS:
        if not env.get(spec.name):
            issues.append(
                {
                    "error_code": "required_env_missing",
                    "detail": f"{spec.name} is required when {SMOKE_ENV}=1.",
                    "env": spec.name,
                }
            )
    return issues


def _browser_config_issues(
    browser_config: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if browser_config is None:
        return []

    issues: list[dict[str, str]] = []
    for key in sorted(browser_config):
        normalized = _normalize_key(key)
        if key not in BROWSER_ALLOWED_TOP_LEVEL_KEYS:
            issues.append(
                {
                    "error_code": "browser_config_top_level_key_unsupported",
                    "detail": f"{key} is not part of the AE Web credential-login config.",
                    "field": key,
                }
            )
        if _contains_forbidden_browser_token(normalized):
            issues.append(
                {
                    "error_code": "browser_config_key_server_only",
                    "detail": f"{key} belongs behind the server-side smoke boundary.",
                    "field": key,
                }
            )

    for field_path in _forbidden_nested_field_paths(browser_config):
        issues.append(
            {
                "error_code": "browser_config_nested_key_server_only",
                "detail": f"{field_path} belongs behind the server-side smoke boundary.",
                "field": field_path,
            }
        )
    return issues


def _required_env_evidence(env: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "scope": spec.scope,
            "purpose": spec.purpose,
            "required_when_enabled": True,
            "configured": bool(env.get(spec.name)),
            "value": "configured" if env.get(spec.name) else "missing",
        }
        for spec in REQUIRED_ENV_SPECS
    ]


def _forbidden_nested_field_paths(
    value: Any,
    *,
    prefix: str = "",
) -> list[str]:
    if isinstance(value, dict):
        field_paths: list[str] = []
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if _contains_forbidden_browser_token(_normalize_key(str(key))):
                field_paths.append(path)
            field_paths.extend(_forbidden_nested_field_paths(child, prefix=path))
        return field_paths
    if isinstance(value, list):
        field_paths = []
        for index, child in enumerate(value):
            field_paths.extend(
                _forbidden_nested_field_paths(child, prefix=f"{prefix}[{index}]")
            )
        return field_paths
    return []


def _contains_forbidden_browser_token(normalized_key: str) -> bool:
    return any(token in normalized_key for token in FORBIDDEN_BROWSER_CONFIG_TOKENS)


def _normalize_key(key: str) -> str:
    normalized = []
    for character in key:
        if character.isupper():
            normalized.append("_")
            normalized.append(character.lower())
        elif character in "-.":
            normalized.append("_")
        else:
            normalized.append(character)
    return "".join(normalized).strip("_").lower()


def assert_boundary_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            "AE Web credential-login browser smoke boundary evidence contains "
            f"unredacted environment value: {leaked_keys[0]}"
        )


def write_boundary_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_boundary_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def load_browser_config_json(raw_config: str | None) -> dict[str, Any] | None:
    if raw_config is None:
        return None
    parsed = json.loads(raw_config)
    if not isinstance(parsed, dict):
        raise ValueError("--browser-config-json must decode to a JSON object.")
    return parsed


def load_browser_config_path(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("--browser-config-path must contain a JSON object.")
    return parsed


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_credential_login_browser_boundary=skipped "
            f"reason={SMOKE_ENV} boundary=pass phases={len(REQUIRED_PHASES)}"
        )
    if evidence["status"] == "PASS":
        configured_count = sum(
            1 for item in evidence["required_env"] if item["configured"]
        )
        return (
            "ae_web_credential_login_browser_boundary=pass "
            f"profile={evidence['activation']['requested_profile']} "
            f"env={configured_count}/{len(REQUIRED_ENV_SPECS)} "
            f"phases={len(REQUIRED_PHASES)}"
        )
    return (
        "ae_web_credential_login_browser_boundary=fail "
        f"issues={len(evidence['issues'])}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the protected AE Web credential-login browser smoke boundary."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional protected JSON boundary evidence output path.",
    )
    parser.add_argument(
        "--browser-config-json",
        help="Optional safe browser runtime config JSON object to validate.",
    )
    parser.add_argument(
        "--browser-config-path",
        type=Path,
        help="Optional path to a browser runtime config JSON object to validate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        browser_config = load_browser_config_json(args.browser_config_json)
        file_config = load_browser_config_path(args.browser_config_path)
        if browser_config is not None and file_config is not None:
            raise ValueError("Use only one browser config input.")
        evidence = run_ae_web_credential_login_browser_smoke_boundary(
            browser_config=browser_config if browser_config is not None else file_config
        )
        if args.output:
            write_boundary_evidence(args.output, evidence)
        output = (
            summary_line(evidence)
            if args.summary
            else json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        print(output)
        return 1 if evidence["status"] == "FAIL" else 0
    except (json.JSONDecodeError, ValueError) as exc:
        print(
            "ae_web_credential_login_browser_boundary=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
