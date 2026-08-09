from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from nex_runtime import build_engine, build_session_factory
from nex_cx.chunking import store_chunk_set
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
    sha256_text,
)
from nex_cx.repository import (
    CxContentRepositoryError,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    InMemoryCxContentRepository,
    SqlAlchemyCxContentRepository,
    build_chunk_embedding_index_record,
    build_chunk_set_record,
    build_content_object_record,
    build_extraction_artifact_record,
    build_lexical_index_record,
    build_source_file_record,
    markdown_storage_uri_from_path,
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


def upload_registration(
    tmp_path: Path,
    *,
    content_text: str = "hello",
    request_id: str = REQUEST_ID,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
) -> dict[str, object]:
    payload = {
        "filename": "source.md",
        "content_type": "text/markdown",
        "content_text": content_text,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if owner_user_id is not None:
        payload["owner_user_id"] = owner_user_id
    return build_upload_registration(
        payload,
        storage_config=storage_config(tmp_path),
        request_id=request_id,
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
        connection.execute(
            text(
                """
                CREATE TABLE cx_extraction_artifacts (
                    extraction_artifact_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    source_file_id TEXT NOT NULL REFERENCES cx_source_files(source_file_id),
                    artifact_kind TEXT NOT NULL DEFAULT 'markdown',
                    status TEXT NOT NULL DEFAULT 'SUCCEEDED',
                    extractor_name TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    markdown_sha256 TEXT NOT NULL,
                    markdown_storage_uri TEXT NOT NULL,
                    markdown_char_count INTEGER NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (content_object_id, extractor_name, extractor_version, markdown_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunk_sets (
                    chunk_set_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
                    chunk_policy_id TEXT NOT NULL,
                    chunk_size INTEGER NOT NULL,
                    chunk_overlap INTEGER NOT NULL,
                    source_markdown_sha256 TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (content_object_id, extraction_artifact_id, chunk_policy_id, source_markdown_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    chunk_set_id TEXT NOT NULL REFERENCES cx_chunk_sets(chunk_set_id),
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    ordinal INTEGER NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    char_count INTEGER NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    text_preview TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (chunk_set_id, ordinal),
                    UNIQUE (chunk_set_id, text_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_chunk_embeddings (
                    chunk_embedding_id TEXT PRIMARY KEY,
                    chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
                    provider_alias TEXT NOT NULL,
                    model_profile_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    vector_dimension INTEGER NOT NULL,
                    embedding_sha256 TEXT NOT NULL,
                    embedding_storage_uri TEXT,
                    status TEXT NOT NULL DEFAULT 'READY',
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (chunk_id, model_profile_id, model_revision)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_lexical_terms (
                    lexical_term_id TEXT PRIMARY KEY,
                    chunk_set_id TEXT NOT NULL REFERENCES cx_chunk_sets(chunk_set_id),
                    tokenizer_requested TEXT NOT NULL,
                    tokenizer_used TEXT NOT NULL,
                    tokenizer_fallback TEXT NOT NULL,
                    fallback_used BOOLEAN NOT NULL DEFAULT 0,
                    term TEXT NOT NULL,
                    document_frequency INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (chunk_set_id, tokenizer_used, term)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_lexical_postings (
                    lexical_posting_id TEXT PRIMARY KEY,
                    lexical_term_id TEXT NOT NULL REFERENCES cx_lexical_terms(lexical_term_id),
                    chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
                    occurrence_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (lexical_term_id, chunk_id)
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


def extraction_result(
    tmp_path: Path,
    document: dict[str, object],
    *,
    markdown_text: str = "# source.md\n\nSECRET_EXTRACTED_MARKDOWN\n",
) -> dict[str, object]:
    markdown_path = tmp_path / "cx" / "extracted-markdown" / "aa" / (
        f"{document['document_id']}.md"
    )
    return {
        "extraction_schema_version": "cx_text_extraction.v1",
        "document_id": document["document_id"],
        "job_id": document["extraction"]["job_id"],
        "status": "SUCCEEDED",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "source_sha256": document["source_sha256"],
        "extracted_markdown_sha256": sha256_text(markdown_text),
        "extracted_markdown_path": str(markdown_path),
        "markdown_char_count": len(markdown_text),
        "markdown_preview": markdown_text[:120],
        "extractor": {
            "provider": "local_mock",
            "mode": "plain_text_to_markdown",
            "version": "slice-0072",
            "source_format": "plain_text",
        },
        "warnings": [],
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }


def chunk_set_payload(
    tmp_path: Path,
    document: dict[str, object],
    *,
    markdown_text: str = "# source.md\n\n" + ("a" * 130) + "SECRET_PRIVATE_CHUNK_SUFFIX",
) -> dict[str, object]:
    result = extraction_result(tmp_path, document, markdown_text=markdown_text)
    return store_chunk_set(
        document_id=str(document["document_id"]),
        extraction=result,
        markdown_text=markdown_text,
        store=ContentIngestionStore(),
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def lexical_index_payload(chunk_set: dict[str, object]) -> dict[str, object]:
    chunk = chunk_set["chunks"][0]
    return {
        "lexical_index_schema_version": "cx_lexical_index.v1",
        "document_id": chunk_set.get("document_id", chunk_set.get("content_object_id")),
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "tokenizer_requested": "mecab_ko",
        "tokenizer_used": "korean_mixed_v1",
        "tokenizer_fallback": "korean_mixed_v1",
        "fallback_used": True,
        "tokenizer_profile": {
            "bm25_tokenizer_requested": "mecab_ko",
            "bm25_tokenizer": "korean_mixed_v1",
            "bm25_tokenizer_fallback": "korean_mixed_v1",
            "fallback_used": True,
            "query_tokenizer_policy": "match_index_tokenizer_with_fallback",
            "dictionary_profile": "none_regex_korean_mixed_v1",
            "dictionary_path_env": None,
            "dictionary_path_configured": False,
        },
        "chunk_count": chunk_set["chunk_count"],
        "unique_token_count": 1,
        "postings": [
            {
                "term": "trace",
                "document_frequency": 1,
                "occurrences": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "ordinal": chunk["ordinal"],
                        "count": 2,
                    }
                ],
            }
        ],
        "created_at": chunk_set["created_at"],
        "updated_at": chunk_set.get("updated_at", chunk_set["created_at"]),
    }


def embedding_index_payload(chunk_set: dict[str, object]) -> dict[str, object]:
    return {
        "embedding_index_schema_version": "cx_embedding_index.v1",
        "document_id": chunk_set.get("document_id", chunk_set.get("content_object_id")),
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "provider_alias": "mock-embedding-default",
        "model_revision": "mock-embedding-v1",
        "deployment_id": "mock-embedding-local",
        "chunk_count": chunk_set["chunk_count"],
        "vector_dimension": 3,
        "chunk_embeddings": [
            {
                "chunk_id": chunk["chunk_id"],
                "ordinal": chunk["ordinal"],
                "text_sha256": chunk["text_sha256"],
                "embedding_sha256": f"{index + 1:064x}",
                "vector_dimension": 3,
            }
            for index, chunk in enumerate(chunk_set["chunks"])
        ],
        "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
        "created_at": chunk_set["created_at"],
        "updated_at": chunk_set.get("updated_at", chunk_set["created_at"]),
    }


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


def test_build_extraction_artifact_record_maps_metadata_without_markdown_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    result = extraction_result(tmp_path, upload)

    record = build_extraction_artifact_record(
        result,
        content_object_id=str(upload["document_id"]),
        source_file_id="11111111-1111-4111-8111-111111111111",
    )

    assert record["artifact_kind"] == "markdown"
    assert record["status"] == "SUCCEEDED"
    assert record["extractor_name"] == "local_mock"
    assert record["extractor_version"] == "slice-0072"
    assert record["markdown_sha256"] == result["extracted_markdown_sha256"]
    assert record["markdown_storage_uri"].startswith(
        "local://cx/extracted-markdown/"
    )
    assert "SECRET_EXTRACTED_MARKDOWN" not in str(record)
    assert markdown_storage_uri_from_path("one.md") == (
        "local://cx/extracted-markdown/one.md"
    )


def test_build_chunk_set_record_maps_metadata_without_private_chunk_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)

    record = build_chunk_set_record(
        chunk_set,
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )

    assert record["content_object_id"] == upload["document_id"]
    assert record["chunk_policy_id"] == chunk_set["chunk_policy"]
    assert record["source_markdown_sha256"] == chunk_set["source_markdown_sha256"]
    assert record["chunk_count"] == len(record["chunks"])
    assert record["chunks"][0]["chunk_set_id"] == record["chunk_set_id"]
    assert record["chunks"][0]["content_object_id"] == upload["document_id"]
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" not in str(record)


def test_build_chunk_embedding_index_record_maps_hashes_without_vectors(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    embedding_index = embedding_index_payload(chunk_set)

    record = build_chunk_embedding_index_record(
        embedding_index,
        chunk_set_id="66666666-6666-4666-8666-666666666666",
    )

    first = record["chunk_embeddings"][0]
    assert record["model_profile_id"] == "mock-embedding-default"
    assert first["chunk_id"] == chunk_set["chunks"][0]["chunk_id"]
    assert first["embedding_sha256"] == embedding_index["chunk_embeddings"][0][
        "embedding_sha256"
    ]
    assert first["vector_dimension"] == 3
    assert "SECRET_PRIVATE_VECTOR" not in str(record)
    assert "[0.0, 0.5, 1.0]" not in str(record)


def test_build_lexical_index_record_maps_terms_without_chunk_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    lexical_index = lexical_index_payload(chunk_set)

    record = build_lexical_index_record(
        lexical_index,
        chunk_set_id="66666666-6666-4666-8666-666666666666",
    )

    term = record["terms"][0]
    posting = term["postings"][0]
    assert record["tokenizer_used"] == "korean_mixed_v1"
    assert record["unique_token_count"] == 1
    assert term["term"] == "trace"
    assert term["document_frequency"] == 1
    assert posting["chunk_id"] == chunk_set["chunks"][0]["chunk_id"]
    assert posting["occurrence_count"] == 2
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" not in str(record)


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


def test_in_memory_repository_saves_extraction_artifacts_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = repository.save_content_object(
        build_content_object_record(
            upload,
            source_file_id=source_file["source_file_id"],
        )
    )
    artifact = build_extraction_artifact_record(
        extraction_result(tmp_path, upload),
        content_object_id=content["content_object_id"],
        source_file_id=source_file["source_file_id"],
    )
    duplicate = {
        **artifact,
        "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
    }

    assert repository.save_extraction_artifact(artifact) == artifact
    assert repository.save_extraction_artifact(duplicate) == artifact
    assert repository.get_extraction_artifact(artifact["extraction_artifact_id"]) == artifact
    assert repository.find_extraction_artifact(
        content_object_id=content["content_object_id"],
        extractor_name=artifact["extractor_name"],
        extractor_version=artifact["extractor_version"],
        markdown_sha256=artifact["markdown_sha256"],
    ) == artifact
    assert repository.get_extraction_artifact("missing") is None
    assert repository.find_extraction_artifact(
        content_object_id=content["content_object_id"],
        extractor_name="other",
        extractor_version=artifact["extractor_version"],
        markdown_sha256=artifact["markdown_sha256"],
    ) is None


def test_in_memory_repository_saves_chunk_sets_idempotently(tmp_path: Path) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    record = build_chunk_set_record(
        chunk_set,
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )
    duplicate = {
        **record,
        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
    }

    assert repository.save_chunk_set(record) == record
    assert repository.save_chunk_set(duplicate) == record
    assert repository.get_chunk_set(record["chunk_set_id"]) == record
    assert repository.find_chunk_set(
        content_object_id=record["content_object_id"],
        extraction_artifact_id=record["extraction_artifact_id"],
        chunk_policy_id=record["chunk_policy_id"],
        source_markdown_sha256=record["source_markdown_sha256"],
    ) == record
    assert repository.get_chunk_set("missing") is None
    assert repository.find_chunk_set(
        content_object_id=record["content_object_id"],
        extraction_artifact_id=record["extraction_artifact_id"],
        chunk_policy_id="other",
        source_markdown_sha256=record["source_markdown_sha256"],
    ) is None


def test_in_memory_repository_saves_lexical_indexes_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    record = build_lexical_index_record(
        lexical_index_payload(chunk_set),
        chunk_set_id="66666666-6666-4666-8666-666666666666",
    )
    duplicate = {
        **record,
        "terms": [
            {
                **record["terms"][0],
                "lexical_term_id": "77777777-7777-4777-8777-777777777777",
            }
        ],
    }

    assert repository.save_lexical_index(record) == record
    assert repository.save_lexical_index(duplicate) == record
    assert repository.find_lexical_index(
        chunk_set_id=record["chunk_set_id"],
        tokenizer_used=record["tokenizer_used"],
    ) == record
    assert repository.find_lexical_index(
        chunk_set_id=record["chunk_set_id"],
        tokenizer_used="other",
    ) is None


def test_in_memory_repository_saves_chunk_embedding_indexes_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    record = build_chunk_embedding_index_record(
        embedding_index_payload(chunk_set),
        chunk_set_id="66666666-6666-4666-8666-666666666666",
    )
    duplicate = {
        **record,
        "chunk_embeddings": [
            {
                **record["chunk_embeddings"][0],
                "chunk_embedding_id": "88888888-8888-4888-8888-888888888888",
            }
        ],
    }

    assert repository.save_chunk_embedding_index(record) == record
    assert repository.save_chunk_embedding_index(duplicate) == record
    assert repository.find_chunk_embedding_index(
        chunk_set_id=record["chunk_set_id"],
        model_profile_id=record["model_profile_id"],
        model_revision=record["model_revision"],
    ) == record
    assert repository.find_chunk_embedding_index(
        chunk_set_id=record["chunk_set_id"],
        model_profile_id="other",
        model_revision=record["model_revision"],
    ) is None


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
    assert repository.save_content_object(content) == content
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


def test_sqlalchemy_repository_saves_and_finds_extraction_artifact(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
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
    artifact = build_extraction_artifact_record(
        extraction_result(tmp_path, upload),
        content_object_id=content["content_object_id"],
        source_file_id=source_file["source_file_id"],
    )
    duplicate = {
        **artifact,
        "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
    }

    saved = repository.save_extraction_artifact(artifact)

    assert saved == artifact
    assert repository.save_extraction_artifact(duplicate) == artifact
    assert repository.get_extraction_artifact(saved["extraction_artifact_id"]) == artifact
    assert repository.find_extraction_artifact(
        content_object_id=content["content_object_id"],
        extractor_name=artifact["extractor_name"],
        extractor_version=artifact["extractor_version"],
        markdown_sha256=artifact["markdown_sha256"],
    ) == artifact
    assert _sqlite_table_count(engine, "cx_extraction_artifacts") == 1
    assert "SECRET_EXTRACTED_MARKDOWN" not in _sqlite_table_dump(
        engine,
        ["cx_extraction_artifacts"],
    )


def test_sqlalchemy_repository_saves_and_finds_chunk_set_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
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
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    chunk_set = chunk_set_payload(tmp_path, upload)
    record = build_chunk_set_record(
        chunk_set,
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
    )
    duplicate = {
        **record,
        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
    }

    saved = repository.save_chunk_set(record)

    assert saved == record
    assert repository.save_chunk_set(duplicate) == record
    assert repository.get_chunk_set(saved["chunk_set_id"]) == record
    assert repository.get_chunk_set("66666666-6666-4666-8666-666666666667") is None
    assert repository.find_chunk_set(
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        chunk_policy_id=record["chunk_policy_id"],
        source_markdown_sha256=record["source_markdown_sha256"],
    ) == record
    assert _sqlite_table_count(engine, "cx_chunk_sets") == 1
    assert _sqlite_table_count(engine, "cx_chunks") == record["chunk_count"]
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" not in _sqlite_table_dump(
        engine,
        ["cx_chunk_sets", "cx_chunks"],
    )


def test_sqlalchemy_repository_saves_and_finds_lexical_index_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
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
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    chunk_set = repository.save_chunk_set(
        build_chunk_set_record(
            chunk_set_payload(tmp_path, upload),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    record = build_lexical_index_record(
        lexical_index_payload(chunk_set),
        chunk_set_id=chunk_set["chunk_set_id"],
    )
    duplicate = {
        **record,
        "terms": [
            {
                **record["terms"][0],
                "lexical_term_id": "77777777-7777-4777-8777-777777777777",
            }
        ],
    }

    saved = repository.save_lexical_index(record)

    assert saved == record
    assert repository.save_lexical_index(duplicate) == record
    assert repository.find_lexical_index(
        chunk_set_id=record["chunk_set_id"],
        tokenizer_used=record["tokenizer_used"],
    ) == record
    assert repository.find_lexical_index(
        chunk_set_id=record["chunk_set_id"],
        tokenizer_used="other",
    ) is None
    assert _sqlite_table_count(engine, "cx_lexical_terms") == 1
    assert _sqlite_table_count(engine, "cx_lexical_postings") == 1
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" not in _sqlite_table_dump(
        engine,
        ["cx_lexical_terms", "cx_lexical_postings"],
    )


def test_sqlalchemy_repository_saves_and_finds_chunk_embedding_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
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
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    chunk_set = repository.save_chunk_set(
        build_chunk_set_record(
            chunk_set_payload(tmp_path, upload),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    record = build_chunk_embedding_index_record(
        embedding_index_payload(chunk_set),
        chunk_set_id=chunk_set["chunk_set_id"],
    )
    duplicate = {
        **record,
        "chunk_embeddings": [
            {
                **record["chunk_embeddings"][0],
                "chunk_embedding_id": "88888888-8888-4888-8888-888888888888",
            }
        ],
    }

    saved = repository.save_chunk_embedding_index(record)

    assert saved == record
    assert repository.save_chunk_embedding_index(duplicate) == record
    assert repository.find_chunk_embedding_index(
        chunk_set_id=record["chunk_set_id"],
        model_profile_id=record["model_profile_id"],
        model_revision=record["model_revision"],
    ) == record
    assert repository.find_chunk_embedding_index(
        chunk_set_id=record["chunk_set_id"],
        model_profile_id="other",
        model_revision=record["model_revision"],
    ) is None
    assert _sqlite_table_count(engine, "cx_chunk_embeddings") == record["chunk_count"]
    assert "[0.0, 0.5, 1.0]" not in _sqlite_table_dump(
        engine,
        ["cx_chunk_embeddings"],
    )


def test_sqlalchemy_repository_keeps_empty_chunk_embedding_index_at_boundary(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    record = {
        "embedding_index_schema_version": "cx_embedding_index.persistence.v1",
        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
        "provider_alias": "mock-embedding-default",
        "model_profile_id": "mock-embedding-default",
        "model_revision": "mock-embedding-v1",
        "deployment_id": "mock-embedding-local",
        "chunk_count": 0,
        "vector_dimension": 0,
        "chunk_embeddings": [],
        "created_trace_id": TRACE_ID,
        "created_at": "2026-08-09T00:00:00Z",
    }

    saved = repository.save_chunk_embedding_index(record)

    assert saved == record
    assert repository.find_chunk_embedding_index(
        chunk_set_id=record["chunk_set_id"],
        model_profile_id=record["model_profile_id"],
        model_revision=record["model_revision"],
    ) is None
    assert _sqlite_table_count(engine, "cx_chunk_embeddings") == 0


def test_sqlalchemy_repository_keeps_empty_lexical_index_at_boundary(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    record = {
        "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
        "tokenizer_requested": "mecab_ko",
        "tokenizer_used": "korean_mixed_v1",
        "tokenizer_fallback": "korean_mixed_v1",
        "fallback_used": True,
        "chunk_count": 0,
        "unique_token_count": 0,
        "terms": [],
        "created_at": "2026-08-09T00:00:00Z",
    }

    saved = repository.save_lexical_index(record)

    assert saved == record
    assert repository.find_lexical_index(
        chunk_set_id=record["chunk_set_id"],
        tokenizer_used=record["tokenizer_used"],
    ) is None
    assert _sqlite_table_count(engine, "cx_lexical_terms") == 0
    assert _sqlite_table_count(engine, "cx_lexical_postings") == 0


def test_sqlalchemy_repository_saves_lexical_term_without_postings(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    record = {
        "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
        "tokenizer_requested": "mecab_ko",
        "tokenizer_used": "korean_mixed_v1",
        "tokenizer_fallback": "korean_mixed_v1",
        "fallback_used": True,
        "chunk_count": 0,
        "unique_token_count": 1,
        "terms": [
            {
                "lexical_term_id": "77777777-7777-4777-8777-777777777777",
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "tokenizer_requested": "mecab_ko",
                "tokenizer_used": "korean_mixed_v1",
                "tokenizer_fallback": "korean_mixed_v1",
                "fallback_used": True,
                "term": "trace",
                "document_frequency": 0,
                "postings": [],
                "created_at": "2026-08-09T00:00:00Z",
            }
        ],
        "created_at": "2026-08-09T00:00:00Z",
    }

    saved = repository.save_lexical_index(record)

    assert saved == record
    assert _sqlite_table_count(engine, "cx_lexical_terms") == 1
    assert _sqlite_table_count(engine, "cx_lexical_postings") == 0


def test_sqlalchemy_repository_saves_empty_chunk_set_without_chunk_rows(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = repository.save_content_object(
        build_content_object_record(
            upload,
            source_file_id=source_file["source_file_id"],
        )
    )
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload, markdown_text=""),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    empty_chunk_set = chunk_set_payload(tmp_path, upload, markdown_text="")
    record = build_chunk_set_record(
        empty_chunk_set,
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
    )

    saved = repository.save_chunk_set(record)

    assert saved["chunks"] == []
    assert saved["chunk_count"] == 0
    assert _sqlite_table_count(engine, "cx_chunk_sets") == 1
    assert _sqlite_table_count(engine, "cx_chunks") == 0


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
        lambda repository: repository.mark_source_file_checksum_verified(
            "33333333-3333-4333-8333-333333333333",
            verified_at="2026-08-09T00:00:00Z",
        ),
        lambda repository: repository.save_extraction_artifact(
            {
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "source_file_id": "33333333-3333-4333-8333-333333333333",
                "artifact_kind": "markdown",
                "status": "SUCCEEDED",
                "extractor_name": "local_mock",
                "extractor_version": "slice-0072",
                "markdown_sha256": "0" * 64,
                "markdown_storage_uri": "local://cx/extracted-markdown/aa/doc.md",
                "markdown_char_count": 10,
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
            }
        ),
        lambda repository: repository.get_extraction_artifact(
            "55555555-5555-4555-8555-555555555555"
        ),
        lambda repository: repository.find_extraction_artifact(
            content_object_id="44444444-4444-4444-8444-444444444444",
            extractor_name="local_mock",
            extractor_version="slice-0072",
            markdown_sha256="0" * 64,
        ),
        lambda repository: repository.save_chunk_set(
            {
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "chunk_policy_id": "chunk_1000_100",
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "source_markdown_sha256": "0" * 64,
                "chunk_count": 0,
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "chunks": [],
            }
        ),
        lambda repository: repository.get_chunk_set(
            "66666666-6666-4666-8666-666666666666"
        ),
        lambda repository: repository.find_chunk_set(
            content_object_id="44444444-4444-4444-8444-444444444444",
            extraction_artifact_id="55555555-5555-4555-8555-555555555555",
            chunk_policy_id="chunk_1000_100",
            source_markdown_sha256="0" * 64,
        ),
        lambda repository: repository.save_lexical_index(
            {
                "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "tokenizer_requested": "mecab_ko",
                "tokenizer_used": "korean_mixed_v1",
                "tokenizer_fallback": "korean_mixed_v1",
                "fallback_used": True,
                "chunk_count": 0,
                "unique_token_count": 0,
                "terms": [
                    {
                        "lexical_term_id": "77777777-7777-4777-8777-777777777777",
                        "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                        "tokenizer_requested": "mecab_ko",
                        "tokenizer_used": "korean_mixed_v1",
                        "tokenizer_fallback": "korean_mixed_v1",
                        "fallback_used": True,
                        "term": "trace",
                        "document_frequency": 1,
                        "postings": [],
                        "created_at": "2026-08-09T00:00:00Z",
                    }
                ],
                "created_at": "2026-08-09T00:00:00Z",
            }
        ),
        lambda repository: repository.find_lexical_index(
            chunk_set_id="66666666-6666-4666-8666-666666666666",
            tokenizer_used="korean_mixed_v1",
        ),
        lambda repository: repository.save_chunk_embedding_index(
            {
                "embedding_index_schema_version": "cx_embedding_index.persistence.v1",
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "provider_alias": "mock-embedding-default",
                "model_profile_id": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "chunk_count": 1,
                "vector_dimension": 3,
                "chunk_embeddings": [
                    {
                        "chunk_embedding_id": "88888888-8888-4888-8888-888888888888",
                        "chunk_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        "provider_alias": "mock-embedding-default",
                        "model_profile_id": "mock-embedding-default",
                        "model_revision": "mock-embedding-v1",
                        "deployment_id": "mock-embedding-local",
                        "vector_dimension": 3,
                        "embedding_sha256": "1" * 64,
                        "embedding_storage_uri": None,
                        "status": "READY",
                        "created_trace_id": TRACE_ID,
                        "created_at": "2026-08-09T00:00:00Z",
                    }
                ],
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
            }
        ),
        lambda repository: repository.find_chunk_embedding_index(
            chunk_set_id="66666666-6666-4666-8666-666666666666",
            model_profile_id="mock-embedding-default",
            model_revision="mock-embedding-v1",
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

    class RaceyExtractionRepository(SqlAlchemyCxContentRepository):
        def _save_extraction_artifact(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert extraction", {}, Exception("race"))

    class RaceyChunkSetRepository(SqlAlchemyCxContentRepository):
        def _save_chunk_set(self, session: Any, record: dict[str, Any]) -> dict[str, Any]:
            raise IntegrityError("insert chunk set", {}, Exception("race"))

    class RaceyLexicalRepository(SqlAlchemyCxContentRepository):
        def _save_lexical_index(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert lexical", {}, Exception("race"))

    class RaceyChunkEmbeddingRepository(SqlAlchemyCxContentRepository):
        def _save_chunk_embedding_index(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert chunk embedding", {}, Exception("race"))

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
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    chunk_set = repository.save_chunk_set(
        build_chunk_set_record(
            chunk_set_payload(tmp_path, upload),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )

    racey_source = RaceySourceRepository(
        build_session_factory(engine),
        local_source_root=tmp_path / "cx" / "source-files",
    )
    racey_content = RaceyContentRepository(build_session_factory(engine))
    racey_extraction = RaceyExtractionRepository(build_session_factory(engine))
    racey_chunk_set = RaceyChunkSetRepository(build_session_factory(engine))
    racey_lexical = RaceyLexicalRepository(build_session_factory(engine))
    racey_chunk_embedding = RaceyChunkEmbeddingRepository(build_session_factory(engine))
    lexical = repository.save_lexical_index(
        build_lexical_index_record(
            lexical_index_payload(chunk_set),
            chunk_set_id=chunk_set["chunk_set_id"],
        )
    )
    chunk_embedding = repository.save_chunk_embedding_index(
        build_chunk_embedding_index_record(
            embedding_index_payload(chunk_set),
            chunk_set_id=chunk_set["chunk_set_id"],
        )
    )

    assert racey_source.save_source_file(source_file_record) == source_file
    assert racey_content.save_content_object(content) == content
    assert racey_extraction.save_extraction_artifact(artifact) == artifact
    assert racey_chunk_set.save_chunk_set(chunk_set) == chunk_set
    assert racey_lexical.save_lexical_index(lexical) == lexical
    assert (
        racey_chunk_embedding.save_chunk_embedding_index(chunk_embedding)
        == chunk_embedding
    )


def test_sqlalchemy_repository_extraction_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyExtractionRepository(SqlAlchemyCxContentRepository):
        def _save_extraction_artifact(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert extraction", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyExtractionRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_extraction_artifact(
            {
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "source_file_id": "33333333-3333-4333-8333-333333333333",
                "artifact_kind": "markdown",
                "status": "SUCCEEDED",
                "extractor_name": "local_mock",
                "extractor_version": "slice-0072",
                "markdown_sha256": "0" * 64,
                "markdown_storage_uri": "local://cx/extracted-markdown/aa/doc.md",
                "markdown_char_count": 10,
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_source_and_content_integrity_without_existing_rows_wrap(
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

    _, engine = sqlite_content_repository(tmp_path)
    upload = upload_registration(tmp_path)
    source_file_record = build_source_file_record(upload)
    content_record = build_content_object_record(
        upload,
        source_file_id=source_file_record["source_file_id"],
    )

    with pytest.raises(CxContentRepositoryError) as source_exc:
        RaceySourceRepository(build_session_factory(engine)).save_source_file(
            source_file_record
        )
    with pytest.raises(CxContentRepositoryError) as content_exc:
        RaceyContentRepository(build_session_factory(engine)).save_content_object(
            content_record
        )

    assert source_exc.value.error_code == "cx_content.repository_unavailable"
    assert content_exc.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_chunk_set_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyChunkSetRepository(SqlAlchemyCxContentRepository):
        def _save_chunk_set(self, session: Any, record: dict[str, Any]) -> dict[str, Any]:
            raise IntegrityError("insert chunk set", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyChunkSetRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_chunk_set(
            {
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "chunk_policy_id": "chunk_1000_100",
                "chunk_size": 1000,
                "chunk_overlap": 100,
                "source_markdown_sha256": "0" * 64,
                "chunk_count": 0,
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "chunks": [],
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_lexical_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyLexicalRepository(SqlAlchemyCxContentRepository):
        def _save_lexical_index(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert lexical", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyLexicalRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_lexical_index(
            {
                "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "tokenizer_requested": "mecab_ko",
                "tokenizer_used": "korean_mixed_v1",
                "tokenizer_fallback": "korean_mixed_v1",
                "fallback_used": True,
                "chunk_count": 0,
                "unique_token_count": 0,
                "terms": [],
                "created_at": "2026-08-09T00:00:00Z",
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_chunk_embedding_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyChunkEmbeddingRepository(SqlAlchemyCxContentRepository):
        def _save_chunk_embedding_index(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert chunk embedding", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyChunkEmbeddingRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_chunk_embedding_index(
            {
                "embedding_index_schema_version": "cx_embedding_index.persistence.v1",
                "chunk_set_id": "66666666-6666-4666-8666-666666666666",
                "provider_alias": "mock-embedding-default",
                "model_profile_id": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "chunk_count": 0,
                "vector_dimension": 0,
                "chunk_embeddings": [],
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


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
    assert cx_repository._bool_from_database(True) is True
    assert cx_repository._bool_from_database(0) is False
    assert cx_repository._bool_from_database("yes") is True
    assert cx_repository._bool_from_database("no") is False
    assert cx_repository._bool_from_database(None) is False
    postgres_session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    assert cx_repository._json_sql_expression(postgres_session, "payload") == (
        "CAST(:payload AS JSONB)"
    )


def test_content_ingestion_store_with_sqlalchemy_repository_dedupes_same_owner(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    first_upload = upload_registration(
        tmp_path,
        content_text="SAME_OWNER_SECRET_UPLOAD",
        request_id=REQUEST_ID,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second_upload = upload_registration(
        tmp_path,
        content_text="SAME_OWNER_SECRET_UPLOAD",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb22",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    first = store.save_upload_registration(
        first_upload,
        source_text="SAME_OWNER_SECRET_UPLOAD",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second = store.save_upload_registration(
        second_upload,
        source_text="SAME_OWNER_SECRET_UPLOAD",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    assert first["dedupe"]["status"] == "CREATED"
    assert second["dedupe"] == {
        "scope": "owner_active_content",
        "status": "ALREADY_EXISTS",
        "existing_document_id": first["document_id"],
    }
    assert second["document_id"] == first["document_id"]
    assert store.get_content_ref(first["document_id"]) is not None
    assert Path(first["storage"]["source_storage_path"]).exists()
    assert _sqlite_table_count(engine, "cx_source_files") == 1
    assert _sqlite_table_count(engine, "cx_content_objects") == 1
    assert _sqlite_table_count(engine, "cx_content_acl_entries") == 1
    assert "SAME_OWNER_SECRET_UPLOAD" not in _sqlite_table_dump(
        engine,
        ["cx_source_files", "cx_content_objects", "cx_content_acl_entries"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_shares_source_across_owners(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    first_upload = upload_registration(
        tmp_path,
        content_text="SHARED_SOURCE_SECRET_UPLOAD",
        request_id=REQUEST_ID,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second_upload = upload_registration(
        tmp_path,
        content_text="SHARED_SOURCE_SECRET_UPLOAD",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb23",
        tenant_id="tenant-a",
        owner_user_id="user-b",
    )

    first = store.save_upload_registration(
        first_upload,
        source_text="SHARED_SOURCE_SECRET_UPLOAD",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second = store.save_upload_registration(
        second_upload,
        source_text="SHARED_SOURCE_SECRET_UPLOAD",
        tenant_id="tenant-a",
        owner_user_id="user-b",
    )

    first_ref = store.get_content_ref(first["document_id"])
    second_ref = store.get_content_ref(second["document_id"])
    assert first["dedupe"]["status"] == "CREATED"
    assert second["dedupe"]["status"] == "CREATED"
    assert first["document_id"] != second["document_id"]
    assert first_ref is not None
    assert second_ref is not None
    assert first_ref["source_file_id"] == second_ref["source_file_id"]
    assert first_ref["content_object_id"] != second_ref["content_object_id"]
    assert _sqlite_table_count(engine, "cx_source_files") == 1
    assert _sqlite_table_count(engine, "cx_content_objects") == 2
    assert _sqlite_table_count(engine, "cx_content_acl_entries") == 2
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=first["source_sha256"],
    )["content_object_id"] == first["document_id"]
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-b",
        source_sha256=second["source_sha256"],
    )["content_object_id"] == second["document_id"]
    assert "SHARED_SOURCE_SECRET_UPLOAD" not in _sqlite_table_dump(
        engine,
        ["cx_source_files", "cx_content_objects", "cx_content_acl_entries"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_persists_extraction_artifact(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    document = upload_registration(
        tmp_path,
        content_text="SECRET_SOURCE_FOR_EXTRACTION",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    store.save_upload_registration(
        document,
        source_text="SECRET_SOURCE_FOR_EXTRACTION",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    result = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    refs = store.get_content_ref(document["document_id"])
    assert refs is not None
    artifact = repository.find_extraction_artifact(
        content_object_id=refs["content_object_id"],
        extractor_name=result["extractor"]["provider"],
        extractor_version=result["extractor"]["version"],
        markdown_sha256=result["extracted_markdown_sha256"],
    )
    assert artifact is not None
    assert artifact["source_file_id"] == refs["source_file_id"]
    assert artifact["markdown_char_count"] == result["markdown_char_count"]
    assert artifact["markdown_storage_uri"].startswith(
        "local://cx/extracted-markdown/"
    )
    assert _sqlite_table_count(engine, "cx_extraction_artifacts") == 1
    assert "SECRET_SOURCE_FOR_EXTRACTION" not in _sqlite_table_dump(
        engine,
        ["cx_extraction_artifacts"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_persists_chunk_set_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = ("a" * 130) + "SECRET_PRIVATE_CHUNK_SUFFIX"
    document = upload_registration(
        tmp_path,
        content_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    store.save_upload_registration(
        document,
        source_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    result = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    public_chunk_set = store_chunk_set(
        document_id=str(document["document_id"]),
        extraction=result,
        markdown_text=Path(result["extracted_markdown_path"]).read_text(
            encoding="utf-8"
        ),
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    refs = store.get_content_ref(str(document["document_id"]))
    assert refs is not None
    artifact = repository.find_extraction_artifact(
        content_object_id=refs["content_object_id"],
        extractor_name=result["extractor"]["provider"],
        extractor_version=result["extractor"]["version"],
        markdown_sha256=result["extracted_markdown_sha256"],
    )
    assert artifact is not None
    persisted = repository.find_chunk_set(
        content_object_id=refs["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        chunk_policy_id=public_chunk_set["chunk_policy"],
        source_markdown_sha256=public_chunk_set["source_markdown_sha256"],
    )
    assert persisted is not None
    assert persisted["chunk_count"] == public_chunk_set["chunk_count"]
    assert persisted["chunks"][0]["text_sha256"] == public_chunk_set["chunks"][0][
        "text_sha256"
    ]
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" in store.get_chunk_text(
        public_chunk_set["chunks"][0]["chunk_id"]
    )
    assert _sqlite_table_count(engine, "cx_chunk_sets") == 1
    assert _sqlite_table_count(engine, "cx_chunks") == public_chunk_set["chunk_count"]
    assert "SECRET_PRIVATE_CHUNK_SUFFIX" not in _sqlite_table_dump(
        engine,
        ["cx_chunk_sets", "cx_chunks"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_persists_lexical_index(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "trace trace SECRET_LEXICAL_PRIVATE_TEXT"
    document = upload_registration(
        tmp_path,
        content_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    store.save_upload_registration(
        document,
        source_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    result = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    public_chunk_set = store_chunk_set(
        document_id=str(document["document_id"]),
        extraction=result,
        markdown_text=Path(result["extracted_markdown_path"]).read_text(
            encoding="utf-8"
        ),
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    lexical_index = lexical_index_payload(public_chunk_set)

    saved = store.save_lexical_index(lexical_index)

    refs = store.get_content_ref(str(document["document_id"]))
    assert refs is not None
    artifact = repository.find_extraction_artifact(
        content_object_id=refs["content_object_id"],
        extractor_name=result["extractor"]["provider"],
        extractor_version=result["extractor"]["version"],
        markdown_sha256=result["extracted_markdown_sha256"],
    )
    assert artifact is not None
    persisted_chunk_set = repository.find_chunk_set(
        content_object_id=refs["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        chunk_policy_id=public_chunk_set["chunk_policy"],
        source_markdown_sha256=public_chunk_set["source_markdown_sha256"],
    )
    assert persisted_chunk_set is not None
    persisted = repository.find_lexical_index(
        chunk_set_id=persisted_chunk_set["chunk_set_id"],
        tokenizer_used=saved["tokenizer_used"],
    )
    assert persisted is not None
    assert persisted["unique_token_count"] == 1
    assert persisted["terms"][0]["postings"][0]["occurrence_count"] == 2
    assert _sqlite_table_count(engine, "cx_lexical_terms") == 1
    assert _sqlite_table_count(engine, "cx_lexical_postings") == 1
    assert "SECRET_LEXICAL_PRIVATE_TEXT" not in _sqlite_table_dump(
        engine,
        ["cx_lexical_terms", "cx_lexical_postings"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_persists_chunk_embeddings(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "SECRET_VECTOR_SOURCE"
    document = upload_registration(
        tmp_path,
        content_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    store.save_upload_registration(
        document,
        source_text=source_text,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    result = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    public_chunk_set = store_chunk_set(
        document_id=str(document["document_id"]),
        extraction=result,
        markdown_text=Path(result["extracted_markdown_path"]).read_text(
            encoding="utf-8"
        ),
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    embedding_index = embedding_index_payload(public_chunk_set)

    saved = store.save_embedding_index(
        embedding_index,
        embedding_vectors={
            public_chunk_set["chunks"][0]["chunk_id"]: [0.0, 0.5, 1.0],
        },
    )

    refs = store.get_content_ref(str(document["document_id"]))
    assert refs is not None
    artifact = repository.find_extraction_artifact(
        content_object_id=refs["content_object_id"],
        extractor_name=result["extractor"]["provider"],
        extractor_version=result["extractor"]["version"],
        markdown_sha256=result["extracted_markdown_sha256"],
    )
    assert artifact is not None
    persisted_chunk_set = repository.find_chunk_set(
        content_object_id=refs["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        chunk_policy_id=public_chunk_set["chunk_policy"],
        source_markdown_sha256=public_chunk_set["source_markdown_sha256"],
    )
    assert persisted_chunk_set is not None
    persisted = repository.find_chunk_embedding_index(
        chunk_set_id=persisted_chunk_set["chunk_set_id"],
        model_profile_id=saved["provider_alias"],
        model_revision=saved["model_revision"],
    )
    assert persisted is not None
    assert persisted["chunk_count"] == saved["chunk_count"]
    assert persisted["chunk_embeddings"][0]["embedding_sha256"] == saved[
        "chunk_embeddings"
    ][0]["embedding_sha256"]
    assert store.get_embedding_vector(public_chunk_set["chunks"][0]["chunk_id"]) == [
        0.0,
        0.5,
        1.0,
    ]
    assert _sqlite_table_count(engine, "cx_chunk_embeddings") == saved["chunk_count"]
    assert "[0.0, 0.5, 1.0]" not in _sqlite_table_dump(
        engine,
        ["cx_chunk_embeddings"],
    )


def test_content_ingestion_store_saves_extraction_result_without_content_refs(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path)
    store.documents[document["document_id"]] = document
    store.jobs[document["extraction"]["job_id"]] = document["ingestion_job"]
    result = extraction_result(tmp_path, document)

    saved = store.save_extraction_result(result)

    assert saved == result
    assert store.get_extraction_result(document["document_id"]) == result
    assert store.content_repository.extraction_artifacts == {}


def test_content_ingestion_store_saves_chunk_set_without_content_refs(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path)
    result = extraction_result(tmp_path, document)
    chunk_set = chunk_set_payload(tmp_path, document)

    saved = store.save_chunk_set(
        chunk_set,
        chunk_texts={chunk_set["chunks"][0]["chunk_id"]: "private chunk text"},
    )

    assert saved == chunk_set
    assert store.get_chunk_set(document["document_id"]) == chunk_set
    assert store.get_chunk_text(chunk_set["chunks"][0]["chunk_id"]) == "private chunk text"
    assert result["document_id"] == document["document_id"]
    assert store.content_repository.chunk_sets == {}


def test_content_ingestion_store_skips_chunk_metadata_without_extractor_shape(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    document_id = str(document["document_id"])
    store.extraction_results[document_id] = {
        "document_id": document_id,
        "extractor": None,
    }
    chunk_set = chunk_set_payload(tmp_path, document)

    store.save_chunk_set(
        chunk_set,
        chunk_texts={chunk_set["chunks"][0]["chunk_id"]: "private chunk text"},
    )

    assert store.content_repository.chunk_sets == {}


def test_content_ingestion_store_skips_chunk_metadata_without_artifact(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    document_id = str(document["document_id"])
    store.extraction_results[document_id] = extraction_result(tmp_path, document)
    chunk_set = chunk_set_payload(tmp_path, document)

    store.save_chunk_set(
        chunk_set,
        chunk_texts={chunk_set["chunks"][0]["chunk_id"]: "private chunk text"},
    )

    assert store.content_repository.chunk_sets == {}


def test_content_ingestion_store_skips_lexical_metadata_without_persisted_chunk_set(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    document_id = str(document["document_id"])
    store.chunk_sets[document_id] = {
        "document_id": document_id,
        "chunk_policy": "chunk_1000_100",
        "chunk_count": 1,
        "chunks": [{"chunk_id": "chunk-001", "ordinal": 0}],
    }
    lexical_index = {
        "lexical_index_schema_version": "cx_lexical_index.v1",
        "document_id": document_id,
        "tokenizer_requested": "mecab_ko",
        "tokenizer_used": "korean_mixed_v1",
        "tokenizer_fallback": "korean_mixed_v1",
        "fallback_used": True,
        "chunk_count": 1,
        "unique_token_count": 0,
        "postings": [],
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
    }

    saved = store.save_lexical_index(lexical_index)

    assert saved == lexical_index
    assert store.content_repository.lexical_indexes == {}


def test_content_ingestion_store_skips_lexical_metadata_without_artifact(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    document_id = str(document["document_id"])
    store.extraction_results[document_id] = extraction_result(tmp_path, document)
    chunk_set = chunk_set_payload(tmp_path, document, markdown_text="source text")
    store.chunk_sets[document_id] = chunk_set
    lexical_index = lexical_index_payload(chunk_set)

    saved = store.save_lexical_index(lexical_index)

    assert saved == lexical_index
    assert store.content_repository.lexical_indexes == {}


def _sqlite_table_count(engine: object, table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one())


def _sqlite_table_dump(engine: object, table_names: list[str]) -> str:
    rows: list[object] = []
    with engine.connect() as connection:
        for table_name in table_names:
            rows.extend(connection.execute(text(f"SELECT * FROM {table_name}")).all())
    return str(rows)
