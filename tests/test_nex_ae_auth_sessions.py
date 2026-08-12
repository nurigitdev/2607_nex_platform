from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_ae_api import auth_sessions
from nex_ae_api.auth_sessions import (
    AE_AUTH_SESSION_FACADE_SCHEMA_VERSION,
    AUTH_SESSION_MODE_OA,
    DEFAULT_LOGIN_TENANT_ID,
    DEFAULT_LOGIN_USER_ID,
    OA_BROWSER_SESSION_SCHEMA_VERSION,
    SESSION_COOKIE_NAME,
    BrowserSessionFacadeError,
    build_browser_session_snapshot,
    normalize_credential_login_request,
    normalize_auth_session_mode,
    normalize_login_request_for_mode,
    normalize_login_request,
    register_auth_session_routes,
    stable_session_id,
    user_claims_from_oa_browser_session,
    validate_browser_session_credentials,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    issue_mock_service_token,
    issue_mock_user_token,
)


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def oa_browser_session(
    *,
    session_id: str = "oa-session-a",
    tenant_id: str = "tenant-oa",
    user_id: str = "user-oa",
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
    status: str = "ACTIVE",
) -> dict[str, object]:
    return {
        "browser_session_schema_version": OA_BROWSER_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "status": status,
        "issuer": "nex-oa",
        "audience": "nex-ae-api",
        "token_use": "user",
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "subject_ref": {"type": "oa.user", "id": user_id},
        "scopes": scopes or [DEFAULT_USER_SCOPE, "documents:upload"],
        "roles": roles if roles is not None else ["employee"],
        "issued_at": "2026-08-12T12:00:00Z",
        "expires_at": "2026-08-12T13:00:00Z",
        "auth_time": "2026-08-12T12:00:00Z",
        "metadata": {
            "raw_token_included": False,
            "service_token_included": False,
            "password_included": False,
            "browser_payload_owner_authoritative": False,
            "claim_owner_authoritative": True,
        },
    }


class FakeOaSessionClient:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, str, str, str]] = []

    def login_with_credentials(
        self,
        login_request: dict[str, object],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        employee_id = str(login_request["employee_id"])
        subject_id = {
            "EMP-001": "user-oa",
            "EMP-002": "user-login-identifier",
            "EMP-003": "user-login-hint",
        }.get(employee_id, f"user-{employee_id.lower()}")
        session = oa_browser_session(
            session_id=f"oa-session-{employee_id}",
            tenant_id=str(login_request["tenant_id"]),
            user_id=subject_id,
            scopes=list(login_request["scopes"]),
            roles=["employee"],
        )
        self.sessions[str(session["session_id"])] = session
        self.calls.append(("login", str(session["session_id"]), request_id, trace_id))
        return {
            "login_response_schema_version": "oa_user_login_response.v1",
            "session": session,
            "metadata": {
                "password_verified": True,
                "raw_password_included": False,
            },
        }

    def issue_session(
        self,
        login_request: dict[str, object],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        session = oa_browser_session(
            session_id=f"oa-session-{login_request['user_id']}",
            tenant_id=str(login_request["tenant_id"]),
            user_id=str(login_request["user_id"]),
            scopes=list(login_request["scopes"]),
            roles=["employee"],
        )
        self.sessions[str(session["session_id"])] = session
        self.calls.append(("issue", str(session["session_id"]), request_id, trace_id))
        return {"session_issue_schema_version": "oa_session_issue.v1", "session": session}

    def introspect_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        self.calls.append(("introspect", session_id, request_id, trace_id))
        session = self.sessions.get(session_id)
        if session is None:
            return {
                "session_introspection_schema_version": "oa_session_introspection.v1",
                "active": False,
                "inactive_reason": "not_found",
                "session": None,
            }
        if session["status"] != "ACTIVE":
            return {
                "session_introspection_schema_version": "oa_session_introspection.v1",
                "active": False,
                "inactive_reason": str(session["status"]).lower(),
                "session": session,
            }
        return {
            "session_introspection_schema_version": "oa_session_introspection.v1",
            "active": True,
            "inactive_reason": None,
            "session": session,
        }

    def revoke_session(
        self,
        session_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, object]:
        self.calls.append(("revoke", session_id, request_id, trace_id))
        session = self.sessions.get(session_id)
        if session is None:
            return {
                "session_revocation_schema_version": "oa_session_revocation.v1",
                "revoked": False,
                "inactive_reason": "not_found",
                "session": None,
            }
        session["status"] = "REVOKED"
        session["revoked_at"] = "2026-08-12T12:05:00Z"
        return {
            "session_revocation_schema_version": "oa_session_revocation.v1",
            "revoked": True,
            "inactive_reason": "revoked",
            "session": session,
        }


def app_client() -> TestClient:
    app = FastAPI()
    register_auth_session_routes(app)
    return TestClient(app)


def app_client_oa(fake_oa: FakeOaSessionClient) -> TestClient:
    app = FastAPI()
    register_auth_session_routes(
        app,
        oa_session_client=fake_oa,
        session_mode=AUTH_SESSION_MODE_OA,
    )
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


def test_oa_backed_auth_session_login_current_logout_uses_opaque_cookie() -> None:
    fake_oa = FakeOaSessionClient()
    client = app_client_oa(fake_oa)
    headers = {
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "X-Request-ID": "request-oa-login",
    }

    login = client.post(
        "/api/v1/auth/session/login",
        headers=headers,
        json={
            "tenant_id": "tenant-oa",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
            "scopes": [DEFAULT_USER_SCOPE, "documents:upload"],
            "ttl_seconds": 1800,
        },
    )
    current = client.get("/api/v1/auth/session", headers=headers)
    logout = client.post("/api/v1/auth/session/logout", headers=headers)
    after_logout = client.get("/api/v1/auth/session", headers=headers)

    assert login.status_code == 200
    payload = login.json()
    assert payload["session_id"] == "oa-session-EMP-001"
    assert payload["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-oa"}
    assert payload["subject_ref"] == {"type": "oa.user", "id": "user-oa"}
    assert payload["metadata"]["raw_token_included"] is False
    assert "Nuri1004!" not in login.text
    set_cookie = login.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=oa-session-EMP-001" in set_cookie
    assert "nex-mock-user." not in set_cookie
    assert current.status_code == 200
    assert current.json()["session_id"] == "oa-session-EMP-001"
    assert logout.status_code == 200
    assert logout.json()["status"] == "REVOKED"
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert after_logout.status_code == 401
    assert [call[0] for call in fake_oa.calls] == [
        "login",
        "introspect",
        "revoke",
    ]
    assert fake_oa.calls[0][2:] == (
        "request-oa-login",
        "4bf92f3577b34da6a3ce929d0e0e4736",
    )


def test_oa_backed_cookie_validation_maps_claims_and_rejects_inactive() -> None:
    fake_oa = FakeOaSessionClient()
    active_session = oa_browser_session(session_id="active-oa-session")
    missing_scope_session = oa_browser_session(
        session_id="missing-scope-session",
        scopes=["documents:upload"],
    )
    revoked_session = oa_browser_session(
        session_id="revoked-oa-session",
        status="REVOKED",
    )
    fake_oa.sessions["active-oa-session"] = active_session
    fake_oa.sessions["missing-scope-session"] = missing_scope_session
    fake_oa.sessions["revoked-oa-session"] = revoked_session

    claims = validate_browser_session_credentials(
        authorization=None,
        cookie_token="active-oa-session",
        request_id="request-a",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        oa_session_client=fake_oa,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    missing_scope = validate_browser_session_credentials(
        authorization=None,
        cookie_token="missing-scope-session",
        oa_session_client=fake_oa,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    revoked = validate_browser_session_credentials(
        authorization=None,
        cookie_token="revoked-oa-session",
        oa_session_client=fake_oa,
        session_mode=AUTH_SESSION_MODE_OA,
    )
    missing = validate_browser_session_credentials(
        authorization=None,
        cookie_token="missing",
        oa_session_client=fake_oa,
        session_mode=AUTH_SESSION_MODE_OA,
    )

    assert hasattr(claims, "tenant_id")
    assert claims.tenant_id == "tenant-oa"
    assert claims.user_id == "user-oa"
    assert isinstance(missing_scope, BrowserSessionFacadeError)
    assert missing_scope.error_code == "TOKEN_SCOPE_MISSING"
    assert isinstance(revoked, BrowserSessionFacadeError)
    assert revoked.error_code == "ae.oa_session_inactive"
    assert "revoked" in revoked.detail
    assert isinstance(missing, BrowserSessionFacadeError)
    assert missing.error_code == "ae.oa_session_inactive"


def test_oa_browser_session_shape_validation_rejects_bad_snapshots() -> None:
    valid = oa_browser_session()
    assert user_claims_from_oa_browser_session(valid).user_id == "user-oa"
    assert normalize_auth_session_mode(None) == "mock"
    assert normalize_auth_session_mode(" OA ") == AUTH_SESSION_MODE_OA

    for mutated, error_code in [
        ({**valid, "tenant_ref": None}, "ae.oa_session_ref_invalid"),
        (
            {**valid, "subject_ref": {"type": "bad", "id": "user-oa"}},
            "ae.oa_session_ref_invalid",
        ),
        ({**valid, "scopes": "workspace:use"}, "ae.oa_session_list_invalid"),
        ({**valid, "roles": [3]}, "ae.oa_session_list_invalid"),
        ({**valid, "issuer": ""}, "ae.oa_session_field_invalid"),
        ({**valid, "audience": "other"}, "ae.browser_token_audience_invalid"),
    ]:
        with pytest.raises(BrowserSessionFacadeError) as exc:
            user_claims_from_oa_browser_session(mutated)
        assert exc.value.error_code == error_code

    with pytest.raises(BrowserSessionFacadeError) as invalid_mode:
        normalize_auth_session_mode("bad")
    assert invalid_mode.value.error_code == "ae.auth_session_mode_invalid"


def test_oa_backed_login_and_logout_map_oa_client_errors() -> None:
    class FailingOaSessionClient(FakeOaSessionClient):
        def login_with_credentials(self, *args, **kwargs):
            raise auth_sessions.OaUserSessionClientError(
                status_code=503,
                error_code="oa.user_login_client_unavailable",
                detail="OA down",
                retryable=True,
            )

    class BadLoginOaSessionClient(FakeOaSessionClient):
        def login_with_credentials(self, *args, **kwargs):
            return {"session": None}

    failing = app_client_oa(FailingOaSessionClient()).post(
        "/api/v1/auth/session/login",
        json={
            "tenant_id": "tenant-oa",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        },
    )
    bad_login = app_client_oa(BadLoginOaSessionClient()).post(
        "/api/v1/auth/session/login",
        json={
            "tenant_id": "tenant-oa",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        },
    )
    missing_logout_client = app_client_oa(FakeOaSessionClient())
    missing_logout_client.cookies.set(SESSION_COOKIE_NAME, "missing")
    missing_logout = missing_logout_client.post("/api/v1/auth/session/logout")

    assert failing.status_code == 503
    assert failing.json()["error_code"] == "oa.user_login_client_unavailable"
    assert failing.json()["retryable"] is True
    assert "Nuri1004!" not in failing.text
    assert bad_login.status_code == 502
    assert bad_login.json()["error_code"] == "ae.oa_user_login_invalid"
    assert missing_logout.status_code == 401
    assert missing_logout.json()["error_code"] == "ae.oa_session_inactive"
    assert "Max-Age=0" in missing_logout.headers["set-cookie"]


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


def test_credential_login_request_validation_is_oa_mode_only() -> None:
    credential_payload = {
        "tenant_id": "tenant-oa",
        "employee_id": "EMP-001",
        "password": "Nuri1004!",
        "requested_scopes": [DEFAULT_USER_SCOPE],
        "ttl_seconds": 1800,
    }

    assert normalize_login_request_for_mode(
        credential_payload,
        session_mode=AUTH_SESSION_MODE_OA,
    ) == {
        "tenant_id": "tenant-oa",
        "employee_id": "EMP-001",
        "password": "Nuri1004!",
        "requested_scopes": (DEFAULT_USER_SCOPE,),
        "scopes": (DEFAULT_USER_SCOPE,),
        "ttl_seconds": 1800,
    }
    assert normalize_credential_login_request(
        {
            "tenant_id": "tenant-oa",
            "login_identifier": "EMP-002",
            "password": "Nuri1004!",
        }
    )["employee_id"] == "EMP-002"
    assert normalize_credential_login_request(
        {
            "tenant_id": "tenant-oa",
            "login_hint": "EMP-003",
            "password": "Nuri1004!",
            "scopes": [DEFAULT_USER_SCOPE, "documents:upload"],
        }
    )["requested_scopes"] == (DEFAULT_USER_SCOPE, "documents:upload")

    with pytest.raises(BrowserSessionFacadeError) as mock_mode_secret:
        normalize_login_request_for_mode({"password": "Nuri1004!"}, session_mode="mock")
    assert mock_mode_secret.value.error_code == "ae.auth_session_login_sensitive_field"
    with pytest.raises(BrowserSessionFacadeError) as mock_mode_employee:
        normalize_login_request_for_mode(credential_payload, session_mode="mock")
    assert mock_mode_employee.value.error_code == "ae.auth_session_login_field_unsupported"

    for payload, error_code in [
        (
            {"tenant_id": "tenant-oa", "password": "Nuri1004!"},
            "ae.auth_session_login_employee_id_missing",
        ),
        (
            {"tenant_id": "tenant-oa", "employee_id": "EMP-001"},
            "ae.auth_session_login_password_missing",
        ),
        (
            {
                **credential_payload,
                "requested_scopes": [DEFAULT_USER_SCOPE],
                "scopes": [DEFAULT_USER_SCOPE],
            },
            "ae.auth_session_login_scope_conflict",
        ),
        (
            {**credential_payload, "roles": ["employee"]},
            "ae.auth_session_login_field_unsupported",
        ),
        (
            {**credential_payload, "password_hash": "secret"},
            "ae.auth_session_login_sensitive_field",
        ),
        (
            {**credential_payload, "employee_id": 3},
            "ae.auth_session_login_text_invalid",
        ),
    ]:
        with pytest.raises(BrowserSessionFacadeError) as exc:
            normalize_credential_login_request(payload)
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
