from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from nex_runtime import build_engine, build_session_factory
from nex_cx.ingestion_orchestration import (
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
    SqlAlchemyIngestionRunRepository,
    _json_expression,
    _json_value,
    _timestamp,
)


NOW = "2026-09-21T00:00:00Z"
LATER = "2026-09-21T00:02:00Z"


def make_run(*, owner: str = "user-a", key: str = "upload-1", run_id: str | None = None):
    document_id = (
        "11111111-1111-1111-1111-111111111111"
        if owner == "user-a"
        else "66666666-6666-6666-6666-666666666666"
    )
    job_id = (
        "22222222-2222-2222-2222-222222222222"
        if owner == "user-a"
        else "77777777-7777-7777-7777-777777777777"
    )
    return build_ingestion_run(
        document_id=document_id,
        job_id=job_id,
        idempotency_key=key,
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": owner},
        trace_id="trace-1",
        request_id="request-1",
        created_at=NOW,
        run_id=run_id,
    )


def sqlite_repository():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_ingest_runs (
                    run_id TEXT PRIMARY KEY,
                    run_schema_version TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step TEXT,
                    step_states TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    checkpoint_version INTEGER NOT NULL,
                    tenant_ref_type TEXT NOT NULL,
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL,
                    owner_subject_ref_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    retry_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE (tenant_ref_id, owner_subject_ref_id, idempotency_key)
                )
                """
            )
        )
    return SqlAlchemyIngestionRunRepository(
        build_session_factory(engine),
        source_kind="sqlite-regression",
        database_env="test",
        redacted_database_url="sqlite://",
    ), engine


@pytest.mark.parametrize(
    "factory",
    [InMemoryIngestionRunRepository, lambda: sqlite_repository()[0]],
)
def test_repository_create_is_owner_scoped_and_idempotent(factory) -> None:
    repository = factory()
    first = repository.create(make_run())
    duplicate = repository.create(
        make_run(run_id="33333333-3333-3333-3333-333333333333")
    )
    other_owner = repository.create(make_run(owner="user-b"))

    assert duplicate == first
    assert other_owner["run_id"] != first["run_id"]
    assert repository.get(
        first["run_id"], tenant_id="tenant-a", owner_subject_id="user-a"
    ) == first
    assert repository.get(
        first["run_id"], tenant_id="tenant-a", owner_subject_id="user-b"
    ) is None
    assert repository.find_by_idempotency_key(
        "upload-1", tenant_id="tenant-a", owner_subject_id="user-a"
    ) == first
    assert repository.find_by_idempotency_key(
        "missing", tenant_id="tenant-a", owner_subject_id="user-a"
    ) is None


@pytest.mark.parametrize(
    "factory",
    [InMemoryIngestionRunRepository, lambda: sqlite_repository()[0]],
)
def test_repository_saves_exactly_one_checkpoint_version(factory) -> None:
    repository = factory()
    created = repository.create(make_run())
    claimed = claim_ingestion_run(
        created,
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
        expected_checkpoint_version=0,
    )
    saved = repository.save(claimed, expected_checkpoint_version=0)
    assert saved == claimed

    with pytest.raises(IngestionRunRepositoryError) as stale:
        repository.save(claimed, expected_checkpoint_version=0)
    assert stale.value.error_code == "cx.ingestion_run.checkpoint_conflict"

    invalid = deepcopy(saved)
    invalid["checkpoint_version"] = 3
    with pytest.raises(IngestionRunRepositoryError) as jump:
        repository.save(invalid, expected_checkpoint_version=1)
    assert jump.value.error_code == "cx.ingestion_run.checkpoint_increment_invalid"


@pytest.mark.parametrize(
    "factory",
    [InMemoryIngestionRunRepository, lambda: sqlite_repository()[0]],
)
def test_repository_rejects_identity_change_and_missing_run(factory) -> None:
    repository = factory()
    created = repository.create(make_run())
    changed = claim_ingestion_run(
        created,
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
    )
    changed["job_id"] = "44444444-4444-4444-4444-444444444444"
    with pytest.raises(IngestionRunRepositoryError) as identity:
        repository.save(changed, expected_checkpoint_version=0)
    assert identity.value.error_code == "cx.ingestion_run.identity_conflict"

    missing = make_run(run_id="55555555-5555-5555-5555-555555555555")
    missing = claim_ingestion_run(
        missing,
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
    )
    with pytest.raises(IngestionRunRepositoryError) as not_found:
        repository.save(missing, expected_checkpoint_version=0)
    assert not_found.value.error_code == "cx.ingestion_run.not_found"


@pytest.mark.parametrize(
    "factory",
    [InMemoryIngestionRunRepository, lambda: sqlite_repository()[0]],
)
def test_repository_lists_only_owner_document_runs(factory) -> None:
    repository = factory()
    first = repository.create(make_run(key="upload-1"))
    second = repository.create(make_run(key="upload-2"))
    repository.create(make_run(owner="user-b", key="upload-3"))

    listed = repository.list_for_document(
        first["document_id"],
        tenant_id="tenant-a",
        owner_subject_id="user-a",
    )
    assert {item["run_id"] for item in listed} == {
        first["run_id"],
        second["run_id"],
    }
    assert repository.list_for_document(
        "missing", tenant_id="tenant-a", owner_subject_id="user-a"
    ) == []


def test_sqlite_repository_stores_no_private_payload() -> None:
    repository, engine = sqlite_repository()
    repository.create(make_run())
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM cx_ingest_runs")).mappings().one()
    serialized = str(dict(row)).lower()
    assert "source_text" not in serialized
    assert "prompt" not in serialized
    assert "vector" not in serialized
    assert row["step_states"]


def test_repository_helpers_cover_datetime_json_and_error_string() -> None:
    observed = datetime(2026, 9, 21, tzinfo=UTC)
    assert _timestamp(observed) == "2026-09-21T00:00:00Z"
    assert _timestamp(None) is None
    assert _timestamp("value") == "value"
    assert _json_value(None, {}) == {}
    assert _json_value('{"a":1}', {}) == {"a": 1}
    assert _json_value({"a": 1}, {}) == {"a": 1}
    error = IngestionRunRepositoryError("code", "detail")
    assert str(error) == "detail"


def test_sqlalchemy_repository_maps_database_failures_to_unavailable() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyIngestionRunRepository(build_session_factory(engine))
    run = make_run()

    for operation in (
        lambda: repository.create(run),
        lambda: repository.get(
            run["run_id"], tenant_id="tenant-a", owner_subject_id="user-a"
        ),
        lambda: repository.list_for_document(
            run["document_id"],
            tenant_id="tenant-a",
            owner_subject_id="user-a",
        ),
    ):
        with pytest.raises(IngestionRunRepositoryError) as exc:
            operation()
        assert exc.value.error_code == "cx.ingestion_run.repository_unavailable"

    claimed = claim_ingestion_run(
        run,
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
    )
    with pytest.raises(IngestionRunRepositoryError) as save_error:
        repository.save(claimed, expected_checkpoint_version=0)
    assert save_error.value.error_code == "cx.ingestion_run.repository_unavailable"


def test_json_expression_selects_postgresql_cast_and_plain_binding() -> None:
    postgres_session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    detached_session = SimpleNamespace(get_bind=lambda: None)
    assert _json_expression(postgres_session, "value") == "CAST(:value AS JSONB)"
    assert _json_expression(detached_session, "value") == ":value"
