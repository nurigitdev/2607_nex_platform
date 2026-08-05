from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import nex_runtime.database as runtime_database
from nex_runtime import (
    DatabaseConfigError,
    build_engine,
    build_session_factory,
    check_database_readiness,
    check_sqlalchemy_engine,
    redact_database_url,
    required_database_url,
    service_database_settings,
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


def test_build_engine_and_session_factory_execute_sql() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")

    assert check_sqlalchemy_engine(engine) is True

    session_factory = build_session_factory(engine)
    with session_factory() as session:
        assert session.execute(text("select 1")).scalar_one() == 1


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
