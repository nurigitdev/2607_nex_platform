#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.production_token_profiles import (  # noqa: E402
    ACCESS_TOKEN_TYPE,
    PRODUCTION_TOKEN_ISSUER,
    PRODUCTION_TOKEN_PROFILES,
    validate_production_token_shape,
)


def run_oa_production_token_profiles() -> dict[str, Any]:
    headers = {"alg": "RS256", "typ": ACCESS_TOKEN_TYPE, "kid": "key-1"}
    common = {
        "iss": PRODUCTION_TOKEN_ISSUER,
        "aud": "nex-cx",
        "iat": 1_000,
        "nbf": 1_000,
        "exp": 1_300,
        "scope": "service:call document:read",
    }
    service_claims = common | {
        "sub": "service:nex-ae-api",
        "jti": "jti-service",
        "token_use": "service_access",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 1,
    }
    delegated_claims = common | {
        "sub": "user:tenant-1:user-1",
        "jti": "jti-user",
        "token_use": "delegated_user_access",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "session_ref": "session-ref-1",
        "authorization_revision": 2,
        "azp": "nex-ae-api",
    }
    service_errors = validate_production_token_shape(
        "service_access", headers=headers, claims=service_claims
    )
    delegated_errors = validate_production_token_shape(
        "delegated_user_access", headers=headers, claims=delegated_claims
    )
    sensitive_errors = validate_production_token_shape(
        "delegated_user_access",
        headers=headers,
        claims=delegated_claims | {"session_token": "must-not-appear"},
    )
    checks = {
        "two_signed_profiles_defined": len(PRODUCTION_TOKEN_PROFILES) == 2,
        "production_issuer_is_deployment_independent": (
            PRODUCTION_TOKEN_ISSUER == "urn:nex-platform:oa"
        ),
        "service_profile_valid": service_errors == (),
        "delegated_profile_valid": delegated_errors == (),
        "sensitive_session_token_rejected": (
            "claim_forbidden:session_token" in sensitive_errors
        ),
        "browser_session_profile_not_signed": (
            "browser_session" not in PRODUCTION_TOKEN_PROFILES
        ),
    }
    passed = all(checks.values())
    return {
        "policy_schema_version": "oa_production_token_profiles.v1",
        "slice": "1244",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_production_token_profile_failed",
        "issuer": PRODUCTION_TOKEN_ISSUER,
        "profiles": {
            name: profile.to_wire()
            for name, profile in PRODUCTION_TOKEN_PROFILES.items()
        },
        "claim_encoding": {
            "audience": "single_service_identifier",
            "scope": "space_delimited_string",
            "time": "integer_numeric_date",
            "session": "non_secret_session_ref_only",
            "authorization": "scope_snapshot_plus_authorization_revision",
        },
        "checks": checks,
        "next_slice": "1245",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_production_token_profiles="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"profiles={len(evidence.get('profiles') or {})} "
        f"issuer={evidence.get('issuer')} next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_production_token_profiles()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
