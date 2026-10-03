from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.service_auth import (
    AeOutboundServiceTokenError,
    resolve_ae_outbound_service_token,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
    issue_mock_user_token,
)
from nex_runtime.compatibility import register_generation_compatibility_routes
from nex_runtime.recovery import register_generation_recovery_policy_routes


REFERENCE = "memory://oa-key-ae-adoption"
KEY_ID = "oa-key-ae-adoption"


@pytest.fixture(scope="module")
def signed_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    claims = {
        "iss": "urn:nex-platform:oa",
        "sub": "service:nex-cx",
        "aud": "nex-ae-api",
        "iat": 500,
        "nbf": 500,
        "exp": 800,
        "jti": "sat-ae-adoption",
        "token_use": "service_access",
        "scope": "service:call",
        "service_id": "nex-cx",
        "credential_id": "cred-cx-runtime",
        "credential_revision": 1,
    }
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims=claims,
        private_key_ref=REFERENCE,
        signing_provider=signer,
    )
    verifier = SignedServiceTokenVerifier(
        BoundedJwksCache(
            StaticJwksSource(
                {
                    "issuer": "urn:nex-platform:oa",
                    "keys": [signer.public_jwk(REFERENCE, key_id=KEY_ID)],
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
    return {"token": token, "admission": admission}


def _facade_client(admission: ServiceTokenAdmissionRuntime) -> TestClient:
    app = FastAPI()
    app.state.service_token_admission = admission

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        return result.to_wire() if hasattr(result, "to_wire") else result

    return TestClient(app)


def test_ae_facade_accepts_signed_service_and_preserves_browser_user(
    signed_runtime: dict[str, Any]
) -> None:
    client = _facade_client(signed_runtime["admission"])
    service = client.get(
        "/guard",
        headers={"Authorization": f"Bearer {signed_runtime['token']}"},
    )
    user = issue_mock_user_token(tenant_id="tenant-a", user_id="user-a")
    browser = client.get(
        "/guard", headers={"Authorization": f"Bearer {user.access_token}"}
    )

    assert service.status_code == 200
    assert service.json()["auth_mode"] == "service"
    assert service.json()["service_id"] == "nex-cx"
    assert browser.status_code == 200
    assert browser.json()["auth_mode"] == "browser_user"


def test_ae_signed_only_rejects_mock_and_does_not_fall_through_to_user_auth(
    signed_runtime: dict[str, Any]
) -> None:
    client = _facade_client(signed_runtime["admission"])
    mock = issue_mock_service_token(service_id="nex-cx", audience="nex-ae-api")

    response = client.get(
        "/guard", headers={"Authorization": f"Bearer {mock.access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.mock_token_forbidden"


def test_shared_ae_routes_use_app_admission_runtime(
    signed_runtime: dict[str, Any]
) -> None:
    app = FastAPI()
    app.state.service_token_admission = signed_runtime["admission"]
    register_generation_compatibility_routes(app, expected_audience="nex-ae-api")
    register_generation_recovery_policy_routes(app, expected_audience="nex-ae-api")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {signed_runtime['token']}"}

    compatibility = client.get(
        "/api/v1/compatibility/generation-rules", headers=headers
    )
    recovery = client.get("/api/v1/recovery/generation-policies", headers=headers)

    assert compatibility.status_code == 200
    assert recovery.status_code == 200


def test_ae_outbound_token_resolution_has_no_signed_profile_mock_fallback() -> None:
    assert resolve_ae_outbound_service_token(
        "signed-token", audience="nex-cx", environ={}
    ) == "signed-token"
    mock = resolve_ae_outbound_service_token(
        None,
        audience="nex-cx",
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    )
    assert mock.startswith("nex-mock-service.")
    assert resolve_ae_outbound_service_token(
        None,
        audience="nex-cx",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_AE_TO_CX_SERVICE_TOKEN": "signed-from-env",
        },
    ) == "signed-from-env"
    assert resolve_ae_outbound_service_token(
        None,
        audience="nex-oa",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-signed-from-env",
        },
    ) == "oa-signed-from-env"

    for configured, audience, environ, code in (
        (" bad ", "nex-cx", {}, "ae.outbound_service_token_invalid"),
        (None, "nex-cx", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"}, "ae.outbound_service_token_missing"),
        (None, "nex-cx", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "wrong"}, "ae.service_token_rollout_profile_invalid"),
        (None, "external", {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ"}, "ae.outbound_service_token_missing"),
    ):
        with pytest.raises(AeOutboundServiceTokenError) as exc:
            resolve_ae_outbound_service_token(
                configured, audience=audience, environ=environ
            )
        assert exc.value.error_code == code
        assert "signed-from-env" not in str(exc.value)


def test_request_without_injected_runtime_keeps_explicit_test_mock_compatibility() -> None:
    app = FastAPI()

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        return result.to_wire() if hasattr(result, "to_wire") else result

    mock = issue_mock_service_token(service_id="nex-cx", audience="nex-ae-api")
    response = TestClient(app).get(
        "/guard", headers={"Authorization": f"Bearer {mock.access_token}"}
    )
    assert response.status_code == 200
    assert response.json()["auth_mode"] == "service"
