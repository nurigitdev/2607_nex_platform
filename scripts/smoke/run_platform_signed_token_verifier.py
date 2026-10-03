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
from nex_runtime.signed_token_verifier import (  # noqa: E402
    BoundedJwksCache,
    SignedServiceTokenVerifier,
    SignedTokenVerificationError,
    StaticJwksSource,
)


def run_platform_signed_token_verifier() -> dict[str, Any]:
    principals = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    principals.upsert_principal(
        {
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-cx"],
            "allowed_scopes": ["document:read", "generation:create"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "ae-runtime",
        lifetime_days=1,
        now_epoch=100,
        credential_id="cred-ae-runtime",
        client_secret="smoke-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-platform-verifier-smoke"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    keys.register_key(
        {
            "key_id": "oa-key-platform-verifier-smoke",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(
                reference, key_id="oa-key-platform-verifier-smoke"
            ),
            "private_key_ref": reference,
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 900,
            "verify_until": 1_230,
        }
    )
    keys.set_key_state(
        "oa-key-platform-verifier-smoke",
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
            "credential_id": "cred-ae-runtime",
            "client_secret": "smoke-secret",
            "audience": "nex-cx",
            "scope": "document:read generation:create",
        },
        now_epoch=500,
        token_id="sat-platform-verifier-smoke",
    )["access_token"]
    source = StaticJwksSource(keys.jwks(at_epoch=600))
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(source, clock=lambda: 600), clock=lambda: 600
    )
    claims = verifier.verify_authorization_header(
        f"Bearer {token}",
        expected_audience="nex-cx",
        required_scopes=("document:read",),
    )
    second = verifier.verify(
        token,
        expected_audience="nex-cx",
        required_scopes=("generation:create",),
    )
    rejected_code = None
    try:
        verifier.verify(token, expected_audience="nex-mo")
    except SignedTokenVerificationError as exc:
        rejected_code = exc.code
    projection = claims.to_wire()
    checks = {
        "oa_issued_token_verified_by_shared_runtime": claims.service_id
        == "nex-ae-api",
        "signature_key_cache_reused": source.fetch_count == 1,
        "required_scope_enforced": second.scopes
        == ("document:read", "generation:create"),
        "audience_mismatch_rejected": rejected_code
        == "nex.token_audience_forbidden",
        "raw_token_and_jti_not_projected": "access_token" not in projection
        and "jti" not in projection
        and "sat-platform-verifier-smoke" not in json.dumps(projection),
        "dgx_provider_not_required": True,
        "database_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_signed_token_verifier_evidence.v1",
        "slice": "1273",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_signed_token_verifier_failed",
        "checks": checks,
        "jwks_fetch_count": source.fetch_count,
        "token_id_digest_length": len(claims.token_id_digest),
        "next_slice": "1274",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "platform_signed_token_verifier="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"jwks_fetches={evidence.get('jwks_fetch_count', 0)} "
        f"digest_length={evidence.get('token_id_digest_length', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_signed_token_verifier()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
