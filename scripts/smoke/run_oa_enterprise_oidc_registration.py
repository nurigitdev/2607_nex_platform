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
from nex_oa.federated_identities import build_federation_provider
from nex_oa.federated_identity_repository import (
    InMemoryOaFederatedIdentityRepository,
)

SCHEMA_VERSION = "oa_enterprise_oidc_registration_evidence.v1"
ISSUER = "https://id.nex-staging.test:8443/v1/identity/oidc/provider/nex-platform"


def run_oa_enterprise_oidc_registration() -> dict[str, Any]:
    registration = load_oa_enterprise_oidc_registration(
        {
            "NEX_PROFILE": "staging_live",
            "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
            "NEX_OA_OIDC_PROVIDER_ID": "openbao-staging",
            "NEX_OA_OIDC_ISSUER": ISSUER,
            "NEX_OA_OIDC_DISCOVERY_URL": (f"{ISSUER}/.well-known/openid-configuration"),
            "NEX_OA_OIDC_CLIENT_ID": "nex-platform-oa-staging",
            "NEX_OA_OIDC_CLIENT_SECRET_REF": (
                "secret://openbao/nex-platform/staging/nex-oa/"
                "NEX_OA_OIDC_CLIENT_SECRET@v1"
            ),
            "NEX_OA_OIDC_REDIRECT_URI": (
                "https://oa.nex-staging.test:8443/api/v1/auth/federated/callback"
            ),
            "NEX_OA_OIDC_SCOPES": "openid",
            "NEX_OA_OIDC_GRANT_TYPE": "authorization_code",
            "NEX_OA_OIDC_RESPONSE_TYPE": "code",
            "NEX_OA_OIDC_PKCE_METHOD": "S256",
            "NEX_OA_OIDC_CLIENT_AUTH_METHOD": "client_secret_basic",
        }
    )
    metadata = validate_enterprise_oidc_discovery(
        registration,
        {
            "issuer": ISSUER,
            "authorization_endpoint": (
                "https://id.nex-staging.test:8443/ui/oidc/authorize"
            ),
            "token_endpoint": (
                "https://id.nex-staging.test:8443/v1/identity/oidc/token"
            ),
            "jwks_uri": ("https://id.nex-staging.test:8443/v1/identity/oidc/keys"),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "scopes_supported": ["openid"],
            "id_token_signing_alg_values_supported": ["RS256"],
        },
    )
    repository = InMemoryOaFederatedIdentityRepository()
    stored = repository.save_provider(
        build_federation_provider(
            registration.provider_payload(display_name="OpenBao staging")
        )
    )
    safe = registration.safe_projection()
    checks = {
        "staging_profile_accepted": registration.provider_id == "openbao-staging",
        "issuer_is_https": registration.issuer.startswith("https://"),
        "discovery_is_issuer_relative": registration.discovery_url
        == f"{registration.issuer}/.well-known/openid-configuration",
        "callback_is_oa_owned": registration.redirect_uri
        == "https://oa.nex-staging.test:8443/api/v1/auth/federated/callback",
        "authorization_code_only": registration.grant_type == "authorization_code"
        and registration.response_type == "code",
        "pkce_s256_required": registration.pkce_method == "S256",
        "minimal_scope_is_exact": registration.scopes == ("openid",),
        "client_auth_is_confidential": registration.client_auth_method
        == "client_secret_basic",
        "discovery_capabilities_verified": metadata["endpoint_count"] == 3,
        "public_provider_metadata_persisted": stored["issuer"] == registration.issuer,
        "secret_reference_not_persisted": "client_secret_reference" not in stored,
        "secret_reference_not_projected": "client_secret_reference" not in safe,
        "secret_value_absent": safe["client_secret_included"] is False,
        "live_idp_postgres_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1438",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": []
        if passed
        else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "scope_count": len(registration.scopes),
            "trusted_claim_count": len(registration.trusted_claims),
            "endpoint_count": metadata["endpoint_count"],
        },
        "decision": {
            "staging_idp_adapter": "openbao_oidc_provider",
            "corporate_idp_contacted": False,
            "client_secret_in_database": False,
            "live_idp_contacted": False,
            "live_postgres_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1439" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_enterprise_oidc_registration=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_enterprise_oidc_registration=pass "
        f"checks={summary.get('check_count', 0)}/14 "
        f"scopes={summary.get('scope_count', 0)} "
        f"claims={summary.get('trusted_claim_count', 0)} "
        f"endpoints={summary.get('endpoint_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_enterprise_oidc_registration()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
