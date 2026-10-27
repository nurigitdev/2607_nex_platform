from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import pytest
from fastapi.testclient import TestClient
from nex_runtime import SqlAlchemyJobQueue, SqlAlchemyWorkerHeartbeatStore
from nex_runtime.postgres_targets import (
    PostgresTargetConfigError,
    resolve_postgres_test_targets,
)
from nex_wa import (
    WA_COMMON_RUNTIME_MIGRATIONS,
    WA_REQUIRED_MIGRATIONS,
    WaPersistenceError,
    build_wa_persistence_runtime,
)
from nex_wa.app import CONTRACT_CATALOG_VERSION, create_wa_app
from run_migrations import load_migrations, run_service_migrations, service_database_env
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql://nex_wa_user:unit-secret@127.0.0.1:5432/nex_wa_test"


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Rows:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str]]:
        return self._rows


class _Session:
    def __init__(
        self,
        rows: list[tuple[str]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.error = error
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object) -> _Rows:
        if self.error is not None:
            raise self.error
        return _Rows(self.rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "NEX_WA_DATABASE_URL": DATABASE_URL,
        "NEX_WA_DB_POOL_SIZE": "6",
        "NEX_WA_DB_MAX_OVERFLOW": "2",
        "NEX_WA_DB_WORKER_POOL_SIZE": "3",
        "NEX_WA_DB_WORKER_MAX_OVERFLOW": "1",
        "NEX_WA_DB_STATEMENT_TIMEOUT_MS": "12000",
        "NEX_WA_DB_WORKER_STATEMENT_TIMEOUT_MS": "45000",
    }
    values.update(overrides)
    return values


def _table_definition(path: Path, table_name: str) -> str:
    sql = path.read_text(encoding="utf-8")
    start = sql.index(f"CREATE TABLE IF NOT EXISTS {table_name}")
    end = sql.index("\n);", start) + 3
    return " ".join(sql[start:end].split())


def test_migration_stream_and_common_runtime_contracts_are_frozen() -> None:
    assert service_database_env("nex-wa", profile="dev") == "NEX_WA_DATABASE_URL"
    assert (
        service_database_env("nex-wa", profile="test")
        == "NEX_WA_TEST_DATABASE_URL"
    )
    migrations = load_migrations("nex-wa")
    assert tuple(item.version for item in migrations) == WA_REQUIRED_MIGRATIONS

    wa_root = ROOT / "database/nex-wa/migrations"
    wc_root = ROOT / "database/nex-wc/migrations"
    wa_job_definition = _table_definition(
        wa_root / "2601_wa_service_job_queue.sql", "service_jobs"
    )
    wc_job_definition = _table_definition(
        wc_root / "0083_service_job_queue_foundation.sql", "service_jobs"
    )
    assert all(
        token in wa_job_definition
        for token in (
            "job_schema_version",
            "idempotency_key",
            "attempt_count",
            "max_attempts",
            "available_at",
        )
    )
    assert all(token in wc_job_definition for token in ("job_schema_version", "available_at"))
    assert "replay_lineage JSONB" in wa_job_definition
    assert "ADD COLUMN IF NOT EXISTS replay_lineage JSONB" in (
        wc_root / "0135_service_job_replay_lineage.sql"
    ).read_text(encoding="utf-8")
    assert _table_definition(
        wa_root / "2602_wa_worker_heartbeat.sql", "service_worker_heartbeats"
    ) == _table_definition(
        wc_root / "0112_service_worker_heartbeat_foundation.sql",
        "service_worker_heartbeats",
    )
    assert not any(
        "wa_work_" in migration.sql
        for migration in migrations[: len(WA_COMMON_RUNTIME_MIGRATIONS)]
    )


def test_migration_dry_run_is_deterministic_without_connecting() -> None:
    result = run_service_migrations(
        "nex-wa",
        database_url="",
        dry_run=True,
        profile="test",
        connect=lambda *_args, **_kwargs: pytest.fail("dry-run must not connect"),
    )

    assert result.planned == WA_REQUIRED_MIGRATIONS
    assert result.applied == WA_REQUIRED_MIGRATIONS
    assert result.skipped == ()


def test_wrong_wa_test_database_or_role_is_rejected_before_connection() -> None:
    with pytest.raises(PostgresTargetConfigError, match="test_database_name_mismatch"):
        resolve_postgres_test_targets(
            {
                "NEX_WA_TEST_DATABASE_URL": (
                    "postgresql://nex_wa_user:secret@127.0.0.1/nex_wa_dev"
                )
            },
            service_ids=("nex-wa",),
        )
    with pytest.raises(PostgresTargetConfigError, match="test_database_role_mismatch"):
        resolve_postgres_test_targets(
            {
                "NEX_WA_TEST_DATABASE_URL": (
                    "postgresql://nex_eos_user:secret@127.0.0.1/nex_wa_test"
                )
            },
            service_ids=("nex-wa",),
        )


def test_runtime_separates_api_and_worker_pools_and_redacts_credentials() -> None:
    engines = [_Engine(), _Engine()]
    sessions = [_Session(), _Session()]
    observed: list[tuple[str, Any]] = []

    def engine_factory(database_url: str, *, pool_settings: Any) -> _Engine:
        observed.append((database_url, pool_settings))
        return engines[len(observed) - 1]

    def session_builder(engine: _Engine):
        index = engines.index(engine)
        return lambda: sessions[index]

    runtime = build_wa_persistence_runtime(
        environ=_environment(),
        engine_factory=engine_factory,  # type: ignore[arg-type]
        session_factory_builder=session_builder,  # type: ignore[arg-type]
    )

    assert runtime.api_pool_settings.pool_size == 6
    assert runtime.api_pool_settings.max_overflow == 2
    assert runtime.api_pool_settings.statement_timeout_ms == 12000
    assert runtime.worker_pool_settings.pool_size == 3
    assert runtime.worker_pool_settings.max_overflow == 1
    assert runtime.worker_pool_settings.statement_timeout_ms == 45000
    assert isinstance(runtime.job_queue, SqlAlchemyJobQueue)
    assert isinstance(runtime.worker_heartbeat_store, SqlAlchemyWorkerHeartbeatStore)
    projection = runtime.public_projection()
    assert projection["database_env"] == "NEX_WA_DATABASE_URL"
    assert "unit-secret" not in str(projection)
    assert "***" in projection["redacted_database_url"]

    with runtime.transaction() as transaction:
        assert transaction.db is sessions[0]
    assert sessions[0].committed is True
    runtime.dispose()
    assert all(engine.disposed for engine in engines)


def test_runtime_rolls_back_failed_unit_of_work() -> None:
    session = _Session()
    runtime = build_wa_persistence_runtime(
        environ=_environment(),
        engine_factory=lambda *_args, **_kwargs: _Engine(),  # type: ignore[arg-type]
        session_factory_builder=lambda _engine: lambda: session,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="abort"), runtime.transaction():
        raise RuntimeError("abort")
    assert session.rolled_back is True
    assert session.closed is True


def test_migration_readiness_reports_current_missing_and_database_failure() -> None:
    sessions = [
        _Session([(version,) for version in WA_REQUIRED_MIGRATIONS]),
        _Session([(WA_REQUIRED_MIGRATIONS[0],)]),
        _Session(error=SQLAlchemyError("offline")),
    ]

    def runtime_for(session: _Session):
        return build_wa_persistence_runtime(
            environ=_environment(),
            engine_factory=lambda *_args, **_kwargs: _Engine(),  # type: ignore[arg-type]
            session_factory_builder=lambda _engine: lambda: session,  # type: ignore[arg-type]
        )

    runtime = runtime_for(sessions[0])
    assert runtime.migration_readiness()["ok"] is True

    runtime = runtime_for(sessions[1])
    missing = runtime.migration_readiness()
    assert missing["ok"] is False
    assert missing["missing_versions"] == list(WA_REQUIRED_MIGRATIONS[1:])

    runtime = runtime_for(sessions[2])
    assert runtime.migration_readiness() == {
        "name": "wa_migrations",
        "ok": False,
        "error_code": "WA_MIGRATION_READINESS_FAILED",
    }


def test_runtime_failure_is_redacted_and_disposes_partial_engine() -> None:
    with pytest.raises(WaPersistenceError, match="configuration is invalid"):
        build_wa_persistence_runtime(environ={})

    api_engine = _Engine()
    calls = 0

    def failing_engine(*_args: object, **_kwargs: object) -> _Engine:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("unit-secret")
        return api_engine

    with pytest.raises(WaPersistenceError) as error:
        build_wa_persistence_runtime(
            environ=_environment(),
            engine_factory=failing_engine,  # type: ignore[arg-type]
        )
    assert "unit-secret" not in str(error.value)
    assert api_engine.disposed is True

    shared_engine = _Engine()
    with pytest.raises(WaPersistenceError):
        build_wa_persistence_runtime(
            environ=_environment(),
            engine_factory=lambda *_args, **_kwargs: shared_engine,  # type: ignore[arg-type]
            session_factory_builder=lambda _engine: (_ for _ in ()).throw(
                SQLAlchemyError("session failure")
            ),  # type: ignore[arg-type]
        )
    assert shared_engine.disposed is True


def test_runtime_disposes_a_shared_api_worker_engine_only_once() -> None:
    shared_engine = _Engine()
    runtime = build_wa_persistence_runtime(
        environ=_environment(),
        engine_factory=lambda *_args, **_kwargs: shared_engine,  # type: ignore[arg-type]
        session_factory_builder=lambda _engine: lambda: _Session(),  # type: ignore[arg-type]
    )

    runtime.dispose()
    assert shared_engine.disposed is True


def test_app_attaches_optional_runtime_and_migration_readiness() -> None:
    runtime = type(
        "Runtime",
        (),
        {
            "migration_readiness": lambda self: {
                "name": "wa_migrations",
                "ok": True,
            },
            "work_evidence_repository": None,
            "work_asset_repository": None,
            "evidence_admission_service": None,
        },
    )()
    app = create_wa_app(
        environ={
            "NEX_WA_DATABASE_URL": DATABASE_URL,
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        },
        persistence_builder=lambda **_kwargs: runtime,  # type: ignore[arg-type]
    )
    without_database = create_wa_app(
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"}
    )

    assert app.state.wa_persistence is runtime
    assert without_database.state.wa_persistence is None
    assert TestClient(app).get("/version").json()["contract_catalog_version"] == (
        CONTRACT_CATALOG_VERSION
    )
