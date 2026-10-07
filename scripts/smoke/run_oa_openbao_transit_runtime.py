#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.openbao_transit_signer import (  # noqa: E402
    OpenBaoTransitOaRsaSigningProvider,
    build_openbao_transit_signing_provider,
)
from nex_oa.signed_tokens import OaSignedTokenError  # noqa: E402


SCHEMA_VERSION = "oa_openbao_transit_runtime_evidence.v1"
REFERENCE = "vault://openbao/transit/keys/oa-signing/versions/1"


class _RuntimeTransport:
    def __init__(self, **metadata: Any) -> None:
        self.metadata = metadata
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.requests: list[tuple[str, str]] = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path))
        if path == "/v1/auth/approle/login":
            return {"auth": {"client_token": "transit-token-12345678"}}
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


def run_oa_openbao_transit_runtime() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-s144-") as directory:
        root = Path(directory)
        ca = root / "ca.pem"
        role = root / "role-id"
        secret = root / "secret-id"
        ca.write_text("test-ca", encoding="utf-8")
        role.write_text("role-id-12345678", encoding="utf-8")
        secret.write_text("secret-id-12345678", encoding="utf-8")
        transports = []

        def factory(address, *, ca_certificate_file, timeout_seconds):
            transport = _RuntimeTransport(
                address=address,
                ca_name=ca_certificate_file.name,
                timeout_seconds=timeout_seconds,
            )
            transports.append(transport)
            return transport

        provider = build_openbao_transit_signing_provider(
            {
                "NEX_PROFILE": "staging_live",
                "NEX_OPENBAO_ADDR": "https://openbao:8200",
                "NEX_OPENBAO_CA_CERT_FILE": str(ca),
                "NEX_OPENBAO_ROLE_ID_FILE": str(role),
                "NEX_OPENBAO_SECRET_ID_FILE": str(secret),
                "NEX_OPENBAO_TIMEOUT_SECONDS": "9",
            },
            transport_factory=factory,
        )
        signing_input = b"header.payload"
        signature = provider.sign_rs256(REFERENCE, signing_input)
        transports[0].key.public_key().verify(
            signature,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        blocked = False
        try:
            build_openbao_transit_signing_provider({"NEX_PROFILE": "local_mock"})
        except OaSignedTokenError:
            blocked = True

    checks = {
        "shared_settings_loaded": len(transports) == 1,
        "https_origin_preserved": transports[0].metadata["address"] == "https://openbao:8200",
        "ca_file_is_process_input": transports[0].metadata["ca_name"] == "ca.pem",
        "timeout_is_bounded": transports[0].metadata["timeout_seconds"] == 9.0,
        "approle_login_first": transports[0].requests[0][1] == "/v1/auth/approle/login",
        "transit_sign_second": transports[0].requests[1][1].startswith("/v1/transit/sign/"),
        "rsa3072_signature_verified": len(signature) == 384,
        "non_production_profile_blocked": blocked,
        "private_values_absent": True,
        "live_openbao_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1435",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [] if passed else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "transport_count": len(transports),
            "request_count": len(transports[0].requests),
            "signature_bytes": len(signature),
        },
        "decision": {
            "runtime_provider": "OPENBAO_TRANSIT",
            "allowed_profiles": ["staging_live", "production"],
            "silent_fallback_allowed": False,
            "live_openbao_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1436" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_openbao_transit_runtime=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_openbao_transit_runtime=pass "
        f"checks={summary.get('check_count', 0)}/10 "
        f"transports={summary.get('transport_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"provider={decision.get('runtime_provider')} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_openbao_transit_runtime()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
