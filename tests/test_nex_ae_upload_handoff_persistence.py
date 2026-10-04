from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nex_ae_api.upload_handoff_persistence as persistence
from nex_ae_api.upload_handoff_persistence import (
    SqlAlchemyUploadHandoffStore,
    UploadHandoffRepositoryError,
    ensure_upload_handoff_metadata_only,
)
from nex_ae_api.uploads import build_default_upload_handoff_store


SOURCE_HASH = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610"


def session_factory(*, with_schema: bool = True):
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ae_upload_handoffs (
                    upload_handoff_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    cx_document_id TEXT NOT NULL,
                    cx_upload_id TEXT NOT NULL,
                    ingestion_job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_payload TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def handoff(**overrides):
    record = {
        "upload_handoff_schema_version": "ae_upload_handoff.v1",
        "upload_handoff_id": "handoff-a",
        "workspace_id": "workspace-a",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        },
        "status": "QUEUED",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-a",
        "source": {
            "filename": "report.md",
            "content_type": "text/markdown",
            "size_bytes": 5,
            "source_sha256": SOURCE_HASH,
            "source_text_hash": SOURCE_HASH,
        },
        "cx_document_ref": {
            "document_id": "document-a",
            "upload_id": "upload-a",
            "ingestion_job_id": "job-a",
            "extraction_status": "PENDING",
            "markdown_available": False,
            "dedupe_status": "CREATED",
            "existing_document_id": None,
        },
        "links": {
            "cx_document": "/api/v1/documents/document-a",
            "cx_ingestion_job": "/api/v1/jobs/job-a",
        },
        "metadata": {
            "raw_source_stored_in_ae": False,
            "cx_storage_redacted": True,
        },
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
    }
    return {**record, **overrides}


def test_repository_persists_restart_safe_owner_scoped_metadata() -> None:
    factory = session_factory()
    first = SqlAlchemyUploadHandoffStore(factory)
    second = SqlAlchemyUploadHandoffStore(factory)

    assert first.save(handoff()) == handoff()
    assert second.get("handoff-a", tenant_id="tenant-a", owner_user_id="user-a") == handoff()
    assert second.get("handoff-a", tenant_id="tenant-a", owner_user_id="user-b") is None
    assert second.get_by_document_id(
        "document-a", tenant_id="tenant-a", owner_user_id="user-a"
    ) == handoff()
    assert second.get_by_document_id("missing") is None
    assert second.list_by_workspace(
        "workspace-a", tenant_id="tenant-a", owner_user_id="user-a"
    ) == [handoff()]
    assert second.list_by_workspace(
        "workspace-a", tenant_id="tenant-a", owner_user_id="user-b"
    ) == []


def test_repository_save_is_idempotent_and_rejects_identity_collision() -> None:
    repository = SqlAlchemyUploadHandoffStore(session_factory())
    assert repository.save(handoff()) == handoff()
    assert repository.save(handoff(updated_at="2026-10-05T00:01:00Z")) == handoff()

    with pytest.raises(UploadHandoffRepositoryError) as exc:
        repository.save(handoff(owner_user_id="user-b"))
    assert exc.value.status_code == 409
    assert exc.value.error_code == "ae.upload_handoff_identity_conflict"


def test_repository_rejects_private_payload_and_incomplete_owner_filter() -> None:
    repository = SqlAlchemyUploadHandoffStore(session_factory())
    for record in (
        handoff(content_text="private"),
        handoff(metadata={"nested": [{"embedding": [0.1]}]}),
    ):
        with pytest.raises(UploadHandoffRepositoryError) as exc:
            repository.save(record)
        assert exc.value.error_code == "ae.upload_handoff_metadata_invalid"

    with pytest.raises(UploadHandoffRepositoryError):
        repository.get("handoff-a", tenant_id="tenant-a")
    with pytest.raises(UploadHandoffRepositoryError):
        ensure_upload_handoff_metadata_only([])


def test_repository_detects_corruption_and_wraps_database_errors() -> None:
    factory = session_factory()
    repository = SqlAlchemyUploadHandoffStore(factory)
    repository.save(handoff())
    with factory() as session:
        with session.begin():
            session.execute(
                text("UPDATE ae_upload_handoffs SET tenant_id = 'tenant-corrupt'")
            )
    with pytest.raises(UploadHandoffRepositoryError) as exc:
        repository.get("handoff-a")
    assert exc.value.error_code == "ae.upload_handoff_integrity_failed"

    unavailable = SqlAlchemyUploadHandoffStore(session_factory(with_schema=False))
    for operation in (
        lambda: unavailable.save(handoff()),
        lambda: unavailable.get("handoff-a"),
        lambda: unavailable.get_by_document_id("document-a"),
        lambda: unavailable.list_by_workspace("workspace-a"),
    ):
        with pytest.raises(UploadHandoffRepositoryError) as unavailable_exc:
            operation()
        assert unavailable_exc.value.error_code == "ae.upload_handoff_store_unavailable"
        assert unavailable_exc.value.retryable is True
        assert str(unavailable_exc.value) == "AE upload handoff store is unavailable."


def test_helpers_cover_postgres_json_invalid_shapes_and_default_wiring(monkeypatch) -> None:
    assert "CAST(:record_payload AS jsonb)" in persistence._insert_sql("postgresql")
    with pytest.raises(UploadHandoffRepositoryError):
        persistence._record_params({})
    with pytest.raises(UploadHandoffRepositoryError):
        persistence._record_params(handoff(source=[]))
    with pytest.raises(UploadHandoffRepositoryError):
        persistence._record_params(handoff(source={"source_sha256": ""}))

    params = persistence._record_params(handoff())
    row = {**params, "record_payload": handoff()}
    assert persistence._record_from_row(row) == handoff()
    with pytest.raises(UploadHandoffRepositoryError):
        persistence._record_from_row({**row, "record_payload": []})

    factory = session_factory()
    app = FastAPI()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=factory)
    assert isinstance(
        build_default_upload_handoff_store(app),
        SqlAlchemyUploadHandoffStore,
    )

    repository = SqlAlchemyUploadHandoffStore(factory)
    repository.save(handoff())
    monkeypatch.setattr(persistence, "_load_one", lambda *args, **kwargs: None)
    with pytest.raises(UploadHandoffRepositoryError) as conflict:
        repository.save(handoff())
    assert conflict.value.error_code == "ae.upload_handoff_write_conflict"


def test_corrupt_payload_paths_propagate_through_document_and_workspace_reads() -> None:
    for corrupt_payload, operation in (
        ("not-json", "document"),
        ("[]", "workspace"),
    ):
        factory = session_factory()
        repository = SqlAlchemyUploadHandoffStore(factory)
        repository.save(handoff())
        with factory() as session:
            with session.begin():
                session.execute(
                    text(
                        "UPDATE ae_upload_handoffs "
                        "SET record_payload = :record_payload"
                    ),
                    {"record_payload": corrupt_payload},
                )

        with pytest.raises(UploadHandoffRepositoryError) as exc:
            if operation == "document":
                repository.get_by_document_id("document-a")
            else:
                repository.list_by_workspace("workspace-a")
        assert exc.value.error_code == "ae.upload_handoff_integrity_failed"
