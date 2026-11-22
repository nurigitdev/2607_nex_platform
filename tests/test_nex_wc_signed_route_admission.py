from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)
from nex_wc.coordination_api import register_coordination_routes
from nex_wc.work_item_api import register_work_item_routes

_KEY_REF = "memory://wc-signed-route-admission"
_KEY_ID = "wc-signed-route-admission"
_WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"


class _WorkItems:
    def create(self, payload):
        return {
            "created": True,
            "work_item": {"work_item_id": _WORK_ITEM_ID, "payload": payload},
        }

    def get(self, *, tenant_id, work_item_id):
        return {"tenant_id": tenant_id, "work_item_id": work_item_id}

    def status(self, *, tenant_id, work_item_id):
        return {
            "tenant_id": tenant_id,
            "work_item_id": work_item_id,
            "state": "CREATED",
        }


class _Coordination:
    def route(self, *, tenant_id, work_item_id, expected_version):
        return {
            "tenant_id": tenant_id,
            "work_item_id": work_item_id,
            "expected_version": expected_version,
            "state": "ROUTED",
        }

    def claim(self, *, tenant_id, work_item_id, expected_version):
        return {
            "tenant_id": tenant_id,
            "work_item_id": work_item_id,
            "expected_version": expected_version,
            "state": "ASSIGNED",
        }


def _signed_client() -> tuple[TestClient, str]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(_KEY_REF)
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": _KEY_ID},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-ae-api",
            "aud": "nex-wc",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-wc-signed-routes",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-ae-api",
            "credential_id": "cred-ae-wc-routes",
            "credential_revision": 1,
        },
        private_key_ref=_KEY_REF,
        signing_provider=signer,
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [signer.public_jwk(_KEY_REF, key_id=_KEY_ID)],
                }
            ),
            clock=lambda: 600,
        ),
        clock=lambda: 600,
    )
    app = FastAPI()
    app.state.service_token_admission = ServiceTokenAdmissionRuntime(
        expected_audience="nex-wc",
        rollout_profile="SIGNED_ONLY",
        signed_verifier=verifier,
        clock=lambda: 600,
    )
    register_work_item_routes(app, service=_WorkItems())  # type: ignore[arg-type]
    register_coordination_routes(app, service=_Coordination())  # type: ignore[arg-type]
    return TestClient(app), token


def test_wc_work_item_and_coordination_routes_admit_signed_service_token() -> None:
    client, token = _signed_client()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-NeX-Tenant-Id": "tenant-signed",
    }

    created = client.post("/api/v1/work-items", headers=headers, json={"goal": "x"})
    routed = client.post(
        f"/api/v1/work-items/{_WORK_ITEM_ID}/route",
        headers=headers,
        json={"expected_version": 1},
    )

    assert created.status_code == 201
    assert created.json()["work_item"]["work_item_id"] == _WORK_ITEM_ID
    assert routed.status_code == 200
    assert routed.json()["state"] == "ROUTED"


def test_wc_signed_only_routes_reject_mock_fallback() -> None:
    client, _ = _signed_client()
    mock = issue_mock_service_token(service_id="nex-ae-api", audience="nex-wc")

    response = client.post(
        "/api/v1/work-items",
        headers={"Authorization": f"Bearer {mock.access_token}"},
        json={},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.mock_token_forbidden"
