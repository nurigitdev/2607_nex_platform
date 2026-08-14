from __future__ import annotations

import base64
import binascii
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SubjectRegistryResolver,
    SubjectRegistryResolverError,
    build_common_job,
    build_default_subject_registry_resolver,
    build_subject_ref,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_cx.document_library import build_document_detail_projection
from nex_cx.repository import (
    CxContentRepositoryError,
    CxContentRepository,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    InMemoryCxContentRepository,
    build_chunk_embedding_index_record,
    build_chunk_set_record,
    build_extraction_artifact_record,
    build_lexical_index_record,
    build_document_summary_persistence_record,
    build_processing_run_persistence_record,
    build_retrieval_package_persistence_record,
    build_summary_embedding_persistence_record,
    build_content_object_record,
    build_source_file_record,
)
from nex_cx.source_ownership import (
    CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION,
    OA_TENANT_SUBJECT_TYPE,
    OA_USER_SUBJECT_TYPE,
    build_source_ownership_ref,
)
from nex_cx.extractors import (
    ExtractionAdapterError,
    ExtractorInput,
    LocalMockTextExtractor,
    TextExtractor,
    markdown_from_source_text,
)

DEFAULT_DATA_ROOT = "/data/nex-platform"
DEFAULT_CHUNK_POLICY = "chunk_1000_100"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_BM25_TOKENIZER = "mecab_ko"
DEFAULT_BM25_TOKENIZER_FALLBACK = "korean_mixed_v1"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
CX_SOURCE_FILE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION = (
    "cx_source_file_materialization_receipt.v1"
)
OWNERSHIP_COMPATIBILITY_MODE = "legacy_owner_fields_mapped_to_oa_subject_refs"
UPLOAD_OWNER_RESOLVER_DISABLED = "disabled"
UPLOAD_OWNER_RESOLVER_VERIFY = "verify"
UPLOAD_OWNER_RESOLVER_MODES = frozenset(
    {
        UPLOAD_OWNER_RESOLVER_DISABLED,
        UPLOAD_OWNER_RESOLVER_VERIFY,
    }
)
UPLOAD_OWNER_RESOLVER_MODE_ENV = "NEX_CX_UPLOAD_OWNER_RESOLVER_MODE"
OWNERSHIP_REF_ALLOWED_FIELDS = frozenset(
    {
        "ownership_schema_version",
        "tenant_ref",
        "owner_subject_ref",
        "uploaded_by_subject_ref",
        "legacy",
        "compatibility_mode",
    }
)
OWNERSHIP_LEGACY_ALLOWED_FIELDS = frozenset({"tenant_id", "owner_user_id"})
SUBJECT_REF_ALLOWED_FIELDS = frozenset({"type", "id"})


@dataclass(frozen=True)
class CxStorageConfig:
    data_root: Path
    source_root: Path
    extracted_markdown_root: Path
    extraction_temp_root: Path
    chunk_policy: str
    chunk_size: int
    chunk_overlap: int
    bm25_tokenizer: str
    bm25_tokenizer_fallback: str
    max_upload_size_bytes: int = DEFAULT_MAX_UPLOAD_SIZE_BYTES


@dataclass
class ContentIngestionStore:
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_texts: dict[str, str] = field(default_factory=dict)
    source_bytes: dict[str, bytes] = field(default_factory=dict)
    extraction_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_texts: dict[str, str] = field(default_factory=dict)
    embedding_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    embedding_vectors: dict[str, list[float]] = field(default_factory=dict)
    lexical_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    retrieval_packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary_texts: dict[str, str] = field(default_factory=dict)
    summary_embedding_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary_embedding_vectors: dict[str, list[float]] = field(default_factory=dict)
    document_processing_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    latest_processing_run_ids_by_document: dict[str, str] = field(default_factory=dict)
    content_repository: CxContentRepository = field(
        default_factory=InMemoryCxContentRepository
    )
    document_content_refs: dict[str, dict[str, str]] = field(default_factory=dict)

    def save_upload_registration(
        self,
        record: dict[str, Any],
        *,
        source_text: str | None = None,
        source_bytes: bytes | None = None,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> dict[str, Any]:
        ownership_ref = _ownership_ref_from_upload_record(record)
        tenant_id = tenant_id or ownership_ref["legacy"]["tenant_id"]
        owner_user_id = owner_user_id or ownership_ref["legacy"]["owner_user_id"]
        uploaded_by_user_id = ownership_ref["uploaded_by_subject_ref"]["id"]
        existing = self.content_repository.find_active_content_object(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            source_sha256=record["source_sha256"],
        )
        if existing is not None and existing["content_object_id"] in self.documents:
            existing_record = self.documents[existing["content_object_id"]]
            self._capture_duplicate_source_content(
                existing_record,
                source_text=source_text,
                source_bytes=source_bytes,
            )
            return mark_upload_registration_duplicate(existing_record)

        source_file = self.content_repository.save_source_file(
            build_source_file_record(record)
        )
        record = align_upload_registration_to_source_file(record, source_file)
        content_object = self.content_repository.save_content_object(
            build_content_object_record(
                record,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                uploaded_by_user_id=uploaded_by_user_id,
                source_file_id=source_file["source_file_id"],
            )
        )
        self.document_content_refs[record["document_id"]] = {
            "source_file_id": source_file["source_file_id"],
            "content_object_id": content_object["content_object_id"],
        }
        self.documents[record["document_id"]] = record
        self.jobs[record["extraction"]["job_id"]] = record["ingestion_job"]
        materialized_source = source_bytes
        if source_text is not None:
            materialized_source = source_text.encode("utf-8")
        if materialized_source is not None:
            verified_at = materialize_local_source_bytes(record, materialized_source)
            self.content_repository.mark_source_file_checksum_verified(
                source_file["source_file_id"],
                verified_at=verified_at,
            )
            self.source_bytes[record["upload_id"]] = materialized_source
            if source_text is not None:
                self.source_texts[record["upload_id"]] = source_text
        return record

    def _capture_duplicate_source_content(
        self,
        record: dict[str, Any],
        *,
        source_text: str | None,
        source_bytes: bytes | None,
    ) -> None:
        materialized_source = source_bytes
        if source_text is not None:
            materialized_source = source_text.encode("utf-8")
        if materialized_source is None:
            return
        refs = self.document_content_refs.get(record["document_id"])
        verified_at = materialize_local_source_bytes(record, materialized_source)
        if refs is not None:
            self.content_repository.mark_source_file_checksum_verified(
                refs["source_file_id"],
                verified_at=verified_at,
            )
        self.source_bytes[record["upload_id"]] = materialized_source
        if source_text is not None:
            self.source_texts[record["upload_id"]] = source_text

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def get_source_text(self, upload_id: str) -> str | None:
        return self.source_texts.get(upload_id)

    def get_source_bytes(self, upload_id: str) -> bytes | None:
        return self.source_bytes.get(upload_id)

    def get_content_ref(self, document_id: str) -> dict[str, str] | None:
        return self.document_content_refs.get(document_id)

    def source_bytes_available(self, upload_id: str | None) -> bool:
        return isinstance(upload_id, str) and upload_id in self.source_bytes

    def save_extraction_result(self, result: dict[str, Any]) -> dict[str, Any]:
        document = self.documents.get(result["document_id"])
        job = self.jobs.get(result["job_id"])
        if document is None or job is None:
            raise IngestionError(
                status_code=404,
                error_code="cx.ingestion_state_not_found",
                detail="Document or ingestion job was not found.",
            )

        job["status"] = "SUCCEEDED"
        job["updated_at"] = result["updated_at"]
        document["extraction"] = {
            **document["extraction"],
            "status": "SUCCEEDED",
            "markdown_available": True,
        }
        document["updated_at"] = result["updated_at"]
        refs = self.document_content_refs.get(result["document_id"])
        if refs is not None:
            self.content_repository.save_extraction_artifact(
                build_extraction_artifact_record(
                    result,
                    content_object_id=refs["content_object_id"],
                    source_file_id=refs["source_file_id"],
                )
            )
        self.extraction_results[result["document_id"]] = result
        return result

    def get_extraction_result(self, document_id: str) -> dict[str, Any] | None:
        return self.extraction_results.get(document_id)

    def save_chunk_set(
        self,
        chunk_set: dict[str, Any],
        *,
        chunk_texts: dict[str, str],
    ) -> dict[str, Any]:
        self.chunk_sets[chunk_set["document_id"]] = chunk_set
        self.chunk_texts.update(chunk_texts)
        self._persist_chunk_set_metadata(chunk_set)
        return chunk_set

    def get_chunk_set(self, document_id: str) -> dict[str, Any] | None:
        return self.chunk_sets.get(document_id)

    def get_chunk_text(self, chunk_id: str) -> str | None:
        return self.chunk_texts.get(chunk_id)

    def _persist_chunk_set_metadata(self, chunk_set: dict[str, Any]) -> None:
        document_id = str(chunk_set["document_id"])
        if "source_markdown_sha256" not in chunk_set:
            return
        refs = self.document_content_refs.get(document_id)
        artifact = self._find_extraction_artifact_for_markdown(
            document_id,
            markdown_sha256=str(chunk_set["source_markdown_sha256"]),
        )
        if refs is None or artifact is None:
            return
        self.content_repository.save_chunk_set(
            build_chunk_set_record(
                chunk_set,
                content_object_id=refs["content_object_id"],
                extraction_artifact_id=artifact["extraction_artifact_id"],
            )
        )

    def save_embedding_index(
        self,
        embedding_index: dict[str, Any],
        *,
        embedding_vectors: dict[str, list[float]],
    ) -> dict[str, Any]:
        self.embedding_indexes[embedding_index["document_id"]] = embedding_index
        self.embedding_vectors.update(embedding_vectors)
        self._persist_embedding_index_metadata(embedding_index)
        return embedding_index

    def get_embedding_index(self, document_id: str) -> dict[str, Any] | None:
        return self.embedding_indexes.get(document_id)

    def get_embedding_vector(self, chunk_id: str) -> list[float] | None:
        return self.embedding_vectors.get(chunk_id)

    def _persist_embedding_index_metadata(
        self,
        embedding_index: dict[str, Any],
    ) -> None:
        required_keys = {
            "chunk_embeddings",
            "created_at",
            "deployment_id",
            "model_revision",
            "provider_alias",
            "vector_dimension",
        }
        if not required_keys.issubset(embedding_index):
            return
        persisted_chunk_set = self._find_persisted_chunk_set(
            str(embedding_index["document_id"])
        )
        if persisted_chunk_set is None:
            return
        self.content_repository.save_chunk_embedding_index(
            build_chunk_embedding_index_record(
                embedding_index,
                chunk_set_id=persisted_chunk_set["chunk_set_id"],
            )
        )

    def save_lexical_index(self, lexical_index: dict[str, Any]) -> dict[str, Any]:
        self.lexical_indexes[lexical_index["document_id"]] = lexical_index
        self._persist_lexical_index_metadata(lexical_index)
        return lexical_index

    def get_lexical_index(self, document_id: str) -> dict[str, Any] | None:
        return self.lexical_indexes.get(document_id)

    def _persist_lexical_index_metadata(self, lexical_index: dict[str, Any]) -> None:
        if "created_at" not in lexical_index or "tokenizer_requested" not in lexical_index:
            return
        persisted_chunk_set = self._find_persisted_chunk_set(
            str(lexical_index["document_id"])
        )
        if persisted_chunk_set is None:
            return
        self.content_repository.save_lexical_index(
            build_lexical_index_record(
                lexical_index,
                chunk_set_id=persisted_chunk_set["chunk_set_id"],
            )
        )

    def _find_persisted_chunk_set(self, document_id: str) -> dict[str, Any] | None:
        refs = self.document_content_refs.get(document_id)
        public_chunk_set = self.chunk_sets.get(document_id)
        if (
            refs is None
            or public_chunk_set is None
            or "source_markdown_sha256" not in public_chunk_set
            or "chunk_policy" not in public_chunk_set
        ):
            return None
        artifact = self._find_extraction_artifact_for_markdown(
            document_id,
            markdown_sha256=str(public_chunk_set["source_markdown_sha256"]),
        )
        if artifact is None:
            return None
        return self.content_repository.find_chunk_set(
            content_object_id=refs["content_object_id"],
            extraction_artifact_id=artifact["extraction_artifact_id"],
            chunk_policy_id=str(public_chunk_set["chunk_policy"]),
            source_markdown_sha256=str(public_chunk_set["source_markdown_sha256"]),
        )

    def _find_extraction_artifact_for_markdown(
        self,
        document_id: str,
        *,
        markdown_sha256: str,
    ) -> dict[str, Any] | None:
        refs = self.document_content_refs.get(document_id)
        extraction = self.extraction_results.get(document_id)
        if refs is None or extraction is None:
            return None

        extractor = extraction.get("extractor")
        if not isinstance(extractor, dict):
            return None
        return self.content_repository.find_extraction_artifact(
            content_object_id=refs["content_object_id"],
            extractor_name=str(extractor["provider"]),
            extractor_version=str(extractor["version"]),
            markdown_sha256=markdown_sha256,
        )

    def save_retrieval_package(self, package: dict[str, Any]) -> dict[str, Any]:
        self.retrieval_packages[package["retrieval_package_id"]] = package
        self._persist_retrieval_package_metadata(package)
        return package

    def get_retrieval_package(self, retrieval_package_id: str) -> dict[str, Any] | None:
        return self.retrieval_packages.get(retrieval_package_id)

    def _persist_retrieval_package_metadata(self, package: dict[str, Any]) -> None:
        required_keys = {
            "created_at",
            "evidence_items",
            "package_hash",
            "permission_snapshot",
            "purpose",
            "query_text",
            "request_id",
            "retrieval_package_id",
            "retrieval_profile",
            "score_summary",
            "source_summary",
            "status",
            "trace_id",
            "updated_at",
        }
        if not required_keys.issubset(package):
            return
        evidence_items = package.get("evidence_items")
        if not isinstance(evidence_items, list):
            return
        if evidence_items and not self._retrieval_evidence_lineage_is_persisted(
            evidence_items
        ):
            return
        self.content_repository.save_retrieval_package_record(
            build_retrieval_package_persistence_record(package)
        )

    def _retrieval_evidence_lineage_is_persisted(
        self,
        evidence_items: list[Any],
    ) -> bool:
        for item in evidence_items:
            if not isinstance(item, dict):
                return False
            document_id_value = item.get("content_object_id")
            chunk_id_value = item.get("chunk_id")
            if not isinstance(document_id_value, str) or not document_id_value:
                return False
            if not isinstance(chunk_id_value, str) or not chunk_id_value:
                return False
            document_id = document_id_value
            chunk_id = chunk_id_value
            refs = self.document_content_refs.get(document_id)
            if refs is None:
                return False
            persisted_chunk_set = self._find_persisted_chunk_set(document_id)
            if persisted_chunk_set is None:
                return False
            if not any(
                chunk["chunk_id"] == chunk_id
                for chunk in persisted_chunk_set["chunks"]
            ):
                return False
        return True

    def save_document_summary(
        self,
        record: dict[str, Any],
        *,
        summary_text: str,
    ) -> dict[str, Any]:
        self.document_summaries[record["document_id"]] = record
        self.summary_texts[record["document_summary_id"]] = summary_text
        self._persist_document_summary_metadata(record)
        return record

    def get_document_summary(self, document_id: str) -> dict[str, Any] | None:
        return self.document_summaries.get(document_id)

    def get_summary_text(self, document_summary_id: str) -> str | None:
        return self.summary_texts.get(document_summary_id)

    def _persist_document_summary_metadata(self, record: dict[str, Any]) -> None:
        required_keys = {
            "created_at",
            "document_summary_id",
            "source_markdown_sha256",
            "summary_char_count",
            "summary_chunk_policy_id",
            "summary_hard_limit_chars",
            "summary_max_chars",
            "summary_storage_uri",
            "summary_text_sha256",
            "updated_at",
        }
        if not required_keys.issubset(record):
            return
        document_id = str(record["document_id"])
        refs = self.document_content_refs.get(document_id)
        artifact = self._find_extraction_artifact_for_markdown(
            document_id,
            markdown_sha256=str(record["source_markdown_sha256"]),
        )
        if refs is None or artifact is None:
            return
        self.content_repository.save_document_summary_record(
            build_document_summary_persistence_record(
                record,
                content_object_id=refs["content_object_id"],
                extraction_artifact_id=artifact["extraction_artifact_id"],
            )
        )

    def save_summary_embedding_index(
        self,
        record: dict[str, Any],
        *,
        embedding_vector: list[float],
    ) -> dict[str, Any]:
        self.summary_embedding_indexes[record["document_id"]] = record
        self.summary_embedding_vectors[record["document_summary_id"]] = embedding_vector
        self._persist_summary_embedding_metadata(record)
        return record

    def get_summary_embedding_index(self, document_id: str) -> dict[str, Any] | None:
        return self.summary_embedding_indexes.get(document_id)

    def get_summary_embedding_vector(
        self,
        document_summary_id: str,
    ) -> list[float] | None:
        return self.summary_embedding_vectors.get(document_summary_id)

    def _persist_summary_embedding_metadata(self, record: dict[str, Any]) -> None:
        required_keys = {
            "created_at",
            "deployment_id",
            "document_summary_id",
            "embedding_sha256",
            "model_revision",
            "provider_alias",
            "vector_dimension",
        }
        if not required_keys.issubset(record):
            return
        persisted_summary = self.content_repository.get_document_summary_record(
            str(record["document_summary_id"])
        )
        if persisted_summary is None:
            return
        self.content_repository.save_summary_embedding_record(
            build_summary_embedding_persistence_record(
                record,
                document_summary_id=persisted_summary["document_summary_id"],
            )
        )

    def save_document_processing_run(self, record: dict[str, Any]) -> dict[str, Any]:
        self.document_processing_runs[record["pipeline_run_id"]] = record
        self.latest_processing_run_ids_by_document[record["document_id"]] = record[
            "pipeline_run_id"
        ]
        self._persist_processing_run_metadata(record)
        return record

    def _persist_processing_run_metadata(self, record: dict[str, Any]) -> None:
        required_keys = {
            "document_id",
            "pipeline_run_id",
            "pipeline_schema_version",
            "request_id",
            "status",
            "step_summary",
            "steps",
            "trace_id",
            "updated_at",
        }
        if not required_keys.issubset(record):
            return
        document_id = str(record["document_id"])
        refs = self.document_content_refs.get(document_id)
        if refs is None:
            return
        persisted_content = self.content_repository.get_content_object(
            str(refs["content_object_id"])
        )
        if persisted_content is None:
            return
        persistence_record = build_processing_run_persistence_record(
            {
                **record,
                "document_id": persisted_content["content_object_id"],
            }
        )
        self.content_repository.save_processing_run_record(persistence_record)

    def get_document_processing_run(self, pipeline_run_id: str) -> dict[str, Any] | None:
        return self.document_processing_runs.get(pipeline_run_id)

    def get_latest_document_processing_run(
        self,
        document_id: str,
    ) -> dict[str, Any] | None:
        pipeline_run_id = self.latest_processing_run_ids_by_document.get(document_id)
        if pipeline_run_id is None:
            return None
        return self.document_processing_runs[pipeline_run_id]


@dataclass(frozen=True)
class IngestionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_INGESTION_STORE = ContentIngestionStore()


def build_storage_config(environ: dict[str, str] | None = None) -> CxStorageConfig:
    env = environ if environ is not None else os.environ
    data_root = Path(env.get("NEX_DATA_ROOT", DEFAULT_DATA_ROOT))
    return CxStorageConfig(
        data_root=data_root,
        source_root=Path(
            env.get("NEX_CX_SOURCE_STORAGE_ROOT", str(data_root / "cx" / "source-files"))
        ),
        extracted_markdown_root=Path(
            env.get(
                "NEX_CX_EXTRACTED_MARKDOWN_ROOT",
                str(data_root / "cx" / "extracted-markdown"),
            )
        ),
        extraction_temp_root=Path(
            env.get(
                "NEX_CX_EXTRACTION_TEMP_ROOT",
                str(data_root / "cx" / "extraction-temp"),
            )
        ),
        chunk_policy=env.get("NEX_CX_DEFAULT_CHUNK_POLICY", DEFAULT_CHUNK_POLICY),
        chunk_size=_positive_int(
            env.get("NEX_CX_CHUNK_SIZE"),
            default=DEFAULT_CHUNK_SIZE,
            field_name="NEX_CX_CHUNK_SIZE",
        ),
        chunk_overlap=_non_negative_int(
            env.get("NEX_CX_CHUNK_OVERLAP"),
            default=DEFAULT_CHUNK_OVERLAP,
            field_name="NEX_CX_CHUNK_OVERLAP",
        ),
        bm25_tokenizer=env.get("NEX_CX_BM25_TOKENIZER", DEFAULT_BM25_TOKENIZER),
        bm25_tokenizer_fallback=env.get(
            "NEX_CX_BM25_TOKENIZER_FALLBACK",
            DEFAULT_BM25_TOKENIZER_FALLBACK,
        ),
        max_upload_size_bytes=_positive_int(
            env.get("NEX_CX_MAX_UPLOAD_SIZE_BYTES"),
            default=DEFAULT_MAX_UPLOAD_SIZE_BYTES,
            field_name="NEX_CX_MAX_UPLOAD_SIZE_BYTES",
        ),
    )


def register_ingestion_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore | None = None,
    storage_config: CxStorageConfig | None = None,
    owner_resolver: SubjectRegistryResolver | None = None,
    owner_resolver_mode: str | None = None,
    database_env: str | None = None,
    redacted_database_url: str | None = None,
    source_kind: str = "memory",
) -> None:
    ingestion_store = store or DEFAULT_INGESTION_STORE
    config = storage_config or build_storage_config()
    resolver_mode = normalize_upload_owner_resolver_mode(
        owner_resolver_mode or os.getenv(UPLOAD_OWNER_RESOLVER_MODE_ENV)
    )
    resolver = owner_resolver
    if resolver is None and resolver_mode != UPLOAD_OWNER_RESOLVER_DISABLED:
        resolver = build_default_subject_registry_resolver(caller_service_id="nex-cx")

    @app.post("/api/v1/documents/uploads", response_model=None)
    def register_upload(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            record = build_upload_registration(
                payload,
                storage_config=config,
                request_id=request_id,
                trace_id=trace_id,
            )
            resolve_upload_ownership(
                record["ownership_ref"],
                owner_resolver=resolver,
                owner_resolver_mode=resolver_mode,
                request_id=request_id,
                trace_id=trace_id,
            )
        except IngestionError as exc:
            return _ingestion_problem_response(request, exc)

        source_text, source_bytes = source_content_from_payload(payload)
        ownership = record["ownership"]
        saved_record = ingestion_store.save_upload_registration(
            record,
            source_text=source_text,
            source_bytes=source_bytes,
            tenant_id=ownership["tenant_id"],
            owner_user_id=ownership["owner_user_id"],
        )
        return JSONResponse(
            status_code=200 if saved_record["dedupe"]["status"] == "ALREADY_EXISTS" else 202,
            content=saved_record,
        )

    @app.get("/api/v1/documents/{document_id}", response_model=None)
    def get_document(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Query(default=None),
        owner_user_id: str | None = Query(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            projection = build_document_detail_projection(
                store=ingestion_store,
                document_id=document_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                source_kind=source_kind,
                database_env=database_env,
                redacted_database_url=redacted_database_url,
            )
        except ValueError as exc:
            return problem_response(
                request,
                status_code=400,
                error_code="cx.document_detail_query_invalid",
                title="Document detail query failed",
                detail=str(exc),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "document-detail-query-failed"
                ),
            )
        except CxContentRepositoryError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Document detail repository unavailable",
                detail=exc.detail,
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "document-detail-repository-unavailable"
                ),
            )
        if projection is None:
            return problem_response(
                request,
                status_code=404,
                error_code="cx.document_not_found",
                title="Document detail was not found",
                detail=(
                    "Document detail was not found or is not visible "
                    "for the requested owner scope."
                ),
                type_uri="https://nex-platform.local/problems/document-not-found",
            )
        return projection

    @app.get(
        "/api/v1/documents/{document_id}/source-file/materialization",
        response_model=None,
    )
    def get_source_file_materialization(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Query(default=None),
        owner_user_id: str | None = Query(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            receipt = build_source_file_materialization_receipt(
                store=ingestion_store,
                document_id=document_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                source_kind=source_kind,
                database_env=database_env,
                redacted_database_url=redacted_database_url,
            )
        except ValueError as exc:
            return problem_response(
                request,
                status_code=400,
                error_code="cx.source_file_materialization_query_invalid",
                title="Source-file materialization query failed",
                detail=str(exc),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "source-file-materialization-query-failed"
                ),
            )
        except CxContentRepositoryError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Source-file materialization repository unavailable",
                detail=exc.detail,
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "source-file-materialization-repository-unavailable"
                ),
            )
        if receipt is None:
            return problem_response(
                request,
                status_code=404,
                error_code="cx.source_file_materialization_not_found",
                title="Source-file materialization was not found",
                detail=(
                    "Source-file materialization was not found or is not visible "
                    "for the requested owner scope."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "source-file-materialization-not-found"
                ),
            )
        return receipt

    @app.get("/api/v1/jobs/{job_id}", response_model=None)
    def get_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        job = ingestion_store.get_job(job_id)
        if job is None:
            return _ingestion_problem_response(
                request,
                IngestionError(
                    status_code=404,
                    error_code="cx.ingestion_job_not_found",
                    detail=f"Ingestion job was not found: {job_id}",
                ),
            )
        return job

    @app.post("/api/v1/jobs/{job_id}/run", response_model=None)
    def run_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return run_text_extraction_job(
                job_id,
                store=ingestion_store,
                storage_config=config,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except IngestionError as exc:
            return _ingestion_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/extraction", response_model=None)
    def get_extraction(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        result = ingestion_store.get_extraction_result(document_id)
        if result is None:
            return _ingestion_problem_response(
                request,
                IngestionError(
                    status_code=404,
                    error_code="cx.extraction_result_not_found",
                    detail=f"Extraction result was not found: {document_id}",
                ),
            )
        return result


def build_upload_registration(
    payload: dict[str, Any],
    *,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    filename = sanitize_filename(_required_string(payload, "filename"))
    content_type = _optional_string(payload, "content_type", "application/octet-stream")
    content_text, source_bytes = source_content_from_payload(payload)

    source_sha256 = _source_sha256_from_payload(payload, content_text, source_bytes)
    size_bytes = _size_bytes_from_payload(payload, content_text, source_bytes)
    validate_upload_size(size_bytes, max_upload_size_bytes=storage_config.max_upload_size_bytes)
    ownership_ref = build_upload_ownership_ref(payload)
    tenant_id = ownership_ref["legacy"]["tenant_id"]
    owner_user_id = ownership_ref["legacy"]["owner_user_id"]
    created_at = _utc_now()
    source_file_id = _source_file_id(source_sha256)
    document_id = _document_id(tenant_id, owner_user_id, source_sha256)
    upload_id = _upload_id(document_id, request_id, trace_id)
    paths = storage_paths_for_document(
        storage_config=storage_config,
        filename=filename,
        source_sha256=source_sha256,
        document_id=document_id,
        source_file_id=source_file_id,
        created_at=created_at,
    )
    job = build_ingestion_job(
        document_id=document_id,
        upload_id=upload_id,
        request_id=request_id,
        trace_id=trace_id,
        created_at=created_at,
    )

    return {
        "document_schema_version": "cx_upload_registration.v1",
        "document_id": document_id,
        "upload_id": upload_id,
        "filename": filename,
        "original_filename": payload["filename"],
        "content_type": content_type,
        "size_bytes": size_bytes,
        "source_sha256": source_sha256,
        "trace_id": trace_id,
        "request_id": request_id,
        "ownership": {
            "tenant_id": tenant_id,
            "owner_user_id": owner_user_id,
        },
        "ownership_ref": ownership_ref,
        "storage": paths,
        "upload_boundary": {
            "payload_source": payload_source_kind(
                content_text=content_text,
                source_bytes=source_bytes,
            ),
            "source_content_in_record": False,
            "checksum_algorithm": "sha256",
            "max_size_bytes": storage_config.max_upload_size_bytes,
        },
        "retrieval_policy": {
            "chunk_policy": storage_config.chunk_policy,
            "chunk_size": storage_config.chunk_size,
            "chunk_overlap": storage_config.chunk_overlap,
            "bm25_tokenizer": storage_config.bm25_tokenizer,
            "bm25_tokenizer_fallback": storage_config.bm25_tokenizer_fallback,
        },
        "extraction": {
            "status": "PENDING",
            "job_id": job["job_id"],
            "markdown_available": False,
        },
        "dedupe": {
            "scope": "owner_active_content",
            "status": "CREATED",
            "existing_document_id": None,
        },
        "ingestion_job": job,
        "created_at": created_at,
        "updated_at": created_at,
    }


def mark_upload_registration_duplicate(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "dedupe": {
            "scope": "owner_active_content",
            "status": "ALREADY_EXISTS",
            "existing_document_id": record["document_id"],
        },
    }


def align_upload_registration_to_source_file(
    record: dict[str, Any],
    source_file: dict[str, Any],
) -> dict[str, Any]:
    storage = {
        **record["storage"],
        "source_storage_backend": source_file["storage_backend"],
        "source_storage_key": source_file["storage_key"],
        "stored_filename": source_file["stored_filename"],
        "stored_extension": source_file["stored_extension"],
    }
    if source_file.get("source_storage_path"):
        storage["source_storage_path"] = source_file["source_storage_path"]
    return {**record, "storage": storage}


def build_source_file_materialization_receipt(
    *,
    store: ContentIngestionStore,
    document_id: str | None,
    tenant_id: str | None,
    owner_user_id: str | None,
    source_kind: str = "repository",
    database_env: str | None = None,
    redacted_database_url: str | None = None,
) -> dict[str, Any] | None:
    projection = build_document_detail_projection(
        store=store,
        document_id=document_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        source_kind=source_kind,
        database_env=database_env,
        redacted_database_url=redacted_database_url,
    )
    if projection is None:
        return None

    document = projection["document"]
    source_lineage = document["source_lineage"]
    source_file_id = source_lineage.get("source_file_id")
    if not isinstance(source_file_id, str) or not source_file_id:
        return None
    source_file = store.content_repository.get_source_file(source_file_id)
    if source_file is None:
        return None

    upload = document["upload"]
    upload_id = upload.get("upload_id")
    checksum_verified_at = source_file.get("checksum_verified_at")
    checksum_verified = isinstance(checksum_verified_at, str) and bool(
        checksum_verified_at
    )
    return {
        "receipt_schema_version": CX_SOURCE_FILE_MATERIALIZATION_RECEIPT_SCHEMA_VERSION,
        "service_id": "nex-cx",
        "source": {
            "source_kind": source_kind,
            "database_env": database_env,
            "redacted_database_url": redacted_database_url,
        },
        "filters": projection["filters"],
        "document": {
            "document_id": document["document_id"],
            "upload_id": upload_id,
            "filename": document["filename"],
            "content_type": document["content_type"],
            "size_bytes": document["size_bytes"],
            "source_sha256": document["source_sha256"],
        },
        "source_file": {
            "source_file_id": source_file["source_file_id"],
            "source_sha256": source_file["source_sha256"],
            "size_bytes": source_file["size_bytes"],
            "content_type": source_file["content_type"],
            "storage_backend": source_file["storage_backend"],
            "storage_key": source_file["storage_key"],
            "storage_uri": source_file["storage_uri"],
            "stored_filename": source_file["stored_filename"],
            "stored_extension": source_file["stored_extension"],
            "checksum_verified": checksum_verified,
            "checksum_verified_at": checksum_verified_at,
        },
        "materialization": {
            "status": "VERIFIED" if checksum_verified else "PENDING",
            "payload_source": upload.get("payload_source"),
            "source_bytes_captured": store.source_bytes_available(upload_id),
            "checksum_algorithm": "sha256",
            "source_content_in_receipt": False,
            "local_storage_path_included": False,
        },
        "metadata": {
            "owner_scoped": True,
            "not_found_and_not_authorized_collapsed": True,
            "raw_source_included": False,
            "storage_path_redacted": True,
            "database_blob_storage": False,
        },
    }


def build_ingestion_job(
    *,
    document_id: str,
    upload_id: str,
    request_id: str,
    trace_id: str,
    created_at: str,
) -> dict[str, Any]:
    return build_common_job(
        job_id=str(uuid5(NAMESPACE_URL, f"cx-ingestion-job:{upload_id}")),
        job_type="cx.document_ingestion",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=build_subject_ref("cx.document", document_id),
        idempotency_key=upload_id,
        max_attempts=1,
        retryable=True,
        links={
            "document": f"/api/v1/documents/{document_id}",
        },
        created_at=created_at,
    )


def run_text_extraction_job(
    job_id: str,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
    extractor: TextExtractor | None = None,
) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise IngestionError(
            status_code=404,
            error_code="cx.ingestion_job_not_found",
            detail=f"Ingestion job was not found: {job_id}",
        )

    document = store.get_document(job["subject_ref"]["id"])
    if document is None:
        raise IngestionError(
            status_code=404,
            error_code="cx.document_not_found",
            detail=f"Document registration was not found: {job['subject_ref']['id']}",
        )

    source_bytes = store.get_source_bytes(document["upload_id"])
    if source_bytes is None:
        raise IngestionError(
            status_code=409,
            error_code="cx.source_content_unavailable",
            detail="Extraction requires source bytes captured at upload registration.",
        )

    selected_extractor = extractor or LocalMockTextExtractor()
    try:
        extracted = selected_extractor.extract_markdown(
            ExtractorInput(
                filename=document["filename"],
                content_type=document["content_type"],
                source_bytes=source_bytes,
                source_sha256=document["source_sha256"],
            )
        )
    except ExtractionAdapterError as exc:
        raise IngestionError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc

    markdown_text = extracted.markdown_text
    markdown_path = Path(document["storage"]["extracted_markdown_path"])
    write_extracted_markdown(markdown_path, markdown_text)
    extracted_sha256 = sha256_text(markdown_text)
    now = _utc_now()
    result = {
        "extraction_schema_version": "cx_text_extraction.v1",
        "document_id": document["document_id"],
        "job_id": job_id,
        "status": "SUCCEEDED",
        "trace_id": trace_id,
        "request_id": request_id,
        "source_sha256": document["source_sha256"],
        "extracted_markdown_sha256": extracted_sha256,
        "extracted_markdown_path": str(markdown_path),
        "markdown_char_count": len(markdown_text),
        "markdown_preview": markdown_text[:120],
        "extractor": {
            "provider": extracted.provider,
            "mode": extracted.mode,
            "version": extracted.version,
            "source_format": extracted.source_format,
        },
        "warnings": extracted.warnings,
        "created_at": now,
        "updated_at": now,
    }
    return store.save_extraction_result(result)


def write_extracted_markdown(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def materialize_local_source_file(record: dict[str, Any], source_text: str) -> str:
    return materialize_local_source_bytes(record, source_text.encode("utf-8"))


def materialize_local_source_bytes(record: dict[str, Any], source_bytes: bytes) -> str:
    storage = record["storage"]
    if storage["source_storage_backend"] != "local_filesystem":
        raise IngestionError(
            status_code=422,
            error_code="cx.source_storage_backend_unsupported",
            detail="Mock source file materialization only supports local_filesystem storage.",
        )

    storage_key = storage["source_storage_key"]
    if storage_key.startswith("/") or ".." in Path(storage_key).parts:
        raise IngestionError(
            status_code=422,
            error_code="cx.source_storage_key_invalid",
            detail="source_storage_key must be a relative safe storage key.",
        )

    computed_sha256 = sha256_bytes(source_bytes)
    if computed_sha256 != record["source_sha256"]:
        raise IngestionError(
            status_code=409,
            error_code="cx.source_checksum_mismatch",
            detail="Source content checksum did not match upload registration.",
            retryable=False,
        )

    source_path = Path(storage["source_storage_path"])
    if not source_path.is_absolute():
        raise IngestionError(
            status_code=422,
            error_code="cx.source_storage_path_invalid",
            detail="source_storage_path must be absolute for local materialization.",
        )

    source_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.exists():
        existing_sha256 = sha256_bytes(source_path.read_bytes())
        if existing_sha256 != record["source_sha256"]:
            raise IngestionError(
                status_code=409,
                error_code="cx.source_file_collision",
                detail="Existing source file checksum differs from upload registration.",
            )
        return _utc_now()

    source_path.write_bytes(source_bytes)
    return _utc_now()


def storage_paths_for_document(
    *,
    storage_config: CxStorageConfig,
    filename: str,
    source_sha256: str,
    document_id: str,
    source_file_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, str]:
    date_partition = storage_date_partition(created_at)
    shard_one = source_sha256[:2]
    shard_two = source_sha256[2:4]
    stored_extension = stored_extension_for(filename)
    storage_object_id = source_file_id or document_id
    stored_filename = f"{storage_object_id}{stored_extension}"
    source_storage_key = f"{date_partition}/{shard_one}/{shard_two}/{stored_filename}"
    return {
        "source_storage_backend": "local_filesystem",
        "source_storage_key": source_storage_key,
        "source_storage_path": str(storage_config.source_root / source_storage_key),
        "stored_filename": stored_filename,
        "stored_extension": stored_extension,
        "extracted_markdown_path": str(
            storage_config.extracted_markdown_root / shard_one / f"{document_id}.md"
        ),
        "extraction_temp_path": str(storage_config.extraction_temp_root / document_id),
    }


def storage_date_partition(created_at: str | None) -> str:
    if (
        isinstance(created_at, str)
        and len(created_at) >= 10
        and created_at[4] == "-"
        and created_at[7] == "-"
    ):
        return created_at[:10].replace("-", "")
    return _utc_now()[:10].replace("-", "")


def stored_extension_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if (
        suffix.startswith(".")
        and 1 < len(suffix) <= 32
        and all(char.isalnum() or char in "._-" for char in suffix[1:])
    ):
        return suffix
    return ""


def sanitize_filename(filename: str) -> str:
    cleaned = filename.strip()
    if not cleaned:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_filename_invalid",
            detail="filename must be a non-empty basename.",
        )
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_filename_invalid",
            detail="filename must not contain path separators.",
        )
    if "\x00" in cleaned:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_filename_invalid",
            detail="filename must not contain control characters.",
        )
    if len(cleaned) > 255:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_filename_invalid",
            detail="filename must be 255 characters or fewer.",
        )
    return cleaned


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_content_from_payload(payload: dict[str, Any]) -> tuple[str | None, bytes | None]:
    content_text = payload.get("content_text")
    content_base64 = payload.get("content_base64")
    if content_text is not None and content_base64 is not None:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_content_source_conflict",
            detail="Provide only one of content_text or content_base64.",
        )
    if content_text is not None:
        if not isinstance(content_text, str):
            raise IngestionError(
                status_code=422,
                error_code="cx.upload_content_text_invalid",
                detail="content_text must be a string when provided.",
            )
        return content_text, None
    if content_base64 is None:
        return None, None
    if not isinstance(content_base64, str) or not content_base64.strip():
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_content_base64_invalid",
            detail="content_base64 must be a non-empty base64 string.",
        )
    try:
        return None, base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_content_base64_invalid",
            detail="content_base64 must be valid base64.",
        ) from exc


def payload_source_kind(
    *,
    content_text: str | None,
    source_bytes: bytes | None,
) -> str:
    if content_text is not None:
        return "content_text"
    if source_bytes is not None:
        return "content_base64"
    return "precomputed_hash"


def validate_upload_size(size_bytes: int, *, max_upload_size_bytes: int) -> None:
    if size_bytes > max_upload_size_bytes:
        raise IngestionError(
            status_code=413,
            error_code="cx.upload_size_exceeds_limit",
            detail=f"size_bytes must be <= {max_upload_size_bytes}.",
        )


def build_upload_ownership_ref(payload: Mapping[str, Any]) -> dict[str, Any]:
    ownership_ref = payload.get("ownership_ref")
    if ownership_ref is not None and not isinstance(ownership_ref, Mapping):
        raise _upload_owner_invalid("ownership_ref must be an object when supplied.")
    ownership_payload = ownership_ref or {}
    _validate_ownership_envelope_metadata(ownership_payload)
    tenant_ref = _subject_ref_from_payload(
        payload,
        ownership_payload,
        field_name="tenant_ref",
        expected_type=OA_TENANT_SUBJECT_TYPE,
        legacy_fields=("tenant_id",),
        default_id=DEFAULT_TENANT_ID,
    )
    owner_subject_ref = _subject_ref_from_payload(
        payload,
        ownership_payload,
        field_name="owner_subject_ref",
        expected_type=OA_USER_SUBJECT_TYPE,
        legacy_fields=("owner_user_id", "user_id"),
        default_id=DEFAULT_OWNER_USER_ID,
    )
    uploaded_by_subject_ref = _subject_ref_from_payload(
        payload,
        ownership_payload,
        field_name="uploaded_by_subject_ref",
        expected_type=OA_USER_SUBJECT_TYPE,
        legacy_fields=("uploaded_by_user_id",),
        default_id=owner_subject_ref["id"],
    )
    _validate_ownership_legacy_map(
        ownership_payload,
        tenant_ref=tenant_ref,
        owner_subject_ref=owner_subject_ref,
    )
    return build_source_ownership_ref(
        tenant_id=tenant_ref["id"],
        owner_user_id=owner_subject_ref["id"],
        uploaded_by_user_id=uploaded_by_subject_ref["id"],
    )


def resolve_upload_ownership(
    ownership_ref: dict[str, Any],
    *,
    owner_resolver: SubjectRegistryResolver | None,
    owner_resolver_mode: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    mode = normalize_upload_owner_resolver_mode(owner_resolver_mode)
    if mode == UPLOAD_OWNER_RESOLVER_DISABLED:
        return None
    if owner_resolver is None:
        raise IngestionError(
            status_code=503,
            error_code="cx.upload_owner_resolver_unavailable",
            detail="CX upload owner resolver is enabled but not configured.",
            retryable=True,
        )
    try:
        return owner_resolver.resolve_ownership_ref(
            ownership_ref,
            request_id=request_id,
            trace_id=trace_id,
            ensure=False,
        )
    except SubjectRegistryResolverError as exc:
        raise IngestionError(
            status_code=exc.status_code,
            error_code="cx.upload_owner_unresolved",
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc


def normalize_upload_owner_resolver_mode(value: str | None) -> str:
    mode = (value or UPLOAD_OWNER_RESOLVER_DISABLED).strip().lower()
    if mode not in UPLOAD_OWNER_RESOLVER_MODES:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_owner_resolver_mode_invalid",
            detail=(
                f"{UPLOAD_OWNER_RESOLVER_MODE_ENV} must be one of: "
                f"{', '.join(sorted(UPLOAD_OWNER_RESOLVER_MODES))}."
            ),
        )
    return mode


def _ownership_ref_from_upload_record(record: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    ownership = record.get("ownership")
    if isinstance(ownership, Mapping):
        payload.update(
            {
                key: ownership[key]
                for key in ("tenant_id", "owner_user_id")
                if key in ownership
            }
        )
    if "ownership_ref" in record:
        payload["ownership_ref"] = record["ownership_ref"]
    return build_upload_ownership_ref(payload)


def _validate_ownership_envelope_metadata(
    ownership_payload: Mapping[str, Any],
) -> None:
    unknown_fields = sorted(set(ownership_payload) - OWNERSHIP_REF_ALLOWED_FIELDS)
    if unknown_fields:
        raise _upload_owner_invalid(
            "ownership_ref contains unsupported fields: "
            f"{', '.join(unknown_fields)}."
        )
    schema_version = ownership_payload.get("ownership_schema_version")
    if (
        schema_version is not None
        and schema_version != CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION
    ):
        raise _upload_owner_invalid(
            "ownership_ref.ownership_schema_version must be "
            f"{CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION}."
        )
    compatibility_mode = ownership_payload.get("compatibility_mode")
    if compatibility_mode is not None and compatibility_mode != OWNERSHIP_COMPATIBILITY_MODE:
        raise _upload_owner_invalid(
            f"ownership_ref.compatibility_mode must be {OWNERSHIP_COMPATIBILITY_MODE}."
        )


def _subject_ref_from_payload(
    payload: Mapping[str, Any],
    ownership_payload: Mapping[str, Any],
    *,
    field_name: str,
    expected_type: str,
    legacy_fields: tuple[str, ...],
    default_id: str,
) -> dict[str, str]:
    if field_name in ownership_payload:
        subject_ref = _required_subject_ref(
            ownership_payload[field_name],
            field_name=f"ownership_ref.{field_name}",
            expected_type=expected_type,
        )
    elif field_name in payload:
        subject_ref = _required_subject_ref(
            payload[field_name],
            field_name=field_name,
            expected_type=expected_type,
        )
    else:
        subject_ref = {
            "type": expected_type,
            "id": _first_legacy_subject_id(
                payload,
                legacy_fields=legacy_fields,
                default_id=default_id,
            ),
        }

    if field_name in ownership_payload and field_name in payload:
        direct_ref = _required_subject_ref(
            payload[field_name],
            field_name=field_name,
            expected_type=expected_type,
        )
        _ensure_matching_subject_ref(
            subject_ref,
            direct_ref,
            field_name=field_name,
        )
    for legacy_field in legacy_fields:
        if legacy_field in payload:
            legacy_id = _owner_string(
                payload,
                legacy_field,
                default=subject_ref["id"],
            )
            if legacy_id != subject_ref["id"]:
                raise _upload_owner_invalid(
                    f"{legacy_field} must match {field_name}.id when both are supplied."
                )
    return subject_ref


def _first_legacy_subject_id(
    payload: Mapping[str, Any],
    *,
    legacy_fields: tuple[str, ...],
    default_id: str,
) -> str:
    for legacy_field in legacy_fields:
        if legacy_field in payload:
            return _owner_string(payload, legacy_field, default=default_id)
    return _owner_string({legacy_fields[0]: default_id}, legacy_fields[0], default=default_id)


def _required_subject_ref(
    value: Any,
    *,
    field_name: str,
    expected_type: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _upload_owner_invalid(f"{field_name} must be an object.")
    unknown_fields = sorted(set(value) - SUBJECT_REF_ALLOWED_FIELDS)
    if unknown_fields:
        raise _upload_owner_invalid(
            f"{field_name} contains unsupported fields: {', '.join(unknown_fields)}."
        )
    subject_type = _owner_string(value, "type")
    if subject_type != expected_type:
        raise _upload_owner_invalid(f"{field_name}.type must be {expected_type}.")
    return {
        "type": subject_type,
        "id": _owner_string(value, "id"),
    }


def _validate_ownership_legacy_map(
    ownership_payload: Mapping[str, Any],
    *,
    tenant_ref: Mapping[str, str],
    owner_subject_ref: Mapping[str, str],
) -> None:
    legacy = ownership_payload.get("legacy")
    if legacy is None:
        return
    if not isinstance(legacy, Mapping):
        raise _upload_owner_invalid("ownership_ref.legacy must be an object.")
    unknown_fields = sorted(set(legacy) - OWNERSHIP_LEGACY_ALLOWED_FIELDS)
    if unknown_fields:
        raise _upload_owner_invalid(
            "ownership_ref.legacy contains unsupported fields: "
            f"{', '.join(unknown_fields)}."
        )
    _ensure_legacy_ref_match(
        legacy,
        legacy_field="tenant_id",
        expected_id=tenant_ref["id"],
        canonical_field="tenant_ref",
    )
    _ensure_legacy_ref_match(
        legacy,
        legacy_field="owner_user_id",
        expected_id=owner_subject_ref["id"],
        canonical_field="owner_subject_ref",
    )


def _ensure_legacy_ref_match(
    legacy: Mapping[str, Any],
    *,
    legacy_field: str,
    expected_id: str,
    canonical_field: str,
) -> None:
    if legacy_field not in legacy:
        return
    legacy_id = _owner_string(legacy, legacy_field, default=expected_id)
    if legacy_id != expected_id:
        raise _upload_owner_invalid(
            f"ownership_ref.legacy.{legacy_field} must match {canonical_field}.id."
        )


def _ensure_matching_subject_ref(
    expected_ref: Mapping[str, str],
    actual_ref: Mapping[str, str],
    *,
    field_name: str,
) -> None:
    if dict(expected_ref) != dict(actual_ref):
        raise _upload_owner_invalid(f"{field_name} must match ownership_ref.{field_name}.")


def _owner_string(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    default: str | None = None,
) -> str:
    value = payload.get(field_name, default) if default is not None else payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _upload_owner_invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _upload_owner_invalid(detail: str) -> IngestionError:
    return IngestionError(
        status_code=422,
        error_code="cx.upload_owner_invalid",
        detail=detail,
    )


def _source_sha256_from_payload(
    payload: dict[str, Any],
    content_text: str | None,
    source_bytes: bytes | None,
) -> str:
    computed_sha256: str | None = None
    if content_text is not None:
        computed_sha256 = sha256_text(content_text)
    if source_bytes is not None:
        computed_sha256 = sha256_bytes(source_bytes)

    if computed_sha256 is not None:
        if "source_sha256" not in payload:
            return computed_sha256
        provided_sha256 = _normalized_source_sha256(payload["source_sha256"])
        if provided_sha256 != computed_sha256:
            raise IngestionError(
                status_code=422,
                error_code="cx.upload_hash_mismatch",
                detail="source_sha256 must match the provided upload content.",
            )
        return computed_sha256

    return _normalized_source_sha256(_required_string(payload, "source_sha256"))


def _normalized_source_sha256(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_hash_invalid",
            detail="source_sha256 must be a 64-character hex string.",
        )
    source_sha256 = value.strip().lower()
    if len(source_sha256) == 64 and all(
        char in "0123456789abcdef" for char in source_sha256
    ):
        return source_sha256

    raise IngestionError(
        status_code=422,
        error_code="cx.upload_hash_invalid",
        detail="source_sha256 must be a 64-character hex string.",
    )


def _size_bytes_from_payload(
    payload: dict[str, Any],
    content_text: str | None,
    source_bytes: bytes | None,
) -> int:
    computed_size: int | None = None
    if content_text is not None:
        computed_size = len(content_text.encode("utf-8"))
    if source_bytes is not None:
        computed_size = len(source_bytes)

    if "size_bytes" not in payload:
        if computed_size is not None:
            return computed_size
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_size_required",
            detail="size_bytes is required when content_text is not provided.",
        )

    size_bytes = payload["size_bytes"]
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_size_invalid",
            detail="size_bytes must be a non-negative integer.",
        )
    if computed_size is not None and size_bytes != computed_size:
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_size_mismatch",
            detail="size_bytes must match the provided upload content.",
        )
    return size_bytes


def _required_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            status_code=422,
            error_code=f"cx.{field_name}_required",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value


def _optional_string(
    payload: dict[str, Any],
    field_name: str,
    default: str,
) -> str:
    value = payload.get(field_name, default)
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            status_code=422,
            error_code=f"cx.{field_name}_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _positive_int(
    value: str | None,
    *,
    default: int,
    field_name: str,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _non_negative_int(
    value: str | None,
    *,
    default: int,
    field_name: str,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _source_file_id(source_sha256: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-source-file:{source_sha256}"))


def _document_id(tenant_id: str, owner_user_id: str, source_sha256: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-document:{tenant_id}:{owner_user_id}:{source_sha256}"))


def _upload_id(document_id: str, request_id: str, trace_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-upload:{document_id}:{request_id}:{trace_id}"))


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _ingestion_problem_response(
    request: Request,
    exc: IngestionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Content ingestion request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/content-ingestion-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
