from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from hashlib import sha256
import pytest

from nex_oa.service_auth import (
    authenticated_oa_service_claims,
    authorize_oa_service_request,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
    issue_mock_service_token,
)


NOW = 1_800_000_000
REFERENCE = "memory://s134-oa-admission"


class Introspector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def introspect(self, token, *, expected_audience, required_scopes):
        scopes = tuple(required_scopes)
        self.calls.append((token, expected_audience, scopes))
        return {
            "active": True,
            "introspection_schema_version": "oa_token_introspection.v1",
            "sub": "service:nex-ae-api",
            "aud": expected_audience,
            "service_id": "nex-ae-api",
            "scope": " ".join(scopes),
            "token_use": "service_access",
            "credential_id": "cred-s134",
            "credential_revision": 1,
            "iat": NOW - 1,
            "exp": NOW + 60,
            "token_id_digest": sha256(b"token-s134").hexdigest(),
        }


def _signed_token(scopes=("service:call",)) -> tuple[str, dict]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    jwk = signer.public_jwk(REFERENCE, key_id="key-s134")
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": "key-s134"},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-ae-api",
            "aud": "nex-oa",
            "service_id": "nex-ae-api",
            "scope": " ".join(scopes),
            "token_use": "service_access",
            "credential_id": "cred-s134",
            "credential_revision": 1,
            "jti": "token-s134",
            "iat": NOW - 1,
            "nbf": NOW - 1,
            "exp": NOW + 60,
        },
        private_key_ref=REFERENCE,
        signing_provider=signer,
    )
    return token, jwk


def _client(*, signed: bool) -> tuple[TestClient, Introspector | None]:
    app = FastAPI()
    introspector = None
    if signed:
        token, jwk = _signed_token()
        introspector = Introspector()
        app.state.token = token
        app.state.service_token_admission = ServiceTokenAdmissionRuntime(
            expected_audience="nex-oa",
            rollout_profile="SIGNED_ONLY",
            signed_verifier=SignedServiceTokenVerifier(
                BoundedJwksCache(
                    StaticJwksSource(
                        {"issuer": "urn:nex-platform:oa", "keys": [jwk]}
                    ),
                    clock=lambda: NOW,
                ),
                clock=lambda: NOW,
            ),
            introspector=introspector,
            clock=lambda: NOW,
        )

    @app.get("/protected")
    def protected(request: Request, authorization: str | None = Header(default=None)):
        problem = authorize_oa_service_request(request, authorization)
        if isinstance(problem, JSONResponse):
            return problem
        claims = authenticated_oa_service_claims(request)
        return {"service_id": claims.service_id, "introspection": claims.introspection_status}

    return TestClient(app), introspector


def test_signed_oa_admission_requires_scope_and_introspection() -> None:
    client, introspector = _client(signed=True)
    token = client.app.state.token

    accepted = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert accepted.status_code == 200
    assert accepted.json() == {"service_id": "nex-ae-api", "introspection": "ACTIVE"}
    assert introspector is not None
    assert introspector.calls == [(token, "nex-oa", ("service:call",))]


def test_signed_oa_admission_fails_closed_for_missing_token() -> None:
    client, _ = _client(signed=True)

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.authorization_missing"


def test_oa_admission_retains_test_mock_compatibility() -> None:
    client, _ = _client(signed=False)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa")

    response = client.get(
        "/protected", headers={"Authorization": f"Bearer {token.access_token}"}
    )

    assert response.status_code == 200
    assert response.json()["service_id"] == "nex-ae-api"


def test_authenticated_claims_requires_prior_admission() -> None:
    app = FastAPI()

    @app.get("/claims")
    def claims(request: Request):
        with pytest.raises(ValueError, match="validated OA service claim"):
            authenticated_oa_service_claims(request)
        return {"ok": True}

    assert TestClient(app).get("/claims").json() == {"ok": True}
