from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_ae_api.auth_sessions import (
    AE_AUTH_SESSION_FACADE_SCHEMA_VERSION,
    DEFAULT_LOGIN_TENANT_ID,
    DEFAULT_LOGIN_USER_ID,
    OA_BROWSER_SESSION_SCHEMA_VERSION,
    SESSION_COOKIE_NAME,
    BrowserSessionFacadeError,
    build_browser_session_snapshot,
    normalize_login_request,
    register_auth_session_routes,
    stable_session_id,
    validate_browser_session_credentials,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    issue_mock_service_token,
    issue_mock_user_token,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def app_client() -> TestClient:
    app = FastAPI()
    register_auth_session_routes(app)
    return TestClient(app)


def user_auth_headers(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    scopes: list[str] | None = None,
    issued_at: datetime | None = None,
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=user_id,
        scopes=scopes or [DEFAULT_USER_SCOPE, "documents:upload"],
        roles=["employee"],
        issued_at=issued_at or datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {issued.access_token}"}


def test_auth_session_login_returns_safe_browser_session_and_http_only_cookie() -> None:
    client = app_client()

    login = client.post(
        "/api/v1/auth/session/login",
        json={
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "scopes": [DEFAULT_USER_SCOPE, "documents:upload"],
            "roles": ["employee"],
            "ttl_seconds": 1800,
        },
    )

    assert login.status_code == 200
    payload = login.json()
    assert payload["browser_session_schema_version"] == OA_BROWSER_SESSION_SCHEMA_VERSION
    assert payload["status"] == "ACTIVE"
    assert payload["issuer"] == "nex-oa"
    assert payload["audience"] == "nex-ae-api"
    assert payload["token_use"] == "user"
    assert payload["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert payload["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert payload["metadata"] == {
        "raw_token_included": False,
        "service_token_included": False,
        "password_included": False,
        "browser_payload_owner_authoritative": False,
        "claim_owner_authoritative": True,
    }
    assert "access_token" not in payload
    assert "password" not in payload
    assert AE_AUTH_SESSION_FACADE_SCHEMA_VERSION == "ae_auth_session_facade.v1"
    set_cookie = login.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_auth_session_current_accepts_authorization_header_and_cookie() -> None:
    client = app_client()

    header_response = client.get(
        "/api/v1/auth/session",
        headers=user_auth_headers(),
    )
    login_response = client.post(
        "/api/v1/auth/session/login",
        json={"login_hint": "user-cookie", "tenant_id": "tenant-cookie"},
    )
    cookie_response = client.get("/api/v1/auth/session")

    assert header_response.status_code == 200
    assert header_response.json()["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert login_response.status_code == 200
    assert cookie_response.status_code == 200
    assert cookie_response.json()["tenant_ref"] == {
        "type": "oa.tenant",
        "id": "tenant-cookie",
    }
    assert cookie_response.json()["subject_ref"] == {
        "type": "oa.user",
        "id": "user-cookie",
    }


def test_auth_session_current_rejects_missing_service_and_scope_failures() -> None:
    client = app_client()
    service_token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ae-api",
        scopes=[DEFAULT_SERVICE_SCOPE],
        issued_at=NOW,
    )

    missing = client.get("/api/v1/auth/session")
    service = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {service_token.access_token}"},
    )
    missing_scope = client.get(
        "/api/v1/auth/session",
        headers=user_auth_headers(scopes=["documents:upload"]),
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert service.status_code == 401
    assert service.json()["error_code"] == "TOKEN_FORMAT_INVALID"
    assert missing_scope.status_code == 401
    assert missing_scope.json()["error_code"] == "TOKEN_SCOPE_MISSING"


def test_auth_session_logout_revokes_current_session_and_deletes_cookie() -> None:
    client = app_client()
    login = client.post(
        "/api/v1/auth/session/login",
        json={"tenant_id": "tenant-a", "user_id": "user-a"},
    )

    logout = client.post("/api/v1/auth/session/logout")
    after_logout = client.get("/api/v1/auth/session")

    assert login.status_code == 200
    assert logout.status_code == 200
    assert logout.json()["status"] == "REVOKED"
    assert "access_token" not in logout.json()
    assert f"{SESSION_COOKIE_NAME}=" in logout.headers["set-cookie"]
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert after_logout.status_code == 401


def test_auth_session_logout_without_credentials_returns_anonymous_safe_failure() -> None:
    response = app_client().post("/api/v1/auth/session/logout")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert f"{SESSION_COOKIE_NAME}=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_login_request_validation_rejects_unsafe_or_malformed_payloads() -> None:
    assert normalize_login_request({}) == {
        "tenant_id": DEFAULT_LOGIN_TENANT_ID,
        "user_id": DEFAULT_LOGIN_USER_ID,
        "scopes": (DEFAULT_USER_SCOPE,),
        "roles": ("employee",),
        "ttl_seconds": 3600,
    }
    assert normalize_login_request({"login_hint": "user-a"})["user_id"] == "user-a"

    for payload, error_code in [
        ({"access_token": "raw"}, "ae.auth_session_login_sensitive_field"),
        ({"unknown": "value"}, "ae.auth_session_login_field_unsupported"),
        ({"tenant_id": 3}, "ae.auth_session_login_text_invalid"),
        ({"scopes": []}, "ae.auth_session_login_list_invalid"),
        ({"roles": ["employee", ""]}, "ae.auth_session_login_list_invalid"),
        ({"ttl_seconds": True}, "ae.auth_session_login_ttl_invalid"),
        ({"ttl_seconds": 0}, "ae.auth_session_login_ttl_invalid"),
        ({"ttl_seconds": 86401}, "ae.auth_session_login_ttl_invalid"),
    ]:
        with pytest.raises(BrowserSessionFacadeError) as exc:
            normalize_login_request(payload)
        assert exc.value.error_code == error_code


def test_login_route_rejects_invalid_json_and_sensitive_fields() -> None:
    client = app_client()

    invalid_json = client.post(
        "/api/v1/auth/session/login",
        content="{bad",
        headers={"Content-Type": "application/json"},
    )
    list_payload = client.post("/api/v1/auth/session/login", json=["bad"])
    sensitive = client.post(
        "/api/v1/auth/session/login",
        json={"access_token": "raw"},
    )

    assert invalid_json.status_code == 400
    assert invalid_json.json()["error_code"] == "ae.auth_session_login_json_invalid"
    assert list_payload.status_code == 400
    assert list_payload.json()["error_code"] == "ae.auth_session_login_object_invalid"
    assert sensitive.status_code == 400
    assert sensitive.json()["error_code"] == "ae.auth_session_login_sensitive_field"


def test_browser_session_snapshot_and_credential_helpers_are_deterministic() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        scopes=[DEFAULT_USER_SCOPE],
        roles=[],
        issued_at=datetime.now(UTC) - timedelta(seconds=1),
        ttl_seconds=60,
    )
    snapshot = build_browser_session_snapshot(issued.claims)
    validation = validate_browser_session_credentials(
        authorization=f"Bearer {issued.access_token}",
        cookie_token=None,
        required_scopes=[DEFAULT_USER_SCOPE],
    )
    expired = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        issued_at=datetime.now(UTC) - timedelta(seconds=2),
        ttl_seconds=1,
    )
    expired_validation = validate_browser_session_credentials(
        authorization=None,
        cookie_token=expired.access_token,
    )

    assert snapshot["session_id"] == stable_session_id(issued.claims)
    assert isinstance(validation, type(issued.claims))
    assert isinstance(expired_validation, BrowserSessionFacadeError)
    assert expired_validation.error_code == "TOKEN_EXPIRED"
