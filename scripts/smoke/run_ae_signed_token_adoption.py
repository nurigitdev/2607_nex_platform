#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-ae-api"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_ae_api.route_auth import authorize_ae_facade_route_request  # noqa: E402
from nex_ae_api.service_auth import (  # noqa: E402
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
    issue_mock_user_token,
)


def run_ae_signed_token_adoption(root: Path = ROOT) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-ae-adoption-smoke"
    signer.generate_key(reference)
    key_id = "oa-key-ae-adoption-smoke"
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": key_id},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-cx",
            "aud": "nex-ae-api",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-ae-adoption-smoke",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-cx",
            "credential_id": "cred-cx-runtime",
            "credential_revision": 1,
        },
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
    admission = ServiceTokenAdmissionRuntime(
        expected_audience="nex-ae-api",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: 600,
    )
    app = FastAPI()
    app.state.service_token_admission = admission

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        return result.to_wire() if hasattr(result, "to_wire") else result

    client = TestClient(app)
    signed_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {token}"}
    )
    mock = issue_mock_service_token(
        service_id="nex-cx", audience="nex-ae-api"
    ).access_token
    mock_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {mock}"}
    )
    user = issue_mock_user_token(tenant_id="tenant-a", user_id="user-a").access_token
    user_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {user}"}
    )
    outbound = resolve_ae_outbound_service_token(
        None,
        audience="nex-cx",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_AE_TO_CX_SERVICE_TOKEN": "signed-outbound-smoke",
        },
    )
    missing_outbound_code = None
    try:
        resolve_ae_outbound_service_token(
            None,
            audience="nex-cx",
            environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
        )
    except AeOutboundServiceTokenError as exc:
        missing_outbound_code = exc.error_code
    package = root / "services/nex-ae-api/nex_ae_api"
    sources = {
        path.name: path.read_text(encoding="utf-8") for path in package.glob("*.py")
    }
    direct_mock_files = sorted(
        name
        for name, text in sources.items()
        if "issue_mock_service_token" in text and name != "service_auth.py"
    )
    direct_validator_files = sorted(
        name for name, text in sources.items() if "validate_authorization_header" in text
    )
    main_text = sources.get("main.py", "")
    serialized = json.dumps(
        {
            "signed": signed_response.json(),
            "mock": mock_response.json(),
            "user": user_response.json(),
        },
        sort_keys=True,
    )
    checks = {
        "ae_signed_service_token_accepted": signed_response.status_code == 200
        and signed_response.json().get("service_id") == "nex-cx",
        "ae_signed_only_rejects_mock": mock_response.status_code == 401
        and mock_response.json().get("error_code") == "nex.mock_token_forbidden",
        "browser_user_path_preserved": user_response.status_code == 200
        and user_response.json().get("auth_mode") == "browser_user",
        "ae_main_wires_shared_admission": "service_token_admission=SERVICE_TOKEN_ADMISSION"
        in main_text,
        "no_direct_ae_mock_fallback": not direct_mock_files,
        "no_direct_ae_legacy_validator": not direct_validator_files,
        "signed_outbound_token_selected": outbound == "signed-outbound-smoke",
        "missing_signed_outbound_token_fails_closed": missing_outbound_code
        == "ae.outbound_service_token_missing",
        "raw_tokens_not_projected": token not in serialized
        and mock not in serialized
        and user not in serialized,
        "dgx_provider_not_required": True,
        "database_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "ae_signed_token_adoption_evidence.v1",
        "slice": "1275",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_signed_token_adoption_failed",
        "checks": checks,
        "direct_mock_file_count": len(direct_mock_files),
        "direct_validator_file_count": len(direct_validator_files),
        "next_slice": "1276",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "ae_signed_token_adoption="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"mock_files={evidence.get('direct_mock_file_count', 0)} "
        f"validators={evidence.get('direct_validator_file_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_signed_token_adoption()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
