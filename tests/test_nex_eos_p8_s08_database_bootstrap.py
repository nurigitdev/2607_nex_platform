from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import pytest
from nex_eos import (
    EOS_TEST_RESET_CONFIRMATION,
    EosDatabaseRuntimeError,
    EosTestDatabaseResetError,
    build_eos_database_runtime,
    reset_eos_test_database,
)
from nex_eos.app import create_eos_app
from run_migrations import (
    load_migrations,
    run_service_migrations,
    service_database_env,
)

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql://nex_eos_user:unit-secret@127.0.0.1:5432/nex_eos_test"


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Session:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _Cursor:
    def __init__(
        self,
        *,
        identity: tuple[str, str] = ("nex_eos_test", "nex_eos_user"),
        tables: tuple[str, ...] = (),
        fail_on_tables: bool = False,
    ) -> None:
        self.identity = identity
        self.tables = tables
        self.fail_on_tables = fail_on_tables
        self.executed: list[Any] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: Any) -> None:
        rendered = str(statement)
        self.executed.append(statement)
        if self.fail_on_tables and "pg_catalog.pg_tables" in rendered:
            raise RuntimeError("database unavailable")

    def fetchone(self) -> tuple[str, str]:
        return self.identity

    def fetchall(self) -> list[tuple[str]]:
        return [(name,) for name in self.tables]


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _runtime_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "NEX_EOS_DATABASE_URL": DATABASE_URL,
        "NEX_EOS_DB_POOL_SIZE": "7",
        "NEX_EOS_DB_MAX_OVERFLOW": "3",
        "NEX_EOS_DB_POOL_TIMEOUT_SECONDS": "11.5",
        "NEX_EOS_DB_POOL_RECYCLE_SECONDS": "601",
        "NEX_EOS_DB_POOL_PRE_PING": "false",
        "NEX_EOS_DB_STATEMENT_TIMEOUT_MS": "12000",
    }
    environment.update(overrides)
    return environment


def _app_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s08",
        "NEX_BUILD_SHA": "p8s08test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    environment.update(overrides)
    return environment


def test_migration_registration_and_baseline_scope() -> None:
    assert service_database_env("nex-eos", profile="dev") == "NEX_EOS_DATABASE_URL"
    assert (
        service_database_env("nex-eos", profile="test") == "NEX_EOS_TEST_DATABASE_URL"
    )

    migrations = load_migrations("nex-eos")
    assert migrations[0].version == "2500_eos_schema_migrations_baseline"
    compact = " ".join(migrations[0].sql.lower().split())
    assert "create table if not exists schema_migrations" in compact
    assert "eos_business_operation" not in compact
    assert "eos_idempotency" not in compact
    assert "eos_outbox" not in compact


def test_migration_dry_run_is_deterministic_without_connecting() -> None:
    result = run_service_migrations(
        "nex-eos",
        database_url="",
        dry_run=True,
        profile="test",
        connect=lambda *_args, **_kwargs: pytest.fail("dry-run must not connect"),
    )

    assert result.planned == tuple(
        migration.version for migration in load_migrations("nex-eos")
    )
    assert result.applied == result.planned
    assert result.skipped == ()
    assert result.dry_run is True
    assert result.profile == "test"


def test_database_runtime_uses_service_pool_and_redacts_secret() -> None:
    engine = _Engine()
    captured: dict[str, Any] = {}
    session = _Session()

    def build_engine(database_url: str, *, pool_settings: Any) -> _Engine:
        captured["database_url"] = database_url
        captured["pool_settings"] = pool_settings
        return engine

    runtime = build_eos_database_runtime(
        environ=_runtime_environment(),
        engine_factory=build_engine,  # type: ignore[arg-type]
        session_factory_builder=lambda received: (
            captured.setdefault("engine", received),
            lambda: session,
        )[1],  # type: ignore[arg-type]
    )

    assert captured["database_url"] == DATABASE_URL
    assert captured["engine"] is engine
    assert runtime.pool_settings.pool_size == 7
    assert runtime.pool_settings.max_overflow == 3
    assert runtime.pool_settings.pool_timeout_seconds == 11.5
    assert runtime.pool_settings.pool_recycle_seconds == 601
    assert runtime.pool_settings.pool_pre_ping is False
    assert runtime.pool_settings.statement_timeout_ms == 12000
    projection = runtime.public_projection()
    assert projection["service_id"] == "nex-eos"
    assert projection["database_env"] == "NEX_EOS_DATABASE_URL"
    assert "unit-secret" not in str(projection)
    assert "***" in projection["redacted_database_url"]

    with runtime.transaction() as transaction:
        assert transaction.db is session
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True

    runtime.dispose()
    assert engine.disposed is True


def test_database_runtime_rolls_back_and_closes_failed_transaction() -> None:
    session = _Session()
    runtime = build_eos_database_runtime(
        environ=_runtime_environment(),
        engine_factory=lambda *_args, **_kwargs: _Engine(),  # type: ignore[arg-type]
        session_factory_builder=lambda _engine: lambda: session,  # type: ignore[arg-type]
    )

    with (
        pytest.raises(RuntimeError, match="abort"),
        runtime.transaction() as transaction,
    ):
        assert transaction.db is session
        raise RuntimeError("abort")

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True


def test_database_runtime_supports_worker_pool_convention() -> None:
    runtime = build_eos_database_runtime(
        environ=_runtime_environment(
            NEX_EOS_DB_WORKER_POOL_SIZE="2",
            NEX_EOS_DB_WORKER_MAX_OVERFLOW="1",
            NEX_EOS_DB_WORKER_STATEMENT_TIMEOUT_MS="45000",
        ),
        workload="worker",
        engine_factory=lambda *_args, **_kwargs: _Engine(),  # type: ignore[arg-type]
        session_factory_builder=lambda _engine: lambda: _Session(),  # type: ignore[arg-type]
    )

    assert runtime.pool_settings.workload == "worker"
    assert runtime.pool_settings.pool_size == 2
    assert runtime.pool_settings.max_overflow == 1
    assert runtime.pool_settings.statement_timeout_ms == 45000


@pytest.mark.parametrize(
    ("environment", "workload"),
    (
        ({}, "api"),
        (
            {"NEX_EOS_DATABASE_URL": "postgresql://nex_eos_user:<password>@db/eos"},
            "api",
        ),
        ({"NEX_EOS_DATABASE_URL": "not a valid URL"}, "api"),
        ({"NEX_EOS_DATABASE_URL": DATABASE_URL}, "batch"),
    ),
)
def test_database_runtime_rejects_missing_placeholder_or_invalid_url(
    environment: dict[str, str],
    workload: str,
) -> None:
    with pytest.raises(EosDatabaseRuntimeError) as error:
        build_eos_database_runtime(environ=environment, workload=workload)

    assert "unit-secret" not in str(error.value)


def test_eos_app_attaches_optional_database_runtime() -> None:
    without_database = create_eos_app(environ=_app_environment())
    assert without_database.state.eos_database_runtime is None

    with_database = create_eos_app(
        environ=_app_environment(NEX_EOS_DATABASE_URL=DATABASE_URL)
    )
    try:
        assert with_database.state.eos_database_runtime is not None
        projection = with_database.state.eos_database_runtime.public_projection()
        assert projection["service_id"] == "nex-eos"
        assert "unit-secret" not in str(projection)
    finally:
        with_database.state.eos_database_runtime.dispose()


@pytest.mark.parametrize(
    ("database_url", "confirmation", "error_code"),
    (
        (DATABASE_URL, "wrong", "eos.test_reset_confirmation_invalid"),
        (
            "postgresql://nex_eos_user:secret@db/nex_eos_dev",
            EOS_TEST_RESET_CONFIRMATION,
            "eos.test_reset_target_invalid",
        ),
        (
            "postgresql://wrong:secret@db/nex_eos_test",
            EOS_TEST_RESET_CONFIRMATION,
            "eos.test_reset_target_invalid",
        ),
        (
            "sqlite:///nex_eos_test.db",
            EOS_TEST_RESET_CONFIRMATION,
            "eos.test_reset_target_invalid",
        ),
        (
            "not a URL",
            EOS_TEST_RESET_CONFIRMATION,
            "eos.test_reset_target_invalid",
        ),
    ),
)
def test_reset_rejects_unsafe_target_before_connect(
    database_url: str,
    confirmation: str,
    error_code: str,
) -> None:
    with pytest.raises(EosTestDatabaseResetError) as error:
        reset_eos_test_database(
            database_url=database_url,
            confirmation=confirmation,
            connect=lambda *_args, **_kwargs: pytest.fail("must not connect"),
        )
    assert error.value.error_code == error_code


def test_reset_rejects_runtime_identity_mismatch_and_rolls_back() -> None:
    connection = _Connection(_Cursor(identity=("nex_eos_dev", "nex_eos_user")))

    with pytest.raises(EosTestDatabaseResetError) as error:
        reset_eos_test_database(
            database_url=DATABASE_URL,
            confirmation=EOS_TEST_RESET_CONFIRMATION,
            connect=lambda *_args, **_kwargs: connection,
        )

    assert error.value.error_code == "eos.test_reset_identity_mismatch"
    assert connection.rolled_back is True
    assert connection.committed is False


def test_reset_truncates_only_eos_tables_and_preserves_migration_history() -> None:
    cursor = _Cursor(
        tables=(
            "eos_business_operation",
            "schema_migrations",
            "oa_subjects",
            "eos_outbox",
            "EOS_BAD",
        )
    )
    connection = _Connection(cursor)

    result = reset_eos_test_database(
        database_url=DATABASE_URL,
        confirmation=EOS_TEST_RESET_CONFIRMATION,
        connect=lambda *_args, **_kwargs: connection,
    )

    assert result.truncated_tables == ("eos_business_operation", "eos_outbox")
    assert result.to_public_projection() == {
        "database_name": "nex_eos_test",
        "database_role": "nex_eos_user",
        "truncated_tables": ["eos_business_operation", "eos_outbox"],
        "schema_migrations_preserved": True,
    }
    assert connection.committed is True
    assert connection.rolled_back is False
    assert len(cursor.executed) == 3
    assert "schema_migrations" not in str(cursor.executed[-1])


def test_reset_commits_when_no_eos_tables_exist() -> None:
    connection = _Connection(_Cursor(tables=("schema_migrations", "other_table")))

    result = reset_eos_test_database(
        database_url=DATABASE_URL,
        confirmation=EOS_TEST_RESET_CONFIRMATION,
        connect=lambda *_args, **_kwargs: connection,
    )

    assert result.truncated_tables == ()
    assert connection.committed is True
    assert connection.rolled_back is False


def test_reset_normalizes_database_failures_and_rolls_back() -> None:
    connection = _Connection(_Cursor(fail_on_tables=True))

    with pytest.raises(EosTestDatabaseResetError) as error:
        reset_eos_test_database(
            database_url=DATABASE_URL,
            confirmation=EOS_TEST_RESET_CONFIRMATION,
            connect=lambda *_args, **_kwargs: connection,
        )

    assert error.value.error_code == "eos.test_reset_failed"
    assert connection.rolled_back is True


def test_environment_example_documents_pool_test_url_and_protected_smoke() -> None:
    contents = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "NEX_EOS_DB_POOL_SIZE=" in contents
    assert "NEX_EOS_DB_WORKER_POOL_SIZE=" in contents
    assert "NEX_EOS_TEST_DATABASE_URL=postgresql://nex_eos_user:" in contents
    assert "NEX_EOS_P8_S08_POSTGRES_SMOKE=0" in contents
    assert "NEX_EOS_PERSISTENCE_MODE" not in contents
