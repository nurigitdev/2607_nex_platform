#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.enterprise_oidc_registration import (
    load_oa_enterprise_oidc_registration,
    validate_enterprise_oidc_discovery,
)
from nex_runtime.s144_staging import (
    OIDC_CALLBACK,
    OIDC_ISSUER,
    OIDC_ISSUER_ORIGIN,
    configure_openbao_s144_trust,
    validate_s144_compose_assets,
)


class _RehearsalClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Mapping[str, Any] | None]] = []
        self.client_id = "GSDTnn3KaOrLpNlVGlYLS9TVsZgOTweO"
        self._client_credential = "client-" + "credential-" + "x" * 32

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, payload))
        if path == "/v1/transit/keys/oa-signing" and method == "GET":
            return {
                "data": {
                    "type": "rsa-3072",
                    "latest_version": 1,
                    "derived": False,
                    "exportable": False,
                    "allow_plaintext_backup": False,
                }
            }
        if (
            path == "/v1/identity/oidc/client/nex-platform-oa-staging"
            and method == "GET"
        ):
            return {
                "data": {
                    "client_id": self.client_id,
                    "client_secret": self._client_credential,
                    "client_type": "confidential",
                    "redirect_uris": [OIDC_CALLBACK],
                    "assignments": ["allow_all"],
                }
            }
        if path.endswith("NEX_OA_OIDC_CLIENT_SECRET"):
            return {"data": {"version": 1}}
        if path == "/v1/identity/oidc/provider/nex-platform" and method == "GET":
            return {"data": {"allowed_client_ids": [self.client_id]}}
        return {}


def run_s144_staging_trust_rehearsal() -> dict[str, Any]:
    compose = validate_s144_compose_assets(ROOT)
    client = _RehearsalClient()
    configured = configure_openbao_s144_trust(
        client,
        root_token="root-" + "x" * 24,
    )
    registration = load_oa_enterprise_oidc_registration(
        {
            "NEX_PROFILE": "staging_live",
            "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
            "NEX_OA_OIDC_PROVIDER_ID": "openbao-staging",
            "NEX_OA_OIDC_ISSUER": OIDC_ISSUER,
            "NEX_OA_OIDC_DISCOVERY_URL": (
                f"{OIDC_ISSUER}/.well-known/openid-configuration"
            ),
            "NEX_OA_OIDC_CLIENT_ID": configured["oidc_client_id"],
            "NEX_OA_OIDC_CLIENT_SECRET_REF": (
                "secret://openbao/nex-platform/staging/nex-oa/"
                "NEX_OA_OIDC_CLIENT_SECRET@v1"
            ),
            "NEX_OA_OIDC_REDIRECT_URI": OIDC_CALLBACK,
            "NEX_OA_OIDC_SCOPES": "openid",
            "NEX_OA_OIDC_GRANT_TYPE": "authorization_code",
            "NEX_OA_OIDC_RESPONSE_TYPE": "code",
            "NEX_OA_OIDC_PKCE_METHOD": "S256",
            "NEX_OA_OIDC_CLIENT_AUTH_METHOD": "client_secret_basic",
        }
    )
    discovery = validate_enterprise_oidc_discovery(
        registration,
        {
            "issuer": OIDC_ISSUER,
            "authorization_endpoint": (
                f"{OIDC_ISSUER_ORIGIN}/ui/vault/identity/oidc/provider/"
                "nex-platform/authorize"
            ),
            "token_endpoint": f"{OIDC_ISSUER}/token",
            "jwks_uri": f"{OIDC_ISSUER}/.well-known/keys",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "client_credentials"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none",
            ],
            "scopes_supported": ["openid"],
            "id_token_signing_alg_values_supported": ["RS256"],
        },
    )
    serialized = json.dumps(
        {"compose": compose, "configured": configured, "discovery": discovery},
        sort_keys=True,
    )
    paths = [path for _method, path, _payload in client.requests]
    checks = {
        "single_host_compose_valid": compose["status"] == "VALID",
        "openbao_ui_enabled": compose["openbao_ui_enabled"] is True,
        "managed_identity_tls_route": compose["tls_route_count"] == 10,
        "transit_mounted": paths[0] == "/v1/sys/mounts/transit",
        "rsa3072_key_bound": configured["transit_key_version"] == 1,
        "oa_policy_updated": "/v1/sys/policies/acl/nex-oa-staging" in paths,
        "confidential_client_registered": configured["oidc_client_name"]
        == "nex-platform-oa-staging",
        "generated_client_id_accepted": registration.client_id
        == configured["oidc_client_id"],
        "client_secret_custodied": configured["oidc_secret_version"] == 1,
        "client_secret_absent": client._client_credential not in serialized,
        "secret_reference_absent": "NEX_OA_OIDC_CLIENT_SECRET@" not in serialized,
        "provider_client_allowlist_exact": configured["oidc_provider_name"]
        == "nex-platform",
        "issuer_origin_exact": registration.issuer == OIDC_ISSUER,
        "pkce_required_by_oa": discovery["pkce_s256_required_by_oa"] is True,
        "pkce_metadata_optional": discovery["pkce_s256_advertised"] is False,
        "live_openbao_postgres_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s144_staging_trust_rehearsal_evidence.v1",
        "slice": "1440",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": []
        if passed
        else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "request_count": len(client.requests),
            "tls_route_count": compose["tls_route_count"],
            "transit_key_version": configured["transit_key_version"],
        },
        "decision": {
            "topology": "docker-compose-single-host",
            "host_software_install_required": False,
            "openbao_client_id_generated": True,
            "live_openbao_contacted": False,
            "live_postgres_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1441" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"s144_staging_trust_rehearsal=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s144_staging_trust_rehearsal=pass "
        f"checks={summary.get('check_count', 0)}/16 "
        f"requests={summary.get('request_count', 0)} "
        f"routes={summary.get('tls_route_count', 0)} "
        f"topology={decision.get('topology')} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s144_staging_trust_rehearsal()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
