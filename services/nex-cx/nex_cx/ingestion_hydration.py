from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_ingestion_job,
    build_upload_registration,
    restore_upload_registration_lineage,
    sha256_text,
)
from nex_cx.document_blob_store import (
    CxDocumentBlobError,
    DOCUMENT_BLOB_URI_PREFIX,
)
from nex_cx.lexical_index import build_tokenizer_profile


CX_INGESTION_HYDRATION_SCHEMA_VERSION = "cx_ingestion_hydration.v1"
MARKDOWN_STORAGE_URI_PREFIX = "local://cx/extracted-markdown/"


@dataclass(frozen=True)
class IngestionHydrationError(Exception):
    error_code: str
    detail: str
    status_code: int = 409
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def hydrate_ingestion_runtime(
    run: Mapping[str, Any],
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
) -> dict[str, Any]:
    document_id = _required_string(run.get("document_id"), "document_id")
    job_id = _required_string(run.get("job_id"), "job_id")
    upload_id = _required_string(run.get("idempotency_key"), "idempotency_key")
    request_id = _required_string(run.get("request_id"), "request_id")
    trace_id = _required_string(run.get("trace_id"), "trace_id")
    content_object = store.content_repository.get_content_object(document_id)
    if content_object is None:
        raise IngestionHydrationError(
            error_code="cx.ingestion_hydration.document_not_found",
            detail="Durable ingestion content metadata was not found.",
            status_code=404,
        )
    _assert_owner_lineage(run, content_object)
    if str(content_object["upload_id"]) != upload_id:
        raise _lineage_conflict("Persisted upload identity does not match the run.")
    source_file = store.content_repository.get_source_file(
        str(content_object["source_file_id"])
    )
    if source_file is None:
        raise _lineage_conflict("Persisted source-file lineage is incomplete.")

    registration = _registration_from_persistence(
        content_object=content_object,
        source_file=source_file,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )
    job = build_ingestion_job(
        document_id=document_id,
        upload_id=upload_id,
        request_id=request_id,
        trace_id=trace_id,
        created_at=str(run.get("created_at") or content_object["created_at"]),
    )
    if job["job_id"] != job_id:
        raise _lineage_conflict("Persisted ingestion job identity does not match the run.")
    registration["ingestion_job"] = job
    registration["extraction"]["job_id"] = job_id
    store.documents[document_id] = registration
    store.jobs[job_id] = job
    store.document_content_refs[document_id] = {
        "source_file_id": str(source_file["source_file_id"]),
        "content_object_id": document_id,
    }

    artifact = store.content_repository.find_latest_extraction_artifact(
        content_object_id=document_id
    )
    chunk_set = store.content_repository.find_latest_chunk_set(
        content_object_id=document_id
    )
    markdown_text: str | None = None
    if artifact is not None:
        markdown_path = _markdown_path(
            artifact,
            storage_config=storage_config,
            document_id=document_id,
        )
        markdown_text = _read_verified_markdown(
            markdown_path,
            artifact,
            store=store,
            content_object=content_object,
        )
        extraction = _extraction_result(
            artifact,
            content_object=content_object,
            job_id=job_id,
            request_id=request_id,
            trace_id=trace_id,
            markdown_path=markdown_path,
            markdown_text=markdown_text,
        )
        store.extraction_results[document_id] = extraction
        registration["extraction"] = {
            **registration["extraction"],
            "status": str(artifact["status"]),
            "markdown_available": True,
        }
    if chunk_set is not None:
        if artifact is None or markdown_text is None:
            raise _lineage_conflict(
                "Persisted chunk metadata has no extraction artifact lineage."
            )
        public_chunk_set, private_texts = _chunk_runtime_state(
            chunk_set,
            artifact=artifact,
            job_id=job_id,
            request_id=request_id,
            trace_id=trace_id,
            markdown_text=markdown_text,
        )
        store.chunk_sets[document_id] = public_chunk_set
        store.chunk_texts.update(private_texts)

    lexical = None
    if chunk_set is not None:
        lexical = _find_persisted_lexical_index(
            store,
            chunk_set_id=str(chunk_set["chunk_set_id"]),
            storage_config=storage_config,
        )
        if lexical is not None:
            store.lexical_indexes[document_id] = _lexical_runtime_state(
                lexical,
                document_id=document_id,
                chunk_set=chunk_set,
                request_id=request_id,
                trace_id=trace_id,
            )

    return {
        "hydration_schema_version": CX_INGESTION_HYDRATION_SCHEMA_VERSION,
        "document_id": document_id,
        "upload_id": upload_id,
        "job_id": job_id,
        "source_file_hydrated": True,
        "extraction_hydrated": artifact is not None,
        "chunk_set_hydrated": chunk_set is not None,
        "private_chunk_count": len(store.chunk_texts) if chunk_set is not None else 0,
        "lexical_index_hydrated": lexical is not None,
        "private_payload_in_evidence": False,
    }


def _registration_from_persistence(
    *,
    content_object: Mapping[str, Any],
    source_file: Mapping[str, Any],
    storage_config: CxStorageConfig,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    ownership_ref = content_object["ownership_ref"]
    candidate = build_upload_registration(
        {
            "filename": content_object["original_filename"],
            "content_type": content_object["content_type"],
            "source_sha256": content_object["source_sha256"],
            "size_bytes": content_object["size_bytes"],
            "ownership_ref": ownership_ref,
        },
        storage_config=storage_config,
        request_id=request_id,
        trace_id=trace_id,
    )
    return restore_upload_registration_lineage(
        candidate,
        content_object=content_object,
        source_file=source_file,
    )


def _assert_owner_lineage(
    run: Mapping[str, Any],
    content_object: Mapping[str, Any],
) -> None:
    run_tenant = run.get("tenant_ref")
    run_owner = run.get("owner_subject_ref")
    ownership = content_object.get("ownership_ref")
    if (
        not isinstance(run_tenant, Mapping)
        or not isinstance(run_owner, Mapping)
        or not isinstance(ownership, Mapping)
        or run_tenant != ownership.get("tenant_ref")
        or run_owner != ownership.get("owner_subject_ref")
    ):
        raise _lineage_conflict("Persisted owner lineage does not match the run.")


def _markdown_path(
    artifact: Mapping[str, Any],
    *,
    storage_config: CxStorageConfig,
    document_id: str,
) -> Path:
    uri = artifact.get("markdown_storage_uri")
    if isinstance(uri, str) and uri.startswith(DOCUMENT_BLOB_URI_PREFIX):
        digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        return (
            storage_config.extraction_temp_root
            / "hydrated"
            / digest[:2]
            / f"{digest}.md"
        )
    if not isinstance(uri, str) or not uri.startswith(MARKDOWN_STORAGE_URI_PREFIX):
        raise _lineage_conflict("Persisted Markdown storage URI is invalid.")
    relative = Path(uri.removeprefix(MARKDOWN_STORAGE_URI_PREFIX))
    if relative.is_absolute() or ".." in relative.parts:
        raise _lineage_conflict("Persisted Markdown storage URI escapes its root.")
    root = storage_config.extracted_markdown_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise _lineage_conflict(
            "Persisted Markdown storage URI escapes its root."
        ) from exc
    return path


def _read_verified_markdown(
    markdown_path: Path,
    artifact: Mapping[str, Any],
    *,
    store: ContentIngestionStore,
    content_object: Mapping[str, Any],
) -> str:
    uri = artifact.get("markdown_storage_uri")
    if isinstance(uri, str) and uri.startswith(DOCUMENT_BLOB_URI_PREFIX):
        if store.document_blob_store is None:
            raise IngestionHydrationError(
                error_code="cx.ingestion_hydration.object_store_unavailable",
                detail="CX document object storage is not configured.",
                status_code=503,
                retryable=True,
            )
        ownership = content_object.get("ownership_ref")
        if not isinstance(ownership, Mapping):
            raise _lineage_conflict("Persisted document ownership is invalid.")
        tenant_ref = ownership.get("tenant_ref")
        owner_ref = ownership.get("owner_subject_ref")
        if not isinstance(tenant_ref, Mapping) or not isinstance(owner_ref, Mapping):
            raise _lineage_conflict("Persisted document ownership is invalid.")
        try:
            markdown_text = store.document_blob_store.get_markdown(
                storage_uri=uri,
                tenant_id=_required_string(tenant_ref.get("id"), "tenant_ref.id"),
                subject_id=_required_string(
                    owner_ref.get("id"), "owner_subject_ref.id"
                ),
                document_id=str(content_object["content_object_id"]),
                expected_sha256=str(artifact["markdown_sha256"]),
            )
        except CxDocumentBlobError as exc:
            raise IngestionHydrationError(
                error_code=exc.error_code,
                detail=exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        if markdown_text is None:
            raise IngestionHydrationError(
                error_code="cx.ingestion_hydration.markdown_unavailable",
                detail="Persisted extracted Markdown is unavailable.",
                status_code=503,
                retryable=True,
            )
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_text, encoding="utf-8")
    else:
        try:
            markdown_text = markdown_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise IngestionHydrationError(
                error_code="cx.ingestion_hydration.markdown_unavailable",
                detail="Persisted extracted Markdown is unavailable.",
                status_code=503,
                retryable=True,
            ) from exc
    if sha256_text(markdown_text) != artifact.get("markdown_sha256"):
        raise _lineage_conflict("Persisted extracted Markdown failed integrity validation.")
    return markdown_text


def _extraction_result(
    artifact: Mapping[str, Any],
    *,
    content_object: Mapping[str, Any],
    job_id: str,
    request_id: str,
    trace_id: str,
    markdown_path: Path,
    markdown_text: str,
) -> dict[str, Any]:
    return {
        "extraction_schema_version": "cx_text_extraction.v1",
        "document_id": str(content_object["content_object_id"]),
        "job_id": job_id,
        "status": str(artifact["status"]),
        "trace_id": trace_id,
        "request_id": request_id,
        "source_sha256": str(content_object["source_sha256"]),
        "extracted_markdown_sha256": str(artifact["markdown_sha256"]),
        "extracted_markdown_path": str(markdown_path),
        "markdown_char_count": int(artifact["markdown_char_count"]),
        "markdown_preview": markdown_text[:120],
        "extractor": {
            "provider": str(artifact["extractor_name"]),
            "mode": "durable_reload",
            "version": str(artifact["extractor_version"]),
            "source_format": Path(str(content_object["original_filename"])).suffix,
        },
        "source_reader": "durable_markdown_artifact",
        "warnings": [],
        "created_at": str(artifact["created_at"]),
        "updated_at": str(artifact["updated_at"]),
    }


def _chunk_runtime_state(
    chunk_set: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    job_id: str,
    request_id: str,
    trace_id: str,
    markdown_text: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    if chunk_set.get("extraction_artifact_id") != artifact.get(
        "extraction_artifact_id"
    ) or chunk_set.get("source_markdown_sha256") != artifact.get("markdown_sha256"):
        raise _lineage_conflict("Persisted chunk set does not match the Markdown artifact.")
    chunks = list(chunk_set.get("chunks") or [])
    private_texts: dict[str, str] = {}
    for chunk in chunks:
        start = int(chunk["start_offset"])
        end = int(chunk["end_offset"])
        if start < 0 or end < start or end > len(markdown_text):
            raise _lineage_conflict("Persisted chunk offsets are invalid.")
        text = markdown_text[start:end]
        if sha256_text(text) != chunk.get("text_sha256"):
            raise _lineage_conflict("Reconstructed private chunk text failed integrity validation.")
        private_texts[str(chunk["chunk_id"])] = text
    public = {
        "chunk_set_schema_version": "cx_chunk_set.v1",
        "document_id": str(chunk_set["content_object_id"]),
        "extraction_job_id": job_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "chunk_policy": str(chunk_set["chunk_policy_id"]),
        "chunk_size": int(chunk_set["chunk_size"]),
        "chunk_overlap": int(chunk_set["chunk_overlap"]),
        "source_markdown_sha256": str(chunk_set["source_markdown_sha256"]),
        "chunk_count": int(chunk_set["chunk_count"]),
        "chunks": chunks,
        "created_at": str(chunk_set["created_at"]),
        "updated_at": str(chunk_set["created_at"]),
    }
    return public, private_texts


def _find_persisted_lexical_index(
    store: ContentIngestionStore,
    *,
    chunk_set_id: str,
    storage_config: CxStorageConfig,
) -> dict[str, Any] | None:
    for tokenizer in dict.fromkeys(
        (storage_config.bm25_tokenizer, storage_config.bm25_tokenizer_fallback)
    ):
        lexical = store.content_repository.find_lexical_index(
            chunk_set_id=chunk_set_id,
            tokenizer_used=tokenizer,
        )
        if lexical is not None:
            return lexical
    return None


def _lexical_runtime_state(
    lexical: Mapping[str, Any],
    *,
    document_id: str,
    chunk_set: Mapping[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    ordinals = {
        str(chunk["chunk_id"]): int(chunk["ordinal"])
        for chunk in chunk_set.get("chunks") or []
    }
    postings = [
        {
            "term": str(term["term"]),
            "document_frequency": int(term["document_frequency"]),
            "occurrences": [
                {
                    "chunk_id": str(posting["chunk_id"]),
                    "ordinal": ordinals[str(posting["chunk_id"])],
                    "count": int(posting["occurrence_count"]),
                }
                for posting in term["postings"]
            ],
        }
        for term in lexical["terms"]
    ]
    tokenizer_requested = str(lexical["tokenizer_requested"])
    tokenizer_used = str(lexical["tokenizer_used"])
    tokenizer_fallback = str(lexical["tokenizer_fallback"])
    fallback_used = bool(lexical["fallback_used"])
    created_at = str(lexical["created_at"])
    return {
        "lexical_index_schema_version": "cx_lexical_index.v1",
        "document_id": document_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "tokenizer_requested": tokenizer_requested,
        "tokenizer_used": tokenizer_used,
        "tokenizer_fallback": tokenizer_fallback,
        "fallback_used": fallback_used,
        "tokenizer_profile": build_tokenizer_profile(
            tokenizer_requested=tokenizer_requested,
            tokenizer_used=tokenizer_used,
            tokenizer_fallback=tokenizer_fallback,
            fallback_used=fallback_used,
        ),
        "chunk_count": int(lexical["chunk_count"]),
        "unique_token_count": int(lexical["unique_token_count"]),
        "postings": postings,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionHydrationError(
            error_code="cx.ingestion_hydration.run_invalid",
            detail=f"{field_name} must be a non-empty string.",
            status_code=422,
        )
    return value.strip()


def _lineage_conflict(detail: str) -> IngestionHydrationError:
    return IngestionHydrationError(
        error_code="cx.ingestion_hydration.lineage_conflict",
        detail=detail,
        status_code=409,
    )
