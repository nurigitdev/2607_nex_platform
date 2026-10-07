#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-oa"))

from nex_oa.openbao_transit_keys import (
    OpenBaoTransitKeyProvisioner,
    register_openbao_transit_key_version,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.signed_token_repository import (
    InMemoryOaSignedTokenRepository,
)
from nex_oa.signing_key_service import OaSigningKeyService

SCHEMA_VERSION = "oa_openbao_transit_key_lifecycle_evidence.v1"


class _ProvisioningTransport:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.requests: list[tuple[str, str]] = []

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path))
        if path == "/v1/auth/approle/login":
            return {"auth": {"client_token": "operator-token-12345678"}}
        if method == "GET":
            pem = self.key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii")
            return {
                "data": {
                    "type": "rsa-3072",
                    "supports_signing": True,
                    "derived": False,
                    "exportable": False,
                    "allow_plaintext_backup": False,
                    "latest_version": 1,
                    "keys": {"1": {"public_key": pem}},
                }
            }
        return {}


def run_oa_openbao_transit_key_lifecycle() -> dict[str, Any]:
    transport = _ProvisioningTransport()
    provisioner = OpenBaoTransitKeyProvisioner.authenticate(
        transport,
        role_id="operator-role-12345678",
        secret_id="operator-secret-12345678",
    )
    repository = InMemoryOaSignedTokenRepository()
    service = OaSigningKeyService(
        repository=repository,
        deployment_profile="production",
    )
    version = provisioner.provision_rsa3072("oa-signing")
    response = register_openbao_transit_key_version(
        provisioner,
        service,
        key_name="oa-signing",
        key_version=version,
        key_id="oa-key-s144-v1",
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=100,
        activate_at=430,
        sign_until=800,
        verify_until=1_130,
    )
    stored = repository.get_signing_key("oa-key-s144-v1")
    jwks = service.jwks(at_epoch=200)
    provisioner.close()

    wire = response["signing_key"]
    public_jwk = deepcopy(wire["public_jwk"])
    checks = {
        "operator_approle_is_separate": transport.requests[0][1]
        == "/v1/auth/approle/login",
        "rsa3072_key_created": transport.requests[1][1]
        == "/v1/transit/keys/oa-signing",
        "key_policy_read_back": sum(
            path == "/v1/transit/keys/oa-signing" for _, path in transport.requests
        )
        == 3,
        "version_is_exact": version == 1,
        "custody_reference_is_opaque": stored["private_key_ref"]
        == "vault://openbao/transit/keys/oa-signing/versions/1",
        "public_jwk_is_rsa": public_jwk.get("kty") == "RSA"
        and public_jwk.get("alg") == "RS256",
        "public_jwk_is_complete": set(public_jwk)
        == {"kty", "use", "alg", "kid", "n", "e"},
        "private_jwk_material_absent": not {
            "d",
            "p",
            "q",
            "dp",
            "dq",
            "qi",
            "oth",
        }.intersection(public_jwk),
        "custody_reference_not_exposed": "private_key_ref" not in wire,
        "prepublished_jwks_available": jwks["keys"] == [public_jwk],
        "operator_token_revoked": transport.requests[-1][1]
        == "/v1/auth/token/revoke-self",
        "live_openbao_not_contacted": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1436",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [] if passed else [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "request_count": len(transport.requests),
            "key_version": version,
            "jwks_key_count": jwks["key_count"],
        },
        "decision": {
            "runtime_has_provisioning_permission": False,
            "private_key_export_allowed": False,
            "database_private_material_allowed": False,
            "live_openbao_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1437" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_transit_key_lifecycle=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_transit_key_lifecycle=pass "
        f"checks={summary.get('check_count', 0)}/12 "
        f"requests={summary.get('request_count', 0)} "
        f"version={summary.get('key_version')} "
        f"jwks={summary.get('jwks_key_count')} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_openbao_transit_key_lifecycle()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
