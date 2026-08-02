from __future__ import annotations

from pathlib import Path

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
)
from nex_cx.repository import (
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    InMemoryCxContentRepository,
    build_content_object_record,
    build_source_file_record,
)


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
