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

from nex_oa.federated_identities import build_federation_provider, OaFederationError  # noqa: E402
from nex_oa.oidc_verifier import (  # noqa: E402
    OidcDiscoveryJwksCache,
    OidcIdTokenVerifier,
    StaticOidcDocumentSource,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402


def run_oa_oidc_verifier() -> dict[str, Any]:
    now = 1_800_000_000
    issuer = "https://id.example.test"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    jwks_url = f"{issuer}/jwks"
    provider = build_federation_provider(
        {
            "provider_id": "company-oidc",
            "issuer": issuer,
            "client_id": "nex-platform",
            "discovery_url": discovery_url,
            "display_name": "Company OIDC",
        }
    )
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key("memory://oidc-key")
    source = StaticOidcDocumentSource(
        {
            discovery_url: {
                "issuer": issuer,
                "jwks_uri": jwks_url,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            jwks_url: {"keys": [jwk]},
        }
    )
    cache = OidcDiscoveryJwksCache(provider, source)
    verifier = OidcIdTokenVerifier(provider, cache)
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "JWT", "kid": jwk["kid"]},
        claims={
            "iss": issuer,
            "sub": "opaque-external-subject",
            "aud": "nex-platform",
            "iat": now,
            "exp": now + 300,
            "nonce": "browser-nonce",
        },
        private_key_ref="memory://oidc-key",
        signing_provider=signer,
    )
    verified = verifier.verify(token, expected_nonce="browser-nonce", now_epoch=now)
    projection = verified.safe_projection()
    rejection = _error_code(
        lambda: verifier.verify(token, expected_nonce="wrong-nonce", now_epoch=now)
    )
    serialized = json.dumps(projection, sort_keys=True).lower()
    checks = {
        "rs256_verified": projection["verification_schema_version"] == "oa_oidc_verification.v1",
        "issuer_exact": projection["issuer"] == issuer,
        "audience_exact": projection["audiences"] == ("nex-platform",),
        "nonce_bound": rejection == "oa.oidc_nonce_invalid",
        "subject_digest_only": len(projection["external_subject_digest"]) == 64 and "opaque-external-subject" not in serialized,
        "nonce_digest_only": len(projection["nonce_digest"]) == 64 and "browser-nonce" not in serialized,
        "raw_token_absent": token not in serialized and projection["raw_id_token_included"] is False,
        "bounded_fetch": source.fetches == [discovery_url, jwks_url],
        "cache_redacted": cache.safe_snapshot()["key_ids_included"] is False,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_oidc_verifier_evidence.v1",
        "slice": "1285",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_oidc_verifier_failed",
        "checks": checks,
        "verification": projection,
        "cache": cache.safe_snapshot(),
        "fetch_count": len(source.fetches),
        "next_slice": "1286" if passed else "blocked",
    }


def _error_code(action: Any) -> str | None:
    try:
        action()
    except OaFederationError as exc:
        return exc.error_code
    return None


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "oa_oidc_verifier="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"fetches={evidence.get('fetch_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_oidc_verifier()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
