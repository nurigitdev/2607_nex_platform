from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.provider_telemetry_persistence import (
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)
from nex_mo.provider_telemetry_repository import (
    ProviderTelemetryRepositoryError,
    SqlAlchemyDurableProviderTelemetryRepository,
    _mutation_params,
)


SQLITE_SCHEMA = """
CREATE TABLE mo_provider_telemetry (
    telemetry_key CHAR(64) PRIMARY KEY,
    capability TEXT NOT NULL,
    request_shape TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    retryable_failure_count INTEGER NOT NULL DEFAULT 0,
    degraded_count INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_outcome TEXT,
    last_observed_at TEXT,
    last_latency_ms INTEGER,
    last_status_code INTEGER,
    last_error_code TEXT,
    last_failure_kind TEXT,
    last_upstream_status_code INTEGER,
    last_retry_at TEXT,
    last_retry_delay_ms INTEGER,
    last_retry_failure_kind TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (capability, request_shape, deployment_id, model_revision),
    CHECK (request_count = success_count + failure_count),
    CHECK (attempt_count = request_count + retry_count),
    CHECK (retryable_failure_count <= failure_count),
    CHECK (degraded_count <= failure_count)
)
"""


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'telemetry.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.execute(text(SQLITE_SCHEMA))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _identity(capability: str = "embedding") -> ProviderTelemetryIdentity:
    return ProviderTelemetryIdentity(
        capability=capability,
        request_shape="openai_embeddings" if capability == "embedding" else "rerank",
        deployment_id=f"{capability}-deployment",
        model_revision=f"{capability}-revision",
    )


def _success(
    identity: ProviderTelemetryIdentity | None = None,
    *,
    observed_at: str = "2026-09-30T01:00:00Z",
) -> ProviderTelemetryMutation:
    return ProviderTelemetryMutation(
        identity=identity or _identity(),
        mutation_kind="success",
        observed_at=observed_at,
        request_increment=1,
        success_increment=1,
        attempt_increment=1,
        last_outcome="success",
        last_latency_ms=11,
        last_status_code=200,
    )


def _failure(identity: ProviderTelemetryIdentity) -> ProviderTelemetryMutation:
    return ProviderTelemetryMutation(
        identity=identity,
        mutation_kind="failure",
        observed_at="2026-09-30T01:00:02Z",
        request_increment=1,
        failure_increment=1,
        retryable_failure_increment=1,
        degraded_increment=1,
        attempt_increment=1,
        last_outcome="failure",
        last_latency_ms=31,
        last_status_code=503,
        last_error_code="mo.remote_embedding.http_error",
        last_failure_kind="upstream_5xx",
        last_upstream_status_code=503,
    )


def _retry(
    identity: ProviderTelemetryIdentity,
    *,
    observed_at: str = "2026-09-30T01:00:01Z",
    delay_ms: int = 250,
) -> ProviderTelemetryMutation:
    return ProviderTelemetryMutation(
        identity=identity,
        mutation_kind="retry",
        observed_at=observed_at,
        attempt_increment=1,
        retry_increment=1,
        last_retry_delay_ms=delay_ms,
        last_retry_failure_kind="upstream_5xx",
    )


def test_repository_atomically_accumulates_success_retry_and_failure(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    identity = _identity()

    first = repository.apply(_success(identity))
    after_retry = repository.apply(_retry(identity))
    final = repository.apply(_failure(identity))

    assert first.request_count == 1
    assert after_retry.request_count == 1
    assert after_retry.attempt_count == 2
    assert final.request_count == 2
    assert final.success_count == 1
    assert final.failure_count == 1
    assert final.retryable_failure_count == 1
    assert final.degraded_count == 1
    assert final.attempt_count == 3
    assert final.retry_count == 1
    assert final.last_outcome == "failure"
    assert final.last_retry_delay_ms == 250


def test_success_clears_prior_failure_diagnostics(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    identity = _identity()
    repository.apply(_failure(identity))

    current = repository.apply(
        _success(identity, observed_at="2026-09-30T01:00:03Z")
    )

    assert current.last_outcome == "success"
    assert current.last_error_code is None
    assert current.last_failure_kind is None
    assert current.last_upstream_status_code is None


def test_older_final_and_retry_events_do_not_regress_last_diagnostics(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    identity = _identity()
    newest_final = repository.apply(_failure(identity))
    repository.apply(_success(identity, observed_at="2026-09-30T00:59:00+00:00"))
    repository.apply(
        _retry(
            identity,
            observed_at="2026-09-30T01:00:05Z",
            delay_ms=500,
        )
    )
    current = repository.apply(
        _retry(
            identity,
            observed_at="2026-09-30T01:00:04Z",
            delay_ms=100,
        )
    )

    assert newest_final.last_observed_at == "2026-09-30T01:00:02Z"
    assert current.request_count == 2
    assert current.success_count == 1
    assert current.failure_count == 1
    assert current.last_outcome == "failure"
    assert current.last_observed_at == "2026-09-30T01:00:02Z"
    assert current.last_error_code == "mo.remote_embedding.http_error"
    assert current.last_retry_at == "2026-09-30T01:00:05Z"
    assert current.last_retry_delay_ms == 500


def test_concurrent_atomic_updates_do_not_lose_counts(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    identity = _identity()

    def apply(index: int) -> None:
        repository.apply(
            _success(
                identity,
                observed_at=f"2026-09-30T01:00:{index:02d}Z",
            )
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(apply, range(40)))

    restarted = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    record = restarted.list_records()[0]
    assert record.request_count == 40
    assert record.success_count == 40
    assert record.attempt_count == 40
    assert record.last_observed_at == "2026-09-30T01:00:39Z"


def test_new_repository_instance_reads_same_durable_rows(
    session_factory: sessionmaker[Session],
) -> None:
    SqlAlchemyDurableProviderTelemetryRepository(session_factory).apply(_success())

    restarted = SqlAlchemyDurableProviderTelemetryRepository(session_factory)

    assert len(restarted.list_records()) == 1
    assert restarted.list_records()[0].request_count == 1


def test_repository_filters_orders_and_clears_rows(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    repository.apply(_success(_identity("reranking")))
    repository.apply(_success(_identity("embedding")))

    assert [row.identity.capability for row in repository.list_records()] == [
        "embedding",
        "reranking",
    ]
    assert len(repository.list_records(capability="reranking")) == 1
    assert repository.clear() == 2
    assert repository.list_records() == []


def test_repository_rejects_unknown_capability_filter(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)

    with pytest.raises(ProviderTelemetryRepositoryError, match="unsupported"):
        repository.list_records(capability="unknown")


def test_mutation_params_use_stable_hash_and_event_timestamps() -> None:
    identity = _identity()
    success = _mutation_params(_success(identity))
    retry = _mutation_params(_retry(identity))

    assert len(str(success["telemetry_key"])) == 64
    assert success["telemetry_key"] == identity.storage_key()
    assert success["last_observed_at"] == "2026-09-30T01:00:00Z"
    assert success["last_retry_at"] is None
    assert retry["last_observed_at"] is None
    assert retry["last_retry_at"] == "2026-09-30T01:00:01Z"


def test_apply_rolls_back_when_upsert_row_cannot_be_read() -> None:
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))

    class SessionStub:
        def __init__(self) -> None:
            self.rolled_back = False
            self.closed = False

        def execute(self, *_args: object, **_kwargs: object) -> object:
            return result

        def commit(self) -> None:
            raise AssertionError("commit must not run")

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    session = SessionStub()
    repository = SqlAlchemyDurableProviderTelemetryRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(ProviderTelemetryRepositoryError, match="did not return"):
        repository.apply(_success())
    assert session.rolled_back is True
    assert session.closed is True


def test_apply_wraps_sqlalchemy_failure_and_closes_session() -> None:
    class FailingSession:
        def __init__(self) -> None:
            self.rolled_back = False
            self.closed = False

        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise SQLAlchemyError("private database failure")

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    session = FailingSession()
    repository = SqlAlchemyDurableProviderTelemetryRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(ProviderTelemetryRepositoryError, match="unavailable"):
        repository.apply(_success())
    assert session.rolled_back is True
    assert session.closed is True


def test_list_and_clear_wrap_database_failure(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyDurableProviderTelemetryRepository(session_factory)
    with session_factory.begin() as session:
        session.execute(text("DROP TABLE mo_provider_telemetry"))

    with pytest.raises(ProviderTelemetryRepositoryError, match="unavailable"):
        repository.list_records()
    with pytest.raises(ProviderTelemetryRepositoryError, match="unavailable"):
        repository.clear()


def test_migration_uses_short_table_atomic_constraints_and_registry() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "database/nex-mo/migrations/1154_mo_provider_telemetry.sql"
    )
    sql = path.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS mo_provider_telemetry" in sql
    assert len("mo_provider_telemetry") <= 24
    assert "telemetry_key CHAR(64) PRIMARY KEY" in sql
    assert "uq_mo_provider_telemetry_identity" in sql
    assert "request_count = success_count + failure_count" in sql
    assert "attempt_count = request_count + retry_count" in sql
    assert "1154_mo_provider_telemetry" in sql
    assert sql.startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")
