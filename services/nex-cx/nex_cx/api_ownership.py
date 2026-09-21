from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.owner_lineage import (
    CxOwnerLineage,
    CxOwnerLineageError,
    attach_owner_lineage,
    build_owner_lineage,
    normalize_owner_lineage,
)


class CxApiOwnershipError(ValueError):
    def __init__(self, *, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def require_owner_assertion_match(
    access_context: CxAccessContext,
    value: object,
) -> CxOwnerLineage:
    expected = build_owner_lineage(access_context)
    try:
        asserted = normalize_owner_lineage(value)
    except CxOwnerLineageError as exc:
        raise CxApiOwnershipError(
            error_code="cx.owner_scope_invalid",
            detail=exc.detail,
        ) from exc
    if asserted.ownership_key != expected.ownership_key:
        raise CxApiOwnershipError(
            error_code="cx.owner_scope_mismatch",
            detail="The asserted owner scope does not match the authenticated CX access context.",
        )
    return expected


def require_optional_owner_aliases_match(
    access_context: CxAccessContext,
    *,
    tenant_id: object = None,
    owner_user_id: object = None,
) -> None:
    supplied = tenant_id is not None or owner_user_id is not None
    if not supplied:
        return
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise CxApiOwnershipError(
            error_code="cx.owner_scope_invalid",
            detail="tenant_id must be a non-empty string when owner aliases are supplied.",
        )
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise CxApiOwnershipError(
            error_code="cx.owner_scope_invalid",
            detail="owner_user_id must be a non-empty string when owner aliases are supplied.",
        )
    if (
        tenant_id.strip() != access_context.tenant_id
        or owner_user_id.strip() != access_context.subject_id
    ):
        raise CxApiOwnershipError(
            error_code="cx.owner_scope_mismatch",
            detail="Owner query aliases must match the authenticated CX access context.",
        )


def owner_scoped_record(
    access_context: CxAccessContext,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return attach_owner_lineage(record, build_owner_lineage(access_context))


def record_visible_to_owner(
    access_context: CxAccessContext,
    record: object,
) -> bool:
    if not isinstance(record, Mapping):
        return False
    try:
        lineage = normalize_owner_lineage(record)
    except CxOwnerLineageError:
        return False
    return lineage.ownership_key == access_context.ownership_key


def content_object_visible_to_owner(
    access_context: CxAccessContext,
    content_object: object,
) -> bool:
    if not isinstance(content_object, Mapping):
        return False
    if content_object.get("lifecycle_status") != "ACTIVE":
        return False
    return record_visible_to_owner(access_context, content_object)


def document_visible_to_owner(
    access_context: CxAccessContext,
    store: object,
    document_id: str,
) -> bool:
    repository = getattr(store, "content_repository", None)
    getter = getattr(repository, "get_content_object", None)
    if not callable(getter):
        return False
    return content_object_visible_to_owner(access_context, getter(document_id))
