from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from nex_oa.auth_events import (
    OA_CREDENTIAL_SECURITY_READ_SCOPE,
    InMemoryOaAuthEventRepository,
    OaAuthEventError,
    SqlAlchemyOaAuthEventRepository,
    _json_loads,
    _json_sql_expression,
    _timestamp_to_wire,
    auth_event_target,
    build_auth_event,
    build_auth_event_repository_for_runtime,
    normalize_event_query,
    project_auth_event,
    record_auth_event_safely,
    register_auth_event_routes,
)
from nex_oa.credential_security import (
    OA_CREDENTIAL_SECURITY_WRITE_SCOPE,
    InMemoryOaCredentialSecurityRepository,
    register_credential_security_routes,
)
from nex_oa.credentials import InMemoryOaCredentialRegistry
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.sessions import InMemoryOaSessionRegistry, register_user_session_routes
from nex_oa.user_login import OaUserLoginService, register_user_login_routes
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
)


def _event_payload(**overrides):
    return {
        "event_type": "LOGIN_SUCCEEDED",
        "outcome": "SUCCEEDED",
        "tenant_id": "tenant-a",
        "subject_id": "user-a",
        "credential_id": "credential-a",
        "actor_ref": "nex.service:nex-ae-api",
        "request_id": "request-1228",
        "trace_id": "1234567890abcdef1234567890abcdef",
        "details": {"credential_status": "ACTIVE"},
        **overrides,
    }


def _sqlite_repository():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE oa_auth_events (
                    event_id TEXT PRIMARY KEY,
                    event_schema_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    tenant_id TEXT,
                    subject_id TEXT,
                    credential_id TEXT,
                    actor_ref TEXT NOT NULL,
                    request_id TEXT,
                    trace_id TEXT,
                    details TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
    return SqlAlchemyOaAuthEventRepository(build_session_factory(engine)), engine


def _headers(*scopes: str):
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-1228",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def _integrated_client(events=None):
    credentials = InMemoryOaCredentialRegistry()
    credentials.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "employee_id": "EMP-001",
            "password": "Current1004!",
        }
    )
    memberships = InMemoryOaTenantMembershipRegistry(
        subject_registry=credentials.subject_registry
    )
    memberships.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "scopes": ["workspace:use"],
        }
    )
    sessions = InMemoryOaSessionRegistry(membership_registry=memberships)
    security = InMemoryOaCredentialSecurityRepository(credentials, sessions)
    login = OaUserLoginService(credentials, sessions)
    event_repository = events or InMemoryOaAuthEventRepository()
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_user_login_routes(
        app, service=login, auth_event_repository=event_repository
    )
    register_user_session_routes(
        app, registry=sessions, auth_event_repository=event_repository
    )
    register_credential_security_routes(
        app, repository=security, auth_event_repository=event_repository
    )
    register_auth_event_routes(app, repository=event_repository)
    return TestClient(app), event_repository, sessions


def test_memory_repository_records_filters_and_projects_safe_events() -> None:
    repository = InMemoryOaAuthEventRepository()
    first = repository.record_event(_event_payload())
    repository.record_event(
        _event_payload(
            event_type="PASSWORD_RESET",
            subject_id="user-b",
            details={"operation": "PASSWORD_RESET"},
        )
    )
    assert first["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert "created_at" not in first
    assert repository.list_events(tenant_id="tenant-a", limit=1)[0]["event_type"] == "PASSWORD_RESET"
    assert repository.list_events(
        tenant_id="tenant-a", subject_id="user-a"
    )[0]["event_type"] == "LOGIN_SUCCEEDED"
    assert repository.list_events(
        tenant_id="tenant-a", event_type="PASSWORD_RESET"
    )[0]["subject_ref"]["id"] == "user-b"
    assert repository.list_events(tenant_id="tenant-b") == []


def test_sql_repository_persists_and_queries_filters() -> None:
    repository, engine = _sqlite_repository()
    recorded = repository.record_event(_event_payload())
    repository.record_event(
        _event_payload(
            event_type="LOGIN_FAILED",
            outcome="BLOCKED",
            subject_id=None,
            credential_id=None,
            details={"error_code": "oa.credential_not_verified"},
        )
    )
    assert recorded["event_type"] == "LOGIN_SUCCEEDED"
    events = repository.list_events(
        tenant_id="tenant-a", event_type="LOGIN_FAILED", limit=10
    )
    assert len(events) == 1
    assert events[0]["subject_ref"] is None
    assert repository.list_events(
        tenant_id="tenant-a", subject_id="user-a"
    )[0]["event_type"] == "LOGIN_SUCCEEDED"
    with engine.connect() as connection:
        details = connection.execute(
            text("SELECT details FROM oa_auth_events WHERE event_type = 'LOGIN_SUCCEEDED'")
        ).scalar_one()
    assert json.loads(details) == {"credential_status": "ACTIVE"}


def test_integrated_auth_paths_emit_safe_events_and_read_route_filters() -> None:
    client, repository, sessions = _integrated_client()
    service_headers = _headers()
    login = client.post(
        "/internal/v1/auth/user-login",
        headers=service_headers,
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Current1004!",
        },
    )
    assert login.status_code == 200
    session_id = login.json()["session"]["session_id"]
    failed_login = client.post(
        "/internal/v1/auth/user-login",
        headers=service_headers,
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Incorrect1004!",
        },
    )
    assert failed_login.status_code == 401
    issued = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=service_headers,
        json={"tenant_id": "tenant-a", "subject_id": "user-a"},
    )
    assert issued.status_code == 200
    assert client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=service_headers,
        json={"session_id": session_id},
    ).status_code == 200
    assert client.post(
        f"/internal/v1/auth/user-sessions/{session_id}/revoke",
        headers=service_headers,
    ).status_code == 200
    reset = client.post(
        "/internal/v1/auth/local-credentials/reset-password",
        headers=_headers(OA_CREDENTIAL_SECURITY_WRITE_SCOPE),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "temporary_password": "Temporary1004!",
            "reason_code": "operator.recovery",
        },
    )
    assert reset.status_code == 200
    assert all(record["status"] == "REVOKED" for record in sessions.sessions.values())

    assert client.get(
        "/internal/v1/auth/security-events", params={"tenant_id": "tenant-a"}
    ).status_code == 401
    denied = client.get(
        "/internal/v1/auth/security-events",
        headers=service_headers,
        params={"tenant_id": "tenant-a"},
    )
    assert denied.status_code == 403
    response = client.get(
        "/internal/v1/auth/security-events",
        headers=_headers(OA_CREDENTIAL_SECURITY_READ_SCOPE),
        params={"tenant_id": "tenant-a", "subject_id": "user-a"},
    )
    assert response.status_code == 200
    event_types = {event["event_type"] for event in response.json()["events"]}
    assert {
        "LOGIN_SUCCEEDED",
        "SESSION_ISSUED",
        "SESSION_INTROSPECTED",
        "SESSION_REVOKED",
        "PASSWORD_RESET",
    } <= event_types
    serialized = json.dumps(repository.events).lower()
    assert "current1004" not in serialized
    assert "incorrect1004" not in serialized
    assert "temporary1004" not in serialized
    assert session_id.lower() not in serialized
    invalid_query = client.get(
        "/internal/v1/auth/security-events",
        headers=_headers(OA_CREDENTIAL_SECURITY_READ_SCOPE),
        params={"tenant_id": "bad tenant"},
    )
    assert invalid_query.status_code == 400


def test_integrated_change_failure_and_missing_session_emit_blocked_events() -> None:
    client, repository, _ = _integrated_client()
    bad_change = client.post(
        "/internal/v1/auth/local-credentials/change-password",
        headers=_headers(OA_CREDENTIAL_SECURITY_WRITE_SCOPE),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "current_password": "Incorrect1004!",
            "new_password": "Changed1004!",
        },
    )
    assert bad_change.status_code == 401
    missing = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=_headers(),
        json={"session_id": "missing-session"},
    )
    assert missing.status_code == 200
    assert missing.json()["active"] is False
    blocked = [event for event in repository.events if event["outcome"] == "BLOCKED"]
    assert {event["event_type"] for event in blocked} >= {
        "PASSWORD_CHANGED",
        "SESSION_INTROSPECTED",
    }


def test_event_validation_rejects_private_or_invalid_shapes() -> None:
    invalid_payloads = (
        _event_payload(event_type="UNKNOWN"),
        _event_payload(outcome="MAYBE"),
        _event_payload(actor_ref=""),
        _event_payload(details={"password": "private"}),
        _event_payload(details=[]),
        _event_payload(details={"active": []}),
        _event_payload(tenant_id="bad tenant"),
        _event_payload(event_type=None),
    )
    for payload in invalid_payloads:
        with pytest.raises(OaAuthEventError):
            build_auth_event(payload)
    with pytest.raises(OaAuthEventError, match="limit"):
        normalize_event_query(tenant_id="tenant-a", limit=0)
    with pytest.raises(OaAuthEventError, match="limit"):
        normalize_event_query(tenant_id="tenant-a", limit=True)
    with pytest.raises(OaAuthEventError):
        normalize_event_query(tenant_id="tenant-a", subject_id="bad subject")


def test_safe_recording_contains_repository_failure(caplog) -> None:
    class FailingRepository:
        def record_event(self, payload):
            raise OaAuthEventError(503, "oa.auth_event_repository_unavailable", "private")

    app = build_service_app(SERVICE_SPECS["nex-oa"])

    @app.get("/record")
    def record(request: Request):
        return {
            "recorded": record_auth_event_safely(
                FailingRepository(),
                event_type="LOGIN_FAILED",
                outcome="FAILED",
                request=request,
                authorization=None,
                details={"error_code": "oa.test"},
            )
        }

    with caplog.at_level(logging.ERROR):
        response = TestClient(app).get("/record")
    assert response.json() == {"recorded": False}
    assert "private" not in caplog.text
    assert record_auth_event_safely(
        None,
        event_type="LOGIN_FAILED",
        outcome="FAILED",
        request=SimpleNamespace(headers={}),
        authorization=None,
    ) is False


def test_helpers_factory_json_and_projection_edges() -> None:
    memory = build_auth_event_repository_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None)
    )
    sql = build_auth_event_repository_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=build_session_factory(build_engine("sqlite+pysqlite:///:memory:")),
        )
    )
    assert isinstance(memory, InMemoryOaAuthEventRepository)
    assert isinstance(sql, SqlAlchemyOaAuthEventRepository)
    assert auth_event_target({}) == {
        "tenant_id": None,
        "subject_id": None,
        "credential_id": None,
    }
    assert auth_event_target(
        {"tenant_id": "tenant-a", "subject_id": "subject-a"}
    ) == {
        "tenant_id": "tenant-a",
        "subject_id": "subject-a",
        "credential_id": None,
    }
    assert _json_loads({"active": True}) == {"active": True}
    assert _json_loads(None) == {}
    assert _json_loads("bad") == {}
    assert _json_loads("[]") == {}
    postgres_session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    assert _json_sql_expression(postgres_session, "details") == "CAST(:details AS JSONB)"
    assert _timestamp_to_wire(datetime(2026, 10, 1)) == "2026-10-01T00:00:00Z"
    event = build_auth_event(_event_payload(tenant_id=None, subject_id=None))
    assert project_auth_event(event)["tenant_ref"] is None


def test_sql_repository_reports_missing_table() -> None:
    repository = SqlAlchemyOaAuthEventRepository(
        build_session_factory(build_engine("sqlite+pysqlite:///:memory:"))
    )
    with pytest.raises(OaAuthEventError) as write_error:
        repository.record_event(_event_payload())
    with pytest.raises(OaAuthEventError) as read_error:
        repository.list_events(tenant_id="tenant-a")
    assert write_error.value.retryable is True
    assert read_error.value.retryable is True


def test_nex_oa_entrypoint_registers_auth_event_route() -> None:
    from nex_oa.main import app

    assert "/internal/v1/auth/security-events" in {route.path for route in app.routes}
