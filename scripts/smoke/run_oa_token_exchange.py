#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository  # noqa: E402
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402


def run_oa_token_exchange() -> dict[str, Any]:
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
    reference = "file:///tmp/oa-key-token-smoke"
    signer.generate_key(reference)
    public_jwk = signer.public_jwk(reference, key_id="oa-key-token-smoke")
    key_service = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    key_service.register_key(
        {
            "key_id": "oa-key-token-smoke",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": public_jwk,
            "private_key_ref": reference,
            "published_at": 100,
            "activate_at": 430,
            "sign_until": 900,
            "verify_until": 1_230,
        }
    )
    key_service.set_key_state(
        "oa-key-token-smoke",
        target_state="ACTIVE",
        expected_revision=1,
        now_epoch=430,
    )
    response = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=key_service,
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
        token_id="sat-smoke",
    )
    header, claims, signing_input, signature = _parts(response["access_token"])
    public_key = rsa.RSAPublicNumbers(
        e=_integer(public_jwk["e"]), n=_integer(public_jwk["n"])
    ).public_key()
    signature_valid = True
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        signature_valid = False
    checks = {
        "rs256_signature_valid": signature_valid,
        "active_kid_used": header.get("kid") == "oa-key-token-smoke",
        "service_subject_bound": claims.get("sub") == "service:nex-cx",
        "credential_lineage_present": claims.get("credential_id") == "cred-cx-runtime",
        "fixed_five_minute_ttl": claims.get("exp") - claims.get("iat") == 300,
        "secret_absent_from_claims": "client_secret" not in claims,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_token_exchange_evidence.v1",
        "slice": "1267",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_token_exchange_failed",
        "checks": checks,
        "algorithm": header.get("alg"),
        "ttl_seconds": response["expires_in"],
        "next_slice": "1268",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_token_exchange="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"alg={evidence.get('algorithm', 'unknown')} "
        f"ttl={evidence.get('ttl_seconds', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_token_exchange()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


def _parts(token: str) -> tuple[dict, dict, bytes, bytes]:
    encoded_header, encoded_claims, encoded_signature = token.split(".")
    return (
        json.loads(_decode(encoded_header)),
        json.loads(_decode(encoded_claims)),
        f"{encoded_header}.{encoded_claims}".encode("ascii"),
        _decode(encoded_signature),
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _integer(value: str) -> int:
    return int.from_bytes(_decode(value), "big")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
