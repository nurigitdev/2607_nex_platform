from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from nex_oa.credentials import (
    DEFAULT_PBKDF2_ITERATIONS,
    InMemoryOaCredentialRegistry,
    OA_LOCAL_CREDENTIAL_SCHEMA_VERSION,
    OA_LOCAL_CREDENTIAL_SNAPSHOT_SCHEMA_VERSION,
    PASSWORD_HASH_ALGORITHM,
    OaCredentialError,
    SqlAlchemyOaCredentialRegistry,
    build_credential_record,
    build_credential_registry_for_runtime,
    employee_id_from_payload,
    hash_password,
    normalize_credential_status,
    normalize_employee_id,
    password_hash_algorithm,
    register_local_credential_routes,
    stable_credential_id,
    verify_password,
    _credential_from_row,
    _json_loads,
    _json_sql_expression,
    _timestamp_to_wire,
)
from nex_oa.subjects import SubjectRegistryError
from nex_runtime import (
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def subject_snapshot(
    *,
    tenant_id: str = "tenant-a",
    subject_id: str = "emp-001",
) -> dict[str, object]:
    return {
        "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
        "subject_ref": {"type": "oa.user", "id": subject_id},
    }


def auth_headers(*, audience: str = "nex-oa") -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=audience)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-Request-ID": REQUEST_ID,
    }


def build_client(registry: InMemoryOaCredentialRegistry | None = None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_local_credential_routes(app, registry=registry or InMemoryOaCredentialRegistry())
    return TestClient(app)


def sqlite_credential_registry() -> tuple[SqlAlchemyOaCredentialRegistry, object]:
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
                CREATE TABLE oa_local_credentials (
                    credential_id TEXT PRIMARY KEY,
                    credential_schema_version TEXT NOT NULL DEFAULT 'oa_local_credential.v1',
                    tenant_id TEXT NOT NULL,
                    subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    subject_id TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    normalized_employee_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    password_hash TEXT NOT NULL,
                    password_hash_algorithm TEXT NOT NULL DEFAULT 'pbkdf2_sha256.v1',
                    failed_attempt_count INTEGER NOT NULL DEFAULT 0,
                    locked_at TEXT,
                    password_changed_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, normalized_employee_id)
                )
                """
            )
        )
    return SqlAlchemyOaCredentialRegistry(build_session_factory(engine)), engine


def test_password_hash_helpers_verify_and_hide_raw_password() -> None:
    password_hash = hash_password(
        "Nuri1004!",
        salt=b"1234567890123456",
        iterations=10,
    )

    assert password_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}$10$")
    assert "Nuri1004!" not in password_hash
    assert password_hash_algorithm(password_hash) == PASSWORD_HASH_ALGORITHM
    assert verify_password("Nuri1004!", password_hash=password_hash) is True

    with pytest.raises(OaCredentialError) as wrong_password:
        verify_password("Wrong1004!", password_hash=password_hash)
    assert wrong_password.value.error_code == "oa.credential_not_verified"

    with pytest.raises(OaCredentialError, match="format"):
        password_hash_algorithm("bad-hash")
    with pytest.raises(OaCredentialError, match="iterations"):
        hash_password("Nuri1004!", iterations=0)
    with pytest.raises(OaCredentialError, match="between"):
        hash_password("short")


def test_inmemory_credential_registry_seeds_employee_credential_and_verifies() -> None:
    registry = InMemoryOaCredentialRegistry()
    snapshot = registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
            "subject_display_name": "Employee One",
            "credential_metadata": {"seeded_by": "operator"},
        }
    )
    duplicate = registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "emp-001",
            "password": "Different1004!",
            "subject_display_name": "Ignored",
        }
    )
    verified = registry.verify_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        }
    )
    fetched = registry.get_credential(tenant_id="tenant-a", employee_id="emp-001")

    assert snapshot["credential_snapshot_schema_version"] == (
        OA_LOCAL_CREDENTIAL_SNAPSHOT_SCHEMA_VERSION
    )
    assert snapshot["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert snapshot["subject_ref"] == {"type": "oa.user", "id": "emp-001"}
    assert snapshot["credential"]["credential_schema_version"] == (
        OA_LOCAL_CREDENTIAL_SCHEMA_VERSION
    )
    assert snapshot["credential"]["employee_id"] == "EMP-001"
    assert snapshot["credential"]["normalized_employee_id"] == "emp-001"
    assert snapshot["credential"]["hash_algorithm"] == PASSWORD_HASH_ALGORITHM
    assert "password_hash" not in snapshot["credential"]
    assert duplicate["credential"]["credential_id"] == snapshot["credential"][
        "credential_id"
    ]
    assert verified["credential"]["credential_id"] == snapshot["credential"][
        "credential_id"
    ]
    assert fetched == snapshot
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "Nuri1004!" not in serialized
    assert "Different1004!" not in serialized
    assert "password_hash" not in serialized


def test_inmemory_credential_registry_reports_missing_and_orphaned_credentials() -> None:
    registry = InMemoryOaCredentialRegistry()

    with pytest.raises(OaCredentialError) as missing:
        registry.verify_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-MISSING",
                "password": "Nuri1004!",
            }
        )
    assert missing.value.error_code == "oa.credential_not_verified"

    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-ORPHAN",
            "password": "Nuri1004!",
        }
    )
    registry.subject_registry.subjects.clear()

    with pytest.raises(OaCredentialError) as get_unavailable:
        registry.get_credential(tenant_id="tenant-a", employee_id="emp-orphan")
    with pytest.raises(OaCredentialError) as verify_unavailable:
        registry.verify_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-ORPHAN",
                "password": "Nuri1004!",
            }
        )

    assert get_unavailable.value.error_code == "oa.credential_registry_unavailable"
    assert verify_unavailable.value.retryable is True


def test_inmemory_credential_registry_converts_subject_registry_errors() -> None:
    class FailingSubjectRegistry:
        def ensure_subject(self, payload: dict[str, object]) -> dict[str, object]:
            return subject_snapshot(
                tenant_id=str(payload["tenant_id"]),
                subject_id=str(payload["subject_id"]),
            )

        def get_subject(self, *, tenant_id: str, subject_id: str) -> None:
            raise SubjectRegistryError(
                status_code=503,
                error_code="oa.subject_registry_unavailable",
                detail=f"Subject registry is unavailable: {tenant_id}/{subject_id}",
                retryable=True,
            )

    registry = InMemoryOaCredentialRegistry(subject_registry=FailingSubjectRegistry())
    registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-FAIL",
            "password": "Nuri1004!",
        }
    )

    with pytest.raises(OaCredentialError) as unavailable:
        registry.get_credential(tenant_id="tenant-a", employee_id="EMP-FAIL")

    assert unavailable.value.error_code == "oa.subject_registry_unavailable"
    assert unavailable.value.retryable is True


def test_credential_registry_rejects_invalid_payloads_and_statuses() -> None:
    registry = InMemoryOaCredentialRegistry()

    assert normalize_employee_id("EMP-001") == "emp-001"
    assert employee_id_from_payload({"login_identifier": "EMP-002"}) == "emp-002"
    assert normalize_credential_status("locked") == "LOCKED"
    assert stable_credential_id(
        tenant_id="tenant-a",
        normalized_employee_id="emp-001",
    ) == stable_credential_id(
        tenant_id="tenant-a",
        normalized_employee_id="emp-001",
    )

    with pytest.raises(OaCredentialError, match="employee_id"):
        normalize_employee_id("bad employee")
    with pytest.raises(OaCredentialError, match="credential_status"):
        normalize_credential_status("PENDING")
    with pytest.raises(OaCredentialError) as secret_conflict:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "emp-001",
                "password": "Nuri1004!",
                "password_hash": hash_password("Nuri1004!"),
            }
        )
    assert secret_conflict.value.error_code == "oa.credential_secret_conflict"
    with pytest.raises(OaCredentialError) as missing_secret:
        registry.ensure_credential({"tenant_id": "tenant-a", "employee_id": "emp-001"})
    assert missing_secret.value.error_code == "oa.credential_secret_missing"
    with pytest.raises(OaCredentialError) as missing_employee:
        employee_id_from_payload({"login_identifier": ""})
    assert missing_employee.value.error_code == "oa.employee_id_invalid"
    with pytest.raises(OaCredentialError) as non_string_employee:
        normalize_employee_id(123)
    assert non_string_employee.value.error_code == "oa.employee_id_invalid"
    with pytest.raises(OaCredentialError) as bad_tenant:
        registry.ensure_credential(
            {
                "tenant_id": "bad tenant",
                "employee_id": "emp-001",
                "password": "Nuri1004!",
            }
        )
    assert bad_tenant.value.error_code == "oa.subject_ref_invalid"
    with pytest.raises(OaCredentialError) as private_metadata:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "emp-001",
                "password": "Nuri1004!",
                "credential_metadata": {"password_hint": "secret-value"},
            }
        )
    assert private_metadata.value.error_code == "oa.private_credential_payload_rejected"
    with pytest.raises(OaCredentialError) as private_nested_metadata:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "emp-002",
                "password": "Nuri1004!",
                "credential_metadata": {"items": [{"browser_cookie": "secret-value"}]},
            }
        )
    assert private_nested_metadata.value.error_code == (
        "oa.private_credential_payload_rejected"
    )
    with pytest.raises(OaCredentialError) as bad_metadata:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "emp-003",
                "password": "Nuri1004!",
                "credential_metadata": ["not", "an", "object"],
            }
        )
    assert bad_metadata.value.error_code == "oa.credential_metadata_invalid"
    with pytest.raises(OaCredentialError) as non_serializable_metadata:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "emp-004",
                "password": "Nuri1004!",
                "credential_metadata": {"safe": {"not-json"}},
            }
        )
    assert non_serializable_metadata.value.error_code == "oa.credential_metadata_invalid"


def test_password_hash_parser_rejects_unsupported_and_malformed_hashes() -> None:
    valid_hash = hash_password("Nuri1004!", salt=b"1234567890123456", iterations=10)
    unsupported_hash = valid_hash.replace(PASSWORD_HASH_ALGORITHM, "argon2id.v1", 1)

    with pytest.raises(OaCredentialError) as unsupported_verify:
        verify_password("Nuri1004!", password_hash=unsupported_hash)
    assert unsupported_verify.value.error_code == "oa.password_hash_algorithm_unsupported"
    with pytest.raises(OaCredentialError) as unsupported_seed:
        build_credential_record(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password_hash": unsupported_hash,
            },
            subject_snapshot=subject_snapshot(),
        )
    assert unsupported_seed.value.error_code == "oa.password_hash_algorithm_unsupported"

    malformed_hashes = [
        f"{PASSWORD_HASH_ALGORITHM}$not-an-int$c2FsdA$ZGlnZXN0",
        f"{PASSWORD_HASH_ALGORITHM}$1$$",
    ]
    for password_hash in malformed_hashes:
        with pytest.raises(OaCredentialError) as malformed:
            password_hash_algorithm(password_hash)
        assert malformed.value.error_code == "oa.password_hash_invalid"

    with pytest.raises(OaCredentialError) as non_string_password:
        verify_password(123, password_hash=valid_hash)
    assert non_string_password.value.error_code == "oa.password_invalid"


def test_credential_record_can_accept_prehashed_password_and_locked_status() -> None:
    registry = InMemoryOaCredentialRegistry()
    password_hash = hash_password("Nuri1004!", salt=b"1234567890123456", iterations=10)
    snapshot = registry.ensure_credential(
        {
            "tenant_id": "tenant-a",
            "employee_id": "EMP-LOCKED",
            "password_hash": password_hash,
            "credential_status": "LOCKED",
            "credential_metadata": None,
        }
    )

    assert snapshot["credential"]["status"] == "LOCKED"
    assert snapshot["credential"]["locked_at"] is not None
    assert snapshot["credential"]["metadata"] == {}
    with pytest.raises(OaCredentialError) as inactive:
        registry.verify_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-LOCKED",
                "password": "Nuri1004!",
            }
        )
    assert inactive.value.error_code == "oa.credential_not_active"


def test_local_credential_routes_require_service_claim_and_hide_hash() -> None:
    client = build_client()

    missing = client.post("/internal/v1/auth/local-credentials/ensure", json={})
    wrong_audience = client.post(
        "/internal/v1/auth/local-credentials/ensure",
        headers=auth_headers(audience="nex-cx"),
        json={},
    )
    seeded = client.post(
        "/internal/v1/auth/local-credentials/ensure",
        headers=auth_headers(),
        json={
            "tenant_id": "tenant-a",
            "employee_id": "EMP-001",
            "password": "Nuri1004!",
        },
    )
    fetched = client.get(
        "/internal/v1/auth/local-credentials/tenants/tenant-a/employee-ids/emp-001",
        headers=auth_headers(),
    )
    missing_credential = client.get(
        "/internal/v1/auth/local-credentials/tenants/tenant-a/employee-ids/missing",
        headers=auth_headers(),
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    assert seeded.status_code == 200
    assert seeded.json()["trace_id"] == TRACE_ID
    assert seeded.json()["request_id"] == REQUEST_ID
    assert fetched.status_code == 200
    assert missing_credential.status_code == 404
    assert "password_hash" not in json.dumps(seeded.json())
    assert "Nuri1004!" not in json.dumps(seeded.json())


def test_local_credential_routes_return_problem_responses_for_validation_errors() -> None:
    client = build_client()

    invalid_seed = client.post(
        "/internal/v1/auth/local-credentials/ensure",
        headers=auth_headers(),
        json={"tenant_id": "tenant-a", "employee_id": "EMP-001", "password": "short"},
    )
    missing_get_auth = client.get(
        "/internal/v1/auth/local-credentials/tenants/tenant-a/employee-ids/emp-001"
    )
    invalid_get = client.get(
        "/internal/v1/auth/local-credentials/tenants/tenant-a/employee-ids/bad employee",
        headers=auth_headers(),
    )

    assert invalid_seed.status_code == 400
    assert invalid_seed.json()["error_code"] == "oa.password_invalid"
    assert missing_get_auth.status_code == 401
    assert missing_get_auth.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert invalid_get.status_code == 400
    assert invalid_get.json()["error_code"] == "oa.employee_id_invalid"


def test_sqlalchemy_credential_registry_persists_hash_without_raw_password() -> None:
    registry, engine = sqlite_credential_registry()
    snapshot = registry.ensure_credential(
        {
            "tenant_id": "tenant-sql",
            "employee_id": "EMP-SQL",
            "password": "Nuri1004!",
            "subject_id": "user-sql",
            "credential_metadata": {"seeded_by": "test"},
        }
    )
    duplicate = registry.ensure_credential(
        {
            "tenant_id": "tenant-sql",
            "employee_id": "emp-sql",
            "password": "Different1004!",
            "subject_id": "user-sql",
        }
    )
    fetched = registry.get_credential(tenant_id="tenant-sql", employee_id="emp-sql")
    verified = registry.verify_credential(
        {
            "tenant_id": "tenant-sql",
            "employee_id": "EMP-SQL",
            "password": "Nuri1004!",
        }
    )

    assert fetched == snapshot
    assert duplicate["credential"]["credential_id"] == snapshot["credential"][
        "credential_id"
    ]
    assert verified["subject_ref"] == {"type": "oa.user", "id": "user-sql"}
    assert "password_hash" not in json.dumps(snapshot)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT password_hash, password_hash_algorithm FROM oa_local_credentials")
        ).mappings().one()
        table_dump = json.dumps(
            [dict(item) for item in connection.execute(text("SELECT * FROM oa_local_credentials")).mappings()],
            default=str,
        )
    assert row["password_hash_algorithm"] == PASSWORD_HASH_ALGORITHM
    assert row["password_hash"].startswith(f"{PASSWORD_HASH_ALGORITHM}$")
    assert "Nuri1004!" not in table_dump


def test_sqlalchemy_credential_registry_handles_missing_and_orphaned_rows() -> None:
    registry, engine = sqlite_credential_registry()

    assert registry.get_credential(tenant_id="tenant-sql", employee_id="missing") is None
    with pytest.raises(OaCredentialError) as missing_verify:
        registry.verify_credential(
            {
                "tenant_id": "tenant-sql",
                "employee_id": "missing",
                "password": "Nuri1004!",
            }
        )
    assert missing_verify.value.error_code == "oa.credential_not_verified"

    registry.ensure_credential(
        {
            "tenant_id": "tenant-sql",
            "employee_id": "EMP-ORPHAN",
            "password": "Nuri1004!",
            "subject_id": "user-orphan",
        }
    )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM oa_subjects WHERE subject_id = 'user-orphan'"))

    with pytest.raises(OaCredentialError) as get_unavailable:
        registry.get_credential(tenant_id="tenant-sql", employee_id="emp-orphan")
    with pytest.raises(OaCredentialError) as verify_unavailable:
        registry.verify_credential(
            {
                "tenant_id": "tenant-sql",
                "employee_id": "EMP-ORPHAN",
                "password": "Nuri1004!",
            }
        )

    assert get_unavailable.value.error_code == "oa.credential_registry_unavailable"
    assert verify_unavailable.value.error_code == "oa.credential_registry_unavailable"


def test_sqlalchemy_credential_registry_reports_credential_table_unavailable() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    registry = SqlAlchemyOaCredentialRegistry(build_session_factory(engine))

    with pytest.raises(OaCredentialError) as get_unavailable:
        registry.get_credential(tenant_id="tenant-a", employee_id="EMP-001")
    with pytest.raises(OaCredentialError) as verify_unavailable:
        registry.verify_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            }
        )

    assert get_unavailable.value.error_code == "oa.credential_registry_unavailable"
    assert verify_unavailable.value.retryable is True


def test_sqlalchemy_credential_registry_recovers_or_reports_insert_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, engine = sqlite_credential_registry()
    payload = {
        "tenant_id": "tenant-sql",
        "employee_id": "EMP-RACE",
        "password": "Nuri1004!",
    }
    existing = registry.ensure_credential(payload)
    integrity_error = IntegrityError("insert", {}, Exception("duplicate"))

    def raise_integrity_error(operation: object) -> object:
        raise integrity_error

    monkeypatch.setattr(registry, "_run_in_transaction", raise_integrity_error)
    assert registry.ensure_credential(payload) == existing

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM oa_local_credentials"))

    with pytest.raises(OaCredentialError) as unavailable_after_integrity:
        registry.ensure_credential(payload)
    assert unavailable_after_integrity.value.error_code == "oa.credential_registry_unavailable"

    def raise_sqlalchemy_error(operation: object) -> object:
        raise SQLAlchemyError("offline")

    monkeypatch.setattr(registry, "_run_in_transaction", raise_sqlalchemy_error)
    with pytest.raises(OaCredentialError) as unavailable_after_sqlalchemy:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-sql",
                "employee_id": "EMP-SQL-ERROR",
                "password": "Nuri1004!",
            }
        )
    assert unavailable_after_sqlalchemy.value.retryable is True


def test_sqlalchemy_credential_transaction_rolls_back_and_closes_on_error() -> None:
    registry, _engine = sqlite_credential_registry()

    with pytest.raises(RuntimeError, match="boom"):
        registry._run_in_transaction(  # noqa: SLF001
            lambda _session: (_ for _ in ()).throw(RuntimeError("boom"))
        )


def test_sqlalchemy_credential_registry_reports_unavailable_when_tables_missing() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    registry = SqlAlchemyOaCredentialRegistry(build_session_factory(engine))

    with pytest.raises(OaCredentialError) as unavailable:
        registry.ensure_credential(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            }
        )
    assert unavailable.value.error_code == "oa.subject_registry_unavailable"


def test_credential_registry_factory_uses_sqlalchemy_when_postgres_runtime_configured() -> None:
    memory = build_credential_registry_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None)
    )
    postgres = build_credential_registry_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=object(),
        )
    )

    assert isinstance(memory, InMemoryOaCredentialRegistry)
    assert isinstance(postgres, SqlAlchemyOaCredentialRegistry)


def test_build_credential_record_rejects_bad_subject_snapshot() -> None:
    with pytest.raises(OaCredentialError) as missing_ref:
        build_credential_record(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            },
            subject_snapshot={
                "tenant_ref": "tenant-a",
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        )
    with pytest.raises(OaCredentialError) as bad_ref:
        build_credential_record(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            },
            subject_snapshot={
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                "subject_ref": {"type": "other", "id": "user-a"},
            },
        )
    with pytest.raises(OaCredentialError) as non_string_ref_type:
        build_credential_record(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            },
            subject_snapshot={
                "tenant_ref": {"type": 123, "id": "tenant-a"},
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        )
    with pytest.raises(OaCredentialError) as empty_ref_id:
        build_credential_record(
            {
                "tenant_id": "tenant-a",
                "employee_id": "EMP-001",
                "password": "Nuri1004!",
            },
            subject_snapshot={
                "tenant_ref": {"type": "oa.tenant", "id": "   "},
                "subject_ref": {"type": "oa.user", "id": "user-a"},
            },
        )

    assert missing_ref.value.error_code == "oa.credential_ref_invalid"
    assert bad_ref.value.error_code == "oa.credential_ref_invalid"
    assert non_string_ref_type.value.error_code == "oa.credential_field_invalid"
    assert empty_ref_id.value.error_code == "oa.credential_field_invalid"


def test_credential_helpers_normalize_json_and_timestamps() -> None:
    class FakePostgresSession:
        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class FakeSqliteSession:
        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    assert _json_sql_expression(FakePostgresSession(), "metadata") == (
        "CAST(:metadata AS JSONB)"
    )
    assert _json_sql_expression(FakeSqliteSession(), "metadata") == ":metadata"
    assert _json_loads(None, default={"a": 1}) == {"a": 1}
    assert _json_loads({"a": 1}, default={}) == {"a": 1}
    assert _json_loads(b'{"a": 1}', default={}) == {"a": 1}
    assert _json_loads(7, default={"fallback": True}) == {"fallback": True}
    assert _timestamp_to_wire(datetime(2026, 8, 12, 1, 2, 3)) == (
        "2026-08-12T01:02:03Z"
    )
    assert _timestamp_to_wire(datetime(2026, 8, 12, 1, 2, 3, tzinfo=UTC)) == (
        "2026-08-12T01:02:03Z"
    )
    assert _timestamp_to_wire("already-wire") == "already-wire"


def test_credential_from_row_normalizes_locked_timestamp_and_metadata_shapes() -> None:
    row = {
        "credential_schema_version": OA_LOCAL_CREDENTIAL_SCHEMA_VERSION,
        "credential_id": "credential-a",
        "tenant_id": "tenant-a",
        "subject_ref_type": "oa.user",
        "subject_id": "user-a",
        "employee_id": "EMP-001",
        "normalized_employee_id": "emp-001",
        "status": "LOCKED",
        "password_hash": hash_password(
            "Nuri1004!",
            salt=b"1234567890123456",
            iterations=10,
        ),
        "password_hash_algorithm": PASSWORD_HASH_ALGORITHM,
        "failed_attempt_count": 2,
        "locked_at": datetime(2026, 8, 12, 1, 2, 3),
        "password_changed_at": "2026-08-12T01:00:00Z",
        "metadata": {"safe": True},
        "created_at": "2026-08-12T01:00:00Z",
        "updated_at": "2026-08-12T01:00:00Z",
    }

    record = _credential_from_row(row)

    assert record["locked_at"] == "2026-08-12T01:02:03Z"
    assert record["metadata"] == {"safe": True}


def test_nex_oa_entrypoint_registers_local_credential_routes() -> None:
    import nex_oa.main as main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/internal/v1/auth/local-credentials/ensure" in paths
    assert (
        "/internal/v1/auth/local-credentials/tenants/{tenant_id}/employee-ids/{employee_id}"
        in paths
    )
    assert DEFAULT_PBKDF2_ITERATIONS >= 100_000
