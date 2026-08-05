from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import nex_runtime.database as runtime_database
from nex_runtime import (
    DatabaseConfigError,
    DatabasePoolSettings,
    build_engine,
    build_session_factory,
    build_unit_of_work,
    check_database_readiness,
    check_sqlalchemy_engine,
    database_pool_settings,
    redact_database_url,
    required_database_url,
    service_database_settings,
    service_database_env_prefix,
    sqlalchemy_database_url,
)


class FakeCursor:
    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[str, str]:
        return ("nex_test_dev", "nex_test_user")


class FakeConnection:
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_required_database_url_rejects_missing_and_placeholder() -> None:
    with pytest.raises(DatabaseConfigError, match="missing database URL env NEX_TEST_DATABASE_URL"):
        required_database_url("NEX_TEST_DATABASE_URL", environ={})

    with pytest.raises(DatabaseConfigError, match="placeholder password"):
        required_database_url(
            "NEX_TEST_DATABASE_URL",
            environ={"NEX_TEST_DATABASE_URL": "postgresql://user:<password>@localhost/db"},
        )


def test_required_database_url_returns_configured_value() -> None:
    assert (
        required_database_url(
            "NEX_TEST_DATABASE_URL",
            environ={"NEX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/db"},
        )
        == "postgresql://user:secret@localhost/db"
    )


def test_redact_database_url_hides_password_and_handles_passwordless_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        redact_database_url("postgresql://user:secret@localhost/db")
        == "postgresql://user:***@localhost/db"
    )
    assert (
        redact_database_url("postgresql://user@localhost/db")
        == "postgresql://user@localhost/db"
    )

    def raise_sqlalchemy_error(database_url: str) -> None:
        raise SQLAlchemyError("bad url")

    monkeypatch.setattr(runtime_database, "make_url", raise_sqlalchemy_error)
    assert redact_database_url("postgresql://user:secret@localhost/db") == "<redacted-database-url>"


def test_service_database_settings_keeps_vector_store_optional() -> None:
    settings = service_database_settings(
        service_id="nex-oa",
        database_env="NEX_OA_DATABASE_URL",
        environ={"NEX_OA_DATABASE_URL": "postgresql://nex_oa_user:secret@localhost/nex_oa_dev"},
    )

    assert settings.service_id == "nex-oa"
    assert settings.vector_database_env is None
    assert settings.vector_database_url is None
    assert settings.redacted_database_url == "postgresql://nex_oa_user:***@localhost/nex_oa_dev"


def test_service_database_settings_falls_back_to_primary_for_cx_vectors() -> None:
    settings = service_database_settings(
        service_id="nex-cx",
        database_env="NEX_CX_DATABASE_URL",
        environ={"NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_dev"},
    )

    assert settings.vector_database_env == "NEX_CX_VECTOR_DATABASE_URL"
    assert settings.vector_database_url == settings.database_url
    assert settings.vector_uses_primary is True
    assert settings.redacted_vector_database_url == "postgresql://nex_cx_user:***@localhost/nex_cx_dev"


def test_service_database_settings_accepts_separate_cx_vector_database() -> None:
    settings = service_database_settings(
        service_id="nex-cx",
        database_env="NEX_CX_DATABASE_URL",
        environ={
            "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_dev",
            "NEX_CX_VECTOR_DATABASE_URL": "postgresql://nex_vector_user:secret@localhost/nex_vector_dev",
        },
    )

    assert settings.vector_database_url == "postgresql://nex_vector_user:secret@localhost/nex_vector_dev"
    assert settings.vector_uses_primary is False
    assert settings.redacted_vector_database_url == "postgresql://nex_vector_user:***@localhost/nex_vector_dev"


def test_service_database_settings_rejects_placeholder_vector_database() -> None:
    with pytest.raises(DatabaseConfigError, match="NEX_CX_VECTOR_DATABASE_URL"):
        service_database_settings(
            service_id="nex-cx",
            database_env="NEX_CX_DATABASE_URL",
            environ={
                "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_dev",
                "NEX_CX_VECTOR_DATABASE_URL": "postgresql://nex_cx_user:<password>@localhost/vector",
            },
        )


def test_service_database_env_prefix_resolves_known_services() -> None:
    assert service_database_env_prefix("nex-cx") == "NEX_CX"
    assert service_database_env_prefix("nex-ae-api") == "NEX_AE"

    with pytest.raises(DatabaseConfigError, match="unknown service id"):
        service_database_env_prefix("unknown")


def test_database_pool_settings_uses_api_defaults_and_service_env_overrides() -> None:
    settings = database_pool_settings(
        "nex-cx",
        environ={
            "NEX_CX_DB_POOL_SIZE": "7",
            "NEX_CX_DB_MAX_OVERFLOW": "11",
            "NEX_CX_DB_POOL_TIMEOUT_SECONDS": "12.5",
            "NEX_CX_DB_POOL_RECYCLE_SECONDS": "600",
            "NEX_CX_DB_POOL_PRE_PING": "false",
            "NEX_CX_DB_STATEMENT_TIMEOUT_MS": "45000",
        },
    )

    assert settings == DatabasePoolSettings(
        service_id="nex-cx",
        env_prefix="NEX_CX",
        workload="api",
        pool_size=7,
        max_overflow=11,
        pool_timeout_seconds=12.5,
        pool_recycle_seconds=600,
        pool_pre_ping=False,
        statement_timeout_ms=45000,
    )


def test_database_pool_settings_uses_worker_defaults_and_specific_overrides() -> None:
    settings = database_pool_settings(
        "nex-cx",
        workload="worker",
        environ={
            "NEX_CX_DB_POOL_SIZE": "9",
            "NEX_CX_DB_WORKER_POOL_SIZE": "4",
            "NEX_CX_DB_WORKER_MAX_OVERFLOW": "2",
            "NEX_CX_DB_STATEMENT_TIMEOUT_MS": "30000",
            "NEX_CX_DB_WORKER_STATEMENT_TIMEOUT_MS": "90000",
        },
    )

    assert settings.pool_size == 4
    assert settings.max_overflow == 2
    assert settings.pool_timeout_seconds == 30.0
    assert settings.pool_recycle_seconds == 1800
    assert settings.pool_pre_ping is True
    assert settings.statement_timeout_ms == 90000


def test_database_pool_settings_uses_truthy_boolean_and_base_worker_fallback() -> None:
    settings = database_pool_settings(
        "nex-mo",
        workload="worker",
        environ={
            "NEX_MO_DB_POOL_PRE_PING": "yes",
            "NEX_MO_DB_POOL_TIMEOUT_SECONDS": "42",
        },
    )

    assert settings.pool_pre_ping is True
    assert settings.pool_timeout_seconds == 42.0
    assert settings.pool_size == 3
    assert settings.statement_timeout_ms == 60000


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"NEX_CX_DB_POOL_SIZE": "0"}, "greater than 0"),
        ({"NEX_CX_DB_MAX_OVERFLOW": "bad"}, "integer"),
        ({"NEX_CX_DB_MAX_OVERFLOW": "-1"}, "greater than or equal to 0"),
        ({"NEX_CX_DB_POOL_TIMEOUT_SECONDS": "bad"}, "number"),
        ({"NEX_CX_DB_POOL_TIMEOUT_SECONDS": "0"}, "greater than 0"),
        ({"NEX_CX_DB_POOL_RECYCLE_SECONDS": "bad"}, "integer"),
        ({"NEX_CX_DB_POOL_PRE_PING": "sometimes"}, "boolean"),
        ({"NEX_CX_DB_STATEMENT_TIMEOUT_MS": "-1"}, "greater than or equal to 0"),
    ],
)
def test_database_pool_settings_rejects_invalid_env_values(
    env: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(DatabaseConfigError, match=message):
        database_pool_settings("nex-cx", environ=env)


def test_database_pool_settings_rejects_unknown_workload() -> None:
    with pytest.raises(DatabaseConfigError, match="unsupported database workload"):
        database_pool_settings("nex-cx", workload="batch", environ={})


def test_build_engine_and_session_factory_execute_sql() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")

    assert check_sqlalchemy_engine(engine) is True

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        assert session.execute(text("select 1")).scalar_one() == 1


def test_build_engine_applies_pool_settings_without_connecting_to_postgres() -> None:
    settings = DatabasePoolSettings(
        service_id="nex-cx",
        env_prefix="NEX_CX",
        workload="api",
        pool_size=2,
        max_overflow=4,
        pool_timeout_seconds=7.5,
        pool_recycle_seconds=99,
        pool_pre_ping=True,
        statement_timeout_ms=12000,
    )

    engine = build_engine(
        "postgresql+psycopg://user:secret@localhost/nex_cx_dev",
        pool_settings=settings,
    )

    assert engine.url.render_as_string(hide_password=True) == (
        "postgresql+psycopg://user:***@localhost/nex_cx_dev"
    )
    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 4
    assert engine.pool._timeout == 7.5
    assert engine.pool._recycle == 99


def test_build_engine_normalizes_bare_postgresql_url_to_psycopg_driver() -> None:
    assert (
        sqlalchemy_database_url("postgresql://user:secret@localhost/nex_cx_dev")
        == "postgresql+psycopg://user:secret@localhost/nex_cx_dev"
    )

    engine = build_engine("postgresql://user:secret@localhost/nex_cx_dev")

    assert engine.url.drivername == "postgresql+psycopg"


def test_build_engine_allows_statement_timeout_to_be_disabled() -> None:
    settings = DatabasePoolSettings(
        service_id="nex-cx",
        env_prefix="NEX_CX",
        workload="api",
        statement_timeout_ms=0,
    )

    engine = build_engine(
        "postgresql+psycopg://user:secret@localhost/nex_cx_dev",
        pool_settings=settings,
    )

    assert engine.pool.size() == 5


def test_unit_of_work_commits_rolls_back_and_requires_active_session() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("create table items (id integer primary key, name text)"))
    session_factory = build_session_factory(engine)
    uow = build_unit_of_work(session_factory)

    with pytest.raises(RuntimeError, match="not active"):
        _ = uow.db

    with build_unit_of_work(session_factory) as active:
        active.db.execute(text("insert into items (name) values ('committed')"))

    with session_factory() as session:
        assert session.execute(text("select count(*) from items")).scalar_one() == 1

    with pytest.raises(ValueError, match="boom"):
        with build_unit_of_work(session_factory) as active:
            active.db.execute(text("insert into items (name) values ('rolled back')"))
            raise ValueError("boom")

    with session_factory() as session:
        assert session.execute(text("select count(*) from items")).scalar_one() == 1


def test_check_database_readiness_reports_missing_placeholder_and_failure() -> None:
    missing = check_database_readiness("NEX_TEST_DATABASE_URL", environ={})
    assert missing["ok"] is False
    assert missing["error_code"] == "DATABASE_URL_MISSING"

    placeholder = check_database_readiness(
        "NEX_TEST_DATABASE_URL",
        environ={"NEX_TEST_DATABASE_URL": "postgresql://user:<password>@localhost/db"},
    )
    assert placeholder["ok"] is False
    assert placeholder["error_code"] == "DATABASE_URL_PLACEHOLDER"
    assert "<password>" not in str(placeholder)

    def fail_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        raise RuntimeError("database unavailable")

    failed = check_database_readiness(
        "NEX_TEST_DATABASE_URL",
        environ={"NEX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/db"},
        connect=fail_connect,
    )
    assert failed["ok"] is False
    assert failed["error_code"] == "DATABASE_CONNECTION_FAILED"


def test_check_database_readiness_reports_database_identity() -> None:
    calls: list[tuple[str, int]] = []

    def fake_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        calls.append((database_url, connect_timeout))
        return FakeConnection()

    check = check_database_readiness(
        "NEX_TEST_DATABASE_URL",
        environ={"NEX_TEST_DATABASE_URL": "postgresql://user:secret@localhost/db"},
        connect=fake_connect,
        connect_timeout=3,
    )

    assert check["ok"] is True
    assert check["database_name"] == "nex_test_dev"
    assert check["database_user"] == "nex_test_user"
    assert check["latency_ms"] >= 0
    assert "secret" not in str(check)
    assert calls == [("postgresql://user:secret@localhost/db", 3)]
