#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402
from nex_runtime.app import SERVICE_SPECS, build_service_app  # noqa: E402
from nex_runtime.auth import issue_mock_service_token  # noqa: E402
from nex_runtime.service_token_admission import (  # noqa: E402
    ServiceTokenAdmissionRuntime,
)
from nex_runtime.signed_token_verifier import (  # noqa: E402
    BoundedJwksCache,
    SignedServiceTokenVerifier,
    StaticJwksSource,
)


class _ActiveIntrospector:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.call_count = 0

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> Mapping[str, Any]:
        self.call_count += 1
        return self.response


def run_platform_service_token_admission() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-admission-smoke"
    signer.generate_key(reference)
    key_id = "oa-key-admission-smoke"
    jti = "sat-admission-smoke"
    claims = {
        "iss": "urn:nex-platform:oa",
        "sub": "service:nex-ae-api",
        "aud": "nex-cx",
        "iat": 500,
        "nbf": 500,
        "exp": 800,
        "jti": jti,
        "token_use": "service_access",
        "scope": "service:call document:read",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-runtime",
        "credential_revision": 1,
    }
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": key_id},
        claims=claims,
        private_key_ref=reference,
        signing_provider=signer,
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [signer.public_jwk(reference, key_id=key_id)],
                }
            ),
            clock=lambda: 600,
        ),
        clock=lambda: 600,
    )
    introspector = _ActiveIntrospector(
        {
            "introspection_schema_version": "oa_token_introspection.v1",
            "active": True,
            "token_use": "service_access",
            "sub": claims["sub"],
            "aud": claims["aud"],
            "scope": claims["scope"],
            "service_id": claims["service_id"],
            "credential_id": claims["credential_id"],
            "credential_revision": claims["credential_revision"],
            "token_id_digest": sha256(jti.encode("utf-8")).hexdigest(),
            "iat": claims["iat"],
            "exp": claims["exp"],
        }
    )
    admission = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        introspector=introspector,
        clock=lambda: 600,
    )
    client = TestClient(
        build_service_app(
            SERVICE_SPECS["nex-cx"], service_token_admission=admission
        )
    )
    read_response = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {token}"},
    )
    sensitive = admission.admit(
        f"Bearer {token}",
        required_scopes=("document:read",),
        route_class="WRITE",
        now_epoch=600,
    )
    mock = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-cx"
    ).access_token
    mock_response = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {mock}"},
    )
    read_body = read_response.json()
    serialized = json.dumps(
        {"read": read_body, "sensitive": sensitive.to_wire()}, sort_keys=True
    )
    checks = {
        "fastapi_read_admission_uses_signed_token": read_response.status_code == 200
        and read_body.get("claims", {}).get("token_kind") == "SIGNED",
        "read_path_uses_local_verification": read_body.get("claims", {}).get(
            "introspection_status"
        )
        == "NOT_REQUIRED",
        "sensitive_path_requires_active_introspection": sensitive.introspection_status
        == "ACTIVE"
        and introspector.call_count == 1,
        "signed_only_rejects_mock": mock_response.status_code == 401
        and mock_response.json().get("error_code") == "nex.mock_token_forbidden",
        "raw_token_and_jti_not_projected": token not in serialized
        and jti not in serialized
        and "jti" not in serialized,
        "dgx_provider_not_required": True,
        "database_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_service_token_admission_evidence.v1",
        "slice": "1274",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_service_token_admission_failed",
        "checks": checks,
        "read_http_status": read_response.status_code,
        "mock_http_status": mock_response.status_code,
        "introspection_call_count": introspector.call_count,
        "next_slice": "1275",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "platform_service_token_admission="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"read={evidence.get('read_http_status', 0)} "
        f"mock={evidence.get('mock_http_status', 0)} "
        f"introspection={evidence.get('introspection_call_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_service_token_admission()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
