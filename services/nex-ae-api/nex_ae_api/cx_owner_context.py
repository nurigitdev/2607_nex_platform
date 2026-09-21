from __future__ import annotations

from collections.abc import Mapping


CX_TENANT_HEADER = "X-NEX-Tenant-ID"
CX_SUBJECT_HEADER = "X-NEX-Subject-ID"
DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_SUBJECT_ID = "local-user"


def cx_owner_headers(tenant_id: object, subject_id: object) -> dict[str, str]:
    return {
        CX_TENANT_HEADER: _owner_id(tenant_id, default=DEFAULT_TENANT_ID),
        CX_SUBJECT_HEADER: _owner_id(subject_id, default=DEFAULT_SUBJECT_ID),
    }


def cx_owner_scope_from_payload(payload: Mapping[str, object]) -> tuple[str, str]:
    ownership_ref = payload.get("ownership_ref")
    if isinstance(ownership_ref, Mapping):
        tenant_ref = ownership_ref.get("tenant_ref")
        owner_ref = ownership_ref.get("owner_subject_ref")
        if isinstance(tenant_ref, Mapping) and isinstance(owner_ref, Mapping):
            return (
                _owner_id(tenant_ref.get("id"), default=DEFAULT_TENANT_ID),
                _owner_id(owner_ref.get("id"), default=DEFAULT_SUBJECT_ID),
            )

    actor_ref = payload.get("actor_claims_ref")
    if isinstance(actor_ref, Mapping):
        return (
            _owner_id(actor_ref.get("tenant_id"), default=DEFAULT_TENANT_ID),
            _owner_id(actor_ref.get("actor_id"), default=DEFAULT_SUBJECT_ID),
        )
    return (
        _owner_id(payload.get("tenant_id"), default=DEFAULT_TENANT_ID),
        _owner_id(
            payload.get("owner_user_id") or payload.get("user_id"),
            default=DEFAULT_SUBJECT_ID,
        ),
    )


def _owner_id(value: object, *, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
