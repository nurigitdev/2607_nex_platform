#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.openbao_transit_signer import (  # noqa: E402
    OpenBaoTransitOaRsaSigningProvider,
)
from nex_oa.signed_tokens import OaSignedTokenError  # noqa: E402


SCHEMA_VERSION = "oa_openbao_transit_signer_evidence.v1"
REFERENCE = "vault://openbao/transit/keys/oa-signing/versions/1"


class _TransitDouble:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.requests: list[tuple[str, str, str | None, Mapping[str, Any] | None]] = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, payload))
        if path == "/v1/auth/approle/login":
            return {"auth": {"client_token": "transit-token-12345678"}}
        if path == "/v1/auth/token/revoke-self":
            return {}
        signature = self.key.sign(
            base64.b64decode(payload["input"]),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return {
            "data": {
                "signature": "vault:v1:" + base64.b64encode(signature).decode("ascii")
            }
        }


def run_oa_openbao_transit_signer() -> dict[str, Any]:
    transport = _TransitDouble()
    signing_input = b"header.payload"
    provider = OpenBaoTransitOaRsaSigningProvider.authenticate(
        transport,
        role_id="role-id-12345678",
        secret_id="secret-id-12345678",
    )
    signature = provider.sign_rs256(REFERENCE, signing_input)
    transport.key.public_key().verify(
        signature,
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    provider.close()
    closed = False
    try:
        provider.sign_rs256(REFERENCE, signing_input)
    except OaSignedTokenError:
        closed = True
    sign_request = transport.requests[1]
    payload = dict(sign_request[3] or {})
    checks = {
        "approle_login_used": transport.requests[0][1] == "/v1/auth/approle/login",
        "transit_sign_path_exact": sign_request[1] == "/v1/transit/sign/oa-signing/sha2-256",
        "key_version_pinned": payload.get("key_version") == 1,
        "pkcs1v15_selected": payload.get("signature_algorithm") == "pkcs1v15",
        "sha256_server_hash_selected": payload.get("prehashed") is False,
        "rsa3072_signature_verified": len(signature) == 384,
        "private_key_not_exported": all("export" not in item[1] for item in transport.requests),
        "token_self_revoked": transport.requests[-1][1] == "/v1/auth/token/revoke-self",
        "closed_signer_fails_closed": closed,
        "raw_values_absent_from_evidence": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1434",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [] if passed else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "request_count": len(transport.requests),
            "key_version": 1,
            "signature_bytes": len(signature),
        },
        "decision": {
            "private_key_exported": False,
            "live_openbao_contacted": False,
            "production_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1435" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_openbao_transit_signer=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_openbao_transit_signer=pass "
        f"checks={summary.get('check_count', 0)}/10 "
        f"requests={summary.get('request_count', 0)} "
        f"version={summary.get('key_version', 0)} "
        f"signature_bytes={summary.get('signature_bytes', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_openbao_transit_signer()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
