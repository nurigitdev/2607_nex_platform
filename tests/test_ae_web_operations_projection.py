from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.web_operations import (
    AE_WEB_OPERATIONS_SUMMARY_SCHEMA_VERSION,
    AeWebOperationsError,
    build_ae_web_operations_summary,
    register_ae_web_operations_routes,
    validate_ae_web_operations_summary,
)
from nex_runtime import issue_mock_service_token, issue_mock_user_token


def test_builds_redacted_service_and_runtime_projection() -> None:
    projection = build_ae_web_operations_summary(
        database_available=True,
        agent_runtime_available=True,
        provider_route_configured=True,
        service_observations=[
            {
                "service_id": "nex-ag",
                "health_status": "HEALTHY",
                "readiness_status": "READY",
                "version": "2.1.0",
            }
        ],
    )

    assert projection["operations_summary_schema_version"] == (
        AE_WEB_OPERATIONS_SUMMARY_SCHEMA_VERSION
    )
    assert projection["overall_status"] == "READY"
    assert projection["runtime"] == {
        "database_status": "AVAILABLE",
        "agent_runtime_status": "AVAILABLE",
        "provider_route_status": "CONFIGURED",
    }
    serialized = repr(projection).lower()
    assert "127.0.0.1:81" not in serialized
    assert "password" not in serialized
    assert "service_token" not in serialized


def test_operator_route_denies_employee_and_service_callers() -> None:
    app = FastAPI()
    register_ae_web_operations_routes(
        app,
        source=lambda: build_ae_web_operations_summary(database_available=True),
    )
    client = TestClient(app)
    employee = issue_mock_user_token(
        tenant_id="tenant-a", user_id="employee-a", roles=["employee"]
    )
    service = issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")

    employee_response = client.get(
        "/api/v1/web/operations/summary",
        headers={"Authorization": f"Bearer {employee.access_token}"},
    )
    service_response = client.get(
        "/api/v1/web/operations/summary",
        headers={"Authorization": f"Bearer {service.access_token}"},
    )

    assert employee_response.status_code == 403
    assert employee_response.json()["error_code"] == "AE_WEB_OPERATIONS_FORBIDDEN"
    assert service_response.status_code == 403


def test_operator_and_admin_can_read_projection_case_insensitively() -> None:
    app = FastAPI()
    register_ae_web_operations_routes(
        app,
        source=lambda: build_ae_web_operations_summary(agent_runtime_available=True),
    )
    client = TestClient(app)

    for role in ("operator", "ADMIN", " Operator "):
        token = issue_mock_user_token(
            tenant_id="tenant-a", user_id=f"user-{role.strip()}", roles=[role]
        )
        response = client.get(
            "/api/v1/web/operations/summary",
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["metadata"]["direct_service_requests_allowed"] is False


def test_projection_failure_is_bounded_service_unavailable() -> None:
    app = FastAPI()

    def unavailable():
        raise RuntimeError("private failure detail")

    register_ae_web_operations_routes(app, source=unavailable)
    token = issue_mock_user_token(
        tenant_id="tenant-a", user_id="operator-a", roles=["operator"]
    )
    response = TestClient(app).get(
        "/api/v1/web/operations/summary",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "AE_WEB_OPERATIONS_UNAVAILABLE"
    assert "private failure detail" not in response.text


def test_rejects_sensitive_or_private_projection_fields() -> None:
    projection = build_ae_web_operations_summary()
    projection["runtime"]["database_url"] = "postgresql://private"
    try:
        validate_ae_web_operations_summary(projection)
    except AeWebOperationsError as exc:
        assert "sensitive keys" in str(exc)
    else:
        raise AssertionError("sensitive projection must be rejected")
