#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from fastapi.testclient import TestClient  # noqa: E402

from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository  # noqa: E402
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_api import register_signed_token_routes  # noqa: E402
from nex_oa.signed_token_repository import InMemoryOaSignedTokenRepository  # noqa: E402
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.token_exchange_service import OaClientCredentialTokenExchangeService  # noqa: E402
from nex_oa.token_signing import InMemoryOaRsaSigningProvider  # noqa: E402
from nex_oa.token_validation_service import OaSignedTokenValidationService  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
)


def run_oa_signed_token_api() -> dict[str, Any]:
    now = int(time())
    principals = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    principals.upsert_principal(
        {
            "principal_id": "cx-api-smoke",
            "service_id": "nex-cx",
            "display_name": "CX API Smoke",
            "allowed_audiences": ["nex-oa", "nex-cx"],
            "allowed_scopes": ["token:introspect", "document:read"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        "cx-api-smoke",
        lifetime_days=1,
        now_epoch=now - 10,
        credential_id="cred-cx-api-smoke",
        client_secret="api-smoke-secret",
    )
    signer = InMemoryOaRsaSigningProvider()
    reference = "file:///tmp/oa-key-api-smoke"
    signer.generate_key(reference)
    keys = OaSigningKeyService(
        repository=InMemoryOaSignedTokenRepository(), deployment_profile="test"
    )
    keys.register_key(
        {
            "key_id": "oa-key-api-smoke",
            "issuer": PRODUCTION_TOKEN_ISSUER,
            "public_jwk": signer.public_jwk(reference, key_id="oa-key-api-smoke"),
            "private_key_ref": reference,
            "published_at": now - 330,
            "activate_at": now,
            "sign_until": now + 600,
            "verify_until": now + 930,
        }
    )
    keys.set_key_state(
        "oa-key-api-smoke", target_state="ACTIVE", expected_revision=1, now_epoch=now
    )
    exchange = OaClientCredentialTokenExchangeService(
        principal_service=principals,
        signing_key_service=keys,
        signing_provider=signer,
    )
    validation = OaSignedTokenValidationService(
        signing_key_service=keys,
        principal_service=principals,
    )
    store = InMemoryOperationalEventStore()
    app = build_service_app(
        SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False
    )
    register_signed_token_routes(
        app,
        token_exchange_service=exchange,
        validation_service=validation,
        signing_key_service=keys,
        audit_emitter=OperationalEventEmitter(service_id="nex-oa", store=store),
    )
    client = TestClient(app)
    issued = client.post(
        "/api/v1/auth/service-token",
        json={
            "grant_type": "client_credentials",
            "credential_id": "cred-cx-api-smoke",
            "client_secret": "api-smoke-secret",
            "audience": "nex-cx",
            "scope": "document:read",
        },
    )
    caller = exchange.exchange(
        {
            "grant_type": "client_credentials",
            "credential_id": "cred-cx-api-smoke",
            "client_secret": "api-smoke-secret",
            "audience": "nex-oa",
            "scope": "token:introspect",
        }
    )["access_token"]
    token = issued.json().get("access_token", "")
    introspected = client.post(
        "/api/v1/auth/introspect",
        json={"token": token, "audience": "nex-cx"},
        headers={"Authorization": f"Bearer {caller}"},
    )
    jwks = client.get("/.well-known/jwks.json")
    checks = {
        "token_route_uses_rs256_compact_jwt": issued.status_code == 200 and token.count(".") == 2,
        "signed_bearer_protects_introspection": introspected.status_code == 200 and introspected.json().get("active") is True,
        "jwks_exposes_public_key_only": jwks.status_code == 200 and jwks.json().get("key_count") == 1 and "d" not in jwks.json()["keys"][0],
        "audit_excludes_secret_and_token": "api-smoke-secret" not in str(store.events) and token not in str(store.events),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_signed_token_api_evidence.v1",
        "slice": "1269",
        "requirement": "S127",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_signed_token_api_failed",
        "checks": checks,
        "jwks_key_count": jwks.json().get("key_count", 0),
        "introspection_active": introspected.json().get("active", False),
        "next_slice": "1270",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_signed_token_api="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"jwks={evidence.get('jwks_key_count', 0)} "
        f"active={str(evidence.get('introspection_active')).lower()} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_signed_token_api()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
