from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

from nex_ag.service_auth import (
    AG_SERVICE_CLAIMS_STATE_KEY,
    AgOutboundServiceTokenError,
    authorize_ag_service_or_admin_request,
    authorize_ag_service_request,
    resolve_ag_outbound_service_token,
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


REFERENCE = "memory://oa-key-ag-adoption"
KEY_ID = "oa-key-ag-adoption"


@pytest.fixture(scope="module")
def signed_runtime() -> dict[str, Any]:
    signer = InMemoryOaRsaSigningProvider()
    signer.generate_key(REFERENCE)
    token = encode_signed_jwt(
        headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
        claims={
            "iss": "urn:nex-platform:oa",
            "sub": "service:nex-oa",
            "aud": "nex-ag",
            "iat": 500,
            "nbf": 500,
            "exp": 800,
            "jti": "sat-ag-adoption",
            "token_use": "service_access",
            "scope": "service:call",
            "service_id": "nex-oa",
            "credential_id": "cred-oa-runtime",
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
            expected_audience="nex-ag",
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            clock=lambda: 600,
        ),
    }


def _client(admission: ServiceTokenAdmissionRuntime) -> TestClient:
    app = FastAPI()
    app.state.service_token_admission = admission

    @app.get("/service")
    def service(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_ag_service_request(request, authorization)
        if denied is not None:
            return denied
        claims = getattr(request.state, AG_SERVICE_CLAIMS_STATE_KEY)
        return {"actor": claims.subject, "kind": claims.token_kind}

    @app.get("/admin")
    def admin(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_ag_service_or_admin_request(
            request,
            authorization,
            admin_error_code="ag.admin_required",
            admin_error_detail="admin role is required",
        )
        return denied or {"authorized": True}

    return TestClient(app)


def test_ag_guard_accepts_signed_service_and_records_claims(
    signed_runtime: dict[str, Any],
) -> None:
    response = _client(signed_runtime["admission"]).get(
        "/service",
        headers={"Authorization": f"Bearer {signed_runtime['token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {"actor": "service:nex-oa", "kind": "SIGNED"}


def test_ag_signed_only_rejects_mock_without_user_fallback(
    signed_runtime: dict[str, Any],
) -> None:
    mock = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    response = _client(signed_runtime["admission"]).get(
        "/admin", headers={"Authorization": f"Bearer {mock.access_token}"}
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "nex.mock_token_forbidden"


def test_ag_admin_guard_preserves_user_role_path(
    signed_runtime: dict[str, Any],
) -> None:
    admin = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    viewer = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    )
    client = _client(signed_runtime["admission"])

    accepted = client.get(
        "/admin", headers={"Authorization": f"Bearer {admin.access_token}"}
    )
    denied = client.get(
        "/admin", headers={"Authorization": f"Bearer {viewer.access_token}"}
    )

    assert accepted.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "ag.admin_required"


def test_ag_outbound_token_resolution_is_profile_driven() -> None:
    assert resolve_ag_outbound_service_token(
        "signed-token", audience="nex-cx", environ={}
    ) == "signed-token"
    assert resolve_ag_outbound_service_token(
        None,
        audience="nex-mo",
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    ).startswith("nex-mock-service.")
    assert resolve_ag_outbound_service_token(
        None,
        audience="nex-cx",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_AG_TO_CX_SERVICE_TOKEN": "cx-signed-from-env",
        },
    ) == "cx-signed-from-env"
    assert resolve_ag_outbound_service_token(
        None,
        audience="nex-ae-api",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ",
            "NEX_AG_TO_AE_SERVICE_TOKEN": "ae-signed-from-env",
        },
    ) == "ae-signed-from-env"

    for configured, audience, environ, code in (
        (" bad ", "nex-cx", {}, "ag.outbound_service_token_invalid"),
        (
            None,
            "nex-cx",
            {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"},
            "ag.outbound_service_token_missing",
        ),
        (
            None,
            "nex-cx",
            {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "wrong"},
            "ag.service_token_rollout_profile_invalid",
        ),
        (
            None,
            "external",
            {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "DUAL_READ"},
            "ag.outbound_service_token_missing",
        ),
    ):
        with pytest.raises(AgOutboundServiceTokenError) as exc:
            resolve_ag_outbound_service_token(
                configured,
                audience=audience,
                environ=environ,
            )
        assert exc.value.error_code == code
        assert str(exc.value) == exc.value.detail


def test_ag_guard_without_injected_runtime_keeps_test_mock_compatibility() -> None:
    app = FastAPI()

    @app.get("/service")
    def service(request: Request, authorization: str | None = Header(default=None)):
        denied = authorize_ag_service_request(request, authorization)
        return denied or {"authorized": True}

    mock = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    response = TestClient(app).get(
        "/service", headers={"Authorization": f"Bearer {mock.access_token}"}
    )

    assert response.status_code == 200
