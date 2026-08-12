from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import run_ae_oa_auth_postgres_smoke as smoke
from nex_ae_api.oa_session_client import OaUserSessionClientError


def protected_env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.SMOKE_PROFILE_ENV: smoke.DEFAULT_PROFILE,
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-pass-0250@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret-pass-0250@127.0.0.1:5432/nex_oa_test"
        ),
    }


class FakeMigrationResult:
    service_id = "nex-test"
    profile = "test"
    planned = ("001", "002")
    applied = ()
    skipped = ("001", "002")
    dry_run = False


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeOaTestClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def post(self, path: str, **kwargs: object) -> FakeResponse:
        return self.response


def sqlite_oa_auth_smoke_tables(*, ae_database_url: str, oa_database_url: str) -> None:
    ae_engine = smoke.build_engine(ae_database_url)
    oa_engine = smoke.build_engine(oa_database_url)
    with ae_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_operational_events (
                    event_id TEXT PRIMARY KEY,
                    event_schema_version TEXT NOT NULL DEFAULT 'operational_event.v1',
                    service_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT,
                    subject_type TEXT,
                    subject_id TEXT,
                    message TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    with oa_engine.begin() as connection:
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


def test_ae_oa_auth_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_oa_auth_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        f"ae_oa_auth_postgres_smoke=skipped reason={smoke.SMOKE_ENV}"
    )


def test_ae_oa_auth_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_ae_oa_auth_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.SMOKE_PROFILE_ENV: "dev"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_ae_oa_auth_postgres_smoke_requires_test_database_urls() -> None:
    missing = smoke.run_ae_oa_auth_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "configuration_invalid"

    env = protected_env()
    env["NEX_AE_TEST_DATABASE_URL"] = (
        "postgresql+psycopg://nex_ae_user:secret-pass-0250@127.0.0.1:5432/nex_ae_dev"
    )
    dev_url = smoke.run_ae_oa_auth_postgres_smoke(env)

    assert dev_url["status"] == "FAIL"
    assert dev_url["failure_code"] == "configuration_invalid"
    assert "must target a *_test database" in dev_url["detail"]


def test_ae_oa_auth_postgres_smoke_passes_with_fake_db_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    migration_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service_id, database_url, profile: (
            migration_calls.append((service_id, profile)) or FakeMigrationResult()
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_ae_oa_auth_postgres_smoke",
        lambda **kwargs: {
            "db_observations": {
                "ae_marker_rows": 1,
                "oa_membership_count": 1,
                "oa_credential_count": 1,
                "oa_session_count": 1,
                "oa_session_status": "REVOKED",
                "oa_session_revoked_at_present": True,
            },
            "checks": {"all_good": True},
        },
    )

    evidence = smoke.run_ae_oa_auth_postgres_smoke(env)
    serialized = json.dumps(evidence, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["redacted_database_urls"]["ae"].endswith("@127.0.0.1:5432/nex_ae_test")
    assert evidence["migrations"]["ae"]["planned_count"] == 2
    assert migration_calls == [("nex-ae-api", "test"), ("nex-oa", "test")]
    assert "secret-pass-0250" not in serialized
    assert "ae_oa_auth_postgres_smoke=pass profile=test" in smoke.summary_line(evidence)


def test_ae_oa_auth_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: FakeMigrationResult())
    monkeypatch.setattr(
        smoke,
        "_execute_ae_oa_auth_postgres_smoke",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    evidence = smoke.run_ae_oa_auth_postgres_smoke(env)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert smoke.summary_line(evidence) == "ae_oa_auth_postgres_smoke=fail reason=execution_failed"


def test_execute_ae_oa_auth_postgres_smoke_runs_with_sqlite_fixture(tmp_path) -> None:
    ae_database_url = f"sqlite+pysqlite:///{tmp_path / 'ae_auth_smoke.sqlite3'}"
    oa_database_url = f"sqlite+pysqlite:///{tmp_path / 'oa_auth_smoke.sqlite3'}"
    sqlite_oa_auth_smoke_tables(
        ae_database_url=ae_database_url,
        oa_database_url=oa_database_url,
    )

    evidence = smoke._execute_ae_oa_auth_postgres_smoke(
        env={
            smoke.AE_SERVICE_SPEC.database_env: ae_database_url,
            smoke.OA_SERVICE_SPEC.database_env: oa_database_url,
        },
        ae_database_url=ae_database_url,
        oa_database_url=oa_database_url,
    )

    assert evidence["checks"]["ae_runtime_mode"] is True
    assert evidence["checks"]["oa_runtime_mode"] is True
    assert evidence["checks"]["ae_marker_write_readback"] is True
    assert evidence["checks"]["membership_status_ok"] is True
    assert evidence["checks"]["credential_status_ok"] is True
    assert evidence["checks"]["login_status_ok"] is True
    assert evidence["checks"]["login_password_verified"] is True
    assert evidence["checks"]["current_status_ok"] is True
    assert evidence["checks"]["protected_status_ok"] is True
    assert evidence["checks"]["logout_status_ok"] is True
    assert evidence["checks"]["current_after_logout_rejected"] is True
    assert evidence["checks"]["cookie_set_after_login"] is True
    assert evidence["checks"]["cookie_removed_after_logout"] is True
    assert evidence["checks"]["protected_owner_scope_claim_derived"] is True
    assert evidence["checks"]["oa_post_logout_inactive"] is True
    assert evidence["checks"]["credential_persisted"] is True
    assert evidence["checks"]["db_session_revoked"] is True
    assert evidence["checks"]["raw_payload_absent"] is True
    assert evidence["db_observations"] == {
        "ae_marker_rows": 1,
        "oa_membership_count": 1,
        "oa_credential_count": 1,
        "oa_session_count": 1,
        "oa_session_status": "REVOKED",
        "oa_session_revoked_at_present": True,
    }
    assert evidence["auth_observations"]["ae_auth_session_mode"] == "oa"
    assert evidence["auth_observations"]["browser_cookie_material_in_evidence"] is False
    assert evidence["adapter_observations"]["oa_client_operations"] == [
        "login_with_credentials",
        "introspect_session",
        "introspect_session",
        "revoke_session",
        "introspect_session",
    ]
    assert evidence["cleanup_observations"]["ae_marker_rows_after_delete"] == 0
    assert evidence["cleanup_observations"]["oa_rows"] == {
        "deleted_sessions": 1,
        "deleted_credentials": 1,
        "deleted_memberships": 1,
        "deleted_subjects": 1,
        "deleted_tenants": 1,
    }


def test_execute_ae_oa_auth_postgres_smoke_failure_edges(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ae_database_url = f"sqlite+pysqlite:///{tmp_path / 'ae_auth_smoke.sqlite3'}"
    oa_database_url = f"sqlite+pysqlite:///{tmp_path / 'oa_auth_smoke.sqlite3'}"
    sqlite_oa_auth_smoke_tables(
        ae_database_url=ae_database_url,
        oa_database_url=oa_database_url,
    )

    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(mode="postgres", api_session_factory=None),
    )
    with pytest.raises(RuntimeError, match="OA PostgreSQL session factory"):
        smoke._execute_ae_oa_auth_postgres_smoke(
            env={},
            ae_database_url=ae_database_url,
            oa_database_url=oa_database_url,
        )

    monkeypatch.undo()
    original_attach = smoke.attach_service_persistence_runtime

    def missing_ae_factory(app: object, spec: object, **kwargs: object) -> object:
        if getattr(spec, "service_id", "") == "nex-ae-api":
            return SimpleNamespace(mode="postgres", api_session_factory=None)
        return original_attach(app, spec, **kwargs)

    monkeypatch.setattr(smoke, "attach_service_persistence_runtime", missing_ae_factory)
    with pytest.raises(RuntimeError, match="AE PostgreSQL session factory"):
        smoke._execute_ae_oa_auth_postgres_smoke(
            env={},
            ae_database_url=ae_database_url,
            oa_database_url=oa_database_url,
        )

    monkeypatch.undo()
    monkeypatch.setattr(smoke, "_count_ae_marker_rows", lambda *args, **kwargs: 0)
    with pytest.raises(RuntimeError, match="smoke checks failed"):
        smoke._execute_ae_oa_auth_postgres_smoke(
            env={},
            ae_database_url=ae_database_url,
            oa_database_url=oa_database_url,
        )


def test_execute_ae_oa_auth_postgres_smoke_route_auth_problem_branch(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ae_database_url = f"sqlite+pysqlite:///{tmp_path / 'ae_auth_smoke.sqlite3'}"
    oa_database_url = f"sqlite+pysqlite:///{tmp_path / 'oa_auth_smoke.sqlite3'}"
    sqlite_oa_auth_smoke_tables(
        ae_database_url=ae_database_url,
        oa_database_url=oa_database_url,
    )
    monkeypatch.setattr(
        smoke,
        "authorize_ae_facade_route_request",
        lambda *args, **kwargs: smoke.JSONResponse(
            {"error_code": "ae.auth_forced_failure"},
            status_code=401,
        ),
    )

    with pytest.raises(Exception, match="Client error"):
        smoke._execute_ae_oa_auth_postgres_smoke(
            env={},
            ae_database_url=ae_database_url,
            oa_database_url=oa_database_url,
        )


def test_testclient_oa_session_client_maps_errors() -> None:
    client = smoke.TestClientOaUserSessionClient(
        FakeOaTestClient(
            FakeResponse(
                503,
                {
                    "error_code": "oa.down",
                    "detail": "OA down",
                    "retryable": True,
                },
            )
        )
    )

    with pytest.raises(OaUserSessionClientError) as raised:
        client.issue_session(
            {
                "tenant_id": "tenant",
                "user_id": "user",
                "scopes": [smoke.DEFAULT_USER_SCOPE],
                "ttl_seconds": 60,
            },
            request_id="request",
            trace_id="0" * 32,
        )

    assert raised.value.status_code == 503
    assert raised.value.error_code == "oa.down"
    assert raised.value.retryable is True
    assert client.calls == [{"operation": "issue_session", "status_code": 503}]


def test_ae_oa_auth_postgres_smoke_helpers_and_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert smoke._json_loads(None) is None
    assert smoke._json_loads({"safe": True}) == {"safe": True}
    assert smoke._json_loads(b'["workspace:use"]') == ["workspace:use"]
    assert smoke._json_loads(3) == 3
    assert smoke._redaction_safe({"value": "safe"}, ["secret"])
    assert not smoke._redaction_safe({"value": "secret"}, ["secret"])
    assert smoke._count_ae_marker_rows(object(), event_id=None) == 0
    assert smoke._delete_ae_smoke_marker(object(), event_id=None) == 0
    assert smoke._safe_response_json(FakeResponse(200, ValueError("bad"))) == {}
    assert smoke._safe_response_json(FakeResponse(200, ["not-object"])) == {}
    assert smoke._failure("example", "detail", profile="test")["status"] == "FAIL"
    smoke._require_test_database_url("sqlite+pysqlite:///example_test", env_name="DB")
    with pytest.raises(ValueError, match="valid database URL"):
        smoke._require_test_database_url("://bad", env_name="DB")
    with pytest.raises(ValueError, match="target a \\*_test database"):
        smoke._require_test_database_url("sqlite+pysqlite:///example_dev", env_name="DB")
    with pytest.raises(ValueError, match="unredacted environment value"):
        smoke.assert_smoke_evidence_redacted(
            "postgresql://user:secret@localhost/nex_ae_test",
            {"NEX_AE_TEST_DATABASE_URL": "postgresql://user:secret@localhost/nex_ae_test"},
        )

    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_oa_auth_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_oa_auth_postgres_smoke=skipped" in capsys.readouterr().out

    assert smoke.main([]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
