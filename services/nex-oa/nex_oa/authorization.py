from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from nex_oa.subjects import normalize_registry_id


OA_AUTHORIZATION_SCHEMA_VERSION = "oa_authorization.v1"
OA_ROLE_SCHEMA_VERSION = "oa_role.v1"
OA_GROUP_SCHEMA_VERSION = "oa_group.v1"
OA_GROUP_MEMBER_SCHEMA_VERSION = "oa_group_member.v1"
OA_GROUP_ROLE_SCHEMA_VERSION = "oa_group_role.v1"
OA_AUTHORIZATION_STATUSES = ("ACTIVE", "DISABLED")

_AUTHZ_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}:[a-z][a-z0-9._-]{0,63}$")
_PRIVATE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
)


@dataclass(frozen=True)
class OaAuthorizationError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def plan_role_upsert(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    role_id = normalize_authorization_id(payload.get("role_id"), field_name="role_id")
    revision = _next_revision(payload.get("expected_revision"), current=current)
    _assert_same_identity(current, tenant_id=tenant_id, key="role_id", value=role_id)
    return {
        "authorization_schema_version": OA_AUTHORIZATION_SCHEMA_VERSION,
        "role_schema_version": OA_ROLE_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "role_id": role_id,
        "display_name": _display_name(payload.get("display_name"), fallback=role_id),
        "description": _optional_text(payload.get("description"), maximum=512),
        "status": normalize_authorization_status(payload.get("status", "ACTIVE")),
        "scopes": normalize_authorization_scopes(payload.get("scopes")),
        "metadata": normalize_authorization_metadata(payload.get("metadata")),
        "previous_revision": revision - 1,
        "revision": revision,
    }


def plan_group_upsert(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    group_id = normalize_authorization_id(payload.get("group_id"), field_name="group_id")
    revision = _next_revision(payload.get("expected_revision"), current=current)
    _assert_same_identity(current, tenant_id=tenant_id, key="group_id", value=group_id)
    return {
        "authorization_schema_version": OA_AUTHORIZATION_SCHEMA_VERSION,
        "group_schema_version": OA_GROUP_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "group_id": group_id,
        "display_name": _display_name(payload.get("display_name"), fallback=group_id),
        "description": _optional_text(payload.get("description"), maximum=512),
        "status": normalize_authorization_status(payload.get("status", "ACTIVE")),
        "metadata": normalize_authorization_metadata(payload.get("metadata")),
        "previous_revision": revision - 1,
        "revision": revision,
    }


def plan_group_member_upsert(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    group_id = normalize_authorization_id(payload.get("group_id"), field_name="group_id")
    subject_id = normalize_registry_id(payload.get("subject_id"), field_name="subject_id")
    revision = _next_revision(payload.get("expected_revision"), current=current)
    _assert_same_identity(current, tenant_id=tenant_id, key="group_id", value=group_id)
    _assert_same_identity(current, tenant_id=tenant_id, key="subject_id", value=subject_id)
    return {
        "authorization_schema_version": OA_AUTHORIZATION_SCHEMA_VERSION,
        "group_member_schema_version": OA_GROUP_MEMBER_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "group_id": group_id,
        "subject_id": subject_id,
        "status": normalize_authorization_status(payload.get("status", "ACTIVE")),
        "previous_revision": revision - 1,
        "revision": revision,
    }


def plan_group_role_upsert(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    group_id = normalize_authorization_id(payload.get("group_id"), field_name="group_id")
    role_id = normalize_authorization_id(payload.get("role_id"), field_name="role_id")
    revision = _next_revision(payload.get("expected_revision"), current=current)
    _assert_same_identity(current, tenant_id=tenant_id, key="group_id", value=group_id)
    _assert_same_identity(current, tenant_id=tenant_id, key="role_id", value=role_id)
    return {
        "authorization_schema_version": OA_AUTHORIZATION_SCHEMA_VERSION,
        "group_role_schema_version": OA_GROUP_ROLE_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "group_id": group_id,
        "role_id": role_id,
        "status": normalize_authorization_status(payload.get("status", "ACTIVE")),
        "previous_revision": revision - 1,
        "revision": revision,
    }


def normalize_authorization_id(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(field_name, f"{field_name} must be a string.")
    normalized = value.strip().lower()
    if not _AUTHZ_ID_PATTERN.fullmatch(normalized):
        raise _invalid(
            field_name,
            f"{field_name} must contain 2-64 lowercase letters, digits, '.', '_' or '-'.",
        )
    return normalized


def normalize_authorization_status(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("status", "status must be ACTIVE or DISABLED.")
    normalized = value.strip().upper()
    if normalized not in OA_AUTHORIZATION_STATUSES:
        raise _invalid("status", "status must be ACTIVE or DISABLED.")
    return normalized


def normalize_authorization_scopes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid("scopes", "scopes must be an array of scope names.")
    normalized: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise _invalid("scopes", "each scope must be a string.")
        scope = item.strip().lower()
        if not _SCOPE_PATTERN.fullmatch(scope):
            raise _invalid("scopes", "each scope must use the resource:action form.")
        normalized.add(scope)
    if not normalized:
        raise _invalid("scopes", "at least one scope is required.")
    return tuple(sorted(normalized))


def normalize_authorization_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid("metadata", "metadata must be an object.")
    metadata = dict(value)
    private_paths = _private_paths(metadata)
    if private_paths:
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_private_metadata",
            detail="metadata contains private fields.",
        )
    return metadata


def _next_revision(
    expected: object,
    *,
    current: Mapping[str, Any] | None,
) -> int:
    expected_revision = _revision(expected, default=0)
    current_revision = _revision(current.get("revision"), default=0) if current else 0
    if expected_revision != current_revision:
        raise OaAuthorizationError(
            status_code=409,
            error_code="oa.authorization_revision_conflict",
            detail="expected_revision does not match the current authorization revision.",
        )
    return current_revision + 1


def _revision(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise _invalid("expected_revision", "expected_revision must be a non-negative integer.")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(
            "expected_revision",
            "expected_revision must be a non-negative integer.",
        ) from exc
    if revision < 0 or str(value) != str(revision):
        raise _invalid("expected_revision", "expected_revision must be a non-negative integer.")
    return revision


def _assert_same_identity(
    current: Mapping[str, Any] | None,
    *,
    tenant_id: str,
    key: str,
    value: str,
) -> None:
    if current is None:
        return
    if current.get("tenant_id") != tenant_id or current.get(key) != value:
        raise OaAuthorizationError(
            status_code=409,
            error_code="oa.authorization_identity_immutable",
            detail="authorization identity fields are immutable.",
        )


def _display_name(value: object, *, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise _invalid("display_name", "display_name must contain 1-128 characters.")
    return value.strip()


def _optional_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("description", "description must be a string.")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise _invalid("description", f"description must contain at most {maximum} characters.")
    return normalized or None


def _private_paths(value: object, prefix: str = "metadata") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            lowered = str(key).lower()
            if any(part in lowered for part in _PRIVATE_KEY_PARTS):
                paths.append(path)
            paths.extend(_private_paths(nested, path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, nested in enumerate(value):
            paths.extend(_private_paths(nested, f"{prefix}[{index}]"))
    return paths


def _invalid(field_name: str, detail: str) -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=400,
        error_code=f"oa.authorization_{field_name}_invalid",
        detail=detail,
    )
