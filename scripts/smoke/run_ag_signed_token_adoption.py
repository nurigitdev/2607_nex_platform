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
sys.path.insert(0, str(ROOT / "services/nex-ag"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_ag.service_auth import authorize_ag_service_request  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt  # noqa: E402
from nex_runtime import (  # noqa: E402
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)


OUTBOUND_CLIENT_MODULES = {
    "artifact_operations.py",
    "generation_audit.py",
    "generation_remediation_handoff.py",
    "job_control.py",
    "readiness.py",
    "service_log_retention.py",
}
DUAL_ADMIN_MODULES = {
    "audit_evidence_api.py",
    "audit_retention_operations.py",
    "federated_operator_operations.py",
    "mvp_acceptance_api.py",
    "operator_reviews.py",
}


def run_ag_signed_token_adoption(root: Path = ROOT) -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    reference = "memory://oa-key-ag-adoption-smoke"
    signer.generate_key(reference)
    key_id = "oa-key-ag-adoption-smoke"
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": key_id},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-oa",
            "aud": "nex-ag",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-ag-adoption-smoke",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-oa",
            "credential_id": "cred-oa-runtime",
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
        expected_audience="nex-ag",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: 600,
    )

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_ag_service_request(request, authorization)
        return denied or {"authorized": True}

    client = TestClient(app)
    signed_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {token}"}
    )
    mock = issue_mock_service_token(
        service_id="nex-oa", audience="nex-ag"
    ).access_token
    mock_response = client.get(
        "/guard", headers={"Authorization": f"Bearer {mock}"}
    )

    package = root / "services/nex-ag/nex_ag"
    sources = {
        path.name: path.read_text(encoding="utf-8") for path in package.glob("*.py")
    }
    legacy_validator_files = sorted(
        name for name, source in sources.items()
        if "validate_authorization_header" in source
    )
    mock_issuer_files = sorted(
        name for name, source in sources.items()
        if "issue_mock_service_token" in source
    )
    outbound_modules = {
        name for name, source in sources.items()
        if "resolve_ag_outbound_service_token" in source
        and name != "service_auth.py"
    }
    dual_admin_modules = {
        name for name, source in sources.items()
        if "authorize_ag_service_or_admin_request" in source
        and name != "service_auth.py"
    }
    serialized = json.dumps(
        {"signed": signed_response.json(), "mock": mock_response.json()},
        sort_keys=True,
    )
    checks = {
        "ag_signed_service_token_accepted": signed_response.status_code == 200,
        "ag_signed_only_rejects_mock": mock_response.status_code == 401
        and mock_response.json().get("error_code") == "nex.mock_token_forbidden",
        "ag_main_wires_shared_admission": (
            "service_token_admission=SERVICE_TOKEN_ADMISSION"
            in sources.get("main.py", "")
        ),
        "no_direct_ag_legacy_validator": not legacy_validator_files,
        "mock_compatibility_is_centralized": mock_issuer_files == ["service_auth.py"],
        "all_ag_outbound_clients_use_profile_resolver": (
            outbound_modules == OUTBOUND_CLIENT_MODULES
        ),
        "admin_user_paths_use_dual_guard": dual_admin_modules == DUAL_ADMIN_MODULES,
        "raw_tokens_not_projected": token not in serialized and mock not in serialized,
        "dgx_provider_not_required": True,
        "database_not_required": True,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "ag_signed_token_adoption_evidence.v1",
        "slice": "1278",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ag_signed_token_adoption_failed",
        "checks": checks,
        "legacy_validator_file_count": len(legacy_validator_files),
        "outbound_client_count": len(outbound_modules),
        "dual_admin_module_count": len(dual_admin_modules),
        "next_slice": "1279",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "ag_signed_token_adoption="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"outbound={evidence.get('outbound_client_count', 0)} "
        f"admin={evidence.get('dual_admin_module_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_signed_token_adoption()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
