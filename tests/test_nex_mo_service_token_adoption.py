from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from nex_mo.provider_auth import (
    authenticated_mo_service_actor,
    authorize_mo_service_request,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)


REFERENCE = "memory://oa-key-mo-adoption"
KEY_ID = "oa-key-mo-adoption"


@pytest.fixture(scope="module")
def signed_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-cx",
            "aud": "nex-mo",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-mo-adoption",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-cx",
            "credential_id": "cred-cx-runtime",
            "credential_revision": 1,
        },
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
    return {
        "token": token,
        "admission": ServiceTokenAdmissionRuntime(
            expected_audience="nex-mo",
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            clock=lambda: 600,
        ),
    }


def _client(admission: ServiceTokenAdmissionRuntime) -> TestClient:
    app = FastAPI()
    app.state.service_token_admission = admission

    @app.get("/guard")
    def guard(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_mo_service_request(request, authorization)
        if denied is not None:
            return denied
        return {"actor": authenticated_mo_service_actor(request)}

    return TestClient(app)


def test_mo_guard_accepts_signed_token_and_carries_actor(
    signed_runtime: dict[str, Any],
) -> None:
    response = _client(signed_runtime["admission"]).get(
        "/guard",
        headers={"Authorization": f"Bearer {signed_runtime['token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {"actor": "service:nex-cx"}


def test_mo_signed_only_guard_rejects_mock_without_fallback(
    signed_runtime: dict[str, Any],
) -> None:
    mock = issue_mock_service_token(service_id="nex-cx", audience="nex-mo")
    response = _client(signed_runtime["admission"]).get(
        "/guard", headers={"Authorization": f"Bearer {mock.access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.mock_token_forbidden"


def test_actor_helper_preserves_explicit_test_mock_compatibility() -> None:
    mock = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")

    assert authenticated_mo_service_actor(
        f"Bearer {mock.access_token}"
    ) == "service:nex-ag"
    with pytest.raises(ValueError, match="validated"):
        authenticated_mo_service_actor(None)
