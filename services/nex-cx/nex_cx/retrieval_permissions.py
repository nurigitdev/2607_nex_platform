from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.api_ownership import record_visible_to_owner


PERMISSION_POLICY_ID = "cx.private_owner_active.v1"
PERMISSION_SNAPSHOT_SCHEMA_VERSION = "cx_retrieval_permission_snapshot.v1"
PERMISSION_DECISION_SCHEMA_VERSION = "cx_retrieval_permission_decision.v1"


@dataclass(frozen=True)
class RetrievalPermissionError(ValueError):
    status_code: int
    error_code: str
    detail: str


def evaluate_retrieval_permission(
    access_context: CxAccessContext,
    content_object: object,
) -> dict[str, Any]:
    if not isinstance(content_object, Mapping):
        return _decision(visible=False, reason="RESOURCE_NOT_FOUND")
    if not record_visible_to_owner(access_context, content_object):
        return _decision(visible=False, reason="RESOURCE_NOT_FOUND")
    if content_object.get("lifecycle_status") != "ACTIVE":
        return _decision(visible=False, reason="RESOURCE_NOT_FOUND")
    return _decision(visible=True, reason="PRIVATE_OWNER_ACTIVE")


def filter_retrieval_document_scope(
    *,
    access_context: CxAccessContext,
    requested_document_ids: Sequence[str],
    content_objects: Mapping[str, object],
    require_all_visible: bool = True,
) -> dict[str, Any]:
    normalized_ids = _normalize_document_ids(requested_document_ids)
    visible_ids: list[str] = []
    denied_count = 0
    for document_id in normalized_ids:
        decision = evaluate_retrieval_permission(
            access_context,
            content_objects.get(document_id),
        )
        if decision["visible"]:
            visible_ids.append(document_id)
        else:
            denied_count += 1

    if require_all_visible and denied_count:
        raise RetrievalPermissionError(
            status_code=404,
            error_code="cx.document_scope_not_found",
            detail="One or more requested documents were not found.",
        )
    return {
        "permission_filter_schema_version": "cx_retrieval_permission_filter.v1",
        "policy_id": PERMISSION_POLICY_ID,
        "requested_document_count": len(normalized_ids),
        "visible_document_ids": visible_ids,
        "visible_document_count": len(visible_ids),
        "filtered_document_count": denied_count,
        # Unauthorized documents are rejected before their chunks are loaded.
        "filtered_chunk_count": 0,
        "chunk_filter_semantics": "denied_documents_not_expanded",
    }


def build_permission_snapshot(
    *,
    access_context: CxAccessContext,
    scope_type: str,
    filter_result: Mapping[str, Any],
) -> dict[str, Any]:
    visible_ids = _string_list(filter_result.get("visible_document_ids"))
    requested_count = _non_negative_int(
        filter_result.get("requested_document_count"),
        field_name="requested_document_count",
    )
    visible_count = _non_negative_int(
        filter_result.get("visible_document_count"),
        field_name="visible_document_count",
    )
    filtered_count = _non_negative_int(
        filter_result.get("filtered_document_count"),
        field_name="filtered_document_count",
    )
    filtered_chunk_count = _non_negative_int(
        filter_result.get("filtered_chunk_count"),
        field_name="filtered_chunk_count",
    )
    if visible_count != len(visible_ids):
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_snapshot_invalid",
            detail="Visible document count does not match the filtered scope.",
        )
    if requested_count != visible_count + filtered_count:
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_snapshot_invalid",
            detail="Requested document count does not match the permission decision.",
        )
    normalized_scope_type = _scope_type(scope_type)
    return {
        "permission_snapshot_schema_version": PERMISSION_SNAPSHOT_SCHEMA_VERSION,
        "actor_type": "oa.user",
        "actor_id": access_context.subject_id,
        "tenant_ref": {"type": "oa.tenant", "id": access_context.tenant_id},
        "scope_requested": {
            "type": normalized_scope_type,
            "document_count": requested_count,
        },
        "scope_applied": {
            "type": "document_ids",
            "document_ids": visible_ids,
        },
        "classification_filter": ["private_owner"],
        "visible_document_count": visible_count,
        "filtered_document_count": filtered_count,
        "filtered_chunk_count": filtered_chunk_count,
        "filtered_chunk_semantics": filter_result.get(
            "chunk_filter_semantics",
            "denied_documents_not_expanded",
        ),
        "policy_version": PERMISSION_POLICY_ID,
    }


def build_evidence_permission_result(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if decision.get("visible") is not True:
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_evidence_invalid",
            detail="Denied content cannot be materialized as retrieval evidence.",
        )
    if decision.get("policy_version") != PERMISSION_POLICY_ID:
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_evidence_invalid",
            detail="Evidence permission policy does not match the active policy.",
        )
    return {
        "visible": True,
        "reason": "PRIVATE_OWNER_ACTIVE",
        "policy_version": PERMISSION_POLICY_ID,
    }


def _decision(*, visible: bool, reason: str) -> dict[str, Any]:
    return {
        "permission_decision_schema_version": PERMISSION_DECISION_SCHEMA_VERSION,
        "visible": visible,
        "reason": reason,
        "policy_version": PERMISSION_POLICY_ID,
    }


def _normalize_document_ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, str):
        raise _invalid_scope()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise _invalid_scope()
        document_id = value.strip()
        if document_id not in seen:
            normalized.append(document_id)
            seen.add(document_id)
    return normalized


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_snapshot_invalid",
            detail="Visible document IDs must be a list of non-empty strings.",
        )
    return list(value)


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_snapshot_invalid",
            detail=f"{field_name} must be a non-negative integer.",
        )
    return value


def _scope_type(value: object) -> str:
    if value not in {"explicit_document_ids", "all_owner_documents"}:
        raise RetrievalPermissionError(
            status_code=500,
            error_code="cx.permission_snapshot_invalid",
            detail="Permission scope type is invalid.",
        )
    return str(value)


def _invalid_scope() -> RetrievalPermissionError:
    return RetrievalPermissionError(
        status_code=422,
        error_code="cx.document_scope_invalid",
        detail="Document IDs must be non-empty strings.",
    )
