from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

DEFAULT_DATA_ROOT = "/data/nex-platform"
DEFAULT_CHUNK_POLICY = "chunk_1000_100"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_BM25_TOKENIZER = "mecab_ko"
DEFAULT_BM25_TOKENIZER_FALLBACK = "korean_mixed_v1"


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


@dataclass
class ContentIngestionStore:
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_texts: dict[str, str] = field(default_factory=dict)
    extraction_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_texts: dict[str, str] = field(default_factory=dict)
    embedding_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    embedding_vectors: dict[str, list[float]] = field(default_factory=dict)
    lexical_indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    retrieval_packages: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save_upload_registration(
        self,
        record: dict[str, Any],
        *,
        source_text: str | None = None,
    ) -> dict[str, Any]:
        self.documents[record["document_id"]] = record
        self.jobs[record["extraction"]["job_id"]] = record["ingestion_job"]
        if source_text is not None:
            self.source_texts[record["upload_id"]] = source_text
        return record

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents.get(document_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def get_source_text(self, upload_id: str) -> str | None:
        return self.source_texts.get(upload_id)

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
        return chunk_set

    def get_chunk_set(self, document_id: str) -> dict[str, Any] | None:
        return self.chunk_sets.get(document_id)

    def get_chunk_text(self, chunk_id: str) -> str | None:
        return self.chunk_texts.get(chunk_id)

    def save_embedding_index(
        self,
        embedding_index: dict[str, Any],
        *,
        embedding_vectors: dict[str, list[float]],
    ) -> dict[str, Any]:
        self.embedding_indexes[embedding_index["document_id"]] = embedding_index
        self.embedding_vectors.update(embedding_vectors)
        return embedding_index

    def get_embedding_index(self, document_id: str) -> dict[str, Any] | None:
        return self.embedding_indexes.get(document_id)

    def get_embedding_vector(self, chunk_id: str) -> list[float] | None:
        return self.embedding_vectors.get(chunk_id)

    def save_lexical_index(self, lexical_index: dict[str, Any]) -> dict[str, Any]:
        self.lexical_indexes[lexical_index["document_id"]] = lexical_index
        return lexical_index

    def get_lexical_index(self, document_id: str) -> dict[str, Any] | None:
        return self.lexical_indexes.get(document_id)

    def save_retrieval_package(self, package: dict[str, Any]) -> dict[str, Any]:
        self.retrieval_packages[package["retrieval_package_id"]] = package
        return package

    def get_retrieval_package(self, retrieval_package_id: str) -> dict[str, Any] | None:
        return self.retrieval_packages.get(retrieval_package_id)


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
    )


def register_ingestion_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore | None = None,
    storage_config: CxStorageConfig | None = None,
) -> None:
    ingestion_store = store or DEFAULT_INGESTION_STORE
    config = storage_config or build_storage_config()

    @app.post("/api/v1/documents/uploads", response_model=None)
    def register_upload(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            record = build_upload_registration(
                payload,
                storage_config=config,
                request_id=request_id_from_headers(request),
                trace_id=payload.get("trace_id") or trace_id_from_headers(request),
            )
        except IngestionError as exc:
            return _ingestion_problem_response(request, exc)

        source_text = payload.get("content_text")
        return JSONResponse(
            status_code=202,
            content=ingestion_store.save_upload_registration(
                record,
                source_text=source_text if isinstance(source_text, str) else None,
            ),
        )

    @app.get("/api/v1/documents/{document_id}", response_model=None)
    def get_document(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = ingestion_store.get_document(document_id)
        if record is None:
            return _ingestion_problem_response(
                request,
                IngestionError(
                    status_code=404,
                    error_code="cx.document_not_found",
                    detail=f"Document registration was not found: {document_id}",
                ),
            )
        return record

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
    content_text = payload.get("content_text")
    if content_text is not None and not isinstance(content_text, str):
        raise IngestionError(
            status_code=422,
            error_code="cx.upload_content_text_invalid",
            detail="content_text must be a string when provided.",
        )

    source_sha256 = _source_sha256_from_payload(payload, content_text)
    size_bytes = _size_bytes_from_payload(payload, content_text)
    created_at = _utc_now()
    document_id = _document_id(filename, content_type, source_sha256)
    upload_id = _upload_id(document_id, request_id, trace_id)
    paths = storage_paths_for_document(
        storage_config=storage_config,
        filename=filename,
        source_sha256=source_sha256,
        document_id=document_id,
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
        "storage": paths,
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
        "ingestion_job": job,
        "created_at": created_at,
        "updated_at": created_at,
    }


def build_ingestion_job(
    *,
    document_id: str,
    upload_id: str,
    request_id: str,
    trace_id: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "job_schema_version": "common_job.v1",
        "job_id": str(uuid5(NAMESPACE_URL, f"cx-ingestion-job:{upload_id}")),
        "job_type": "cx.document_ingestion",
        "status": "QUEUED",
        "trace_id": trace_id,
        "request_id": request_id,
        "subject_ref": {
            "type": "cx.document",
            "id": document_id,
        },
        "idempotency_key": upload_id,
        "attempt_count": 0,
        "max_attempts": 1,
        "retryable": True,
        "links": {
            "document": f"/api/v1/documents/{document_id}",
        },
        "created_at": created_at,
        "updated_at": created_at,
    }


def run_text_extraction_job(
    job_id: str,
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
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

    source_text = store.get_source_text(document["upload_id"])
    if source_text is None:
        raise IngestionError(
            status_code=409,
            error_code="cx.source_content_unavailable",
            detail="Mock extraction requires content_text captured at upload registration.",
        )

    markdown_text = markdown_from_source_text(
        source_text,
        filename=document["filename"],
        content_type=document["content_type"],
    )
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
            "provider": "local_mock",
            "mode": "content_text_to_markdown",
            "version": "slice-0012",
        },
        "created_at": now,
        "updated_at": now,
    }
    return store.save_extraction_result(result)


def markdown_from_source_text(
    source_text: str,
    *,
    filename: str,
    content_type: str,
) -> str:
    stripped = source_text.strip()
    if not stripped:
        return f"# {filename}\n\n"
    if filename.lower().endswith(".md") or content_type == "text/markdown":
        return _ensure_trailing_newline(stripped)
    return _ensure_trailing_newline(f"# {filename}\n\n{stripped}")


def write_extracted_markdown(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def storage_paths_for_document(
    *,
    storage_config: CxStorageConfig,
    filename: str,
    source_sha256: str,
    document_id: str,
    created_at: str | None = None,
) -> dict[str, str]:
    date_partition = storage_date_partition(created_at)
    shard_one = source_sha256[:2]
    shard_two = source_sha256[2:4]
    stored_extension = stored_extension_for(filename)
    stored_filename = f"{document_id}{stored_extension}"
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


def _source_sha256_from_payload(payload: dict[str, Any], content_text: str | None) -> str:
    if content_text is not None:
        return sha256_text(content_text)

    source_sha256 = _required_string(payload, "source_sha256").lower()
    if len(source_sha256) == 64 and all(char in "0123456789abcdef" for char in source_sha256):
        return source_sha256

    raise IngestionError(
        status_code=422,
        error_code="cx.upload_hash_invalid",
        detail="source_sha256 must be a 64-character hex string.",
    )


def _size_bytes_from_payload(payload: dict[str, Any], content_text: str | None) -> int:
    if "size_bytes" not in payload:
        if content_text is not None:
            return len(content_text.encode("utf-8"))
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


def _document_id(filename: str, content_type: str, source_sha256: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-document:{filename}:{content_type}:{source_sha256}"))


def _upload_id(document_id: str, request_id: str, trace_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cx-upload:{document_id}:{request_id}:{trace_id}"))


def _ensure_trailing_newline(value: str) -> str:
    if value.endswith("\n"):
        return value
    return f"{value}\n"


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
