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
    build_document_summary_persistence_record,
    build_extraction_artifact_record,
    build_lexical_index_record,
    build_processing_run_persistence_record,
    build_retrieval_package_persistence_record,
    build_source_file_record,
    build_summary_embedding_persistence_record,
    bounded_content_object_query_limit,
    markdown_storage_uri_from_path,
)
from nex_cx.summaries import build_document_summary_record
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
                    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant',
                    tenant_ref_id TEXT NOT NULL,
                    owner_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    owner_subject_ref_id TEXT NOT NULL,
                    uploaded_by_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user',
                    uploaded_by_subject_ref_id TEXT NOT NULL,
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
                CREATE UNIQUE INDEX ux_cx_content_owner_subject_source_active
                ON cx_content_objects (
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    source_sha256
                )
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
                    principal_ref_type TEXT NOT NULL,
                    principal_ref_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by_user_id TEXT,
                    granted_by_subject_ref_type TEXT,
                    granted_by_subject_ref_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (content_object_id, principal_type, principal_id, permission)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX ux_cx_content_acl_subject_ref_permission
                ON cx_content_acl_entries (
                    content_object_id,
                    principal_ref_type,
                    principal_ref_id,
                    permission
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
                CREATE TABLE cx_document_summaries (
                    document_summary_id TEXT PRIMARY KEY,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    extraction_artifact_id TEXT NOT NULL REFERENCES cx_extraction_artifacts(extraction_artifact_id),
                    prompt_template_version_id TEXT,
                    summary_chunk_policy_id TEXT NOT NULL DEFAULT 'summary_1000_0',
                    summary_text_sha256 TEXT NOT NULL,
                    summary_storage_uri TEXT NOT NULL,
                    summary_char_count INTEGER NOT NULL,
                    summary_max_chars INTEGER NOT NULL DEFAULT 900,
                    summary_hard_limit_chars INTEGER NOT NULL DEFAULT 1000,
                    status TEXT NOT NULL DEFAULT 'READY',
                    language_code TEXT,
                    model_profile_id TEXT,
                    model_revision TEXT,
                    created_trace_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (summary_char_count <= summary_hard_limit_chars),
                    UNIQUE (content_object_id, extraction_artifact_id, summary_text_sha256)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_summary_embeddings (
                    summary_embedding_id TEXT PRIMARY KEY,
                    document_summary_id TEXT NOT NULL REFERENCES cx_document_summaries(document_summary_id),
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
                    UNIQUE (document_summary_id, model_profile_id, model_revision)
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
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_packages (
                    retrieval_package_id TEXT PRIMARY KEY,
                    retrieval_package_schema_version TEXT NOT NULL DEFAULT 'cx_retrieval_context_package.v1',
                    package_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    query_text_sha256 TEXT NOT NULL,
                    query_text_preview TEXT,
                    query_embedding_provided BOOLEAN NOT NULL DEFAULT 0,
                    query_embedding_sha256 TEXT,
                    query_embedding_dimension INTEGER NOT NULL DEFAULT 0,
                    purpose TEXT NOT NULL,
                    retrieval_policy_id TEXT NOT NULL,
                    retrieval_policy_version TEXT,
                    retrieval_policy_hash TEXT,
                    retrieval_policy_source TEXT NOT NULL,
                    ranker_mix TEXT NOT NULL,
                    rerank_state TEXT NOT NULL,
                    permission_snapshot_hash TEXT NOT NULL,
                    source_summary TEXT NOT NULL DEFAULT '{}',
                    score_summary TEXT NOT NULL DEFAULT '{}',
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    no_answer_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_retrieval_evidence_items (
                    retrieval_package_id TEXT NOT NULL REFERENCES cx_retrieval_packages(retrieval_package_id),
                    evidence_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    content_object_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    content_version_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL REFERENCES cx_chunks(chunk_id),
                    chunk_policy_id TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '{}',
                    citation_label TEXT NOT NULL,
                    evidence_text_sha256 TEXT NOT NULL,
                    evidence_text_preview TEXT NOT NULL,
                    final_score REAL NOT NULL DEFAULT 0,
                    scores TEXT NOT NULL DEFAULT '{}',
                    matched_terms TEXT NOT NULL DEFAULT '[]',
                    permission_result TEXT NOT NULL DEFAULT '{}',
                    neighbor_context TEXT NOT NULL DEFAULT '[]',
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (retrieval_package_id, evidence_id),
                    UNIQUE (retrieval_package_id, rank)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_runs (
                    pipeline_run_id TEXT PRIMARY KEY,
                    pipeline_schema_version TEXT NOT NULL DEFAULT 'cx_document_processing_pipeline.v1',
                    document_id TEXT NOT NULL REFERENCES cx_content_objects(content_object_id),
                    status TEXT NOT NULL,
                    trace_id TEXT,
                    request_id TEXT NOT NULL,
                    job_id TEXT,
                    job_type TEXT,
                    job_status TEXT,
                    job_attempt_count INTEGER NOT NULL DEFAULT 0,
                    job_max_attempts INTEGER NOT NULL DEFAULT 0,
                    job_retryable BOOLEAN,
                    job_subject_ref TEXT NOT NULL DEFAULT '{}',
                    job_links TEXT NOT NULL DEFAULT '{}',
                    step_total INTEGER NOT NULL DEFAULT 0,
                    step_succeeded INTEGER NOT NULL DEFAULT 0,
                    step_skipped INTEGER NOT NULL DEFAULT 0,
                    step_failed INTEGER NOT NULL DEFAULT 0,
                    queued_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE cx_document_processing_steps (
                    pipeline_run_id TEXT NOT NULL REFERENCES cx_document_processing_runs(pipeline_run_id),
                    step_order INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_ref_type TEXT,
                    output_ref_id TEXT,
                    output_ref_document_id TEXT REFERENCES cx_content_objects(content_object_id),
                    output_ref_hash TEXT,
                    error_code TEXT,
                    error_detail_sha256 TEXT,
                    error_retryable BOOLEAN,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (pipeline_run_id, step_order),
                    UNIQUE (pipeline_run_id, step_id)
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


def document_summary_payload(
    tmp_path: Path,
    document: dict[str, object],
    *,
    extraction: dict[str, object] | None = None,
    summary_text: str = "Bounded private summary text.",
) -> dict[str, object]:
    source_extraction = extraction or extraction_result(tmp_path, document)
    return build_document_summary_record(
        document_id=str(document["document_id"]),
        extraction=source_extraction,
        summary_text=summary_text,
        prompt_event=None,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        max_chars=900,
        hard_limit_chars=1000,
    )


def summary_embedding_payload(summary: dict[str, object]) -> dict[str, object]:
    return {
        "summary_embedding_schema_version": "cx_document_summary_embedding.v1",
        "document_id": summary["document_id"],
        "document_summary_id": summary["document_summary_id"],
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "provider_alias": "mock-embedding-default",
        "model_revision": "mock-embedding-v1",
        "deployment_id": "mock-embedding-local",
        "summary_text_sha256": summary["summary_text_sha256"],
        "embedding_sha256": "3" * 64,
        "vector_dimension": 3,
        "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
        "created_at": summary["created_at"],
        "updated_at": summary["updated_at"],
    }


def retrieval_package_payload(
    *,
    document_id: str,
    chunk: dict[str, object],
    query_text: str = "SECRET_RETRIEVAL_QUERY",
    evidence_text: str = "SECRET_RETRIEVAL_EVIDENCE_TEXT",
) -> dict[str, object]:
    return {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_package_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "package_hash": "4" * 64,
        "status": "READY",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "query_text": query_text,
        "query_embedding_snapshot": {
            "provided": True,
            "embedding_sha256": "5" * 64,
            "vector_dimension": 3,
        },
        "purpose": "grounded_answer",
        "retrieval_profile": {
            "quality_policy": {
                "policy_id": "weighted_rrf_vector_bm25_v1",
                "policy_version": "2026-08-09",
                "policy_hash": "6" * 64,
                "policy_source": "ag_registry_active",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
            }
        },
        "permission_snapshot": {
            "actor_type": "user",
            "actor_id": "user-a",
            "scope_applied": {"type": "document_ids", "document_ids": [document_id]},
        },
        "evidence_items": [
            {
                "evidence_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "rank": 1,
                "content_object_id": document_id,
                "content_version_id": chunk["text_sha256"],
                "chunk_id": chunk["chunk_id"],
                "chunk_policy_id": "chunk_1000_100",
                "source_anchor": {
                    "type": "character_range",
                    "start_offset": chunk["start_offset"],
                    "end_offset": chunk["end_offset"],
                },
                "citation_label": "[1]",
                "text": evidence_text,
                "neighbor_context": [],
                "scores": {
                    "bm25_score": 1.0,
                    "vector_score": 0.8,
                    "final_score": 0.9,
                },
                "matched_terms": ["retrieval"],
                "permission_result": {
                    "visible": True,
                    "reason": "local_mock_service_scope",
                },
                "quality_flags": [],
            }
        ],
        "source_summary": {
            "source_count": 1,
            "document_count": 1,
            "chunk_count": 1,
            "source_types": ["cx.document"],
        },
        "score_summary": {
            "best_score": 0.9,
            "score_spread": 0.0,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "rerank_state": "NOT_APPLIED",
        },
        "warnings": [],
        "no_answer_reason": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
    }


def processing_run_payload(
    *,
    document_id: str,
    pipeline_run_id: str = "99999999-9999-4999-8999-999999999999",
    status: str = "SUCCEEDED",
    updated_at: str = "2026-08-09T00:00:10Z",
) -> dict[str, Any]:
    completed_at = updated_at if status in {"SUCCEEDED", "FAILED", "CANCELLED"} else None
    steps: list[dict[str, Any]] = []
    if status == "SUCCEEDED":
        steps = [
            {
                "step_id": "summary",
                "status": "SUCCEEDED",
                "output_ref": {
                    "type": "cx.document_summary",
                    "id": "77777777-7777-4777-8777-777777777777",
                    "document_id": document_id,
                    "text": "SECRET_OUTPUT_REF_TEXT",
                },
                "error": None,
            }
        ]
    if status == "FAILED":
        steps = [
            {
                "step_id": "summary",
                "status": "FAILED",
                "output_ref": None,
                "error": {
                    "error_code": "cx.summary_failed",
                    "detail": "SECRET_PROCESSING_ERROR_DETAIL",
                    "retryable": False,
                },
            }
        ]
    return {
        "pipeline_schema_version": "cx_document_processing_pipeline.v1",
        "pipeline_run_id": pipeline_run_id,
        "document_id": document_id,
        "status": status,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "job": {
            "job_schema_version": "common_job.v1",
            "job_id": "job-processing-001",
            "job_type": "cx.document_processing",
            "status": status,
            "subject_ref": {"type": "cx.document", "id": document_id},
            "idempotency_key": f"cx.document_processing:{document_id}",
            "attempt_count": 1 if status != "QUEUED" else 0,
            "max_attempts": 3,
            "retryable": status != "SUCCEEDED",
            "links": {"processing": f"/api/v1/documents/{document_id}/processing"},
            "created_at": "2026-08-09T00:00:00Z",
            "updated_at": updated_at,
        },
        "steps": steps,
        "step_summary": {
            "total": len(steps),
            "succeeded": sum(1 for step in steps if step["status"] == "SUCCEEDED"),
            "skipped": 0,
            "failed": sum(1 for step in steps if step["status"] == "FAILED"),
        },
        "queued_at": "2026-08-09T00:00:00Z" if status == "QUEUED" else None,
        "started_at": None if status == "QUEUED" else "2026-08-09T00:00:01Z",
        "completed_at": completed_at,
        "updated_at": updated_at,
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
    assert record["ownership_ref"] == {
        "ownership_schema_version": (
            cx_repository.CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION
        ),
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": "user-a"},
        "uploaded_by_subject_ref": {"type": "oa.user", "id": "user-a"},
        "legacy": {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }


def test_build_content_object_record_allows_explicit_uploader_subject(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    source_file = build_source_file_record(upload)

    record = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="owner-a",
        uploaded_by_user_id="uploader-a",
        source_file_id=source_file["source_file_id"],
    )

    assert record["ownership_ref"]["owner_subject_ref"] == {
        "type": "oa.user",
        "id": "owner-a",
    }
    assert record["ownership_ref"]["uploaded_by_subject_ref"] == {
        "type": "oa.user",
        "id": "uploader-a",
    }


@pytest.mark.parametrize(
    ("kwargs", "field_name"),
    [
        ({"tenant_id": ""}, "tenant_id"),
        ({"owner_user_id": "   "}, "owner_user_id"),
    ],
)
def test_build_content_object_record_rejects_blank_owner_scope_aliases(
    tmp_path: Path,
    kwargs: dict[str, str],
    field_name: str,
) -> None:
    upload = upload_registration(tmp_path)
    source_file = build_source_file_record(upload)

    with pytest.raises(ValueError, match=f"{field_name} must be a non-empty string"):
        build_content_object_record(
            upload,
            source_file_id=source_file["source_file_id"],
            **kwargs,
        )


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


def test_build_document_summary_persistence_record_maps_metadata_without_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(
        tmp_path,
        upload,
        summary_text="SECRET_PRIVATE_SUMMARY_BODY",
    )
    summary["prompt_template_version_id"] = "11111111-1111-4111-8111-111111111111"

    record = build_document_summary_persistence_record(
        summary,
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )

    assert record["document_summary_id"] == summary["document_summary_id"]
    assert record["content_object_id"] == upload["document_id"]
    assert record["summary_text_sha256"] == summary["summary_text_sha256"]
    assert record["summary_storage_uri"] == summary["summary_storage_uri"]
    assert record["summary_char_count"] == summary["summary_char_count"]
    assert record["prompt_template_version_id"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert record["model_profile_id"] == "mock-document-summary"
    assert record["model_revision"] == "slice-0027"
    assert "SECRET_PRIVATE_SUMMARY_BODY" not in str(record)


def test_build_document_summary_persistence_record_tolerates_legacy_summarizer_shape(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(tmp_path, upload)
    summary["summarizer"] = "legacy-summary-profile"

    record = build_document_summary_persistence_record(
        summary,
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )

    assert record["model_profile_id"] is None
    assert record["model_revision"] is None


def test_build_summary_embedding_persistence_record_maps_hash_without_vector(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(tmp_path, upload)
    embedding = summary_embedding_payload(summary)
    embedding["embedding_storage_uri"] = "pgvector://cx/summary/embedding/001"
    embedding["status"] = "STALE"

    record = build_summary_embedding_persistence_record(
        embedding,
        document_summary_id=str(summary["document_summary_id"]),
    )

    assert record["document_summary_id"] == summary["document_summary_id"]
    assert record["model_profile_id"] == "mock-embedding-default"
    assert record["embedding_sha256"] == "3" * 64
    assert record["embedding_storage_uri"] == "pgvector://cx/summary/embedding/001"
    assert record["status"] == "STALE"
    assert "[0.0, 0.5, 1.0]" not in str(record)


def test_build_summary_embedding_persistence_record_uses_explicit_model_profile(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(tmp_path, upload)
    embedding = summary_embedding_payload(summary)
    embedding["model_profile_id"] = "summary-embedding-profile"

    record = build_summary_embedding_persistence_record(
        embedding,
        document_summary_id=str(summary["document_summary_id"]),
    )

    assert record["model_profile_id"] == "summary-embedding-profile"
    assert record["status"] == "READY"


def test_build_retrieval_package_persistence_record_maps_hashes_without_raw_text(
    tmp_path: Path,
) -> None:
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    query_text = "SECRET_RETRIEVAL_QUERY_" + ("x" * 400)
    evidence_text = "SECRET_RETRIEVAL_EVIDENCE_TEXT_" + ("y" * 400)
    package = retrieval_package_payload(
        document_id=str(upload["document_id"]),
        chunk=chunk_set["chunks"][0],
        query_text=query_text,
        evidence_text=evidence_text,
    )

    record = build_retrieval_package_persistence_record(package)

    assert record["retrieval_package_schema_version"] == (
        "cx_retrieval_package.persistence.v1"
    )
    assert record["retrieval_package_id"] == package["retrieval_package_id"]
    assert record["query_text_sha256"] == sha256_text(query_text)
    assert record["query_embedding_provided"] is True
    assert record["query_embedding_dimension"] == 3
    assert record["retrieval_policy_id"] == "weighted_rrf_vector_bm25_v1"
    assert record["ranker_mix"] == "weighted_rrf_vector_bm25_v1"
    assert record["rerank_state"] == "NOT_APPLIED"
    assert record["evidence_count"] == 1
    assert record["evidence_items"][0]["evidence_text_sha256"] == sha256_text(
        evidence_text
    )
    assert record["evidence_items"][0]["final_score"] == 0.9
    assert query_text not in str(record)
    assert evidence_text not in str(record)


def test_build_processing_run_persistence_record_maps_safe_metadata() -> None:
    run = processing_run_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        status="FAILED",
    )

    record = build_processing_run_persistence_record(run)

    assert record["processing_run_schema_version"] == (
        "cx_document_processing_run.persistence.v1"
    )
    assert record["pipeline_run_id"] == run["pipeline_run_id"]
    assert record["document_id"] == run["document_id"]
    assert record["job_id"] == "job-processing-001"
    assert record["job_status"] == "FAILED"
    assert record["job_subject_ref"] == {
        "type": "cx.document",
        "id": "44444444-4444-4444-8444-444444444444",
    }
    assert record["step_failed"] == 1
    assert record["steps"][0]["processing_step_schema_version"] == (
        "cx_document_processing_step.persistence.v1"
    )
    assert record["steps"][0]["error_code"] == "cx.summary_failed"
    assert record["steps"][0]["error_detail_sha256"] == sha256_text(
        "SECRET_PROCESSING_ERROR_DETAIL"
    )
    assert "SECRET_PROCESSING_ERROR_DETAIL" not in str(record)
    assert "SECRET_OUTPUT_REF_TEXT" not in str(record)


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


def test_in_memory_repository_lists_active_content_objects_by_owner_scope(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    user_a_first = upload_registration(
        tmp_path,
        content_text="first",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    user_a_second = upload_registration(
        tmp_path,
        content_text="second",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb22",
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    user_b = upload_registration(
        tmp_path,
        content_text="third",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb23",
        tenant_id="tenant-a",
        owner_user_id="user-b",
    )
    tenant_b = upload_registration(
        tmp_path,
        content_text="fourth",
        request_id="0189f0ff-8f22-4f72-9b47-b481dc21bb24",
        tenant_id="tenant-b",
        owner_user_id="user-a",
    )
    for upload in (user_a_first, user_a_second, user_b, tenant_b):
        source_file = repository.save_source_file(build_source_file_record(upload))
        repository.save_content_object(
            build_content_object_record(
                upload,
                tenant_id=str(upload["ownership"]["tenant_id"]),
                owner_user_id=str(upload["ownership"]["owner_user_id"]),
                source_file_id=source_file["source_file_id"],
            )
        )
    inactive = {
        **repository.get_content_object(str(user_a_first["document_id"])),
        "content_object_id": "22222222-2222-4222-8222-222222222222",
        "upload_id": "33333333-3333-4333-8333-333333333333",
        "lifecycle_status": "ARCHIVED",
    }
    repository.save_content_object(inactive)

    records = repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        limit=10,
    )

    assert [record["content_object_id"] for record in records] == [
        user_a_second["document_id"],
        user_a_first["document_id"],
    ]
    assert repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        limit=1,
    ) == [records[0]]
    assert repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-b",
    )[0]["content_object_id"] == user_b["document_id"]
    assert repository.list_active_content_objects(
        tenant_id="tenant-b",
        owner_user_id="user-a",
    )[0]["content_object_id"] == tenant_b["document_id"]
    assert bounded_content_object_query_limit(None) == 50
    assert bounded_content_object_query_limit(0) == 1
    assert bounded_content_object_query_limit(500) == 100
    with pytest.raises(ValueError, match="query limit must be an integer"):
        bounded_content_object_query_limit("wide")


def test_in_memory_repository_normalizes_legacy_content_owner_fields(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    record = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id="source-file-a",
    )
    legacy_record = dict(record)
    legacy_record.pop("ownership_ref")

    saved = repository.save_content_object(legacy_record)

    assert "ownership_ref" not in legacy_record
    assert saved["ownership_ref"]["tenant_ref"] == {
        "type": "oa.tenant",
        "id": "tenant-a",
    }
    assert saved["ownership_ref"]["owner_subject_ref"] == {
        "type": "oa.user",
        "id": "user-a",
    }
    assert repository.find_active_content_object(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_sha256=upload["source_sha256"],
    ) == saved


def test_in_memory_repository_rejects_invalid_owner_subject_ref_type(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    record = build_content_object_record(
        upload,
        source_file_id="source-file-a",
    )
    record["ownership_ref"]["owner_subject_ref"]["type"] = "cx.local_user"

    with pytest.raises(ValueError, match="owner_subject_ref.type must be oa.user"):
        repository.save_content_object(record)


@pytest.mark.parametrize(
    ("ref_name", "bad_type", "expected_field"),
    [
        ("tenant_ref", "cx.tenant", "tenant_ref.type"),
        ("uploaded_by_subject_ref", "cx.local_user", "uploaded_by_subject_ref.type"),
    ],
)
def test_in_memory_repository_rejects_invalid_content_ownership_ref_types(
    tmp_path: Path,
    ref_name: str,
    bad_type: str,
    expected_field: str,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    record = build_content_object_record(
        upload,
        source_file_id="source-file-a",
    )
    record["ownership_ref"][ref_name]["type"] = bad_type

    with pytest.raises(ValueError, match=f"{expected_field} must be"):
        repository.save_content_object(record)


def test_in_memory_repository_treats_incomplete_ownership_ref_as_legacy_alias(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    record = build_content_object_record(
        upload,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        source_file_id="source-file-a",
    )
    record["ownership_ref"] = {
        "tenant_ref": "legacy-string-ref",
        "owner_subject_ref": None,
    }

    saved = repository.save_content_object(record)

    assert saved["ownership_ref"]["tenant_ref"] == {
        "type": "oa.tenant",
        "id": "tenant-a",
    }
    assert saved["ownership_ref"]["owner_subject_ref"] == {
        "type": "oa.user",
        "id": "user-a",
    }


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


def test_in_memory_repository_saves_document_summaries_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    record = build_document_summary_persistence_record(
        document_summary_payload(tmp_path, upload),
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )
    duplicate = {
        **record,
        "document_summary_id": "99999999-9999-4999-8999-999999999999",
    }

    assert repository.save_document_summary_record(record) == record
    assert repository.save_document_summary_record(duplicate) == record
    assert repository.get_document_summary_record(record["document_summary_id"]) == record
    assert repository.find_document_summary_record(
        content_object_id=record["content_object_id"],
        extraction_artifact_id=record["extraction_artifact_id"],
        summary_text_sha256=record["summary_text_sha256"],
    ) == record
    assert repository.get_document_summary_record("missing") is None
    assert repository.find_document_summary_record(
        content_object_id=record["content_object_id"],
        extraction_artifact_id=record["extraction_artifact_id"],
        summary_text_sha256="0" * 64,
    ) is None


def test_in_memory_repository_returns_latest_document_summary(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    older = build_document_summary_persistence_record(
        document_summary_payload(tmp_path, upload, summary_text="older"),
        content_object_id=str(upload["document_id"]),
        extraction_artifact_id="55555555-5555-4555-8555-555555555555",
    )
    newer = {
        **older,
        "document_summary_id": "99999999-9999-4999-8999-999999999999",
        "extraction_artifact_id": "66666666-6666-4666-8666-666666666666",
        "summary_text_sha256": "9" * 64,
        "updated_at": "2099-01-01T00:00:00Z",
    }

    repository.save_document_summary_record(older)
    repository.save_document_summary_record(newer)

    assert repository.get_latest_document_summary_record(
        str(upload["document_id"])
    ) == newer
    assert repository.get_latest_document_summary_record("missing") is None


def test_in_memory_repository_saves_summary_embeddings_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(tmp_path, upload)
    record = build_summary_embedding_persistence_record(
        summary_embedding_payload(summary),
        document_summary_id=str(summary["document_summary_id"]),
    )
    duplicate = {
        **record,
        "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }

    assert repository.save_summary_embedding_record(record) == record
    assert repository.save_summary_embedding_record(duplicate) == record
    assert repository.get_summary_embedding_record(record["summary_embedding_id"]) == record
    assert repository.find_summary_embedding_record(
        document_summary_id=record["document_summary_id"],
        model_profile_id=record["model_profile_id"],
        model_revision=record["model_revision"],
    ) == record
    assert repository.get_summary_embedding_record("missing") is None
    assert repository.find_summary_embedding_record(
        document_summary_id=record["document_summary_id"],
        model_profile_id="other",
        model_revision=record["model_revision"],
    ) is None


def test_in_memory_repository_returns_latest_summary_embedding(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    summary = document_summary_payload(tmp_path, upload)
    older = build_summary_embedding_persistence_record(
        summary_embedding_payload(summary),
        document_summary_id=str(summary["document_summary_id"]),
    )
    newer = {
        **older,
        "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "model_profile_id": "explicit-latest-profile",
        "created_at": "2099-01-01T00:00:00Z",
    }

    repository.save_summary_embedding_record(older)
    repository.save_summary_embedding_record(newer)

    assert repository.get_latest_summary_embedding_record(
        str(summary["document_summary_id"])
    ) == newer
    assert repository.get_latest_summary_embedding_record("missing") is None


def test_in_memory_repository_saves_retrieval_packages_idempotently(
    tmp_path: Path,
) -> None:
    repository = InMemoryCxContentRepository()
    upload = upload_registration(tmp_path)
    chunk_set = chunk_set_payload(tmp_path, upload)
    record = build_retrieval_package_persistence_record(
        retrieval_package_payload(
            document_id=str(upload["document_id"]),
            chunk=chunk_set["chunks"][0],
        )
    )
    duplicate = {
        **record,
        "retrieval_package_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbc",
    }

    assert repository.save_retrieval_package_record(record) == record
    assert repository.save_retrieval_package_record(duplicate) == record
    assert repository.get_retrieval_package_record(record["retrieval_package_id"]) == record
    assert (
        repository.find_retrieval_package_record_by_hash(record["package_hash"])
        == record
    )
    assert repository.get_retrieval_package_record("missing") is None
    assert repository.find_retrieval_package_record_by_hash("0" * 64) is None


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


def test_in_memory_repository_saves_processing_run_record() -> None:
    repository = InMemoryCxContentRepository()
    record = build_processing_run_persistence_record(
        processing_run_payload(
            document_id="44444444-4444-4444-8444-444444444444",
            status="SUCCEEDED",
        )
    )

    saved = repository.save_processing_run_record(record)

    assert saved == record
    assert repository.get_processing_run_record(record["pipeline_run_id"]) == record
    assert repository.get_latest_processing_run_record(record["document_id"]) == record
    assert repository.get_processing_run_record("missing") is None
    assert repository.get_latest_processing_run_record("missing") is None


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
        content_row = connection.execute(
            text(
                """
                SELECT
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id,
                    uploaded_by_subject_ref_type,
                    uploaded_by_subject_ref_id
                FROM cx_content_objects
                WHERE content_object_id = :content_object_id
                """
            ),
            {"content_object_id": saved["content_object_id"]},
        ).mappings().one()
        acl_row = connection.execute(
            text(
                """
                SELECT
                    principal_ref_type,
                    principal_ref_id,
                    granted_by_subject_ref_type,
                    granted_by_subject_ref_id
                FROM cx_content_acl_entries
                WHERE content_object_id = :content_object_id
                  AND permission = 'owner'
                """
            ),
            {"content_object_id": saved["content_object_id"]},
        ).mappings().one()
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
    assert dict(content_row) == {
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "tenant-a",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "user-a",
        "uploaded_by_subject_ref_type": "oa.user",
        "uploaded_by_subject_ref_id": "user-a",
    }
    assert dict(acl_row) == {
        "principal_ref_type": "oa.user",
        "principal_ref_id": "user-a",
        "granted_by_subject_ref_type": "oa.user",
        "granted_by_subject_ref_id": "user-a",
    }
    assert acl_count == 1


def test_sqlalchemy_repository_lists_active_content_objects_by_owner_scope(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)
    specs = [
        ("tenant-a", "user-a", "first", "2026-08-10T00:00:00Z"),
        ("tenant-a", "user-a", "second", "2026-08-10T00:00:02Z"),
        ("tenant-a", "user-b", "third", "2026-08-10T00:00:03Z"),
    ]
    content_by_text: dict[str, dict[str, Any]] = {}
    for index, (tenant_id, owner_user_id, text_value, created_at) in enumerate(specs):
        upload = upload_registration(
            tmp_path,
            content_text=text_value,
            request_id=f"0189f0ff-8f22-4f72-9b47-b481dc21bb3{index}",
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        source_file = repository.save_source_file(build_source_file_record(upload))
        content = build_content_object_record(
            upload,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            source_file_id=source_file["source_file_id"],
        )
        content["created_at"] = created_at
        content["updated_at"] = created_at
        content_by_text[text_value] = repository.save_content_object(content)
    inactive = {
        **content_by_text["first"],
        "content_object_id": "22222222-2222-4222-8222-222222222222",
        "upload_id": "33333333-3333-4333-8333-333333333333",
        "source_sha256": "4" * 64,
        "lifecycle_status": "ARCHIVED",
    }
    repository.save_content_object(inactive)

    records = repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        limit=10,
    )

    assert [record["content_object_id"] for record in records] == [
        content_by_text["second"]["content_object_id"],
        content_by_text["first"]["content_object_id"],
    ]
    assert repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        limit=1,
    ) == [records[0]]
    assert repository.list_active_content_objects(
        tenant_id="tenant-a",
        owner_user_id="user-b",
    )[0]["content_object_id"] == content_by_text["third"]["content_object_id"]


def test_sqlalchemy_repository_dedupes_by_canonical_owner_refs(
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
    legacy_alias_drift = {
        **first,
        "content_object_id": "22222222-2222-4222-8222-222222222222",
        "tenant_id": "legacy-tenant-alias",
        "owner_user_id": "legacy-owner-alias",
        "upload_id": "33333333-3333-4333-8333-333333333333",
        "ownership_ref": first["ownership_ref"],
    }

    assert repository.save_content_object(first) == first
    assert repository.save_content_object(legacy_alias_drift) == first
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM cx_content_objects"))
            .scalar_one()
        ) == 1


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


def test_sqlalchemy_repository_saves_and_finds_document_summary_metadata(
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
    extraction = extraction_result(tmp_path, upload)
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction,
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    record = build_document_summary_persistence_record(
        document_summary_payload(
            tmp_path,
            upload,
            extraction=extraction,
            summary_text="SECRET_SQL_SUMMARY_TEXT",
        ),
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
    )
    record["prompt_template_version_id"] = "11111111-1111-4111-8111-111111111111"
    duplicate = {
        **record,
        "document_summary_id": "99999999-9999-4999-8999-999999999999",
    }

    saved = repository.save_document_summary_record(record)

    assert saved == record
    assert repository.save_document_summary_record(duplicate) == record
    assert repository.get_document_summary_record(saved["document_summary_id"]) == record
    assert repository.get_document_summary_record(
        "99999999-9999-4999-8999-999999999998"
    ) is None
    assert repository.find_document_summary_record(
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        summary_text_sha256=record["summary_text_sha256"],
    ) == record
    assert repository.find_document_summary_record(
        content_object_id=content["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        summary_text_sha256="0" * 64,
    ) is None
    assert _sqlite_table_count(engine, "cx_document_summaries") == 1
    assert "SECRET_SQL_SUMMARY_TEXT" not in _sqlite_table_dump(
        engine,
        ["cx_document_summaries"],
    )


def test_sqlalchemy_repository_returns_latest_document_summary_metadata(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)
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
    older_extraction = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload, markdown_text="older markdown"),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    newer_extraction = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction_result(tmp_path, upload, markdown_text="newer markdown"),
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    older = repository.save_document_summary_record(
        build_document_summary_persistence_record(
            document_summary_payload(
                tmp_path,
                upload,
                extraction=extraction_result(
                    tmp_path,
                    upload,
                    markdown_text="older markdown",
                ),
                summary_text="older",
            ),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=older_extraction["extraction_artifact_id"],
        )
    )
    newer = build_document_summary_persistence_record(
        document_summary_payload(
            tmp_path,
            upload,
            extraction=extraction_result(tmp_path, upload, markdown_text="newer markdown"),
            summary_text="newer",
        ),
        content_object_id=content["content_object_id"],
        extraction_artifact_id=newer_extraction["extraction_artifact_id"],
    )
    newer["updated_at"] = "2099-01-01T00:00:00Z"
    saved_newer = repository.save_document_summary_record(newer)

    assert repository.get_latest_document_summary_record(
        content["content_object_id"]
    ) == saved_newer
    assert repository.get_latest_document_summary_record("missing") is None
    assert older["document_summary_id"] != saved_newer["document_summary_id"]


def test_sqlalchemy_repository_saves_and_finds_summary_embedding_metadata(
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
    extraction = extraction_result(tmp_path, upload)
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction,
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    summary = repository.save_document_summary_record(
        build_document_summary_persistence_record(
            document_summary_payload(tmp_path, upload, extraction=extraction),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    record = build_summary_embedding_persistence_record(
        summary_embedding_payload(
            {
                **document_summary_payload(tmp_path, upload, extraction=extraction),
                "document_summary_id": summary["document_summary_id"],
            }
        ),
        document_summary_id=summary["document_summary_id"],
    )
    duplicate = {
        **record,
        "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }

    saved = repository.save_summary_embedding_record(record)

    assert saved == record
    assert repository.save_summary_embedding_record(duplicate) == record
    assert repository.get_summary_embedding_record(saved["summary_embedding_id"]) == record
    assert repository.get_summary_embedding_record(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab"
    ) is None
    assert repository.find_summary_embedding_record(
        document_summary_id=summary["document_summary_id"],
        model_profile_id=record["model_profile_id"],
        model_revision=record["model_revision"],
    ) == record
    assert repository.find_summary_embedding_record(
        document_summary_id=summary["document_summary_id"],
        model_profile_id="other",
        model_revision=record["model_revision"],
    ) is None
    assert _sqlite_table_count(engine, "cx_document_summary_embeddings") == 1
    assert "[0.0, 0.5, 1.0]" not in _sqlite_table_dump(
        engine,
        ["cx_document_summary_embeddings"],
    )


def test_sqlalchemy_repository_returns_latest_summary_embedding_metadata(
    tmp_path: Path,
) -> None:
    repository, _ = sqlite_content_repository(tmp_path)
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
    extraction = extraction_result(tmp_path, upload)
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction,
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    summary = repository.save_document_summary_record(
        build_document_summary_persistence_record(
            document_summary_payload(tmp_path, upload, extraction=extraction),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    older = repository.save_summary_embedding_record(
        build_summary_embedding_persistence_record(
            summary_embedding_payload(
                {
                    **document_summary_payload(tmp_path, upload, extraction=extraction),
                    "document_summary_id": summary["document_summary_id"],
                }
            ),
            document_summary_id=summary["document_summary_id"],
        )
    )
    newer = {
        **older,
        "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "model_profile_id": "explicit-latest-profile",
        "model_revision": "mock-embedding-v2",
        "created_at": "2099-01-01T00:00:00Z",
    }
    saved_newer = repository.save_summary_embedding_record(newer)

    assert repository.get_latest_summary_embedding_record(
        summary["document_summary_id"]
    ) == saved_newer
    assert repository.get_latest_summary_embedding_record("missing") is None
    assert older["summary_embedding_id"] != saved_newer["summary_embedding_id"]


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
        lambda repository: repository.save_document_summary_record(
            {
                "document_summary_schema_version": "cx_document_summary.persistence.v1",
                "document_summary_id": "99999999-9999-4999-8999-999999999999",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "prompt_template_version_id": None,
                "summary_chunk_policy_id": "summary_1000_0",
                "summary_text_sha256": "2" * 64,
                "summary_storage_uri": (
                    "memory://cx/document-summaries/"
                    "99999999-9999-4999-8999-999999999999.md"
                ),
                "summary_char_count": 10,
                "summary_max_chars": 900,
                "summary_hard_limit_chars": 1000,
                "status": "READY",
                "language_code": None,
                "model_profile_id": "mock-document-summary",
                "model_revision": "slice-0027",
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
            }
        ),
        lambda repository: repository.get_document_summary_record(
            "99999999-9999-4999-8999-999999999999"
        ),
        lambda repository: repository.find_document_summary_record(
            content_object_id="44444444-4444-4444-8444-444444444444",
            extraction_artifact_id="55555555-5555-4555-8555-555555555555",
            summary_text_sha256="2" * 64,
        ),
        lambda repository: repository.save_summary_embedding_record(
            {
                "summary_embedding_schema_version": (
                    "cx_document_summary_embedding.persistence.v1"
                ),
                "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "document_summary_id": "99999999-9999-4999-8999-999999999999",
                "provider_alias": "mock-embedding-default",
                "model_profile_id": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "vector_dimension": 3,
                "embedding_sha256": "3" * 64,
                "embedding_storage_uri": None,
                "status": "READY",
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
            }
        ),
        lambda repository: repository.get_summary_embedding_record(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ),
        lambda repository: repository.find_summary_embedding_record(
            document_summary_id="99999999-9999-4999-8999-999999999999",
            model_profile_id="mock-embedding-default",
            model_revision="mock-embedding-v1",
        ),
        lambda repository: repository.save_retrieval_package_record(
            {
                "retrieval_package_schema_version": "cx_retrieval_package.persistence.v1",
                "retrieval_package_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "package_hash": "7" * 64,
                "status": "NO_ANSWER",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "query_text_sha256": "8" * 64,
                "query_text_preview": "private query preview",
                "query_embedding_provided": False,
                "query_embedding_sha256": None,
                "query_embedding_dimension": 0,
                "purpose": "grounded_answer",
                "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
                "retrieval_policy_version": "2026-08-09",
                "retrieval_policy_hash": "9" * 64,
                "retrieval_policy_source": "ag_registry_active",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "NOT_APPLIED",
                "permission_snapshot_hash": "a" * 64,
                "source_summary": {},
                "score_summary": {},
                "warning_count": 0,
                "evidence_count": 0,
                "no_answer_reason": "no_terms_matched",
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
                "evidence_items": [],
            }
        ),
        lambda repository: repository.get_retrieval_package_record(
            "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        ),
        lambda repository: repository.find_retrieval_package_record_by_hash("7" * 64),
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

    class RaceyDocumentSummaryRepository(SqlAlchemyCxContentRepository):
        def _save_document_summary_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert document summary", {}, Exception("race"))

    class RaceySummaryEmbeddingRepository(SqlAlchemyCxContentRepository):
        def _save_summary_embedding_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert summary embedding", {}, Exception("race"))

    class RaceyRetrievalPackageRepository(SqlAlchemyCxContentRepository):
        def _save_retrieval_package_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert retrieval package", {}, Exception("race"))

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
    racey_document_summary = RaceyDocumentSummaryRepository(build_session_factory(engine))
    racey_summary_embedding = RaceySummaryEmbeddingRepository(build_session_factory(engine))
    racey_retrieval_package = RaceyRetrievalPackageRepository(
        build_session_factory(engine)
    )
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
    summary = repository.save_document_summary_record(
        build_document_summary_persistence_record(
            document_summary_payload(tmp_path, upload),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    summary_embedding = repository.save_summary_embedding_record(
        build_summary_embedding_persistence_record(
            summary_embedding_payload(
                {
                    **document_summary_payload(tmp_path, upload),
                    "document_summary_id": summary["document_summary_id"],
                }
            ),
            document_summary_id=summary["document_summary_id"],
        )
    )
    retrieval_package = repository.save_retrieval_package_record(
        build_retrieval_package_persistence_record(
            retrieval_package_payload(
                document_id=content["content_object_id"],
                chunk=chunk_set["chunks"][0],
            )
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
    assert racey_document_summary.save_document_summary_record(summary) == summary
    assert (
        racey_summary_embedding.save_summary_embedding_record(summary_embedding)
        == summary_embedding
    )
    assert (
        racey_retrieval_package.save_retrieval_package_record(retrieval_package)
        == retrieval_package
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


def test_sqlalchemy_repository_document_summary_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyDocumentSummaryRepository(SqlAlchemyCxContentRepository):
        def _save_document_summary_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert document summary", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyDocumentSummaryRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_document_summary_record(
            {
                "document_summary_schema_version": "cx_document_summary.persistence.v1",
                "document_summary_id": "99999999-9999-4999-8999-999999999999",
                "content_object_id": "44444444-4444-4444-8444-444444444444",
                "extraction_artifact_id": "55555555-5555-4555-8555-555555555555",
                "prompt_template_version_id": None,
                "summary_chunk_policy_id": "summary_1000_0",
                "summary_text_sha256": "2" * 64,
                "summary_storage_uri": (
                    "memory://cx/document-summaries/"
                    "99999999-9999-4999-8999-999999999999.md"
                ),
                "summary_char_count": 10,
                "summary_max_chars": 900,
                "summary_hard_limit_chars": 1000,
                "status": "READY",
                "language_code": None,
                "model_profile_id": "mock-document-summary",
                "model_revision": "slice-0027",
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_summary_embedding_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceySummaryEmbeddingRepository(SqlAlchemyCxContentRepository):
        def _save_summary_embedding_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert summary embedding", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceySummaryEmbeddingRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_summary_embedding_record(
            {
                "summary_embedding_schema_version": (
                    "cx_document_summary_embedding.persistence.v1"
                ),
                "summary_embedding_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "document_summary_id": "99999999-9999-4999-8999-999999999999",
                "provider_alias": "mock-embedding-default",
                "model_profile_id": "mock-embedding-default",
                "model_revision": "mock-embedding-v1",
                "deployment_id": "mock-embedding-local",
                "vector_dimension": 3,
                "embedding_sha256": "3" * 64,
                "embedding_storage_uri": None,
                "status": "READY",
                "created_trace_id": TRACE_ID,
                "created_at": "2026-08-09T00:00:00Z",
            }
        )

    assert exc_info.value.error_code == "cx_content.repository_unavailable"


def test_sqlalchemy_repository_retrieval_package_integrity_without_existing_row_wraps(
    tmp_path: Path,
) -> None:
    class RaceyRetrievalPackageRepository(SqlAlchemyCxContentRepository):
        def _save_retrieval_package_record(
            self,
            session: Any,
            record: dict[str, Any],
        ) -> dict[str, Any]:
            raise IntegrityError("insert retrieval package", {}, Exception("race"))

    _, engine = sqlite_content_repository(tmp_path)
    repository = RaceyRetrievalPackageRepository(build_session_factory(engine))

    with pytest.raises(CxContentRepositoryError) as exc_info:
        repository.save_retrieval_package_record(
            {
                "retrieval_package_schema_version": "cx_retrieval_package.persistence.v1",
                "retrieval_package_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "package_hash": "7" * 64,
                "status": "NO_ANSWER",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "query_text_sha256": "8" * 64,
                "query_text_preview": "private query preview",
                "query_embedding_provided": False,
                "query_embedding_sha256": None,
                "query_embedding_dimension": 0,
                "purpose": "grounded_answer",
                "retrieval_policy_id": "weighted_rrf_vector_bm25_v1",
                "retrieval_policy_version": "2026-08-09",
                "retrieval_policy_hash": "9" * 64,
                "retrieval_policy_source": "ag_registry_active",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "NOT_APPLIED",
                "permission_snapshot_hash": "a" * 64,
                "source_summary": {},
                "score_summary": {},
                "warning_count": 0,
                "evidence_count": 0,
                "no_answer_reason": "no_terms_matched",
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
                "evidence_items": [],
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


def test_content_ingestion_store_with_sqlalchemy_repository_persists_document_summary(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "SECRET_SUMMARY_SOURCE"
    summary_text = "SECRET_PRIVATE_DOCUMENT_SUMMARY"
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
    summary = document_summary_payload(
        tmp_path,
        document,
        extraction=result,
        summary_text=summary_text,
    )

    saved = store.save_document_summary(summary, summary_text=summary_text)

    refs = store.get_content_ref(str(document["document_id"]))
    assert refs is not None
    artifact = repository.find_extraction_artifact(
        content_object_id=refs["content_object_id"],
        extractor_name=result["extractor"]["provider"],
        extractor_version=result["extractor"]["version"],
        markdown_sha256=result["extracted_markdown_sha256"],
    )
    assert artifact is not None
    persisted = repository.find_document_summary_record(
        content_object_id=refs["content_object_id"],
        extraction_artifact_id=artifact["extraction_artifact_id"],
        summary_text_sha256=saved["summary_text_sha256"],
    )
    assert persisted is not None
    assert persisted["document_summary_id"] == saved["document_summary_id"]
    assert persisted["summary_char_count"] == len(summary_text)
    assert persisted["model_profile_id"] == "mock-document-summary"
    assert store.get_summary_text(saved["document_summary_id"]) == summary_text
    assert _sqlite_table_count(engine, "cx_document_summaries") == 1
    assert summary_text not in _sqlite_table_dump(engine, ["cx_document_summaries"])


def test_content_ingestion_store_with_sqlalchemy_repository_persists_summary_embedding(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "SECRET_SUMMARY_EMBEDDING_SOURCE"
    summary_text = "SECRET_SUMMARY_EMBEDDING_TEXT"
    vector = [0.0, 0.5, 1.0]
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
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    summary = store.save_document_summary(
        document_summary_payload(
            tmp_path,
            document,
            extraction=extraction,
            summary_text=summary_text,
        ),
        summary_text=summary_text,
    )
    embedding = summary_embedding_payload(summary)

    saved = store.save_summary_embedding_index(embedding, embedding_vector=vector)

    persisted = repository.find_summary_embedding_record(
        document_summary_id=summary["document_summary_id"],
        model_profile_id=saved["provider_alias"],
        model_revision=saved["model_revision"],
    )
    assert persisted is not None
    assert persisted["embedding_sha256"] == saved["embedding_sha256"]
    assert persisted["vector_dimension"] == len(vector)
    assert store.get_summary_embedding_vector(summary["document_summary_id"]) == vector
    assert _sqlite_table_count(engine, "cx_document_summary_embeddings") == 1
    assert str(vector) not in _sqlite_table_dump(
        engine,
        ["cx_document_summary_embeddings"],
    )


def test_sqlalchemy_repository_saves_and_finds_retrieval_package_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    source_text = "retrieval body SECRET_RETRIEVAL_SOURCE"
    upload = upload_registration(tmp_path, content_text=source_text)
    source_file = repository.save_source_file(build_source_file_record(upload))
    content = repository.save_content_object(
        build_content_object_record(upload, source_file_id=source_file["source_file_id"])
    )
    extraction = extraction_result(tmp_path, upload, markdown_text=source_text)
    artifact = repository.save_extraction_artifact(
        build_extraction_artifact_record(
            extraction,
            content_object_id=content["content_object_id"],
            source_file_id=source_file["source_file_id"],
        )
    )
    chunk_set = repository.save_chunk_set(
        build_chunk_set_record(
            chunk_set_payload(tmp_path, upload, markdown_text=source_text),
            content_object_id=content["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
        )
    )
    query_text = "SECRET_SQL_RETRIEVAL_QUERY_" + ("x" * 400)
    evidence_text = "SECRET_SQL_RETRIEVAL_EVIDENCE_" + ("y" * 400)
    record = build_retrieval_package_persistence_record(
        retrieval_package_payload(
            document_id=content["content_object_id"],
            chunk=chunk_set["chunks"][0],
            query_text=query_text,
            evidence_text=evidence_text,
        )
    )
    duplicate = {
        **record,
        "retrieval_package_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbc",
    }

    saved = repository.save_retrieval_package_record(record)

    assert saved == record
    assert repository.save_retrieval_package_record(duplicate) == record
    assert (
        repository.get_retrieval_package_record(record["retrieval_package_id"])
        == record
    )
    assert (
        repository.find_retrieval_package_record_by_hash(record["package_hash"])
        == record
    )
    assert repository.get_retrieval_package_record(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbd"
    ) is None
    assert repository.find_retrieval_package_record_by_hash("0" * 64) is None
    assert _sqlite_table_count(engine, "cx_retrieval_packages") == 1
    assert _sqlite_table_count(engine, "cx_retrieval_evidence_items") == 1
    dump = _sqlite_table_dump(
        engine,
        ["cx_retrieval_packages", "cx_retrieval_evidence_items"],
    )
    assert query_text not in dump
    assert evidence_text not in dump
    assert "SECRET_RETRIEVAL_SOURCE" not in dump


def test_sqlalchemy_repository_saves_no_answer_retrieval_package_without_evidence(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    package = retrieval_package_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        chunk={
            "chunk_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "text_sha256": "1" * 64,
            "start_offset": 0,
            "end_offset": 0,
        },
        query_text="SECRET_NO_ANSWER_QUERY_" + ("x" * 400),
        evidence_text="unused",
    )
    package.update(
        {
            "retrieval_package_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "package_hash": "7" * 64,
            "status": "NO_ANSWER",
            "query_embedding_snapshot": {
                "provided": False,
                "embedding_sha256": None,
                "vector_dimension": 0,
            },
            "evidence_items": [],
            "score_summary": {
                "best_score": 0.0,
                "score_spread": 0.0,
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "NOT_APPLIED",
            },
            "no_answer_reason": "no_terms_matched",
        }
    )
    record = build_retrieval_package_persistence_record(package)

    saved = repository.save_retrieval_package_record(record)

    assert saved == record
    assert saved["query_embedding_provided"] is False
    assert saved["query_embedding_sha256"] is None
    assert saved["query_embedding_dimension"] == 0
    assert saved["evidence_items"] == []
    assert saved["evidence_count"] == 0
    assert _sqlite_table_count(engine, "cx_retrieval_packages") == 1
    assert _sqlite_table_count(engine, "cx_retrieval_evidence_items") == 0
    assert package["query_text"] not in _sqlite_table_dump(
        engine,
        ["cx_retrieval_packages"],
    )


def test_content_ingestion_store_with_sqlalchemy_repository_persists_retrieval_package(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "retrieval body " + ("SOURCE_PRIVATE_" * 30)
    document = upload_registration(tmp_path, content_text=source_text)
    store.save_upload_registration(document, source_text=source_text)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    chunk_set = store_chunk_set(
        document_id=str(document["document_id"]),
        extraction=extraction,
        markdown_text=Path(extraction["extracted_markdown_path"]).read_text(
            encoding="utf-8"
        ),
        store=store,
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    query_text = "SECRET_STORE_RETRIEVAL_QUERY_" + ("x" * 400)
    evidence_text = "SECRET_STORE_RETRIEVAL_EVIDENCE_" + ("y" * 400)
    package = retrieval_package_payload(
        document_id=str(document["document_id"]),
        chunk=chunk_set["chunks"][0],
        query_text=query_text,
        evidence_text=evidence_text,
    )

    saved = store.save_retrieval_package(package)

    persisted = repository.find_retrieval_package_record_by_hash(package["package_hash"])
    assert saved == package
    assert persisted is not None
    assert persisted["retrieval_package_id"] == package["retrieval_package_id"]
    assert persisted["evidence_count"] == 1
    assert persisted["evidence_items"][0]["chunk_id"] == chunk_set["chunks"][0][
        "chunk_id"
    ]
    assert _sqlite_table_count(engine, "cx_retrieval_packages") == 1
    assert _sqlite_table_count(engine, "cx_retrieval_evidence_items") == 1
    dump = _sqlite_table_dump(
        engine,
        ["cx_retrieval_packages", "cx_retrieval_evidence_items"],
    )
    assert query_text not in dump
    assert evidence_text not in dump
    assert source_text not in dump


def test_content_ingestion_store_persists_no_answer_retrieval_without_evidence_refs(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    package = retrieval_package_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        chunk={
            "chunk_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "text_sha256": "1" * 64,
            "start_offset": 0,
            "end_offset": 0,
        },
        query_text="SECRET_STORE_NO_ANSWER_QUERY_" + ("x" * 400),
        evidence_text="unused",
    )
    package.update(
        {
            "retrieval_package_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "package_hash": "b" * 64,
            "status": "NO_ANSWER",
            "query_embedding_snapshot": {
                "provided": False,
                "embedding_sha256": None,
                "vector_dimension": 0,
            },
            "evidence_items": [],
            "score_summary": {
                "best_score": 0.0,
                "score_spread": 0.0,
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
                "rerank_state": "NOT_APPLIED",
            },
            "no_answer_reason": "no_terms_matched",
        }
    )

    store.save_retrieval_package(package)

    persisted = repository.get_retrieval_package_record(
        str(package["retrieval_package_id"])
    )
    assert persisted is not None
    assert persisted["status"] == "NO_ANSWER"
    assert persisted["evidence_items"] == []
    assert _sqlite_table_count(engine, "cx_retrieval_packages") == 1
    assert _sqlite_table_count(engine, "cx_retrieval_evidence_items") == 0


def test_sqlalchemy_repository_upserts_processing_run_metadata_without_raw_payloads(
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
    queued = build_processing_run_persistence_record(
        processing_run_payload(
            document_id=content["content_object_id"],
            status="QUEUED",
            updated_at="2026-08-09T00:00:00Z",
        )
    )
    succeeded = build_processing_run_persistence_record(
        processing_run_payload(
            document_id=content["content_object_id"],
            status="SUCCEEDED",
            updated_at="2026-08-09T00:00:10Z",
        )
    )

    saved_queued = repository.save_processing_run_record(queued)
    saved_succeeded = repository.save_processing_run_record(succeeded)

    assert saved_queued["status"] == "QUEUED"
    assert saved_queued["steps"] == []
    assert saved_succeeded == succeeded
    assert (
        repository.get_processing_run_record(succeeded["pipeline_run_id"])
        == succeeded
    )
    assert (
        repository.get_latest_processing_run_record(content["content_object_id"])
        == succeeded
    )
    assert repository.get_processing_run_record(
        "11111111-1111-4111-8111-111111111111"
    ) is None
    assert repository.get_latest_processing_run_record(
        "22222222-2222-4222-8222-222222222222"
    ) is None
    assert _sqlite_table_count(engine, "cx_document_processing_runs") == 1
    assert _sqlite_table_count(engine, "cx_document_processing_steps") == 1
    dump = _sqlite_table_dump(
        engine,
        ["cx_document_processing_runs", "cx_document_processing_steps"],
    )
    assert "SECRET_OUTPUT_REF_TEXT" not in dump
    assert "SECRET_PROCESSING_ERROR_DETAIL" not in dump


def test_in_memory_repository_lists_processing_runs_with_filters_and_step_toggle() -> None:
    repository = InMemoryCxContentRepository()
    succeeded = build_processing_run_persistence_record(
        processing_run_payload(
            document_id="44444444-4444-4444-8444-444444444444",
            pipeline_run_id="99999999-9999-4999-8999-999999999999",
            status="SUCCEEDED",
            updated_at="2026-08-09T00:00:10Z",
        )
    )
    failed_payload = processing_run_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        pipeline_run_id="88888888-8888-4888-8888-888888888888",
        status="FAILED",
        updated_at="2026-08-09T00:00:20Z",
    )
    failed_payload["request_id"] = "request-failed"
    failed_payload["job"]["job_id"] = "job-processing-failed"
    failed = build_processing_run_persistence_record(failed_payload)
    repository.save_processing_run_record(succeeded)
    repository.save_processing_run_record(failed)

    listed = repository.list_processing_run_records(
        document_id="44444444-4444-4444-8444-444444444444",
        include_steps=False,
    )
    failed_only = repository.list_processing_run_records(
        status="FAILED",
        request_id="request-failed",
        job_id="job-processing-failed",
    )

    assert [record["pipeline_run_id"] for record in listed] == [
        "88888888-8888-4888-8888-888888888888",
        "99999999-9999-4999-8999-999999999999",
    ]
    assert listed[0]["steps"] == []
    assert listed[0]["step_failed"] == 1
    assert failed_only == [failed]
    assert repository.list_processing_run_records(
        document_id="33333333-3333-4333-8333-333333333333"
    ) == []
    assert repository.list_processing_run_records(trace_id="missing-trace") == []
    assert repository.list_processing_run_records(request_id="missing-request") == []
    assert repository.list_processing_run_records(job_id="missing-job") == []
    assert repository.list_processing_run_records(status="CANCELLED") == []
    assert len(repository.list_processing_run_records(limit=0)) == 1


def test_sqlalchemy_repository_lists_processing_runs_with_filters_and_safe_rows(
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
    succeeded = build_processing_run_persistence_record(
        processing_run_payload(
            document_id=content["content_object_id"],
            pipeline_run_id="99999999-9999-4999-8999-999999999999",
            status="SUCCEEDED",
            updated_at="2026-08-09T00:00:10Z",
        )
    )
    failed_payload = processing_run_payload(
        document_id=content["content_object_id"],
        pipeline_run_id="88888888-8888-4888-8888-888888888888",
        status="FAILED",
        updated_at="2026-08-09T00:00:20Z",
    )
    failed_payload["request_id"] = "request-failed"
    failed_payload["job"]["job_id"] = "job-processing-failed"
    failed = build_processing_run_persistence_record(failed_payload)
    repository.save_processing_run_record(succeeded)
    repository.save_processing_run_record(failed)

    listed = repository.list_processing_run_records(
        document_id=content["content_object_id"],
        include_steps=False,
    )
    failed_by_status = repository.list_processing_run_records(
        status="FAILED",
        trace_id=TRACE_ID,
    )
    failed_by_request_and_job = repository.list_processing_run_records(
        request_id="request-failed",
        job_id="job-processing-failed",
    )

    assert [record["pipeline_run_id"] for record in listed] == [
        "88888888-8888-4888-8888-888888888888",
        "99999999-9999-4999-8999-999999999999",
    ]
    assert listed[0]["steps"] == []
    assert failed_by_status == [failed]
    assert failed_by_request_and_job == [failed]
    assert repository.list_processing_run_records(status="CANCELLED") == []
    assert len(repository.list_processing_run_records(limit=0)) == 1
    assert _sqlite_table_count(engine, "cx_document_processing_runs") == 2
    dump = _sqlite_table_dump(
        engine,
        ["cx_document_processing_runs", "cx_document_processing_steps"],
    )
    assert "SECRET_OUTPUT_REF_TEXT" not in dump
    assert "SECRET_PROCESSING_ERROR_DETAIL" not in dump


def test_sqlalchemy_repository_saves_failed_processing_run_error_hash(
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
    failed = build_processing_run_persistence_record(
        processing_run_payload(
            document_id=content["content_object_id"],
            status="FAILED",
            updated_at="2026-08-09T00:00:10Z",
        )
    )

    saved = repository.save_processing_run_record(failed)

    assert saved == failed
    assert saved["steps"][0]["error_code"] == "cx.summary_failed"
    assert saved["steps"][0]["error_detail_sha256"] == sha256_text(
        "SECRET_PROCESSING_ERROR_DETAIL"
    )
    assert _sqlite_table_count(engine, "cx_document_processing_runs") == 1
    assert _sqlite_table_count(engine, "cx_document_processing_steps") == 1
    assert "SECRET_PROCESSING_ERROR_DETAIL" not in _sqlite_table_dump(
        engine,
        ["cx_document_processing_runs", "cx_document_processing_steps"],
    )


def test_content_ingestion_store_persists_processing_run_metadata(
    tmp_path: Path,
) -> None:
    repository, engine = sqlite_content_repository(tmp_path)
    store = ContentIngestionStore(content_repository=repository)
    source_text = "processing body " + ("SOURCE_PRIVATE_" * 30)
    document = upload_registration(tmp_path, content_text=source_text)
    store.save_upload_registration(document, source_text=source_text)
    run = processing_run_payload(
        document_id=str(document["document_id"]),
        status="SUCCEEDED",
        updated_at="2026-08-09T00:00:10Z",
    )

    saved = store.save_document_processing_run(run)

    persisted = repository.get_processing_run_record(str(run["pipeline_run_id"]))
    assert saved == run
    assert persisted is not None
    assert persisted["pipeline_run_id"] == run["pipeline_run_id"]
    assert persisted["document_id"] == document["document_id"]
    assert persisted["status"] == "SUCCEEDED"
    assert persisted["step_succeeded"] == 1
    assert persisted["steps"][0]["output_ref_type"] == "cx.document_summary"
    assert _sqlite_table_count(engine, "cx_document_processing_runs") == 1
    assert _sqlite_table_count(engine, "cx_document_processing_steps") == 1
    dump = _sqlite_table_dump(
        engine,
        ["cx_document_processing_runs", "cx_document_processing_steps"],
    )
    assert source_text not in dump
    assert "SECRET_OUTPUT_REF_TEXT" not in dump


def test_content_ingestion_store_skips_processing_persistence_without_content_ref(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    run = processing_run_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        status="SUCCEEDED",
    )

    saved = store.save_document_processing_run(run)

    assert saved == run
    assert store.get_document_processing_run(str(run["pipeline_run_id"])) == run
    assert store.content_repository.processing_run_records == {}


def test_content_ingestion_store_skips_processing_persistence_for_sparse_record() -> None:
    store = ContentIngestionStore()
    sparse = {
        "document_id": "44444444-4444-4444-8444-444444444444",
        "pipeline_run_id": "99999999-9999-4999-8999-999999999999",
    }

    saved = store.save_document_processing_run(sparse)

    assert saved == sparse
    assert store.content_repository.processing_run_records == {}


def test_content_ingestion_store_skips_processing_persistence_without_persisted_content() -> None:
    store = ContentIngestionStore()
    run = processing_run_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        status="SUCCEEDED",
    )
    store.document_content_refs[str(run["document_id"])] = {
        "content_object_id": str(run["document_id"]),
        "source_file_id": "11111111-1111-4111-8111-111111111111",
    }

    saved = store.save_document_processing_run(run)

    assert saved == run
    assert store.content_repository.processing_run_records == {}


def test_content_ingestion_store_skips_retrieval_metadata_without_persisted_lineage(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    package = retrieval_package_payload(
        document_id="44444444-4444-4444-8444-444444444444",
        chunk={
            "chunk_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "text_sha256": "1" * 64,
            "start_offset": 0,
            "end_offset": 10,
        },
    )

    saved = store.save_retrieval_package(package)

    assert saved == package
    assert store.get_retrieval_package(str(package["retrieval_package_id"])) == package
    assert store.content_repository.retrieval_package_records == {}


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


def test_content_ingestion_store_skips_summary_metadata_without_artifact(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    document_id = str(document["document_id"])
    summary = document_summary_payload(tmp_path, document)

    saved = store.save_document_summary(summary, summary_text="private summary")

    assert saved == summary
    assert store.get_document_summary(document_id) == summary
    assert store.get_summary_text(summary["document_summary_id"]) == "private summary"
    assert store.content_repository.document_summary_records == {}


def test_content_ingestion_store_skips_summary_metadata_without_required_shape(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    store.save_upload_registration(document, source_text="source text")
    record = {
        "document_id": document["document_id"],
        "document_summary_id": "summary-001",
    }

    saved = store.save_document_summary(record, summary_text="private summary")

    assert saved == record
    assert store.content_repository.document_summary_records == {}


def test_content_ingestion_store_skips_summary_embedding_without_persisted_summary(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    summary = document_summary_payload(tmp_path, document)
    embedding = summary_embedding_payload(summary)

    saved = store.save_summary_embedding_index(
        embedding,
        embedding_vector=[0.0, 0.5, 1.0],
    )

    assert saved == embedding
    assert store.get_summary_embedding_index(summary["document_id"]) == embedding
    assert store.content_repository.summary_embedding_records == {}


def test_content_ingestion_store_skips_summary_embedding_without_required_shape(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="source text")
    record = {
        "document_id": document["document_id"],
        "document_summary_id": "summary-001",
    }

    saved = store.save_summary_embedding_index(
        record,
        embedding_vector=[0.0, 0.5, 1.0],
    )

    assert saved == record
    assert store.content_repository.summary_embedding_records == {}


def _sqlite_table_count(engine: object, table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one())


def _sqlite_table_dump(engine: object, table_names: list[str]) -> str:
    rows: list[object] = []
    with engine.connect() as connection:
        for table_name in table_names:
            rows.extend(connection.execute(text(f"SELECT * FROM {table_name}")).all())
    return str(rows)
