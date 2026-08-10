from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text

from nex_oa.subjects import (
    DEFAULT_SUBJECT_ID,
    DEFAULT_TENANT_ID,
    InMemoryOaSubjectRegistry,
    OA_SUBJECT_REGISTRY_SNAPSHOT_SCHEMA_VERSION,
    OA_TENANT_REF_TYPE,
    OA_USER_REF_TYPE,
    SqlAlchemyOaSubjectRegistry,
    SubjectRegistryError,
    build_subject_record,
    build_subject_registry_for_runtime,
    build_subject_registry_snapshot,
    build_tenant_record,
    normalize_registry_id,
    normalize_subject_status,
    payload_has_private_identity_data,
    register_subject_registry_routes,
)
from nex_runtime import (
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
)


ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def subject_registry_schema() -> dict[str, object]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_oa"
            / "subject_registry_snapshot.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-cx", audience="nex-oa")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def build_test_client(registry: InMemoryOaSubjectRegistry | None = None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_subject_registry_routes(
        app,
        registry=registry or InMemoryOaSubjectRegistry(),
    )
    return TestClient(app)


def sqlite_subject_registry() -> tuple[SqlAlchemyOaSubjectRegistry, object]:
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
    return SqlAlchemyOaSubjectRegistry(build_session_factory(engine)), engine


def test_subject_registry_snapshot_matches_contract_schema() -> None:
    registry = InMemoryOaSubjectRegistry()
    snapshot = registry.ensure_subject(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "tenant_display_name": "Tenant A",
            "subject_display_name": "User A",
            "tenant_metadata": {"source": "test"},
            "subject_metadata": {"department": "ops"},
        }
    )
    snapshot["trace_id"] = TRACE_ID
    snapshot["request_id"] = REQUEST_ID

    Draft202012Validator(subject_registry_schema()).validate(snapshot)
    assert snapshot["snapshot_schema_version"] == (
        OA_SUBJECT_REGISTRY_SNAPSHOT_SCHEMA_VERSION
    )
    assert snapshot["tenant_ref"] == {"type": OA_TENANT_REF_TYPE, "id": "tenant-a"}
    assert snapshot["subject_ref"] == {"type": OA_USER_REF_TYPE, "id": "user-a"}
    assert snapshot["compatibility_aliases"] == {
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "user_id": "user-a",
    }
    assert snapshot["capabilities"]["stable_subject_registry"] is True
    assert snapshot["capabilities"]["password_login"] is False
    assert "0198_oa_subject_registry_resolver_client" == snapshot["next_slice"]


def test_subject_registry_defaults_are_local_refs_and_idempotent() -> None:
    registry = InMemoryOaSubjectRegistry()
    first = registry.ensure_subject({})
    second = registry.ensure_subject(
        {
            "tenant_id": DEFAULT_TENANT_ID,
            "owner_user_id": DEFAULT_SUBJECT_ID,
            "subject_display_name": "Changed",
        }
    )

    assert first == second
    assert first["tenant_ref"]["id"] == DEFAULT_TENANT_ID
    assert first["subject_ref"]["id"] == DEFAULT_SUBJECT_ID
    assert registry.get_tenant(DEFAULT_TENANT_ID)["display_name"] == "Local Tenant"
    assert registry.get_subject(
        tenant_id=DEFAULT_TENANT_ID,
        subject_id=DEFAULT_SUBJECT_ID,
    ) == first


def test_subject_registry_rejects_invalid_ids_status_and_private_payload() -> None:
    with pytest.raises(SubjectRegistryError) as bad_id:
        normalize_registry_id("bad id", field_name="subject_id")
    assert bad_id.value.error_code == "oa.subject_ref_invalid"

    with pytest.raises(SubjectRegistryError) as bad_status:
        normalize_subject_status("LOCKED")
    assert bad_status.value.error_code == "oa.subject_status_invalid"

    assert payload_has_private_identity_data({"safe": [{"email": "x@example.test"}]})
    registry = InMemoryOaSubjectRegistry()
    with pytest.raises(SubjectRegistryError) as private_payload:
        registry.ensure_subject({"subject_metadata": {"api_token": "secret-value"}})
    assert private_payload.value.error_code == "oa.private_identity_payload_rejected"
    assert "secret-value" not in private_payload.value.detail


def test_build_subject_record_requires_valid_tenant_ref() -> None:
    tenant = build_tenant_record({"tenant_id": "tenant-a"})
    subject = build_subject_record(
        {"subject_id": "user-a", "subject_status": "disabled"},
        tenant=tenant,
    )
    snapshot = build_subject_registry_snapshot(tenant=tenant, subject=subject)

    assert subject["status"] == "DISABLED"
    assert snapshot["subject_ref"] == {"type": OA_USER_REF_TYPE, "id": "user-a"}

    with pytest.raises(SubjectRegistryError, match="tenant_ref.id"):
        build_subject_record(
            {"subject_id": "user-a"},
            tenant={"tenant_ref": {"type": OA_TENANT_REF_TYPE}},
        )


def test_subject_registry_api_requires_service_claim() -> None:
    response = build_test_client().post("/internal/v1/subject-registry/ensure", json={})

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_subject_registry_api_ensures_and_reads_subject_snapshot() -> None:
    client = build_test_client()
    ensure = client.post(
        "/internal/v1/subject-registry/ensure",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "tenant_display_name": "Tenant A",
            "display_name": "User A",
        },
    )

    assert ensure.status_code == 200
    payload = ensure.json()
    assert payload["trace_id"] == TRACE_ID
    assert payload["request_id"] == REQUEST_ID
    assert payload["tenant"]["display_name"] == "Tenant A"
    assert payload["subject"]["display_name"] == "User A"
    assert "x@example.test" not in json.dumps(payload).lower()

    tenant = client.get(
        "/internal/v1/subject-registry/tenants/tenant-a",
        headers=auth_headers(),
    )
    subject = client.get(
        "/internal/v1/subject-registry/tenants/tenant-a/subjects/user-a",
        headers=auth_headers(),
    )

    assert tenant.status_code == 200
    assert tenant.json()["subject"] is None
    assert tenant.json()["compatibility_aliases"] == {"tenant_id": "tenant-a"}
    assert subject.status_code == 200
    assert subject.json()["subject_ref"] == {"type": OA_USER_REF_TYPE, "id": "user-a"}


def test_subject_registry_api_reports_validation_and_not_found() -> None:
    client = build_test_client()
    invalid = client.post(
        "/internal/v1/subject-registry/ensure",
        headers=auth_headers(),
        json={"tenant_id": "tenant a"},
    )
    missing_tenant = client.get(
        "/internal/v1/subject-registry/tenants/missing",
        headers=auth_headers(),
    )
    missing_subject = client.get(
        "/internal/v1/subject-registry/tenants/local-tenant/subjects/missing",
        headers=auth_headers(),
    )

    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "oa.subject_ref_invalid"
    assert missing_tenant.status_code == 404
    assert missing_tenant.json()["error_code"] == "oa.tenant_not_found"
    assert missing_subject.status_code == 404
    assert missing_subject.json()["error_code"] == "oa.subject_not_found"


def test_sqlalchemy_subject_registry_persists_refs_without_private_identity_payload() -> None:
    registry, engine = sqlite_subject_registry()
    snapshot = registry.ensure_subject(
        {
            "tenant_id": "tenant-sql",
            "owner_user_id": "user-sql",
            "tenant_metadata": {"region": "local"},
            "subject_metadata": {"role_hint": "operator"},
        }
    )
    duplicate = registry.ensure_subject(
        {
            "tenant_id": "tenant-sql",
            "subject_id": "user-sql",
            "subject_display_name": "Ignored",
        }
    )

    assert duplicate == snapshot
    assert registry.get_tenant("tenant-sql")["metadata"] == {"region": "local"}
    assert registry.get_subject(tenant_id="tenant-sql", subject_id="user-sql") == snapshot
    with engine.connect() as connection:
        table_dump = "\n".join(
            str(row)
            for row in connection.execute(text("SELECT * FROM oa_subjects")).fetchall()
        )
    assert "operator" in table_dump
    assert "password" not in table_dump.lower()
    assert "token" not in table_dump.lower()


def test_sqlalchemy_subject_registry_reports_unavailable_when_tables_are_missing() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    registry = SqlAlchemyOaSubjectRegistry(build_session_factory(engine))

    with pytest.raises(SubjectRegistryError) as exc_info:
        registry.ensure_subject({"tenant_id": "tenant-a", "subject_id": "user-a"})

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True


def test_subject_registry_factory_uses_sqlalchemy_when_postgres_runtime_is_configured() -> None:
    memory = build_subject_registry_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None)
    )
    postgres = build_subject_registry_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=lambda: None,
        )
    )

    assert isinstance(memory, InMemoryOaSubjectRegistry)
    assert isinstance(postgres, SqlAlchemyOaSubjectRegistry)


def test_nex_oa_entrypoint_registers_subject_registry_routes() -> None:
    import nex_oa.main as main

    assert "/internal/v1/subject-registry/ensure" in {
        getattr(route, "path", "") for route in main.app.routes
    }
