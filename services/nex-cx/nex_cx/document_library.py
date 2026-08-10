from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from nex_cx.repository import (
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    OA_TENANT_REF_TYPE,
    OA_USER_SUBJECT_REF_TYPE,
    bounded_content_object_query_limit,
)

if TYPE_CHECKING:
    from nex_cx.ingestion import ContentIngestionStore


CX_DOCUMENT_LIBRARY_PROJECTION_SCHEMA_VERSION = "cx_document_library_projection.v1"
CX_DOCUMENT_LIBRARY_ITEM_SCHEMA_VERSION = "cx_document_library_item.v1"
CX_DOCUMENT_LIBRARY_QUERY_FILTER_SCHEMA_VERSION = "cx_document_library_query_filters.v1"


def build_document_library_query_filters(
    *,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
    limit: int | str | None = None,
) -> dict[str, Any]:
    normalized_tenant_id = _required_non_empty_text(
        tenant_id or DEFAULT_TENANT_ID,
        field_name="tenant_id",
    )
    normalized_owner_user_id = _required_non_empty_text(
        owner_user_id or DEFAULT_OWNER_USER_ID,
        field_name="owner_user_id",
    )
    return {
        "filter_schema_version": CX_DOCUMENT_LIBRARY_QUERY_FILTER_SCHEMA_VERSION,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": normalized_tenant_id},
        "owner_subject_ref": {
            "type": OA_USER_SUBJECT_REF_TYPE,
            "id": normalized_owner_user_id,
        },
        "lifecycle_status": "ACTIVE",
        "limit": bounded_content_object_query_limit(limit),
    }


def build_document_library_projection(
    *,
    store: ContentIngestionStore,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
    limit: int | str | None = None,
    source_kind: str = "repository",
    database_env: str | None = None,
    redacted_database_url: str | None = None,
) -> dict[str, Any]:
    filters = build_document_library_query_filters(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        limit=limit,
    )
    content_objects = store.content_repository.list_active_content_objects(
        tenant_id=filters["tenant_ref"]["id"],
        owner_user_id=filters["owner_subject_ref"]["id"],
        limit=filters["limit"],
    )
    documents = [
        project_document_library_item(store=store, content_object=content_object)
        for content_object in content_objects
    ]
    return {
        "projection_schema_version": CX_DOCUMENT_LIBRARY_PROJECTION_SCHEMA_VERSION,
        "service_id": "nex-cx",
        "source": {
            "source_kind": source_kind,
            "database_env": database_env,
            "redacted_database_url": redacted_database_url,
        },
        "filters": {
            "filter_schema_version": filters["filter_schema_version"],
            "tenant_ref": deepcopy(filters["tenant_ref"]),
            "owner_subject_ref": deepcopy(filters["owner_subject_ref"]),
            "lifecycle_status": filters["lifecycle_status"],
        },
        "pagination": {"limit": filters["limit"], "returned": len(documents)},
        "summary": {
            "document_count": len(documents),
            "summary_available_count": sum(
                1 for document in documents if document["summary"]["available"]
            ),
            "summary_embedding_available_count": sum(
                1
                for document in documents
                if document["summary_embedding"]["available"]
            ),
        },
        "documents": documents,
        "metadata": {
            "owner_scoped": True,
            "raw_source_included": False,
            "raw_summary_included": False,
            "embedding_vector_included": False,
            "storage_path_redacted": True,
        },
    }


def project_document_library_item(
    *,
    store: ContentIngestionStore,
    content_object: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = _required_non_empty_text(
        content_object.get("content_object_id"),
        field_name="content_object_id",
    )
    ownership_ref = _mapping_copy(content_object.get("ownership_ref"))
    summary = _latest_summary_record(store, document_id)
    summary_embedding = _latest_summary_embedding_record(
        store,
        document_id=document_id,
        summary=summary,
    )
    processing_run = _latest_processing_run_record(store, document_id)
    return {
        "document_library_schema_version": CX_DOCUMENT_LIBRARY_ITEM_SCHEMA_VERSION,
        "document_id": document_id,
        "upload_id": content_object.get("upload_id"),
        "tenant_ref": _mapping_copy(ownership_ref.get("tenant_ref")),
        "owner_subject_ref": _mapping_copy(ownership_ref.get("owner_subject_ref")),
        "uploaded_by_subject_ref": _mapping_copy(
            ownership_ref.get("uploaded_by_subject_ref")
        ),
        "filename": content_object.get("original_filename"),
        "content_type": content_object.get("content_type"),
        "size_bytes": _int_value(content_object.get("size_bytes")),
        "source_sha256": content_object.get("source_sha256"),
        "classification": content_object.get("classification"),
        "lifecycle_status": content_object.get("lifecycle_status"),
        "retrieval_policy": _mapping_copy(content_object.get("retrieval_policy")),
        "created_at": content_object.get("created_at"),
        "updated_at": content_object.get("updated_at"),
        "summary": _project_summary(summary),
        "summary_embedding": _project_summary_embedding(summary_embedding),
        "processing": _project_processing_run(processing_run),
        "links": {
            "cx_document": f"/api/v1/documents/{document_id}",
            "cx_summary": f"/api/v1/documents/{document_id}/summary",
            "cx_summary_embedding": (
                f"/api/v1/documents/{document_id}/summary-embedding"
            ),
            "cx_processing_runs": f"/api/v1/documents/{document_id}/processing/runs",
        },
        "metadata": {
            "raw_source_included": False,
            "raw_summary_included": False,
            "embedding_vector_included": False,
            "storage_path_redacted": True,
        },
    }


def _latest_summary_record(
    store: ContentIngestionStore,
    document_id: str,
) -> dict[str, Any] | None:
    summary = store.get_document_summary(document_id)
    if summary is not None:
        return summary
    return store.content_repository.get_latest_document_summary_record(document_id)


def _latest_summary_embedding_record(
    store: ContentIngestionStore,
    *,
    document_id: str,
    summary: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    embedding = store.get_summary_embedding_index(document_id)
    if embedding is not None:
        return embedding
    if summary is None:
        return None
    document_summary_id = _optional_non_empty_text(summary.get("document_summary_id"))
    if document_summary_id is None:
        return None
    return store.content_repository.get_latest_summary_embedding_record(
        document_summary_id,
    )


def _latest_processing_run_record(
    store: ContentIngestionStore,
    document_id: str,
) -> dict[str, Any] | None:
    processing_run = store.get_latest_document_processing_run(document_id)
    if processing_run is not None:
        return processing_run
    return store.content_repository.get_latest_processing_run_record(document_id)


def _project_summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    if summary is None:
        return {
            "available": False,
            "status": "NOT_AVAILABLE",
            "document_summary_id": None,
            "summary_text_sha256": None,
            "summary_preview": None,
            "summary_char_count": 0,
            "model_profile_id": None,
            "model_revision": None,
            "updated_at": None,
        }
    summarizer = _mapping_copy(summary.get("summarizer"))
    return {
        "available": True,
        "status": summary.get("status", "READY"),
        "document_summary_id": summary.get("document_summary_id"),
        "summary_text_sha256": summary.get("summary_text_sha256"),
        "summary_preview": summary.get("summary_preview"),
        "summary_char_count": _int_value(summary.get("summary_char_count")),
        "model_profile_id": summary.get("model_profile_id")
        or summarizer.get("model_profile_id"),
        "model_revision": summary.get("model_revision") or summarizer.get("model_revision"),
        "updated_at": summary.get("updated_at"),
    }


def _project_summary_embedding(
    summary_embedding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if summary_embedding is None:
        return {
            "available": False,
            "status": "NOT_AVAILABLE",
            "summary_embedding_id": None,
            "model_profile_id": None,
            "model_revision": None,
            "vector_dimension": None,
            "embedding_sha256": None,
            "created_at": None,
        }
    model_profile_id = summary_embedding.get("model_profile_id") or summary_embedding.get(
        "provider_alias"
    )
    return {
        "available": True,
        "status": summary_embedding.get("status", "READY"),
        "summary_embedding_id": summary_embedding.get("summary_embedding_id"),
        "model_profile_id": model_profile_id,
        "model_revision": summary_embedding.get("model_revision"),
        "vector_dimension": _positive_int_or_none(
            summary_embedding.get("vector_dimension")
        ),
        "embedding_sha256": summary_embedding.get("embedding_sha256"),
        "created_at": summary_embedding.get("created_at"),
    }


def _project_processing_run(
    processing_run: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if processing_run is None:
        return {
            "available": False,
            "latest_pipeline_run_id": None,
            "status": "NOT_AVAILABLE",
            "step_total": 0,
            "step_failed": 0,
            "updated_at": None,
        }
    step_summary = _mapping_copy(processing_run.get("step_summary"))
    return {
        "available": True,
        "latest_pipeline_run_id": processing_run.get("pipeline_run_id"),
        "status": processing_run.get("status"),
        "step_total": _int_value(
            processing_run.get("step_total", step_summary.get("total"))
        ),
        "step_failed": _int_value(
            processing_run.get("step_failed", step_summary.get("failed"))
        ),
        "updated_at": processing_run.get("updated_at"),
    }


def _required_non_empty_text(value: object, *, field_name: str) -> str:
    text = _optional_non_empty_text(value)
    if text is None:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return text


def _optional_non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_copy(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return deepcopy(dict(value))


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 1:
        return None
    return value
