from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from nex_oa.credential_security import (
    OA_CREDENTIAL_SECURITY_WRITE_SCOPE,
    InMemoryOaCredentialSecurityRepository,
    OaCredentialSecurityError,
    SqlAlchemyOaCredentialSecurityRepository,
    _timestamp_to_wire,
    _lockout_expired,
    build_credential_security_repository_for_runtime,
    normalize_password_change_request,
    normalize_password_reset_request,
    register_credential_security_routes,
)
from nex_oa.credentials import (
    InMemoryOaCredentialRegistry,
    hash_password,
    verify_password,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.sessions import InMemoryOaSessionRegistry
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


def _memory_repository():
    credentials = InMemoryOaCredentialRegistry()
    snapshot = credentials.ensure_credential(
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
    sessions = InMemoryOaSessionRegistry(membership_registry=memberships)
    sessions.sessions = {
        "matching": {
            "status": "ACTIVE",
            "tenant_ref": {"id": "tenant-a"},
            "subject_ref": {"id": "user-a"},
            "revoked_at": None,
            "updated_at": "2026-10-01T00:00:00Z",
        },
        "other": {
            "status": "ACTIVE",
            "tenant_ref": {"id": "tenant-a"},
            "subject_ref": {"id": "user-b"},
            "revoked_at": None,
            "updated_at": "2026-10-01T00:00:00Z",
        },
    }
    repository = InMemoryOaCredentialSecurityRepository(credentials, sessions)
    record = credentials.credentials[("tenant-a", "emp-001")]
    return repository, credentials, sessions, record, snapshot


def _sqlite_repository(*, include_sessions: bool = True):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE oa_local_credentials (
                    credential_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    normalized_employee_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_hash_algorithm TEXT NOT NULL,
                    failed_attempt_count INTEGER NOT NULL DEFAULT 0,
                    locked_at TEXT,
                    password_changed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, normalized_employee_id)
                )
                """
            )
        )
        if include_sessions:
            connection.execute(
                text(
                    """
                    CREATE TABLE oa_user_sessions (
                        session_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        subject_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        revoked_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
        password_hash = hash_password("Current1004!")
        connection.execute(
            text(
                """
                INSERT INTO oa_local_credentials (
                    credential_id, tenant_id, subject_id, employee_id,
                    normalized_employee_id, status, password_hash,
                    password_hash_algorithm, failed_attempt_count, locked_at,
                    password_changed_at, updated_at
                ) VALUES (
                    'credential-a', 'tenant-a', 'user-a', 'EMP-001',
                    'emp-001', 'ACTIVE', :password_hash, 'argon2id.v1',
                    0, NULL, :now, :now
                )
                """
            ),
            {"password_hash": password_hash, "now": "2026-10-01T00:00:00Z"},
        )
        if include_sessions:
            connection.execute(
                text(
                    """
                    INSERT INTO oa_user_sessions
                        (session_id, tenant_id, subject_id, status, revoked_at, updated_at)
                    VALUES
                        ('matching', 'tenant-a', 'user-a', 'ACTIVE', NULL, :now),
                        ('other', 'tenant-a', 'user-b', 'ACTIVE', NULL, :now)
                    """
                ),
                {"now": "2026-10-01T00:00:00Z"},
            )
    return SqlAlchemyOaCredentialSecurityRepository(build_session_factory(engine)), engine


def _change_payload(**overrides):
    return {
        "tenant_id": "tenant-a",
        "employee_id": "EMP-001",
        "current_password": "Current1004!",
        "new_password": "Changed1004!",
        **overrides,
    }


def _reset_payload(**overrides):
    return {
        "tenant_id": "tenant-a",
        "employee_id": "EMP-001",
        "temporary_password": "Temporary1004!",
        "reason_code": "operator.recovery",
        **overrides,
    }


def _headers(*, include_write_scope: bool = True):
    scopes = [DEFAULT_SERVICE_SCOPE]
    if include_write_scope:
        scopes.append(OA_CREDENTIAL_SECURITY_WRITE_SCOPE)
    issued = issue_mock_service_token(
        service_id="nex-ag", audience="nex-oa", scopes=scopes
    )
    return {"Authorization": f"Bearer {issued.access_token}"}


def test_memory_password_change_rotates_hash_and_revokes_matching_sessions() -> None:
    repository, _, sessions, record, _ = _memory_repository()
    old_hash = record["password_hash"]

    result = repository.change_password(_change_payload())

    assert result["operation"] == "PASSWORD_CHANGED"
    assert result["credential_status"] == "ACTIVE"
    assert result["revoked_session_count"] == 1
    assert result["metadata"]["session_identifiers_included"] is False
    assert record["password_hash"] != old_hash
    assert verify_password("Changed1004!", password_hash=record["password_hash"])
    assert sessions.sessions["matching"]["status"] == "REVOKED"
    assert sessions.sessions["other"]["status"] == "ACTIVE"


def test_memory_reset_requires_change_and_revokes_active_sessions() -> None:
    repository, _, sessions, record, _ = _memory_repository()

    reset = repository.reset_password(_reset_payload())
    assert reset["operation"] == "PASSWORD_RESET"
    assert reset["credential_status"] == "PASSWORD_RESET_REQUIRED"
    assert sessions.sessions["matching"]["status"] == "REVOKED"

    sessions.sessions["new"] = {
        "status": "ACTIVE",
        "tenant_ref": {"id": "tenant-a"},
        "subject_ref": {"id": "user-a"},
        "revoked_at": None,
        "updated_at": "2026-10-01T00:00:00Z",
    }
    changed = repository.change_password(
        _change_payload(
            current_password="Temporary1004!", new_password="Final1004!"
        )
    )
    assert changed["credential_status"] == "ACTIVE"
    assert record["failed_attempt_count"] == 0
    assert sessions.sessions["new"]["status"] == "REVOKED"


def test_memory_change_failure_is_enumeration_safe_and_tracks_lockout() -> None:
    repository, _, sessions, record, _ = _memory_repository()
    for attempt in range(5):
        with pytest.raises(OaCredentialSecurityError) as caught:
            repository.change_password(
                _change_payload(current_password="Incorrect1004!")
            )
        assert caught.value.error_code == "oa.credential_not_verified"
        assert record["failed_attempt_count"] == attempt + 1
    assert record["status"] == "LOCKED"
    assert sessions.sessions["matching"]["status"] == "ACTIVE"

    with pytest.raises(OaCredentialSecurityError) as missing:
        repository.change_password(_change_payload(employee_id="missing"))
    assert missing.value.error_code == "oa.credential_not_verified"


def test_memory_rejects_reuse_disabled_reset_and_invalid_payloads() -> None:
    repository, _, _, record, _ = _memory_repository()
    with pytest.raises(OaCredentialSecurityError) as reuse:
        repository.change_password(_change_payload(new_password="Current1004!"))
    assert reuse.value.error_code == "oa.password_reuse_not_allowed"

    record["status"] = "DISABLED"
    with pytest.raises(OaCredentialSecurityError) as disabled_change:
        repository.change_password(_change_payload())
    with pytest.raises(OaCredentialSecurityError) as disabled_reset:
        repository.reset_password(_reset_payload())
    assert disabled_change.value.error_code == "oa.credential_not_verified"
    assert disabled_reset.value.error_code == "oa.credential_disabled"

    with pytest.raises(OaCredentialSecurityError, match="Unsupported"):
        normalize_password_change_request({**_change_payload(), "password_hint": "x"})
    with pytest.raises(OaCredentialSecurityError, match="Required"):
        normalize_password_reset_request({"tenant_id": "tenant-a"})
    with pytest.raises(OaCredentialSecurityError, match="between"):
        normalize_password_change_request(_change_payload(new_password="short"))
    with pytest.raises(OaCredentialSecurityError, match="string"):
        normalize_password_change_request(_change_payload(new_password=42))
    with pytest.raises(OaCredentialSecurityError, match="tenant_id"):
        normalize_password_change_request(_change_payload(tenant_id="bad tenant"))
    with pytest.raises(OaCredentialSecurityError, match="employee_id"):
        normalize_password_change_request(_change_payload(employee_id="bad employee"))
    with pytest.raises(OaCredentialSecurityError, match="object"):
        normalize_password_change_request(None)  # type: ignore[arg-type]
    with pytest.raises(OaCredentialSecurityError, match="reason_code"):
        normalize_password_reset_request(_reset_payload(reason_code=""))
    with pytest.raises(OaCredentialSecurityError, match="reason_code"):
        normalize_password_reset_request(_reset_payload(reason_code=42))


def test_memory_change_handles_locked_expiry_and_corrupt_hash() -> None:
    repository, _, _, record, _ = _memory_repository()
    record["status"] = "LOCKED"
    record["locked_at"] = datetime.now(UTC).isoformat()
    with pytest.raises(OaCredentialSecurityError) as locked:
        repository.change_password(_change_payload())
    assert locked.value.error_code == "oa.credential_not_verified"

    record["locked_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    result = repository.change_password(_change_payload())
    assert result["credential_status"] == "ACTIVE"

    repository, _, _, record, _ = _memory_repository()
    record["password_hash"] = "corrupt"
    with pytest.raises(OaCredentialSecurityError) as corrupt:
        repository.change_password(_change_payload())
    assert corrupt.value.error_code == "oa.password_hash_invalid"


def test_sql_change_commits_failure_state_then_rotates_atomically() -> None:
    repository, engine = _sqlite_repository()
    with pytest.raises(OaCredentialSecurityError) as wrong:
        repository.change_password(_change_payload(current_password="Incorrect1004!"))
    assert wrong.value.error_code == "oa.credential_not_verified"
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT failed_attempt_count FROM oa_local_credentials")
        ).scalar_one() == 1

    result = repository.change_password(_change_payload())
    assert result["revoked_session_count"] == 1
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, password_hash, failed_attempt_count "
                "FROM oa_local_credentials"
            )
        ).mappings().one()
        session_states = dict(
            connection.execute(
                text("SELECT session_id, status FROM oa_user_sessions")
            ).all()
        )
    assert row["status"] == "ACTIVE"
    assert row["failed_attempt_count"] == 0
    assert verify_password("Changed1004!", password_hash=row["password_hash"])
    assert session_states == {"matching": "REVOKED", "other": "ACTIVE"}


def test_sql_reset_and_missing_or_disabled_targets() -> None:
    repository, engine = _sqlite_repository()
    result = repository.reset_password(_reset_payload())
    assert result["credential_status"] == "PASSWORD_RESET_REQUIRED"
    assert result["reason_code"] == "operator.recovery"

    with pytest.raises(OaCredentialSecurityError) as missing:
        repository.reset_password(_reset_payload(employee_id="missing"))
    assert missing.value.status_code == 404

    with engine.begin() as connection:
        connection.execute(text("UPDATE oa_local_credentials SET status = 'DISABLED'"))
    with pytest.raises(OaCredentialSecurityError) as disabled:
        repository.reset_password(_reset_payload())
    assert disabled.value.error_code == "oa.credential_disabled"


def test_sql_change_handles_missing_locked_corrupt_and_zero_revocations() -> None:
    repository, engine = _sqlite_repository()
    with pytest.raises(OaCredentialSecurityError) as missing:
        repository.change_password(_change_payload(employee_id="missing"))
    assert missing.value.error_code == "oa.credential_not_verified"

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE oa_local_credentials SET status = 'LOCKED', locked_at = :now"),
            {"now": datetime.now(UTC).isoformat()},
        )
    with pytest.raises(OaCredentialSecurityError) as locked:
        repository.change_password(_change_payload())
    assert locked.value.error_code == "oa.credential_not_verified"

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE oa_local_credentials SET status = 'ACTIVE', "
                "locked_at = NULL, password_hash = 'corrupt'"
            )
        )
    with pytest.raises(OaCredentialSecurityError) as corrupt:
        repository.change_password(_change_payload())
    assert corrupt.value.error_code == "oa.password_hash_invalid"

    with engine.begin() as connection:
        replacement = hash_password("Current1004!")
        connection.execute(
            text("UPDATE oa_local_credentials SET password_hash = :hash"),
            {"hash": replacement},
        )
        connection.execute(text("UPDATE oa_user_sessions SET status = 'REVOKED'"))
    reset = repository.reset_password(_reset_payload())
    assert reset["revoked_session_count"] == 0


def test_sql_rotation_rolls_back_when_session_store_is_unavailable() -> None:
    repository, engine = _sqlite_repository(include_sessions=False)
    with engine.connect() as connection:
        before = connection.execute(
            text("SELECT password_hash FROM oa_local_credentials")
        ).scalar_one()
    with pytest.raises(OaCredentialSecurityError) as unavailable:
        repository.change_password(_change_payload())
    assert unavailable.value.error_code == "oa.credential_security_unavailable"
    with engine.connect() as connection:
        after = connection.execute(
            text("SELECT password_hash FROM oa_local_credentials")
        ).scalar_one()
    assert after == before


def test_routes_require_dedicated_scope_and_never_return_secrets() -> None:
    repository, _, _, _, _ = _memory_repository()
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_credential_security_routes(app, repository=repository)
    client = TestClient(app)

    assert client.post(
        "/internal/v1/auth/local-credentials/change-password", json=_change_payload()
    ).status_code == 401
    denied = client.post(
        "/internal/v1/auth/local-credentials/change-password",
        headers=_headers(include_write_scope=False),
        json=_change_payload(),
    )
    assert denied.status_code == 403
    response = client.post(
        "/internal/v1/auth/local-credentials/change-password",
        headers=_headers(),
        json=_change_payload(),
    )
    assert response.status_code == 200
    body = response.json()
    serialized = response.text.lower()
    assert body["request_id"]
    assert "changed1004" not in serialized
    assert "password_hash" not in serialized or '"password_hash_included":false' in serialized
    assert "matching" not in serialized

    bad_reset = client.post(
        "/internal/v1/auth/local-credentials/reset-password",
        headers=_headers(),
        json=_reset_payload(employee_id="missing"),
    )
    assert bad_reset.status_code == 404
    reset = client.post(
        "/internal/v1/auth/local-credentials/reset-password",
        headers=_headers(),
        json=_reset_payload(),
    )
    assert reset.status_code == 200
    assert reset.json()["credential_status"] == "PASSWORD_RESET_REQUIRED"
    assert client.post(
        "/internal/v1/auth/local-credentials/reset-password", json=_reset_payload()
    ).status_code == 401


def test_repository_factory_and_lockout_time_edges() -> None:
    repository, credentials, sessions, _, _ = _memory_repository()
    memory = build_credential_security_repository_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_MEMORY, api_session_factory=None),
        credential_registry=credentials,
        session_registry=sessions,
    )
    postgres = build_credential_security_repository_for_runtime(
        SimpleNamespace(
            mode=PERSISTENCE_MODE_POSTGRES,
            api_session_factory=build_session_factory(build_engine("sqlite+pysqlite:///:memory:")),
        ),
        credential_registry=credentials,
        session_registry=sessions,
    )
    assert isinstance(memory, InMemoryOaCredentialSecurityRepository)
    assert isinstance(postgres, SqlAlchemyOaCredentialSecurityRepository)
    assert isinstance(repository, InMemoryOaCredentialSecurityRepository)
    postgres_without_factory = build_credential_security_repository_for_runtime(
        SimpleNamespace(mode=PERSISTENCE_MODE_POSTGRES, api_session_factory=None),
        credential_registry=credentials,
        session_registry=sessions,
    )
    assert isinstance(postgres_without_factory, InMemoryOaCredentialSecurityRepository)
    assert _lockout_expired(None) is False
    assert _lockout_expired(object()) is False
    assert _lockout_expired(datetime.now(UTC) - timedelta(hours=1)) is True
    assert _lockout_expired(
        (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    ) is True
    assert _lockout_expired("invalid") is False
    assert _timestamp_to_wire(datetime(2026, 10, 1)) == "2026-10-01T00:00:00Z"


def test_sql_transaction_helper_preserves_domain_errors() -> None:
    repository, _ = _sqlite_repository()
    expected = OaCredentialSecurityError(409, "oa.test", "test")
    with pytest.raises(OaCredentialSecurityError) as caught:
        repository._run(lambda _session: (_ for _ in ()).throw(expected))
    assert caught.value is expected


def test_nex_oa_entrypoint_registers_credential_security_routes() -> None:
    from nex_oa.main import app

    paths = {route.path for route in app.routes}
    assert "/internal/v1/auth/local-credentials/change-password" in paths
    assert "/internal/v1/auth/local-credentials/reset-password" in paths
