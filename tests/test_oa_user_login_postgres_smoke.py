from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import run_oa_user_login_postgres_smoke as oa_login_smoke


def sqlite_oa_user_login_smoke_tables(database_url: str) -> None:
    engine = oa_login_smoke.build_engine(database_url)
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


def test_oa_user_login_postgres_smoke_skips_by_default() -> None:
    evidence = oa_login_smoke.run_oa_user_login_postgres_smoke(environ={})

    assert evidence["status"] == "SKIPPED"
    assert oa_login_smoke.summary_line(evidence) == (
        "oa_user_login_postgres_smoke=skipped "
        "reason=NEX_OA_USER_LOGIN_POSTGRES_SMOKE"
    )


def test_oa_user_login_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = oa_login_smoke.run_oa_user_login_postgres_smoke(
        environ={
            "NEX_OA_USER_LOGIN_POSTGRES_SMOKE": "1",
            "NEX_OA_USER_LOGIN_POSTGRES_SMOKE_PROFILE": "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_oa_user_login_postgres_smoke_reports_pass_without_leaking_secret(
    monkeypatch,
) -> None:
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        oa_login_smoke,
        "service_database_env",
        lambda service_id, profile: f"{service_id}:{profile}:env",
    )
    monkeypatch.setattr(
        oa_login_smoke,
        "service_database_url",
        lambda service_id, profile, environ: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        oa_login_smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: (
            migration_calls.append((service_id, profile))
            or SimpleNamespace(
                service_id=service_id,
                profile=profile,
                planned=("001", "002", "003"),
                applied=("003",),
                skipped=("001", "002"),
                dry_run=False,
            )
        ),
    )
    monkeypatch.setattr(
        oa_login_smoke,
        "_execute_oa_user_login_postgres_smoke",
        lambda database_env, database_url, runtime_environ: {
            "tenant_id": "tenant-smoke",
            "subject_id": "user-smoke",
            "normalized_employee_id": "emp-smoke",
            "session_id": "session-smoke",
            "db_observations": {
                "credential_count": 1,
                "hash_algorithm": "pbkdf2_sha256.v1",
                "membership_count": 1,
                "session_count": 1,
            },
            "checks": {"raw_payload_absent": True},
            "cleanup_observations": {
                "deleted_sessions": 1,
                "deleted_credentials": 1,
                "deleted_memberships": 1,
                "deleted_subjects": 1,
                "deleted_tenants": 1,
            },
        },
    )

    evidence = oa_login_smoke.run_oa_user_login_postgres_smoke(
        environ={"NEX_OA_USER_LOGIN_POSTGRES_SMOKE": "1"}
    )

    assert evidence["status"] == "PASS"
    assert evidence["database_env"] == "nex-oa:test:env"
    assert evidence["redacted_database_url"] == "postgresql://user:***@localhost/db"
    assert evidence["migration"]["applied"] == ["003"]
    assert migration_calls == [("nex-oa", "test")]
    assert "secret" not in json.dumps(evidence)
    assert oa_login_smoke.summary_line(evidence) == (
        "oa_user_login_postgres_smoke=pass service=nex-oa "
        "db_env=nex-oa:test:env"
    )


def test_oa_user_login_postgres_smoke_reports_config_and_execution_failures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        oa_login_smoke,
        "service_database_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            oa_login_smoke.MigrationError("missing database URL env")
        ),
    )
    config_failure = oa_login_smoke.run_oa_user_login_postgres_smoke(
        environ={"NEX_OA_USER_LOGIN_POSTGRES_SMOKE": "1"}
    )

    assert config_failure["status"] == "FAIL"
    assert config_failure["failure_code"] == "configuration_invalid"

    monkeypatch.setattr(
        oa_login_smoke,
        "service_database_url",
        lambda *args, **kwargs: "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setattr(
        oa_login_smoke,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            service_id="nex-oa",
            profile="test",
            planned=(),
            applied=(),
            skipped=(),
            dry_run=False,
        ),
    )
    monkeypatch.setattr(
        oa_login_smoke,
        "_execute_oa_user_login_postgres_smoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    execution_failure = oa_login_smoke.run_oa_user_login_postgres_smoke(
        environ={"NEX_OA_USER_LOGIN_POSTGRES_SMOKE": "1"}
    )

    assert execution_failure["status"] == "FAIL"
    assert execution_failure["failure_code"] == "execution_failed"
    assert oa_login_smoke.summary_line(execution_failure) == (
        "oa_user_login_postgres_smoke=fail service=nex-oa reason=execution_failed"
    )


def test_oa_user_login_postgres_smoke_executes_with_sqlite_fixture(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'oa_login_smoke.sqlite3'}"
    sqlite_oa_user_login_smoke_tables(database_url)

    evidence = oa_login_smoke._execute_oa_user_login_postgres_smoke(
        database_env="NEX_OA_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            oa_login_smoke.SERVICE_SPEC.database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )

    assert evidence["checks"]["runtime_mode"] is True
    assert evidence["checks"]["credential_status_ok"] is True
    assert evidence["checks"]["membership_status_ok"] is True
    assert evidence["checks"]["login_status_ok"] is True
    assert evidence["checks"]["login_password_verified"] is True
    assert evidence["checks"]["login_subject_matches"] is True
    assert evidence["checks"]["readback_status_ok"] is True
    assert evidence["checks"]["readback_session_roundtrip"] is True
    assert evidence["checks"]["introspection_status_ok"] is True
    assert evidence["checks"]["introspection_active"] is True
    assert evidence["checks"]["revocation_status_ok"] is True
    assert evidence["checks"]["revocation_inactive"] is True
    assert evidence["checks"]["revoked_introspection_status_ok"] is True
    assert evidence["checks"]["revoked_introspection_inactive"] is True
    assert evidence["checks"]["credential_persisted"] is True
    assert evidence["checks"]["credential_hash_algorithm_recorded"] is True
    assert evidence["checks"]["raw_password_not_stored"] is True
    assert evidence["checks"]["membership_persisted"] is True
    assert evidence["checks"]["session_persisted"] is True
    assert evidence["checks"]["db_session_revoked"] is True
    assert evidence["checks"]["raw_payload_absent"] is True
    assert evidence["db_observations"]["credential_count"] == 1
    assert evidence["db_observations"]["hash_algorithm"] == "pbkdf2_sha256.v1"
    assert evidence["db_observations"]["raw_password_match_count"] == 0
    assert evidence["db_observations"]["membership_count"] == 1
    assert evidence["db_observations"]["session_count"] == 1
    assert evidence["db_observations"]["session_status"] == "REVOKED"
    assert evidence["cleanup_observations"] == {
        "deleted_sessions": 1,
        "deleted_credentials": 1,
        "deleted_memberships": 1,
        "deleted_subjects": 1,
        "deleted_tenants": 1,
    }


def test_oa_user_login_postgres_smoke_execute_failure_edges(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'oa_login_smoke.sqlite3'}"
    sqlite_oa_user_login_smoke_tables(database_url)

    monkeypatch.setattr(
        oa_login_smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(api_session_factory=None),
    )
    with pytest.raises(RuntimeError, match="user-login PostgreSQL smoke factory"):
        oa_login_smoke._execute_oa_user_login_postgres_smoke(
            database_env="NEX_OA_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                oa_login_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )

    monkeypatch.undo()
    monkeypatch.setattr(
        oa_login_smoke,
        "_db_observations",
        lambda *args, **kwargs: {
            "credential_count": 0,
            "credential_status": None,
            "hash_algorithm": None,
            "credential_subject_id": None,
            "raw_password_match_count": 1,
            "membership_count": 0,
            "session_count": 0,
            "session_tenant_id": None,
            "session_subject_id": None,
            "session_status": None,
            "session_revoked_at": None,
            "session_scopes": [],
            "session_roles": [],
        },
    )
    with pytest.raises(RuntimeError, match="smoke checks failed"):
        oa_login_smoke._execute_oa_user_login_postgres_smoke(
            database_env="NEX_OA_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                oa_login_smoke.SERVICE_SPEC.database_env: database_url,
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )


def test_oa_user_login_postgres_smoke_helpers_and_main(monkeypatch, capsys) -> None:
    assert oa_login_smoke._json_loads(None) is None
    assert oa_login_smoke._json_loads({"safe": True}) == {"safe": True}
    assert oa_login_smoke._json_loads(b'["workspace:use"]') == ["workspace:use"]
    assert oa_login_smoke._json_loads(3) == 3
    assert oa_login_smoke._redaction_safe({"value": "safe"}, ["secret"])
    assert not oa_login_smoke._redaction_safe({"value": "secret"}, ["secret"])
    assert oa_login_smoke._failure(
        "example",
        "detail",
        profile="test",
    )["status"] == "FAIL"

    monkeypatch.setattr(oa_login_smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        oa_login_smoke,
        "run_oa_user_login_postgres_smoke",
        lambda: {
            "smoke_schema_version": "oa_user_login_postgres_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": "NEX_OA_USER_LOGIN_POSTGRES_SMOKE is not enabled.",
        },
    )

    assert oa_login_smoke.main(["--summary"]) == 0
    assert "oa_user_login_postgres_smoke=skipped" in capsys.readouterr().out

    assert oa_login_smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
