from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from nex_runtime import build_engine, build_session_factory
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
)
from nex_cx.repository import (
    CxContentRepositoryError,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    InMemoryCxContentRepository,
    SqlAlchemyCxContentRepository,
    build_content_object_record,
    build_source_file_record,
)
import nex_cx.repository as cx_repository


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def upload_registration(tmp_path: Path, *, content_text: str = "hello") -> dict[str, object]:
    return build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": content_text,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def sqlite_content_repository(
    tmp_path: Path,
) -> tuple[SqlAlchemyCxContentRepository, object]:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE cx_source_files (
                    source_file_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    first_seen_trace_id TEXT,
                    storage_backend TEXT NOT NULL DEFAULT 'local_filesystem',
                    storage_key TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    stored_extension TEXT NOT NULL,
                    checksum_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (storage_backend, storage_key)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_objects (
                    content_object_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    source_sha256 TEXT NOT NULL,
                    upload_id TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'internal',
                    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    retrieval_policy TEXT NOT NULL DEFAULT '{}',
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_owner_source_active
                ON cx_content_objects (tenant_id, owner_user_id, source_sha256)
                WHERE lifecycle_status = 'ACTIVE'
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_content_acl_entries (
                    acl_entry_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    principal_type TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by_user_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (content_object_id, principal_type, principal_id, permission)
                )
                """
            )
        )
    return (
        SqlAlchemyCxContentRepository(
            build_session_factory(engine),
            local_source_root=tmp_path / "cx" / "source-files",
        ),
        engine,
    )


def test_build_source_file_record_maps_storage_metadata_without_raw_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path, content_text="private source")

    record = build_source_file_record(upload)

    assert record["source_file_id"]
    assert record["source_sha256"] == upload["source_sha256"]
    assert record["storage_backend"] == "local_filesystem"
    assert record["storage_key"] == upload["storage"]["source_storage_key"]
    assert record["storage_uri"].startswith("local://cx/source-files/")
    assert record["checksum_verified_at"] is None
    assert "private source" not in str(record)


def test_build_content_object_record_keeps_owner_scope_and_source_ref(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    source_file = build_source_file_record(upload)

    record = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id=source_file["source_file_id"],
    )

    assert record["content_object_id"] == upload["document_id"]
    assert record["tenant_id"] == "tenant-a"
    assert record["owner_user_id"] == "user-a"
    assert record["source_file_id"] == source_file["source_file_id"]
    assert record["lifecycle_status"] == "ACTIVE"
    assert record["retrieval_policy"]["chunk_policy"] == "chunk_1000_100"


def test_in_memory_repository_dedupes_source_files_by_sha256(tmp_path: Path) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    first = build_source_file_record(upload)
    second = {**first, "source_file_id": "different-id"}

    assert repository.save_source_file(first) == first
    assert repository.save_source_file(second) == first
    assert repository.get_source_file_by_sha256(upload["source_sha256"]) == first
    assert repository.get_source_file(first["source_file_id"]) == first


def test_in_memory_repository_finds_active_content_object_by_owner_and_hash(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = repository.save_content_object(
        build_content_object_record(
            upload,
            tenant_id="tenant-a",
            owner_user_id="user-a",
            source_file_id=source_file["source_file_id"],
        )
    )

    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=upload["source_sha256"],
    ) == content
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-b",
        source_sha256=upload["source_sha256"],
    ) is None
    assert repository.get_source_file_by_sha256("0" * 64) is None


def test_in_memory_repository_ignores_inactive_content_for_active_lookup(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    inactive = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id=source_file["source_file_id"],
    )
    inactive["lifecycle_status"] = "DELETED"

    repository.save_content_object(inactive)

    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=upload["source_sha256"],
    ) is None


def test_content_ingestion_store_persists_private_repository_records(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    upload = upload_registration(tmp_path, content_text="private source text")

    public = store.save_upload_registration(upload, source_text="private source text")

    refs = store.get_content_ref(upload["document_id"])
    assert public == upload
    assert refs is not None
    assert refs["content_object_id"] == upload["document_id"]
    assert store.content_repository.get_content_object(refs["content_object_id"]) is not None
    assert store.content_repository.get_source_file(refs["source_file_id"]) is not None
    assert "private source text" not in str(store.content_repository.content_objects)
    assert DEFAULT_TENANT_ID
    assert DEFAULT_OWNER_USER_ID


def test_sqlalchemy_repository_dedupes_source_files_by_sha256_and_storage_path(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    first = build_source_file_record(upload)
    second = {**first, "source_file_id": "11111111-1111-4111-8111-111111111111"}

    saved = repository.save_source_file(first)

    assert repository.save_source_file(second) == saved
    assert repository.get_source_file_by_sha256(upload["source_sha256"]) == saved
    assert repository.get_source_file(first["source_file_id"]) == saved
    assert saved["source_storage_path"] == str(
        tmp_path / "cx" / "source-files" / first["storage_key"]
    )
    assert "hello" not in str(saved)


def test_sqlalchemy_repository_can_return_source_metadata_without_local_path(
    tmp_path: Path,
) -> None:
    _, engine = sqlite_content_repository(tmp_path)
    repository = SqlAlchemyCxContentRepository(build_session_factory(engine))
    upload = upload_registration(tmp_path)

    saved = repository.save_source_file(build_source_file_record(upload))

    assert saved["storage_backend"] == "local_filesystem"
    assert "source_storage_path" not in saved


def test_sqlalchemy_repository_saves_content_object_and_owner_acl(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id=source_file["source_file_id"],
    )

    saved = repository.save_content_object(content)

    assert saved == content
    assert repository.get_content_object(saved["content_object_id"]) == content
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=upload["source_sha256"],
    ) == content
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-b",
        source_sha256=upload["source_sha256"],
    ) is None
    with engine.connect() as connection:
        acl_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM cx_content_acl_entries
                WHERE content_object_id = :content_object_id
                  AND principal_id = 'user-a'
                  AND permission = 'owner'
                """
            ),
            {"content_object_id": saved["content_object_id"]},
        ).scalar_one()
    assert acl_count == 1


def test_sqlalchemy_repository_returns_existing_active_owner_content(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    first = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id=source_file["source_file_id"],
    )
    duplicate = {**first, "content_object_id": "22222222-2222-4222-8222-222222222222"}

    assert repository.save_content_object(first) == first
    assert repository.save_content_object(duplicate) == first

    with engine.connect() as connection:
        content_count = connection.execute(
            text("SELECT count(*) FROM cx_content_objects")
        ).scalar_one()
        acl_count = connection.execute(
            text("SELECT count(*) FROM cx_content_acl_entries")
        ).scalar_one()
    assert content_count == 1
    assert acl_count == 1


def test_sqlalchemy_repository_keeps_existing_owner_acl_idempotent(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id=source_file["source_file_id"],
    )
    repository.save_content_object(content)

    repository._run_in_transaction(
        lambda session: repository._insert_owner_acl_entry(session, content)
    )

    with engine.connect() as connection:
        acl_count = connection.execute(
            text("SELECT count(*) FROM cx_content_acl_entries")
        ).scalar_one()
    assert acl_count == 1


def test_sqlalchemy_repository_marks_source_checksum_verified(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))

    verified = repository.mark_source_file_checksum_verified(
        source_file["source_file_id"],
        verified_at="2026-08-09T00:00:00Z",
    )

    assert verified["checksum_verified_at"] == "2026-08-09T00:00:00Z"


def test_sqlalchemy_repository_reports_missing_source_file_for_checksum(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.mark_source_file_checksum_verified(
            "33333333-3333-4333-8333-333333333333",
            verified_at="2026-08-09T00:00:00Z",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "cx_content.source_file_not_found"


def test_sqlalchemy_repository_wraps_database_errors(tmp_path: Path) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyCxContentRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.get_source_file("33333333-3333-4333-8333-333333333333")

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "cx_content.repository_unavailable"


@pytest.mark.parametrize(
    "operation",
    [
        lambda repository: repository.save_source_file({"source_sha256": "0" * 64}),
        lambda repository: repository.get_source_file_by_sha256("0" * 64),
        lambda repository: repository.save_content_object(
            {
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "tenant_id": "tenant-a",
                "owner_user_id": "user-a",
                "source_sha256": "0" * 64,
            }
        ),
        lambda repository: repository.get_content_object(
            "44444444-4444-4444-8444-444444444444"
        ),
        lambda repository: repository.find_active_content_object(
            tenant_id="tenant-a",
            owner_user_id="user-a",
            source_sha256="0" * 64,
        ),
    ],
)
def test_sqlalchemy_repository_wraps_missing_table_errors(
    operation: Any,
) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyCxContentRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        operation(repository)

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_integrity_race_fallbacks_return_existing_records(
    tmp_path: Path,
) -> None:
    class RaceySourceRepository(SqlAlchemyCxContentRepository):
        def _save_source_file(self, session: Any, record: dict[str, Any]) -> dict[str, Any]:
            raise IntegrityError("insert source", {}, Exception("race"))

    class RaceyContentRepository(SqlAlchemyCxContentRepository):
        def _save_content_object(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert content", {}, Exception("race"))

    repository, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file_record = build_source_file_record(upload)
    source_file = repository.save_source_file(source_file_record)
    content = repository.save_content_object(
        build_content_object_record(
            upload,
            tenant_id="tenant-a",
            owner_user_id="user-a",
            source_file_id=source_file["source_file_id"],
        )
    )

    racey_source = RaceySourceRepository(
        build_session_factory(engine),
        local_source_root=tmp_path / "cx" / "source-files",
    )
    racey_content = RaceyContentRepository(build_session_factory(engine))

    assert racey_source.save_source_file(source_file_record) == source_file
    assert racey_content.save_content_object(content) == content


def test_repository_json_and_timestamp_helpers_cover_database_type_variants() -> None:
    assert cx_repository._json_loads(None, default={"empty": True}) == {"empty": True}
    assert cx_repository._json_loads({"a": 1}, default={}) == {"a": 1}
    assert cx_repository._json_loads(b'{"a":2}', default={}) == {"a": 2}
    assert cx_repository._json_loads(3, default={"fallback": True}) == {
        "fallback": True
    }
    assert cx_repository._timestamp_to_wire(
        datetime.fromisoformat("2026-08-09T00:00:00+00:00")
    ) == "2026-08-09T00:00:00Z"
    assert cx_repository._timestamp_to_wire(
        datetime.fromisoformat("2026-08-09T00:00:00")
    ) == "2026-08-09T00:00:00Z"
