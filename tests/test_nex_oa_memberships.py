from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from nex_oa.memberships import (
    DEFAULT_MEMBERSHIP_ROLES,
    DEFAULT_MEMBERSHIP_SCOPES,
    OA_MEMBERSHIP_AUTHORITY_WRITE_SCOPE,
    OA_TENANT_MEMBERSHIP_SCHEMA_VERSION,
    OA_TENANT_MEMBERSHIP_SNAPSHOT_SCHEMA_VERSION,
    InMemoryOaTenantMembershipRegistry,
    OaMembershipError,
    SqlAlchemyOaTenantMembershipRegistry,
    _json_loads,
    _json_sql_expression,
    _membership_from_row,
    build_membership_record,
    build_membership_snapshot,
    build_tenant_membership_registry_for_runtime,
    normalize_membership_status,
    register_identity_membership_routes,
)
from nex_oa.subjects import (
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    InMemoryOaSubjectRegistry,
    SubjectRegistryError,
    build_subject_record,
    build_subject_registry_snapshot,
    build_tenant_record,
)
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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers(
    *,
    audience: str = "nex-oa",
    bootstrap_scope: bool = True,
    authority_scope: bool = False,
) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE]
    if bootstrap_scope:
        scopes.append(OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE)
    if authority_scope:
        scopes.append(OA_MEMBERSHIP_AUTHORITY_WRITE_SCOPE)
    issued = issue_mock_service_token(
        service_id="nex-ae-api", audience=audience, scopes=scopes
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def subject_snapshot() -> dict[str, object]:
    tenant = build_tenant_record(
        {"tenant_id": "tenant-a", "tenant_display_name": "Tenant A"}
    )
    subject = build_subject_record(
        {"subject_id": "user-a", "subject_display_name": "User A"},
        tenant=tenant,
    )
    return build_subject_registry_snapshot(tenant=tenant, subject=subject)


def build_client(
    registry: InMemoryOaTenantMembershipRegistry | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_membership_routes(
        app,
        registry=registry or InMemoryOaTenantMembershipRegistry(),
    )
    return TestClient(app)


def sqlite_membership_registry() -> tuple[SqlAlchemyOaTenantMembershipRegistry, object]:
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
                    revision INTEGER NOT NULL DEFAULT 1,
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
                    revision INTEGER NOT NULL DEFAULT 1,
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
    return SqlAlchemyOaTenantMembershipRegistry(build_session_factory(engine)), engine


def test_membership_record_and_snapshot_are_safe() -> None:
    record = build_membership_record(
        {
            "roles": ["employee", "reviewer"],
            "scopes": ["workspace:use", "documents:read"],
            "membership_metadata": {"team": "ops"},
        },
        subject_snapshot=subject_snapshot(),
    )
    snapshot = build_membership_snapshot(
        membership=record,
        subject_snapshot=subject_snapshot(),
    )
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert record["membership_schema_version"] == OA_TENANT_MEMBERSHIP_SCHEMA_VERSION
    assert snapshot["membership_snapshot_schema_version"] == (
        OA_TENANT_MEMBERSHIP_SNAPSHOT_SCHEMA_VERSION
    )
    assert snapshot["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert snapshot["subject_ref"] == {"type": "oa.user", "id": "user-a"}
    assert snapshot["membership"]["roles"] == ["employee", "reviewer"]
    assert snapshot["membership"]["scopes"] == ["workspace:use", "documents:read"]
    assert snapshot["capabilities"]["stable_tenant_membership"] is True
    assert snapshot["capabilities"]["oa_session_issuance"] is True
    assert snapshot["capabilities"]["password_login"] is True
    assert snapshot["next_slice"] == "1212_oa_identity_trust_hardening_boundary"
    assert "secret-value" not in serialized
    assert "raw_token" not in serialized


def test_in_memory_membership_registry_is_idempotent_and_readable() -> None:
    registry = InMemoryOaTenantMembershipRegistry()
    first = registry.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "tenant_display_name": "Tenant A",
            "subject_display_name": "User A",
        }
    )
    duplicate = registry.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "roles": ["changed"],
        }
    )

    assert duplicate == first
    assert first["membership"]["roles"] == list(DEFAULT_MEMBERSHIP_ROLES)
    assert first["membership"]["scopes"] == list(DEFAULT_MEMBERSHIP_SCOPES)
    assert registry.get_membership(tenant_id="tenant-a", subject_id="user-a") == first
    assert registry.get_membership(tenant_id="tenant-a", subject_id="missing") is None


@pytest.mark.parametrize("registry_kind", ["memory", "sqlite"])
def test_membership_authority_replacement_is_revision_guarded_and_replay_safe(
    registry_kind,
) -> None:
    registry = (
        InMemoryOaTenantMembershipRegistry()
        if registry_kind == "memory"
        else sqlite_membership_registry()[0]
    )
    created = registry.ensure_membership(
        {
            "tenant_id": "tenant-agent",
            "subject_id": "agent-ia",
            "roles": ["nex-agent", "nex-agent-ia"],
            "scopes": ["work:delegate"],
        }
    )

    updated = registry.replace_authority(
        tenant_id="tenant-agent",
        subject_id="agent-ia",
        payload={
            "expected_revision": created["membership"]["revision"],
            "roles": ["nex-agent", "nex-agent-ia"],
            "scopes": ["work:claim", "work:delegate"],
        },
    )
    replayed = registry.replace_authority(
        tenant_id="tenant-agent",
        subject_id="agent-ia",
        payload={
            "expected_revision": updated["membership"]["revision"],
            "roles": ["nex-agent", "nex-agent-ia"],
            "scopes": ["work:claim", "work:delegate"],
        },
    )

    assert updated["membership"]["revision"] == 2
    assert updated["membership"]["scopes"] == ["work:claim", "work:delegate"]
    assert replayed["membership"] == updated["membership"]

    with pytest.raises(OaMembershipError) as conflict:
        registry.replace_authority(
            tenant_id="tenant-agent",
            subject_id="agent-ia",
            payload={
                "expected_revision": 1,
                "roles": ["nex-agent"],
                "scopes": ["work:delegate"],
            },
        )
    assert conflict.value.error_code == "oa.membership_authority_revision_conflict"


@pytest.mark.parametrize("registry_kind", ["memory", "sqlite"])
def test_membership_authority_replacement_rejects_missing_membership(
    registry_kind,
) -> None:
    registry = (
        InMemoryOaTenantMembershipRegistry()
        if registry_kind == "memory"
        else sqlite_membership_registry()[0]
    )

    with pytest.raises(OaMembershipError) as raised:
        registry.replace_authority(
            tenant_id="tenant-missing",
            subject_id="agent-missing",
            payload={
                "expected_revision": 1,
                "roles": ["nex-agent"],
                "scopes": ["work:claim"],
            },
        )

    assert raised.value.error_code == "oa.membership_not_found"


def test_membership_authority_api_requires_lifecycle_scope_and_updates_profile() -> None:
    client = build_client()
    client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-authority",
            "subject_id": "agent-authority",
            "roles": ["nex-agent", "nex-agent-ia"],
            "scopes": ["work:delegate"],
        },
    )
    path = (
        "/internal/v1/identity/memberships/tenants/tenant-authority/"
        "subjects/agent-authority/authority"
    )
    payload = {
        "expected_revision": 1,
        "roles": ["nex-agent", "nex-agent-ia"],
        "scopes": ["work:claim", "work:delegate"],
    }

    denied = client.put(path, headers=auth_headers(), json=payload)
    updated = client.put(
        path,
        headers=auth_headers(authority_scope=True),
        json=payload,
    )

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "TOKEN_SCOPE_MISSING"
    assert updated.status_code == 200
    assert updated.json()["membership"]["revision"] == 2
    assert updated.json()["membership"]["scopes"] == [
        "work:claim",
        "work:delegate",
    ]

    conflict = client.put(
        path,
        headers=auth_headers(authority_scope=True),
        json={**payload, "scopes": ["work:delegate"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == (
        "oa.membership_authority_revision_conflict"
    )


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({}, "oa.membership_authority_field_missing"),
        (
            {
                "expected_revision": 1,
                "roles": ["agent"],
                "scopes": ["work"],
                "unexpected": True,
            },
            "oa.membership_authority_field_invalid",
        ),
        (
            {"expected_revision": True, "roles": ["agent"], "scopes": ["work"]},
            "oa.membership_authority_revision_invalid",
        ),
        (
            {"expected_revision": 0, "roles": ["agent"], "scopes": ["work"]},
            "oa.membership_authority_revision_invalid",
        ),
        (
            {"expected_revision": 1, "roles": [], "scopes": ["work"]},
            "oa.membership_list_invalid",
        ),
        (
            {
                "expected_revision": 1,
                "roles": ["agent", "agent"],
                "scopes": ["work"],
            },
            "oa.membership_authority_duplicate",
        ),
    ],
)
def test_membership_authority_replacement_rejects_invalid_contract(
    payload, error_code
) -> None:
    registry = InMemoryOaTenantMembershipRegistry()
    registry.ensure_membership(
        {"tenant_id": "tenant-a", "subject_id": "subject-a"}
    )

    with pytest.raises(OaMembershipError) as raised:
        registry.replace_authority(
            tenant_id="tenant-a",
            subject_id="subject-a",
            payload=payload,
        )
    assert raised.value.error_code == error_code


def test_membership_validation_rejects_invalid_status_refs_and_private_payloads() -> None:
    assert normalize_membership_status("disabled") == "DISABLED"
    assert str(
        OaMembershipError(
            status_code=400,
            error_code="example",
            detail="plain detail",
        )
    ) == "plain detail"

    for payload, error_code in [
        ({"membership_status": "LOCKED"}, "oa.membership_status_invalid"),
        ({"roles": []}, "oa.membership_list_invalid"),
        ({"scopes": "workspace:use"}, "oa.membership_list_invalid"),
        ({"roles": [3]}, "oa.membership_field_invalid"),
        ({"roles": [" "]}, "oa.membership_field_invalid"),
        ({"membership_metadata": None}, None),
        ({"membership_metadata": []}, "oa.membership_metadata_invalid"),
        ({"membership_metadata": {"bad": {1, 2}}}, "oa.membership_metadata_invalid"),
        ({"membership_metadata": {"api_token": "secret-value"}}, "oa.private_identity_payload_rejected"),
    ]:
        if error_code is None:
            assert build_membership_record(payload, subject_snapshot=subject_snapshot())[
                "metadata"
            ] == {}
            continue
        with pytest.raises(OaMembershipError) as exc:
            build_membership_record(payload, subject_snapshot=subject_snapshot())
        assert exc.value.error_code == error_code

    with pytest.raises(OaMembershipError) as bad_ref:
        build_membership_snapshot(
            membership={
                "tenant_ref": {"type": "bad", "id": "tenant-a"},
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
            subject_snapshot=subject_snapshot(),
        )
    assert bad_ref.value.error_code == "oa.membership_ref_invalid"

    with pytest.raises(OaMembershipError) as missing_ref:
        build_membership_snapshot(
            membership={
                "tenant_ref": None,
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
            subject_snapshot=subject_snapshot(),
        )
    assert missing_ref.value.error_code == "oa.membership_ref_invalid"

    with pytest.raises(OaMembershipError) as bad_ref_id:
        build_membership_snapshot(
            membership={
                "tenant_ref": {"type": "oa.tenant", "id": "tenant a"},
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
            subject_snapshot=subject_snapshot(),
        )
    assert bad_ref_id.value.error_code == "oa.subject_ref_invalid"


def test_membership_api_requires_service_claim_and_supports_readback() -> None:
    client = build_client()
    missing_auth = client.post("/internal/v1/identity/memberships/ensure", json={})
    wrong_audience = client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=auth_headers(audience="nex-cx"),
        json={},
    )
    missing_scope = client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=auth_headers(bootstrap_scope=False),
        json={},
    )
    invalid = client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=auth_headers(),
        json={"roles": []},
    )
    ensure = client.post(
        "/internal/v1/identity/memberships/ensure",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-route",
            "subject_id": "user-route",
            "roles": ["employee"],
            "scopes": ["workspace:use"],
        },
    )
    readback = client.get(
        "/internal/v1/identity/memberships/tenants/tenant-route/subjects/user-route",
        headers=auth_headers(),
    )
    missing = client.get(
        "/internal/v1/identity/memberships/tenants/tenant-route/subjects/missing",
        headers=auth_headers(),
    )
    get_missing_auth = client.get(
        "/internal/v1/identity/memberships/tenants/tenant-route/subjects/user-route"
    )
    get_invalid_id = client.get(
        "/internal/v1/identity/memberships/tenants/tenant route/subjects/user-route",
        headers=auth_headers(),
    )

    assert missing_auth.status_code == 401
    assert missing_scope.status_code == 403
    assert missing_scope.json()["error_code"] == "TOKEN_SCOPE_MISSING"
    assert missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "oa.membership_list_invalid"
    assert ensure.status_code == 200
    assert ensure.json()["trace_id"] == TRACE_ID
    assert ensure.json()["request_id"] == REQUEST_ID
    assert readback.status_code == 200
    assert readback.json()["membership"] == ensure.json()["membership"]
    assert get_missing_auth.status_code == 401
    assert get_missing_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert get_invalid_id.status_code == 400
    assert get_invalid_id.json()["error_code"] == "oa.subject_ref_invalid"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "oa.membership_not_found"


def test_sqlalchemy_membership_registry_persists_membership_without_private_data() -> None:
    registry, engine = sqlite_membership_registry()
    snapshot = registry.ensure_membership(
        {
            "tenant_id": "tenant-sql",
            "subject_id": "user-sql",
            "roles": ["employee", "analyst"],
            "scopes": ["workspace:use", "documents:read"],
            "membership_metadata": {"department": "qa"},
        }
    )
    duplicate = registry.ensure_membership(
        {
            "tenant_id": "tenant-sql",
            "subject_id": "user-sql",
            "roles": ["changed"],
        }
    )

    assert duplicate == snapshot
    assert registry.get_membership(tenant_id="tenant-sql", subject_id="user-sql") == snapshot
    assert registry.get_membership(tenant_id="tenant-sql", subject_id="missing") is None
    with engine.connect() as connection:
        table_dump = "\n".join(
            str(row)
            for row in connection.execute(
                text("SELECT roles, scopes, metadata FROM oa_tenant_memberships")
            ).fetchall()
        )
    assert "analyst" in table_dump
    assert "documents:read" in table_dump
    assert "password" not in table_dump.lower()
    assert "token" not in table_dump.lower()


def test_sqlalchemy_membership_registry_reports_unavailable_when_tables_are_missing() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    registry = SqlAlchemyOaTenantMembershipRegistry(build_session_factory(engine))

    with pytest.raises(OaMembershipError) as exc:
        registry.ensure_membership({"tenant_id": "tenant-a", "subject_id": "user-a"})

    assert exc.value.status_code == 503
    assert exc.value.retryable is True


def test_membership_registry_handles_missing_subject_snapshots_and_sqlalchemy_failures(
    monkeypatch,
) -> None:
    registry = InMemoryOaTenantMembershipRegistry()
    registry.memberships[("tenant-a", "user-a")] = build_membership_record(
        {},
        subject_snapshot=subject_snapshot(),
    )
    with pytest.raises(OaMembershipError) as missing_subject:
        registry.get_membership(tenant_id="tenant-a", subject_id="user-a")
    assert missing_subject.value.error_code == "oa.membership_registry_unavailable"
    with pytest.raises(OaMembershipError) as missing_authority_subject:
        registry.replace_authority(
            tenant_id="tenant-a",
            subject_id="user-a",
            payload={
                "expected_revision": 1,
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
    assert missing_authority_subject.value.error_code == (
        "oa.membership_registry_unavailable"
    )

    monkeypatch.setattr(
        registry.subject_registry,
        "get_subject",
        lambda **_kwargs: (_ for _ in ()).throw(
            SubjectRegistryError(503, "oa.subject_registry_unavailable", "boom", True)
        ),
    )
    with pytest.raises(OaMembershipError) as failed_authority_subject:
        registry.replace_authority(
            tenant_id="tenant-a",
            subject_id="user-a",
            payload={
                "expected_revision": 1,
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
    assert failed_authority_subject.value.retryable is True

    sql_registry, _engine = sqlite_membership_registry()
    sql_registry.ensure_membership({"tenant_id": "tenant-a", "subject_id": "user-a"})
    sql_registry._subject_registry = InMemoryOaSubjectRegistry()
    with pytest.raises(OaMembershipError) as sql_missing_subject:
        sql_registry.get_membership(tenant_id="tenant-a", subject_id="user-a")
    assert sql_missing_subject.value.error_code == "oa.membership_registry_unavailable"
    with pytest.raises(OaMembershipError) as sql_missing_authority_subject:
        sql_registry.replace_authority(
            tenant_id="tenant-a",
            subject_id="user-a",
            payload={
                "expected_revision": 1,
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
    assert sql_missing_authority_subject.value.error_code == (
        "oa.membership_registry_unavailable"
    )

    failing_get = SqlAlchemyOaTenantMembershipRegistry(lambda: None)
    monkeypatch.setattr(
        failing_get,
        "_session_factory",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )
    with pytest.raises(OaMembershipError) as failed_get:
        failing_get.get_membership(tenant_id="tenant-a", subject_id="user-a")
    assert failed_get.value.error_code == "oa.membership_registry_unavailable"
    monkeypatch.setattr(
        failing_get,
        "_run_in_transaction",
        lambda operation: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )
    with pytest.raises(OaMembershipError) as failed_authority_update:
        failing_get.replace_authority(
            tenant_id="tenant-a",
            subject_id="user-a",
            payload={
                "expected_revision": 1,
                "roles": ["employee"],
                "scopes": ["workspace:use"],
            },
        )
    assert failed_authority_update.value.error_code == (
        "oa.membership_registry_unavailable"
    )


def test_sqlalchemy_authority_update_fails_closed_on_concurrent_row_loss(
    monkeypatch,
) -> None:
    registry = SqlAlchemyOaTenantMembershipRegistry(lambda: None)
    existing = {
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "subject_ref": {"type": "oa.user", "id": "user-a"},
        "revision": 1,
        "roles": ["employee"],
        "scopes": ["workspace:use"],
    }
    monkeypatch.setattr(
        registry,
        "_select_membership",
        lambda *_args, **_kwargs: existing,
    )

    class ConcurrentSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(rowcount=0)

    with pytest.raises(OaMembershipError) as raised:
        registry._replace_authority(
            ConcurrentSession(),
            tenant_id="tenant-a",
            subject_id="user-a",
            expected_revision=1,
            roles=["nex-agent"],
            scopes=["work:claim"],
        )

    assert raised.value.error_code == "oa.membership_registry_unavailable"


def test_sqlalchemy_membership_integrity_fallbacks_and_rollback(monkeypatch) -> None:
    registry = SqlAlchemyOaTenantMembershipRegistry(
        lambda: None,
        subject_registry=InMemoryOaSubjectRegistry(),
    )

    existing = {"membership": {"status": "ACTIVE"}}
    monkeypatch.setattr(
        registry,
        "_run_in_transaction",
        lambda operation: (_ for _ in ()).throw(
            IntegrityError("stmt", "params", Exception("duplicate"))
        ),
    )
    monkeypatch.setattr(registry, "get_membership", lambda **kwargs: existing)
    assert registry.ensure_membership({"tenant_id": "tenant-a", "subject_id": "user-a"}) == existing

    monkeypatch.setattr(registry, "get_membership", lambda **kwargs: None)
    with pytest.raises(OaMembershipError) as integrity_missing:
        registry.ensure_membership({"tenant_id": "tenant-b", "subject_id": "user-b"})
    assert integrity_missing.value.error_code == "oa.membership_registry_unavailable"

    monkeypatch.setattr(
        registry,
        "_run_in_transaction",
        lambda operation: (_ for _ in ()).throw(SQLAlchemyError("boom")),
    )
    with pytest.raises(OaMembershipError) as sqlalchemy_failure:
        registry.ensure_membership({"tenant_id": "tenant-c", "subject_id": "user-c"})
    assert sqlalchemy_failure.value.error_code == "oa.membership_registry_unavailable"

    class RollbackSession:
        def __init__(self) -> None:
            self.rolled_back = False
            self.closed = False

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    rollback_session = RollbackSession()
    rollback_registry = SqlAlchemyOaTenantMembershipRegistry(lambda: rollback_session)
    with pytest.raises(RuntimeError):
        rollback_registry._run_in_transaction(
            lambda session: (_ for _ in ()).throw(RuntimeError("rollback"))
        )
    assert rollback_session.rolled_back is True
    assert rollback_session.closed is True


def test_membership_json_and_timestamp_helpers_cover_storage_variants() -> None:
    assert _json_loads(None, default={"safe": True}) == {"safe": True}
    assert _json_loads({"safe": True}, default={}) == {"safe": True}
    assert _json_loads(b'["employee"]', default=[]) == ["employee"]
    assert _json_loads(123, default=[]) == []

    aware_row = {
        "membership_schema_version": OA_TENANT_MEMBERSHIP_SCHEMA_VERSION,
        "tenant_id": "tenant-a",
        "subject_ref_type": "oa.user",
        "subject_id": "user-a",
        "status": "ACTIVE",
        "roles": ["employee"],
        "scopes": ["workspace:use"],
        "metadata": {"team": "ops"},
        "created_at": "2026-08-12T00:00:00Z",
        "updated_at": "2026-08-12T00:00:00Z",
    }
    naive_row = {
        **aware_row,
        "created_at": __import__("datetime").datetime(2026, 8, 12, 1, 2, 3),
        "updated_at": __import__("datetime").datetime(2026, 8, 12, 1, 2, 3),
    }
    aware_datetime_row = {
        **aware_row,
        "created_at": __import__("datetime").datetime(
            2026,
            8,
            12,
            1,
            2,
            3,
            tzinfo=__import__("datetime").UTC,
        ),
        "updated_at": __import__("datetime").datetime(
            2026,
            8,
            12,
            1,
            2,
            3,
            tzinfo=__import__("datetime").UTC,
        ),
    }

    assert _membership_from_row(aware_row)["created_at"] == "2026-08-12T00:00:00Z"
    assert _membership_from_row(naive_row)["created_at"].endswith("Z")
    assert _membership_from_row(aware_datetime_row)["created_at"].endswith("Z")

    class PostgresSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    assert _json_sql_expression(PostgresSession(), "metadata") == "CAST(:metadata AS JSONB)"


def test_membership_factory_selects_persistence_adapter() -> None:
    subject_registry = InMemoryOaSubjectRegistry()
    memory = build_tenant_membership_registry_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None),
        subject_registry=subject_registry,
    )
    postgres = build_tenant_membership_registry_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=lambda: None,
        ),
        subject_registry=subject_registry,
    )
    default_memory = build_tenant_membership_registry_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None)
    )

    assert isinstance(memory, InMemoryOaTenantMembershipRegistry)
    assert memory.subject_registry is subject_registry
    assert isinstance(postgres, SqlAlchemyOaTenantMembershipRegistry)
    assert isinstance(default_memory, InMemoryOaTenantMembershipRegistry)


def test_nex_oa_entrypoint_registers_membership_routes() -> None:
    from nex_oa import main

    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/internal/v1/identity/memberships/ensure" in paths
    assert (
        "/internal/v1/identity/memberships/tenants/{tenant_id}/subjects/{subject_id}"
        in paths
    )
