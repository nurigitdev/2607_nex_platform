from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient

import nex_ae_api.route_auth as ae_route_auth
from nex_ae_api.auth_guard import BrowserAuthError
from nex_ae_api.auth_sessions import SESSION_COOKIE_NAME
from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    authorize_ae_facade_route_request,
)
from nex_runtime import issue_mock_service_token, issue_mock_user_token


def test_facade_route_auth_accepts_service_claim_and_user_claim() -> None:
    app = FastAPI()

    @app.get("/guard")
    def guarded(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        if hasattr(result, "to_wire"):
            return result.to_wire()
        return result

    service_token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ae-api",
    )
    user_token = issue_mock_user_token(tenant_id="tenant-a", user_id="user-a")
    client = TestClient(app)

    service_response = client.get(
        "/guard",
        headers={"Authorization": f"Bearer {service_token.access_token}"},
    )
    user_response = client.get(
        "/guard",
        headers={"Authorization": f"Bearer {user_token.access_token}"},
    )

    assert service_response.status_code == 200
    assert service_response.json()["auth_mode"] == "service"
    assert service_response.json()["metadata"]["raw_token_included"] is False
    assert user_response.status_code == 200
    assert user_response.json()["auth_mode"] == "browser_user"
    assert user_response.json()["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert user_response.json()["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert AeFacadeRouteAuthContext(auth_mode="browser_user").is_browser_user is True
    assert AeFacadeRouteAuthContext(auth_mode="service").is_browser_user is False
    assert AeFacadeRouteAuthContext(auth_mode="service").to_wire()["service_id"] is None


def test_facade_route_auth_accepts_browser_cookie_and_rejects_missing_auth() -> None:
    app = FastAPI()

    @app.get("/guard")
    def guarded(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        if hasattr(result, "to_wire"):
            return result.to_wire()
        return result

    token = issue_mock_user_token(tenant_id="tenant-cookie", user_id="user-cookie")
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token.access_token)

    cookie_response = client.get("/guard")
    client.cookies.clear()
    missing_response = client.get("/guard")
    client.cookies.set(SESSION_COOKIE_NAME, "bad-cookie")
    bad_cookie_response = client.get("/guard")

    assert cookie_response.status_code == 200
    assert cookie_response.json()["auth_mode"] == "browser_user"
    assert cookie_response.json()["tenant_ref"]["id"] == "tenant-cookie"
    assert missing_response.status_code == 401
    assert missing_response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert bad_cookie_response.status_code == 401
    assert bad_cookie_response.json()["error_code"] == "TOKEN_FORMAT_INVALID"


def test_facade_route_auth_maps_browser_context_build_failure(monkeypatch) -> None:
    app = FastAPI()

    @app.get("/guard")
    def guarded(request: Request, authorization: str | None = Header(default=None)):
        result = authorize_ae_facade_route_request(request, authorization)
        if hasattr(result, "to_wire"):
            return result.to_wire()
        return result

    def raise_context_error(*args, **kwargs):
        raise BrowserAuthError(
            status_code=401,
            error_code="ae.browser_token_use_invalid",
            detail="Bad token use.",
        )

    monkeypatch.setattr(
        ae_route_auth,
        "build_browser_user_auth_context",
        raise_context_error,
    )
    user_token = issue_mock_user_token(tenant_id="tenant-a", user_id="user-a")

    response = TestClient(app).get(
        "/guard",
        headers={"Authorization": f"Bearer {user_token.access_token}"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "ae.browser_token_use_invalid"
