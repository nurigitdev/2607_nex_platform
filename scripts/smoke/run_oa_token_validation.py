#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository  # noqa: E402
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_oa.token_validation_service import OaSignedTokenValidationService  # noqa: E402


def run_oa_token_validation() -> dict[str, Any]:
    principals = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    principals.upsert_principal(
        {
            "principal_id": "cx-runtime",
            "service_id": "nex-cx",
            "display_name": "CX Runtime",
            "allowed_audiences": ["nex-oa"],
            "allowed_scopes": ["token:introspect"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "cx-runtime",
        lifetime_days=1,
        now_epoch=100,
        credential_id="cred-cx-runtime",
        client_secret="smoke-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-validation-smoke"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    keys.register_key(
        {
            "key_id": "oa-key-validation-smoke",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(reference, key_id="oa-key-validation-smoke"),
            "private_key_ref": reference,
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 900,
            "verify_until": 1_230,
        }
    )
    keys.set_key_state(
        "oa-key-validation-smoke",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )
    token = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    ).exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": "cred-cx-runtime",
            "client_secret": "smoke-secret",
            "audience": "nex-oa",
            "scope": "token:introspect",
        },
        now_epoch=500,
        token_id="sat-validation-smoke",
    )["access_token"]
    validator = OaSignedTokenValidationService(
        signing_key_service=keys,
        principal_service=principals,
    )
    active = validator.introspect(
        token,
        expected_audience="nex-oa",
        required_scopes=("token:introspect",),
        now_epoch=600,
    )
    claims = validator.validate(token, expected_audience="nex-oa", now_epoch=600)
    keys.revoke_token_claims(
        claims,
        reason_code="OPERATOR",
        now_epoch=600,
        revocation_id="rev-validation-smoke",
    )
    revoked = validator.introspect(
        token,
        expected_audience="nex-oa",
        now_epoch=600,
    )
    checks = {
        "valid_signature_and_lineage_active": active.get("active") is True,
        "credential_projected_without_token": active.get("credential_id") == "cred-cx-runtime" and "access_token" not in active,
        "revoked_jti_is_inactive": revoked.get("active") is False and revoked.get("reason_code") == "oa.token_revoked",
        "raw_jti_not_projected": "jti" not in active and "jti" not in revoked,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_token_validation_evidence.v1",
        "slice": "1268",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_token_validation_failed",
        "checks": checks,
        "active_before_revoke": active.get("active"),
        "active_after_revoke": revoked.get("active"),
        "next_slice": "1269",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_token_validation="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"active_before={str(evidence.get('active_before_revoke')).lower()} "
        f"active_after={str(evidence.get('active_after_revoke')).lower()} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_token_validation()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
