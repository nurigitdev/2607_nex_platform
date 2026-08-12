from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_oa.memberships import (
    InMemoryOaTenantMembershipRegistry,
    OaMembershipError,
    SqlAlchemyOaTenantMembershipRegistry,
)
from nex_oa.sessions import (
    InMemoryOaSessionRegistry,
    OA_BROWSER_SESSION_SCHEMA_VERSION,
    OA_SESSION_ISSUE_SCHEMA_VERSION,
    OA_SESSION_INTROSPECTION_SCHEMA_VERSION,
    OA_SESSION_REVOCATION_SCHEMA_VERSION,
    OA_USER_SESSION_SCHEMA_VERSION,
    OaSessionError,
    SqlAlchemyOaSessionRegistry,
    build_browser_session_snapshot,
    build_oa_session_registry_for_runtime,
    build_session_record,
    build_session_introspection_response,
    build_session_revocation_response,
    build_revoked_session_record,
    normalize_session_issue_request,
    normalize_session_introspection_request,
    register_user_session_routes,
    safe_session_metadata,
    stable_session_id,
    _json_loads,
    _json_sql_expression,
    _session_from_row,
)
from nex_runtime import (
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
)


ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def browser_session_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_oa"
            / "browser_session.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def auth_headers(*, audience: str = "nex-oa") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def memory_membership_registry() -> InMemoryOaTenantMembershipRegistry:
    registry = InMemoryOaTenantMembershipRegistry()
    registry.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "roles": ["employee", "analyst"],
            "scopes": ["workspace:use", "documents:read"],
        }
    )
    registry.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "disabled-user",
            "membership_status": "DISABLED",
            "scopes": ["workspace:use"],
        }
    )
    return registry


def build_client(registry: InMemoryOaSessionRegistry | None = None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_user_session_routes(
        app,
        registry=registry or InMemoryOaSessionRegistry(memory_membership_registry()),
    )
    return TestClient(app)


def sqlite_session_registry() -> tuple[SqlAlchemyOaSessionRegistry, object]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE oa_tenants (
                    tenant_id TEXT PRIMARY KEY,
                    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant',
                    display_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE oa_subjects (
                    tenant_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    display_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, subject_ref_type, subject_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE oa_tenant_memberships (
                    tenant_id TEXT NOT NULL,
                    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    subject_id TEXT NOT NULL,
                    membership_schema_version TEXT NOT NULL DEFAULT 'oa_tenant_membership.v1',
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    roles TEXT NOT NULL DEFAULT '[]',
                    scopes TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, subject_ref_type, subject_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE oa_user_sessions (
                    session_id TEXT PRIMARY KEY,
                    session_schema_version TEXT NOT NULL DEFAULT 'oa_user_session.v1',
                    tenant_id TEXT NOT NULL,
                    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    subject_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    issuer TEXT NOT NULL DEFAULT 'nex-oa',
                    audience TEXT NOT NULL DEFAULT 'nex-ae-api',
                    token_use TEXT NOT NULL DEFAULT 'user',
                    scopes TEXT NOT NULL DEFAULT '[]',
                    roles TEXT NOT NULL DEFAULT '[]',
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    auth_time TEXT NOT NULL,
                    revoked_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    membership = SqlAlchemyOaTenantMembershipRegistry(build_session_factory(engine))
    membership.ensure_membership(
        {
            "tenant_id": "tenant-sql",
            "subject_id": "user-sql",
            "roles": ["employee"],
            "scopes": ["workspace:use", "documents:read"],
        }
    )
    return (
        SqlAlchemyOaSessionRegistry(
            build_session_factory(engine),
            membership_registry=membership,
        ),
        engine,
    )


def test_session_issue_snapshot_matches_browser_contract_and_hides_credentials() -> None:
    registry = InMemoryOaSessionRegistry(memory_membership_registry())
    issued = registry.issue_session(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "requested_scopes": ["workspace:use"],
            "ttl_seconds": 1800,
        }
    )
    session = issued["session"]
    serialized = json.dumps(issued, ensure_ascii=False)

    Draft202012Validator(browser_session_schema()).validate(session)
    assert issued["session_issue_schema_version"] == OA_SESSION_ISSUE_SCHEMA_VERSION
    assert session["browser_session_schema_version"] == OA_BROWSER_SESSION_SCHEMA_VERSION
    assert session["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert session["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert session["scopes"] == ["workspace:use"]
    assert session["roles"] == ["employee", "analyst"]
    assert issued["credential_delivery"]["raw_token_included"] is False
    assert issued["metadata"]["raw_token_stored"] is False
    assert "access_token" not in serialized
    assert "secret-value" not in serialized


def test_session_issue_requires_active_membership_and_granted_scopes() -> None:
    registry = InMemoryOaSessionRegistry(memory_membership_registry())

    for payload, status_code, error_code in [
        ({"tenant_id": "tenant-a", "subject_id": "missing"}, 404, "oa.membership_not_found"),
        ({"tenant_id": "tenant-a", "subject_id": "disabled-user"}, 403, "oa.membership_inactive"),
        (
            {
                "tenant_id": "tenant-a",
                "subject_id": "user-a",
                "requested_scopes": ["admin:all"],
            },
            403,
            "oa.session_scope_not_granted",
        ),
        ({"tenant_id": "tenant a", "subject_id": "user-a"}, 400, "oa.subject_ref_invalid"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "ttl_seconds": True}, 400, "oa.session_ttl_invalid"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "ttl_seconds": 0}, 400, "oa.session_ttl_invalid"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "ttl_seconds": 86401}, 400, "oa.session_ttl_invalid"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "requested_scopes": []}, 400, "oa.session_list_invalid"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "password": "secret-value"}, 400, "oa.private_identity_payload_rejected"),
        ({"tenant_id": "tenant-a", "subject_id": "user-a", "unknown": "value"}, 400, "oa.session_issue_field_unsupported"),
    ]:
        with pytest.raises(OaSessionError) as exc:
            registry.issue_session(payload)
        assert exc.value.status_code == status_code
        assert exc.value.error_code == error_code


def test_session_issue_maps_membership_registry_failure_and_bad_snapshot() -> None:
    class FailingMembershipRegistry:
        def get_membership(self, **_: object) -> dict[str, object] | None:
            raise OaMembershipError(
                status_code=503,
                error_code="oa.membership_registry_unavailable",
                detail="membership unavailable",
                retryable=True,
            )

    class BadSnapshotMembershipRegistry:
        def get_membership(self, **_: object) -> dict[str, object] | None:
            return {"membership_snapshot_schema_version": "broken.v1"}

    failing = InMemoryOaSessionRegistry(FailingMembershipRegistry())
    bad_snapshot = InMemoryOaSessionRegistry(BadSnapshotMembershipRegistry())

    with pytest.raises(OaSessionError) as unavailable:
        failing.issue_session({"tenant_id": "tenant-a", "subject_id": "user-a"})
    assert unavailable.value.status_code == 503
    assert unavailable.value.error_code == "oa.membership_registry_unavailable"
    assert unavailable.value.retryable is True

    with pytest.raises(OaSessionError) as invalid:
        bad_snapshot.issue_session({"tenant_id": "tenant-a", "subject_id": "user-a"})
    assert invalid.value.status_code == 500
    assert invalid.value.error_code == "oa.membership_snapshot_invalid"


def test_session_routes_require_service_claim_issue_and_readback() -> None:
    client = build_client()
    missing_auth = client.post("/internal/v1/auth/user-sessions/issue", json={})
    wrong_audience = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=auth_headers(audience="nex-cx"),
        json={},
    )
    issued = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=auth_headers(),
        json={"tenant_id": "tenant-a", "subject_id": "user-a"},
    )
    session_id = issued.json()["session"]["session_id"]
    readback = client.get(
        f"/internal/v1/auth/user-sessions/{session_id}",
        headers=auth_headers(),
    )
    missing = client.get(
        "/internal/v1/auth/user-sessions/missing",
        headers=auth_headers(),
    )
    get_missing_auth = client.get(f"/internal/v1/auth/user-sessions/{session_id}")

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert issued.status_code == 200
    assert issued.json()["trace_id"] == TRACE_ID
    assert issued.json()["request_id"] == REQUEST_ID
    assert readback.status_code == 200
    assert readback.json()["session"] == issued.json()["session"]
    assert readback.json()["membership_snapshot_schema_version"] is None
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "oa.session_not_found"
    assert get_missing_auth.status_code == 401


def test_session_routes_map_registry_errors_to_problem_json() -> None:
    registry = InMemoryOaSessionRegistry(memory_membership_registry())
    failure = OaSessionError(
        status_code=503,
        error_code="oa.session_registry_unavailable",
        detail="registry failed",
        retryable=True,
    )

    def raise_failure(*_: object, **__: object) -> dict[str, object]:
        raise failure

    registry.issue_session = raise_failure
    registry.get_session = raise_failure
    registry.introspect_session = raise_failure
    registry.revoke_session = raise_failure
    client = build_client(registry)

    issue = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=auth_headers(),
        json={},
    )
    readback = client.get(
        "/internal/v1/auth/user-sessions/session-a",
        headers=auth_headers(),
    )
    introspection = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(),
        json={"session_id": "session-a"},
    )
    revocation = client.post(
        "/internal/v1/auth/user-sessions/session-a/revoke",
        headers=auth_headers(),
    )

    assert issue.status_code == 503
    assert issue.json()["error_code"] == "oa.session_registry_unavailable"
    assert readback.status_code == 503
    assert readback.json()["retryable"] is True
    assert introspection.status_code == 503
    assert introspection.json()["title"] == "OA session request failed"
    assert revocation.status_code == 503
    assert revocation.json()["error_code"] == "oa.session_registry_unavailable"


def test_session_introspection_reports_active_inactive_and_hides_credentials() -> None:
    registry = InMemoryOaSessionRegistry(memory_membership_registry())
    issued = registry.issue_session(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "requested_scopes": ["workspace:use"],
        }
    )
    session_id = issued["session"]["session_id"]

    active = registry.introspect_session({"session_id": session_id})
    missing = registry.introspect_session({"session_id": "missing-session"})

    revoked_record = dict(registry.sessions[session_id])
    revoked_record.update(
        {
            "session_id": "revoked-session",
            "status": "REVOKED",
            "revoked_at": "2026-08-12T00:00:00Z",
        }
    )
    registry.sessions["revoked-session"] = revoked_record
    revoked = registry.introspect_session({"session_id": "revoked-session"})

    expired_record = dict(registry.sessions[session_id])
    expired_record.update(
        {
            "session_id": "expired-session",
            "expires_at": "2000-01-01T00:00:00Z",
        }
    )
    registry.sessions["expired-session"] = expired_record
    expired = registry.introspect_session({"session_id": "expired-session"})

    naive_future_record = dict(registry.sessions[session_id])
    naive_future_record.update(
        {
            "session_id": "naive-future-session",
            "expires_at": "2999-01-01T00:00:00",
        }
    )
    registry.sessions["naive-future-session"] = naive_future_record
    naive_future = registry.introspect_session({"session_id": "naive-future-session"})

    serialized = json.dumps(active, ensure_ascii=False)
    assert active["session_introspection_schema_version"] == (
        OA_SESSION_INTROSPECTION_SCHEMA_VERSION
    )
    assert active["active"] is True
    assert active["inactive_reason"] is None
    assert active["session"] == issued["session"]
    assert active["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert active["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert active["credential_delivery"] == {
        "raw_token_included": False,
        "cookie_value_included": False,
        "service_credential_included": False,
        "ae_cookie_owner": True,
    }
    assert active["metadata"]["session_id_authoritative"] is True
    assert active["metadata"]["raw_token_stored"] is False
    assert missing["active"] is False
    assert missing["inactive_reason"] == "not_found"
    assert missing["session"] is None
    assert revoked["active"] is False
    assert revoked["inactive_reason"] == "revoked"
    assert expired["active"] is False
    assert expired["inactive_reason"] == "expired"
    assert naive_future["active"] is True
    assert "access_token" not in serialized
    assert "secret-value" not in serialized


def test_session_introspection_request_validation_rejects_private_payloads() -> None:
    assert normalize_session_introspection_request({"session_id": " session-a "}) == {
        "session_id": "session-a"
    }
    for payload, error_code in [
        ({"session_id": ""}, "oa.session_field_invalid"),
        (
            {"session_id": "session-a", "tenant_id": "tenant-a"},
            "oa.session_introspection_field_unsupported",
        ),
        (
            {"session_id": "session-a", "cookie": "secret-value"},
            "oa.private_identity_payload_rejected",
        ),
    ]:
        with pytest.raises(OaSessionError) as exc:
            normalize_session_introspection_request(payload)
        assert exc.value.error_code == error_code
        assert str(exc.value) == exc.value.detail


def test_session_introspection_route_requires_service_claim_and_returns_context() -> None:
    client = build_client()
    issued = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=auth_headers(),
        json={"tenant_id": "tenant-a", "subject_id": "user-a"},
    )
    session_id = issued.json()["session"]["session_id"]

    missing_auth = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        json={"session_id": session_id},
    )
    wrong_audience = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(audience="nex-cx"),
        json={"session_id": session_id},
    )
    active = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(),
        json={"session_id": session_id},
    )
    missing = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(),
        json={"session_id": "missing"},
    )
    rejected = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(),
        json={"session_id": session_id, "token": "secret-value"},
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert active.status_code == 200
    assert active.json()["active"] is True
    assert active.json()["trace_id"] == TRACE_ID
    assert active.json()["request_id"] == REQUEST_ID
    assert missing.status_code == 200
    assert missing.json()["inactive_reason"] == "not_found"
    assert rejected.status_code == 400
    assert rejected.json()["error_code"] == "oa.private_identity_payload_rejected"


def test_session_revocation_marks_existing_sessions_idempotently() -> None:
    registry = InMemoryOaSessionRegistry(memory_membership_registry())
    issued = registry.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )
    session_id = issued["session"]["session_id"]

    first = registry.revoke_session(session_id)
    second = registry.revoke_session(session_id)
    missing = registry.revoke_session("missing-session")
    introspection = registry.introspect_session({"session_id": session_id})
    serialized = json.dumps(first, ensure_ascii=False)

    assert first["session_revocation_schema_version"] == (
        OA_SESSION_REVOCATION_SCHEMA_VERSION
    )
    assert first["session_id"] == session_id
    assert first["revoked"] is True
    assert first["already_revoked"] is False
    assert first["idempotent"] is True
    assert first["active"] is False
    assert first["inactive_reason"] == "revoked"
    assert first["session"]["status"] == "REVOKED"
    assert first["revoked_at"] is not None
    assert first["metadata"]["session_revocation_authoritative"] is True
    assert second["revoked"] is True
    assert second["already_revoked"] is True
    assert second["revoked_at"] == first["revoked_at"]
    assert missing["revoked"] is False
    assert missing["already_revoked"] is False
    assert missing["inactive_reason"] == "not_found"
    assert missing["metadata"]["session_revocation_authoritative"] is False
    assert introspection["active"] is False
    assert introspection["inactive_reason"] == "revoked"
    assert "access_token" not in serialized
    assert "secret-value" not in serialized


def test_session_revocation_route_requires_claim_and_updates_introspection() -> None:
    client = build_client()
    issued = client.post(
        "/internal/v1/auth/user-sessions/issue",
        headers=auth_headers(),
        json={"tenant_id": "tenant-a", "subject_id": "user-a"},
    )
    session_id = issued.json()["session"]["session_id"]

    missing_auth = client.post(f"/internal/v1/auth/user-sessions/{session_id}/revoke")
    wrong_audience = client.post(
        f"/internal/v1/auth/user-sessions/{session_id}/revoke",
        headers=auth_headers(audience="nex-cx"),
    )
    revoked = client.post(
        f"/internal/v1/auth/user-sessions/{session_id}/revoke",
        headers=auth_headers(),
    )
    repeated = client.post(
        f"/internal/v1/auth/user-sessions/{session_id}/revoke",
        headers=auth_headers(),
    )
    missing = client.post(
        "/internal/v1/auth/user-sessions/missing/revoke",
        headers=auth_headers(),
    )
    introspection = client.post(
        "/internal/v1/auth/user-sessions/introspect",
        headers=auth_headers(),
        json={"session_id": session_id},
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert revoked.json()["trace_id"] == TRACE_ID
    assert revoked.json()["request_id"] == REQUEST_ID
    assert repeated.status_code == 200
    assert repeated.json()["already_revoked"] is True
    assert missing.status_code == 200
    assert missing.json()["inactive_reason"] == "not_found"
    assert introspection.status_code == 200
    assert introspection.json()["active"] is False
    assert introspection.json()["inactive_reason"] == "revoked"


def test_session_record_helpers_are_deterministic_and_validate_shape() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        scopes=["workspace:use"],
        roles=[],
        issued_at=datetime(2999, 8, 12, 12, 0, tzinfo=UTC),
    )
    record = build_session_record(issued.claims)
    snapshot = build_browser_session_snapshot(record)

    assert record["session_schema_version"] == OA_USER_SESSION_SCHEMA_VERSION
    assert record["session_id"] == stable_session_id(issued.claims)
    assert snapshot["metadata"] == safe_session_metadata()
    assert build_session_introspection_response(record)["active"] is True

    expired = {**record, "status": "EXPIRED"}
    assert build_session_introspection_response(expired)["inactive_reason"] == "expired"
    revoked_record, already_revoked, update_required = build_revoked_session_record(
        record
    )
    repeated_record, repeated_already_revoked, repeated_update_required = (
        build_revoked_session_record(revoked_record)
    )
    revocation = build_session_revocation_response(
        revoked_record,
        session_id=str(revoked_record["session_id"]),
        already_revoked=already_revoked,
    )

    assert revoked_record["status"] == "REVOKED"
    assert already_revoked is False
    assert update_required is True
    assert repeated_record == revoked_record
    assert repeated_already_revoked is True
    assert repeated_update_required is False
    assert revocation["revoked"] is True
    assert revocation["inactive_reason"] == "revoked"

    for mutated, error_code in [
        ({**record, "status": "LOCKED"}, "oa.session_status_invalid"),
        ({**record, "tenant_ref": None}, "oa.session_ref_invalid"),
        ({**record, "tenant_ref": {"type": "bad", "id": "tenant-a"}}, "oa.session_ref_invalid"),
        ({**record, "scopes": "workspace:use"}, "oa.session_list_invalid"),
        ({**record, "roles": [3]}, "oa.session_field_invalid"),
        ({**record, "session_id": ""}, "oa.session_field_invalid"),
    ]:
        with pytest.raises(OaSessionError) as exc:
            build_browser_session_snapshot(mutated)
        assert exc.value.error_code == error_code


def test_sqlalchemy_session_registry_persists_session_without_raw_token() -> None:
    registry, engine = sqlite_session_registry()
    issued = registry.issue_session(
        {"tenant_id": "tenant-sql", "subject_id": "user-sql"}
    )
    session_id = issued["session"]["session_id"]
    readback = registry.get_session(session_id)
    introspection = registry.introspect_session({"session_id": session_id})
    missing_introspection = registry.introspect_session({"session_id": "missing"})
    missing_revocation = registry.revoke_session("missing")
    revocation = registry.revoke_session(session_id)
    repeated_revocation = registry.revoke_session(session_id)
    revoked_introspection = registry.introspect_session({"session_id": session_id})

    assert readback is not None
    assert readback["session"] == issued["session"]
    assert introspection["active"] is True
    assert introspection["session"] == issued["session"]
    assert missing_introspection["active"] is False
    assert missing_introspection["inactive_reason"] == "not_found"
    assert missing_revocation["revoked"] is False
    assert missing_revocation["inactive_reason"] == "not_found"
    assert revocation["revoked"] is True
    assert revocation["already_revoked"] is False
    assert repeated_revocation["already_revoked"] is True
    assert revoked_introspection["active"] is False
    assert revoked_introspection["inactive_reason"] == "revoked"
    assert registry.get_session("missing") is None
    with engine.connect() as connection:
        table_dump = "\n".join(
            str(row)
            for row in connection.execute(
                text("SELECT scopes, roles, metadata FROM oa_user_sessions")
            ).fetchall()
        )
        status_row = connection.execute(
            text(
                """
                SELECT status, revoked_at
                FROM oa_user_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().one()
    assert "workspace:use" in table_dump
    assert status_row["status"] == "REVOKED"
    assert status_row["revoked_at"] is not None
    assert "access_token" not in table_dump
    assert "secret-value" not in table_dump


def test_sqlalchemy_session_registry_reports_unavailable_and_rolls_back(monkeypatch) -> None:
    registry = SqlAlchemyOaSessionRegistry(
        lambda: None,
        membership_registry=memory_membership_registry(),
    )
    monkeypatch.setattr(
        registry,
        "_run_in_transaction",
        lambda operation: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )
    with pytest.raises(OaSessionError) as issue_failure:
        registry.issue_session({"tenant_id": "tenant-a", "subject_id": "user-a"})
    assert issue_failure.value.error_code == "oa.session_registry_unavailable"

    monkeypatch.setattr(
        registry,
        "_session_factory",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )
    with pytest.raises(OaSessionError) as read_failure:
        registry.get_session("session-a")
    assert read_failure.value.error_code == "oa.session_registry_unavailable"
    with pytest.raises(OaSessionError) as introspection_failure:
        registry.introspect_session({"session_id": "session-a"})
    assert introspection_failure.value.error_code == "oa.session_registry_unavailable"
    with pytest.raises(OaSessionError) as revocation_failure:
        registry.revoke_session("session-a")
    assert revocation_failure.value.error_code == "oa.session_registry_unavailable"

    class RollbackSession:
        def __init__(self) -> None:
            self.rolled_back = False
            self.closed = False

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    rollback_session = RollbackSession()
    rollback_registry = SqlAlchemyOaSessionRegistry(
        lambda: rollback_session,
        membership_registry=memory_membership_registry(),
    )
    with pytest.raises(RuntimeError):
        rollback_registry._run_in_transaction(
            lambda session: (_ for _ in ()).throw(RuntimeError("rollback"))
        )
    assert rollback_session.rolled_back is True
    assert rollback_session.closed is True


def test_session_json_timestamp_and_factory_helpers_cover_storage_variants() -> None:
    assert _json_loads(None, default={"safe": True}) == {"safe": True}
    assert _json_loads({"safe": True}, default={}) == {"safe": True}
    assert _json_loads(b'["workspace:use"]', default=[]) == ["workspace:use"]
    assert _json_loads(123, default=[]) == []

    row = {
        "session_schema_version": OA_USER_SESSION_SCHEMA_VERSION,
        "session_id": "session-a",
        "tenant_id": "tenant-a",
        "subject_ref_type": "oa.user",
        "subject_id": "user-a",
        "status": "ACTIVE",
        "issuer": "nex-oa",
        "audience": "nex-ae-api",
        "token_use": "user",
        "scopes": ["workspace:use"],
        "roles": ["employee"],
        "issued_at": datetime(2026, 8, 12, 1, 2, 3),
        "expires_at": datetime(2026, 8, 12, 2, 2, 3, tzinfo=UTC),
        "auth_time": "2026-08-12T01:02:03Z",
        "revoked_at": None,
        "metadata": {"safe": True},
        "created_at": "2026-08-12T01:02:03Z",
        "updated_at": "2026-08-12T01:02:03Z",
    }

    assert _session_from_row(row)["issued_at"].endswith("Z")

    class PostgresSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    assert _json_sql_expression(PostgresSession(), "metadata") == "CAST(:metadata AS JSONB)"

    memory = build_oa_session_registry_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None),
        membership_registry=memory_membership_registry(),
    )
    postgres = build_oa_session_registry_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=lambda: None,
        ),
        membership_registry=memory_membership_registry(),
    )

    assert isinstance(memory, InMemoryOaSessionRegistry)
    assert isinstance(postgres, SqlAlchemyOaSessionRegistry)


def test_nex_oa_entrypoint_registers_session_routes() -> None:
    import nex_oa.main as main

    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/internal/v1/auth/user-sessions/issue" in paths
    assert "/internal/v1/auth/user-sessions/introspect" in paths
    assert "/internal/v1/auth/user-sessions/{session_id}/revoke" in paths
    assert "/internal/v1/auth/user-sessions/{session_id}" in paths
