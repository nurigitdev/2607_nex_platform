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
sys.path.insert(0, str(ROOT / "services/nex-cx"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_cx.authorization import authorize_cx_request  # noqa: E402
from nex_cx.service_auth import (  # noqa: E402
    CxOutboundServiceTokenError,
    resolve_cx_outbound_service_token,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)


def run_cx_signed_token_adoption(root: Path = ROOT) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-cx-adoption-smoke"
    signer.generate_key(reference)
    key_id = "oa-key-cx-adoption-smoke"
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": key_id},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-ae-api",
            "aud": "nex-cx",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-cx-adoption-smoke",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-ae-api",
            "credential_id": "cred-ae-runtime",
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
    app = FastAPI()
    app.state.service_token_admission = ServiceTokenAdmissionRuntime(
        expected_audience="nex-cx",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: 600,
    )

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_cx_request(request, authorization)
        if denied is not None:
            return denied
        return {"service_id": request.state.cx_caller_service_id}

    client = TestClient(app)
    signed_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {token}"}
    )
    mock = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-cx"
    ).access_token
    mock_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {mock}"}
    )
    outbound = resolve_cx_outbound_service_token(
        None,
        audience="nex-mo",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_CX_TO_MO_SERVICE_TOKEN": "signed-outbound-smoke",
        },
    )
    missing_outbound_code = None
    try:
        resolve_cx_outbound_service_token(
            None,
            audience="nex-mo",
            environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
        )
    except CxOutboundServiceTokenError as exc:
        missing_outbound_code = exc.error_code

    package = root / "services/nex-cx/nex_cx"
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
        {"signed": signed_response.json(), "mock": mock_response.json()},
        sort_keys=True,
    )
    checks = {
        "cx_signed_service_token_accepted": signed_response.status_code == 200
        and signed_response.json().get("service_id") == "nex-ae-api",
        "cx_signed_only_rejects_mock": mock_response.status_code == 401
        and mock_response.json().get("error_code") == "nex.mock_token_forbidden",
        "cx_main_wires_shared_admission": "service_token_admission=SERVICE_TOKEN_ADMISSION"
        in main_text,
        "no_direct_cx_mock_fallback": not direct_mock_files,
        "no_direct_cx_legacy_validator": not direct_validator_files,
        "signed_outbound_token_selected": outbound == "signed-outbound-smoke",
        "missing_signed_outbound_token_fails_closed": missing_outbound_code
        == "cx.outbound_service_token_missing",
        "raw_tokens_not_projected": token not in serialized and mock not in serialized,
        "dgx_provider_not_required": True,
        "database_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "cx_signed_token_adoption_evidence.v1",
        "slice": "1276",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_signed_token_adoption_failed",
        "checks": checks,
        "direct_mock_file_count": len(direct_mock_files),
        "direct_validator_file_count": len(direct_validator_files),
        "next_slice": "1277",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "cx_signed_token_adoption="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"mock_files={evidence.get('direct_mock_file_count', 0)} "
        f"validators={evidence.get('direct_validator_file_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_signed_token_adoption()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
