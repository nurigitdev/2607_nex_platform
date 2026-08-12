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
    SqlAlchemyOaTenantMembershipRegistry,
)
from nex_oa.sessions import (
    InMemoryOaSessionRegistry,
    OA_BROWSER_SESSION_SCHEMA_VERSION,
    OA_SESSION_ISSUE_SCHEMA_VERSION,
    OA_USER_SESSION_SCHEMA_VERSION,
    OaSessionError,
    SqlAlchemyOaSessionRegistry,
    build_browser_session_snapshot,
    build_oa_session_registry_for_runtime,
    build_session_record,
    normalize_session_issue_request,
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


def test_session_record_helpers_are_deterministic_and_validate_shape() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id="user-a",
        scopes=["workspace:use"],
        roles=[],
        issued_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
    )
    record = build_session_record(issued.claims)
    snapshot = build_browser_session_snapshot(record)

    assert record["session_schema_version"] == OA_USER_SESSION_SCHEMA_VERSION
    assert record["session_id"] == stable_session_id(issued.claims)
    assert snapshot["metadata"] == safe_session_metadata()

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

    assert readback is not None
    assert readback["session"] == issued["session"]
    assert registry.get_session("missing") is None
    with engine.connect() as connection:
        table_dump = "\n".join(
            str(row)
            for row in connection.execute(
                text("SELECT scopes, roles, metadata FROM oa_user_sessions")
            ).fetchall()
        )
    assert "workspace:use" in table_dump
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
    assert "/internal/v1/auth/user-sessions/{session_id}" in paths
