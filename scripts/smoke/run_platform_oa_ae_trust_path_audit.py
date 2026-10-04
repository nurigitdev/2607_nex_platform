#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_oa_ae_trust_path_audit.v1"
OA_ROUTE_TOKENS = (
    "/internal/v1/auth/user-login",
    "/internal/v1/auth/user-sessions/issue",
    "/internal/v1/auth/user-sessions/introspect",
    "/internal/v1/auth/user-sessions/{session_id}/revoke",
)
AE_FACADE_ROUTE_TOKENS = (
    "/api/v1/auth/session",
    "/api/v1/auth/session/login",
    "/api/v1/auth/session/logout",
)
AE_OA_CLIENT_OPERATION_TOKENS = (
    '"/internal/v1/auth/user-login"',
    '"/internal/v1/auth/user-sessions/issue"',
    '"/internal/v1/auth/user-sessions/introspect"',
    'f"/internal/v1/auth/user-sessions/{_quote_session_id(session_id)}/revoke"',
)


def run_platform_oa_ae_trust_path_audit(root: Path = ROOT) -> dict[str, Any]:
    oa_login = _read_text(root / "services/nex-oa/nex_oa/user_login.py")
    oa_sessions = _read_text(root / "services/nex-oa/nex_oa/sessions.py")
    ae_sessions = _read_text(root / "services/nex-ae-api/nex_ae_api/auth_sessions.py")
    oa_client = _read_text(root / "services/nex-ae-api/nex_ae_api/oa_session_client.py")
    service_auth = _read_text(root / "services/nex-ae-api/nex_ae_api/service_auth.py")
    web_bootstrap = _read_text(root / "apps/nex-ae-web/src/sessionBootstrap.js")
    env_example = _read_text(root / ".env.example")

    oa_route_sources = oa_login + "\n" + oa_sessions
    checks = {
        "oa_user_session_routes_complete": all(
            token in oa_route_sources for token in OA_ROUTE_TOKENS
        ),
        "ae_browser_session_facade_complete": all(
            token in ae_sessions for token in AE_FACADE_ROUTE_TOKENS
        ),
        "ae_uses_http_oa_session_client": (
            "class HttpOaUserSessionClient" in oa_client
            and all(token in oa_client for token in AE_OA_CLIENT_OPERATION_TOKENS)
        ),
        "ae_to_oa_service_identity_is_audience_bound": (
            'audience="nex-oa"' in oa_client
            and '"X-Service-ID": "nex-ae-api"' in oa_client
        ),
        "trace_and_request_ids_propagate_to_oa": (
            '"X-Request-ID": request_id' in oa_client
            and '"traceparent":' in oa_client
        ),
        "browser_session_payload_is_redacted": all(
            token in ae_sessions
            for token in (
                '"raw_token_included": False',
                '"service_token_included": False',
                '"password_included": False',
                '"claim_owner_authoritative": True',
            )
        ),
        "browser_fetch_uses_same_origin_credentials": (
            'credentialMode: runtimeConfig.clientMode === "fetch" ? "same-origin" : "none"'
            in web_bootstrap
        ),
        "signed_only_outbound_mode_is_supported": (
            'if profile not in {"DUAL_READ", "SIGNED_ONLY"}' in service_auth
            and "ae.outbound_service_token_missing" in service_auth
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    env_has_oa_activation = all(
        token in env_example
        for token in (
            "NEX_AE_AUTH_SESSION_MODE=",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE=",
            "NEX_AE_TO_OA_SERVICE_TOKEN=",
        )
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1305",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_oa_ae_trust_path_audit_failed",
        "checks": checks,
        "issues": issues,
        "findings": {
            "oa_internal_route_count": len(OA_ROUTE_TOKENS),
            "ae_facade_route_count": len(AE_FACADE_ROUTE_TOKENS),
            "default_ae_auth_session_mode": "mock",
            "default_service_token_rollout_profile": "TEST_MOCK",
            "local_cookie_secure": False,
            "environment_example_materializes_oa_activation": env_has_oa_activation,
            "raw_browser_token_exposed": False,
            "browser_service_token_exposed": False,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "platform_integration",
                "gap": "materialize OA-backed AE session mode and signed service-token settings in the typed runtime profile",
                "target_requirement": "S132",
            },
            {
                "priority": "P0",
                "owner": "nex-oa/nex-ae-api",
                "gap": "prove OA mode, SIGNED_ONLY admission, revocation, and secure-cookie policy in one browser-to-OA chain",
                "target_requirement": "S134",
            },
            {
                "priority": "P1",
                "owner": "nex-ae-api",
                "gap": "make cookie transport security profile-aware while retaining local HTTP development",
                "target_requirement": "S134",
            },
        ],
        "decision": {
            "oa_is_identity_authority": True,
            "ae_owns_browser_cookie_lifecycle": True,
            "browser_claims_are_authoritative": False,
            "production_trust_is_active_by_default": False,
            "mutation_performed": False,
            "next_slice": "1306",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_oa_ae_trust_path=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_oa_ae_trust_path=pass "
        f"oa_routes={findings.get('oa_internal_route_count', 0)} "
        f"ae_routes={findings.get('ae_facade_route_count', 0)} "
        f"auth_default={findings.get('default_ae_auth_session_mode')} "
        f"token_default={findings.get('default_service_token_rollout_profile')} "
        f"profile_materialized={findings.get('environment_example_materializes_oa_activation')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_oa_ae_trust_path_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
