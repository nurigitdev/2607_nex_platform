from __future__ import annotations

from hashlib import sha256
from typing import Any, Sequence

import pytest
from fastapi.testclient import TestClient

from nex_oa.service_auth import (
    LocalOaJwksSource,
    LocalOaTokenIntrospector,
    build_oa_local_service_token_admission,
)
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    SERVICE_SPECS,
    ServiceTokenAdmissionError,
    build_service_app,
    issue_mock_service_token,
    register_service_token_admission_routes,
)


KEY_REF = "memory://oa-local-admission"
KEY_ID = "oa-local-admission"


class FakeSigningKeyService:
    def __init__(self, jwk: dict[str, Any]) -> None:
        self.jwk = jwk
        self.calls = 0

    def jwks(self) -> dict[str, Any]:
        self.calls += 1
        return {"issuer": "urn:nex-platform:oa", "keys": [self.jwk]}


class FakeValidationService:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "token": token,
                "expected_audience": expected_audience,
                "required_scopes": tuple(required_scopes),
            }
        )
        return self.result


def _signed_material() -> tuple[InMemoryOaRsaSigningProvider, dict[str, Any], str]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(KEY_REF)
    claims = {
        "iss": "urn:nex-platform:oa",
        "sub": "service:nex-ae-api",
        "aud": "nex-oa",
        "iat": 500,
        "nbf": 500,
        "exp": 800,
        "jti": "sat-oa-local",
        "token_use": "service_access",
        "scope": "service:call",
        "service_id": "nex-ae-api",
        "credential_id": "cred-ae-local",
        "credential_revision": 1,
    }
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims=claims,
        private_key_ref=KEY_REF,
        signing_provider=signer,
    )
    return signer, claims, token


def _introspection(claims: dict[str, Any]) -> dict[str, Any]:
    return {
        "introspection_schema_version": "oa_token_introspection.v1",
        "active": True,
        "token_use": claims["token_use"],
        "sub": claims["sub"],
        "aud": claims["aud"],
        "scope": claims["scope"],
        "service_id": claims["service_id"],
        "credential_id": claims["credential_id"],
        "credential_revision": claims["credential_revision"],
        "token_id_digest": sha256(claims["jti"].encode()).hexdigest(),
        "iat": claims["iat"],
        "exp": claims["exp"],
    }


def test_oa_local_signed_admission_uses_local_jwks_and_introspection() -> None:
    signer, claims, token = _signed_material()
    keys = FakeSigningKeyService(signer.public_jwk(KEY_REF, key_id=KEY_ID))
    validation = FakeValidationService(_introspection(claims))
    runtime = build_oa_local_service_token_admission(
        signing_key_service=keys,  # type: ignore[arg-type]
        validation_service=validation,  # type: ignore[arg-type]
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
        clock=lambda: 600,
    )

    admitted = runtime.admit(
        f"Bearer {token}",
        required_scopes=("service:call",),
        route_class="CREDENTIAL",
    )

    assert admitted.service_id == "nex-ae-api"
    assert admitted.introspection_status == "ACTIVE"
    assert keys.calls == 1
    assert validation.calls == [
        {
            "token": token,
            "expected_audience": "nex-oa",
            "required_scopes": ("service:call",),
        }
    ]


def test_oa_local_sources_delegate_without_exposing_secrets() -> None:
    signer, claims, token = _signed_material()
    keys = FakeSigningKeyService(signer.public_jwk(KEY_REF, key_id=KEY_ID))
    validation = FakeValidationService(_introspection(claims))

    assert LocalOaJwksSource(keys).fetch_jwks()["keys"][0]["kid"] == KEY_ID  # type: ignore[arg-type]
    result = LocalOaTokenIntrospector(validation).introspect(  # type: ignore[arg-type]
        token,
        expected_audience="nex-oa",
        required_scopes=("service:call",),
    )
    assert result["active"] is True


def test_oa_local_admission_profiles_fail_closed() -> None:
    mock = build_oa_local_service_token_admission(
        signing_key_service=None,  # type: ignore[arg-type]
        validation_service=None,  # type: ignore[arg-type]
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
        clock=lambda: 600,
    )
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa")
    assert mock.admit(f"Bearer {token.access_token}").token_kind == "MOCK"

    with pytest.raises(ValueError, match="integer"):
        build_oa_local_service_token_admission(
            signing_key_service=None,  # type: ignore[arg-type]
            validation_service=None,  # type: ignore[arg-type]
            environ={
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ",
                "NEX_MOCK_COMPATIBILITY_DEADLINE_EPOCH": "bad",
            },
        )
    with pytest.raises(ValueError, match="legacy mock callers"):
        build_oa_local_service_token_admission(
            signing_key_service=None,  # type: ignore[arg-type]
            validation_service=None,  # type: ignore[arg-type]
            environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ"},
        )


def test_service_admission_routes_can_attach_after_app_construction() -> None:
    app = build_service_app(SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False)
    runtime = build_oa_local_service_token_admission(
        signing_key_service=None,  # type: ignore[arg-type]
        validation_service=None,  # type: ignore[arg-type]
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    )
    app.state.service_token_admission = runtime
    register_service_token_admission_routes(app, spec=SERVICE_SPECS["nex-oa"])
    register_service_token_admission_routes(app, spec=SERVICE_SPECS["nex-oa"])
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-oa")

    accepted = client.post(
        "/internal/v1/auth/service-claim/active",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["claim_status"] == "ACTIVE"
    assert sum(
        route.path == "/internal/v1/auth/service-claim/active"
        for route in app.routes
    ) == 1

    app.state.service_token_admission = None
    unavailable = client.post("/internal/v1/auth/service-claim/active")
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "nex.service_token_admission_unavailable"


def test_oa_main_attaches_local_admission_runtime() -> None:
    import nex_oa.main as main

    assert main.app.state.service_token_admission is main.SERVICE_TOKEN_ADMISSION
    assert "/internal/v1/auth/user-login" in {route.path for route in main.app.routes}
