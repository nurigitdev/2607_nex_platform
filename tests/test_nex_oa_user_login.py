from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_oa.credentials import InMemoryOaCredentialRegistry, OaCredentialError
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.sessions import (
    InMemoryOaSessionRegistry,
    OA_SESSION_ISSUE_SCHEMA_VERSION,
    OaSessionError,
)
from nex_oa.subjects import InMemoryOaSubjectRegistry
from nex_oa.user_login import (
    OA_USER_LOGIN_RESPONSE_SCHEMA_VERSION,
    OaUserLoginError,
    OaUserLoginService,
    build_session_issue_payload_for_login,
    normalize_user_login_request,
    register_user_login_routes,
)
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(*, audience: str = "nex-oa") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def build_login_service() -> tuple[
    OaUserLoginService,
    InMemoryOaCredentialRegistry,
    InMemoryOaTenantMembershipRegistry,
    InMemoryOaSessionRegistry,
]:
    subject_registry = InMemoryOaSubjectRegistry()
    credential_registry = InMemoryOaCredentialRegistry(
        subject_registry=subject_registry
    )
    membership_registry = InMemoryOaTenantMembershipRegistry(
        subject_registry=subject_registry
    )
    session_registry = InMemoryOaSessionRegistry(membership_registry)
    service = OaUserLoginService(
        credential_registry=credential_registry,
        session_registry=session_registry,
    )
    return service, credential_registry, membership_registry, session_registry


def seed_active_employee(
    credential_registry: InMemoryOaCredentialRegistry,
    membership_registry: InMemoryOaTenantMembershipRegistry,
    *,
    tenant_id: str = "tenant-a",
    employee_id: str = "EMP-001",
    subject_id: str = "user-a",
    password: str = "Nuri1004!",
    scopes: list[str] | None = None,
    credential_status: str = "ACTIVE",
) -> None:
    credential_registry.ensure_credential(
        {
            "tenant_id": tenant_id,
            "employee_id": employee_id,
            "subject_id": subject_id,
            "password": password,
            "credential_status": credential_status,
        }
    )
    membership_registry.ensure_membership(
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "roles": ["employee", "analyst"],
            "scopes": scopes or ["workspace:use", "documents:read"],
        }
    )


def build_client(service: OaUserLoginService | None = None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    if service is None:
        service, credential_registry, membership_registry, _session_registry = (
            build_login_service()
        )
        seed_active_employee(credential_registry, membership_registry)
    register_user_login_routes(app, service=service)
    return TestClient(app)


def test_user_login_verifies_password_and_issues_browser_session() -> None:
    service, credential_registry, membership_registry, session_registry = (
        build_login_service()
    )
    seed_active_employee(credential_registry, membership_registry)

    response = service.login(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
            "requested_scopes": ["workspace:use"],
            "ttl_seconds": 1800,
        }
    )
    session = response["session"]
    serialized = json.dumps(response, ensure_ascii=False)

    assert response["login_response_schema_version"] == (
        OA_USER_LOGIN_RESPONSE_SCHEMA_VERSION
    )
    assert response["session_issue_schema_version"] == OA_SESSION_ISSUE_SCHEMA_VERSION
    assert response["service_id"] == "nex-oa"
    assert response["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert response["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert session["scopes"] == ["workspace:use"]
    assert session["roles"] == ["employee", "analyst"]
    assert response["metadata"]["password_verified"] is True
    assert response["metadata"]["credential_lookup"] == "employee_id"
    assert response["metadata"]["credential_snapshot_included"] is False
    assert response["metadata"]["hash_material_included"] is False
    assert session["session_id"] in session_registry.sessions
    assert "Nuri1004!" not in serialized
    assert "password_hash" not in serialized


def test_user_login_rejects_bad_secret_inactive_credential_and_missing_membership() -> None:
    service, credential_registry, membership_registry, _session_registry = (
        build_login_service()
    )
    seed_active_employee(credential_registry, membership_registry)
    credential_registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-NO-MEMBERSHIP",
            "subject_id": "user-no-membership",
            "password": "Nuri1004!",
        }
    )
    seed_active_employee(
        credential_registry,
        membership_registry,
        employee_id="EMP-LOCKED",
        subject_id="locked-user",
        credential_status="LOCKED",
    )

    for payload, status_code, error_code in [
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Wrong1004!",
            },
            401,
            "oa.credential_not_verified",
        ),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-LOCKED",
                "password": "Nuri1004!",
            },
            401,
            "oa.credential_not_active",
        ),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-NO-MEMBERSHIP",
                "password": "Nuri1004!",
            },
            404,
            "oa.membership_not_found",
        ),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
                "requested_scopes": ["admin:all"],
            },
            403,
            "oa.session_scope_not_granted",
        ),
    ]:
        with pytest.raises(OaUserLoginError) as exc:
            service.login(payload)
        assert exc.value.status_code == status_code
        assert exc.value.error_code == error_code


def test_user_login_request_validation_blocks_unsupported_and_private_fields() -> None:
    assert normalize_user_login_request(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        }
    ) == {
        "tenant_id": "tenant-a",
        "employee_id": "EMP-001",
        "password": "Nuri1004!",
    }

    for payload, error_code in [
        (["not", "an", "object"], "oa.login_payload_invalid"),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
                "remember_me": True,
            },
            "oa.login_field_unsupported",
        ),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
                "password_hash": "secret-value",
            },
            "oa.login_private_payload_rejected",
        ),
        (
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
                "api_key": "secret-value",
            },
            "oa.login_private_payload_rejected",
        ),
    ]:
        with pytest.raises(OaUserLoginError) as exc:
            normalize_user_login_request(payload)
        assert exc.value.error_code == error_code


def test_login_session_issue_payload_uses_credential_subject_ref() -> None:
    credential_snapshot = {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "subject_ref": {"type": "oa.user", "id": "user-a"},
    }
    assert build_session_issue_payload_for_login(
        {"requested_scopes": ["workspace:use"], "ttl_seconds": 1200},
        credential_snapshot=credential_snapshot,
    ) == {
        "tenant_id": "tenant-a",
        "subject_id": "user-a",
        "requested_scopes": ["workspace:use"],
        "ttl_seconds": 1200,
    }

    for bad_snapshot in [
        {},
        {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "subject_ref": {"type": "other", "id": "user-a"},
        },
        {
            "tenant_ref": {"type": "oa.tenant", "id": "   "},
            "subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        {
            "tenant_ref": {"type": 123, "id": "tenant-a"},
            "subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        {
            "tenant_ref": {"type": "   ", "id": "tenant-a"},
            "subject_ref": {"type": "oa.user", "id": "user-a"},
        },
    ]:
        with pytest.raises(OaUserLoginError) as exc:
            build_session_issue_payload_for_login(
                {},
                credential_snapshot=bad_snapshot,
            )
        assert exc.value.error_code == "oa.login_credential_snapshot_invalid"


def test_user_login_service_maps_registry_failures_without_leaking_secrets() -> None:
    class FailingCredentialRegistry:
        def verify_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
            raise OaCredentialError(
                status_code=503,
                error_code="oa.credential_registry_unavailable",
                detail="credential registry unavailable",
                retryable=True,
            )

    class PassingCredentialRegistry:
        def verify_credential(self, payload: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                "subject_ref": {"type": "oa.user", "id": "user-a"},
                "credential": {"status": "ACTIVE"},
            }

    class FailingSessionRegistry:
        def issue_session(self, payload: Mapping[str, Any]) -> dict[str, Any]:
            raise OaSessionError(
                status_code=503,
                error_code="oa.session_registry_unavailable",
                detail="session registry unavailable",
                retryable=True,
            )

    with pytest.raises(OaUserLoginError) as credential_error:
        OaUserLoginService(
            credential_registry=FailingCredentialRegistry(),
            session_registry=FailingSessionRegistry(),
        ).login(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            }
        )
    with pytest.raises(OaUserLoginError) as session_error:
        OaUserLoginService(
            credential_registry=PassingCredentialRegistry(),
            session_registry=FailingSessionRegistry(),
        ).login(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            }
        )

    assert credential_error.value.error_code == "oa.credential_registry_unavailable"
    assert credential_error.value.retryable is True
    assert session_error.value.error_code == "oa.session_registry_unavailable"
    assert str(session_error.value) == "session registry unavailable"


def test_user_login_route_requires_service_claim_and_returns_safe_context() -> None:
    client = build_client()

    missing_auth = client.post("/internal/v1/auth/user-login", json={})
    wrong_audience = client.post(
        "/internal/v1/auth/user-login",
        headers=auth_headers(audience="nex-cx"),
        json={},
    )
    invalid_payload = client.post(
        "/internal/v1/auth/user-login",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
            "password_hash": "secret-value",
        },
    )
    logged_in = client.post(
        "/internal/v1/auth/user-login",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
            "requested_scopes": ["workspace:use"],
        },
    )
    serialized = json.dumps(logged_in.json(), ensure_ascii=False)

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert invalid_payload.status_code == 400
    assert invalid_payload.json()["error_code"] == "oa.login_private_payload_rejected"
    assert logged_in.status_code == 200
    assert logged_in.json()["trace_id"] == TRACE_ID
    assert logged_in.json()["request_id"] == REQUEST_ID
    assert logged_in.json()["metadata"]["password_verified"] is True
    assert logged_in.json()["session"]["subject_ref"] == {
        "type": "oa.user",
        "id": "user-a",
    }
    assert "Nuri1004!" not in serialized
    assert "password_hash" not in serialized


def test_user_login_route_maps_service_errors() -> None:
    class FailingLoginService:
        def login(self, payload: dict[str, object]) -> dict[str, object]:
            raise OaUserLoginError(
                status_code=503,
                error_code="oa.user_login_unavailable",
                detail="user login unavailable",
                retryable=True,
            )

    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_user_login_routes(app, service=FailingLoginService())
    client = TestClient(app)

    response = client.post(
        "/internal/v1/auth/user-login",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        },
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "oa.user_login_unavailable"
    assert response.json()["retryable"] is True


def test_nex_oa_entrypoint_registers_user_login_route() -> None:
    import nex_oa.main as main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/internal/v1/auth/user-login" in paths
