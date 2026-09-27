from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_ae_api.auth_guard import BrowserAuthError, apply_claim_owner_scope
from nex_ae_api.route_auth import AeFacadeRouteAuthContext


OWNER_SCOPE_SCHEMA_VERSION = "ae_workspace_chat_owner_scope.v1"


@dataclass(frozen=True)
class WorkspaceChatOwnerScope:
    tenant_id: str
    owner_user_id: str
    authority: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "owner_scope_schema_version": OWNER_SCOPE_SCHEMA_VERSION,
            "tenant_ref": {"type": "oa.tenant", "id": self.tenant_id},
            "owner_subject_ref": {"type": "oa.user", "id": self.owner_user_id},
            "authority": self.authority,
        }


@dataclass(frozen=True)
class WorkspaceChatOwnerError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def owner_scoped_payload(
    payload: Mapping[str, Any],
    auth_context: AeFacadeRouteAuthContext,
) -> tuple[dict[str, Any], WorkspaceChatOwnerScope]:
    if auth_context.browser_context is not None:
        try:
            normalized = apply_claim_owner_scope(payload, auth_context.browser_context)
        except BrowserAuthError as exc:
            raise WorkspaceChatOwnerError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
            ) from exc
        scope = WorkspaceChatOwnerScope(
            tenant_id=auth_context.browser_context.tenant_id,
            owner_user_id=auth_context.browser_context.user_id,
            authority="claim",
        )
        return _with_canonical_owner(normalized, scope), scope

    scope = service_owner_scope_from_payload(payload)
    return _with_canonical_owner(dict(payload), scope), scope


def service_owner_scope_from_payload(
    payload: Mapping[str, Any],
) -> WorkspaceChatOwnerScope:
    canonical_tenant, canonical_owner = _canonical_owner_ids(payload)
    alias_tenant = _text(payload.get("tenant_id"))
    alias_owner = _text(payload.get("owner_user_id")) or _text(payload.get("user_id"))
    tenant_id = canonical_tenant or alias_tenant
    owner_user_id = canonical_owner or alias_owner
    if tenant_id is None or owner_user_id is None:
        raise WorkspaceChatOwnerError(
            status_code=400,
            error_code="ae.workspace_chat_owner_scope_required",
            detail="Service calls require explicit tenant and owner identifiers.",
        )
    if canonical_tenant and alias_tenant and canonical_tenant != alias_tenant:
        raise _scope_mismatch("tenant")
    if canonical_owner and alias_owner and canonical_owner != alias_owner:
        raise _scope_mismatch("owner")
    return WorkspaceChatOwnerScope(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        authority="service_payload",
    )


def owner_scope_from_record(record: Mapping[str, Any]) -> WorkspaceChatOwnerScope:
    tenant_id = _text(record.get("tenant_id"))
    owner_user_id = _text(record.get("owner_user_id")) or _text(record.get("user_id"))
    if tenant_id is None or owner_user_id is None:
        raise WorkspaceChatOwnerError(
            status_code=500,
            error_code="ae.workspace_chat_record_owner_invalid",
            detail="Persisted workspace or chat owner scope is incomplete.",
        )
    return WorkspaceChatOwnerScope(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        authority="persisted_record",
    )


def record_matches_owner(
    record: Mapping[str, Any],
    scope: WorkspaceChatOwnerScope,
) -> bool:
    try:
        record_scope = owner_scope_from_record(record)
    except WorkspaceChatOwnerError:
        return False
    return (
        record_scope.tenant_id == scope.tenant_id
        and record_scope.owner_user_id == scope.owner_user_id
    )


def browser_owner_scope(
    auth_context: AeFacadeRouteAuthContext,
) -> WorkspaceChatOwnerScope | None:
    if auth_context.browser_context is None:
        return None
    return WorkspaceChatOwnerScope(
        tenant_id=auth_context.browser_context.tenant_id,
        owner_user_id=auth_context.browser_context.user_id,
        authority="claim",
    )


def _with_canonical_owner(
    payload: dict[str, Any],
    scope: WorkspaceChatOwnerScope,
) -> dict[str, Any]:
    payload["tenant_id"] = scope.tenant_id
    payload["owner_user_id"] = scope.owner_user_id
    payload["user_id"] = scope.owner_user_id
    payload["ownership_ref"] = {
        "tenant_ref": {"type": "oa.tenant", "id": scope.tenant_id},
        "owner_subject_ref": {"type": "oa.user", "id": scope.owner_user_id},
    }
    return payload


def _canonical_owner_ids(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    ownership_ref = payload.get("ownership_ref")
    if not isinstance(ownership_ref, Mapping):
        return None, None
    tenant_ref = ownership_ref.get("tenant_ref")
    owner_ref = ownership_ref.get("owner_subject_ref")
    tenant_id = _text(tenant_ref.get("id")) if isinstance(tenant_ref, Mapping) else None
    owner_id = _text(owner_ref.get("id")) if isinstance(owner_ref, Mapping) else None
    return tenant_id, owner_id


def _scope_mismatch(field: str) -> WorkspaceChatOwnerError:
    return WorkspaceChatOwnerError(
        status_code=409,
        error_code="ae.workspace_chat_owner_scope_mismatch",
        detail=f"Canonical and compatibility {field} identifiers must match.",
    )


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
