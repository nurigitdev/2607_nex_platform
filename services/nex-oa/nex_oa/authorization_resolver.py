from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import OaAuthorizationRepository
from nex_oa.subjects import normalize_registry_id


OA_EFFECTIVE_AUTHORIZATION_SCHEMA_VERSION = "oa_effective_authorization.v1"


@dataclass
class OaEffectiveAuthorizationResolver:
    repository: OaAuthorizationRepository

    def resolve(self, membership: Mapping[str, Any]) -> dict[str, Any]:
        record = _membership_record(membership)
        tenant_id, subject_id = _membership_ids(record)
        if record.get("status") != "ACTIVE":
            raise _inactive_membership()
        inputs = self.repository.authorization_inputs(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        return resolve_effective_authorization(record, inputs=inputs)


def resolve_effective_authorization(
    membership: Mapping[str, Any],
    *,
    inputs: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    tenant_id, subject_id = _membership_ids(membership)
    if membership.get("status") != "ACTIVE":
        raise _inactive_membership()
    direct_roles = _string_set(membership.get("roles"), field_name="roles")
    direct_scopes = _string_set(membership.get("scopes"), field_name="scopes")

    tenant_roles = {
        str(item["role_id"]): item
        for item in inputs.get("roles", ())
        if _same_tenant(item, tenant_id) and item.get("status") == "ACTIVE"
    }
    active_groups = {
        str(item["group_id"]): item
        for item in inputs.get("groups", ())
        if _same_tenant(item, tenant_id) and item.get("status") == "ACTIVE"
    }
    member_group_ids = {
        str(item["group_id"])
        for item in inputs.get("group_members", ())
        if _same_tenant(item, tenant_id)
        and item.get("subject_id") == subject_id
        and item.get("status") == "ACTIVE"
        and item.get("group_id") in active_groups
    }
    group_roles = {
        str(item["role_id"])
        for item in inputs.get("group_roles", ())
        if _same_tenant(item, tenant_id)
        and item.get("group_id") in member_group_ids
        and item.get("role_id") in tenant_roles
        and item.get("status") == "ACTIVE"
    }
    effective_roles = tuple(sorted(direct_roles | group_roles))
    role_scopes = {
        scope
        for role_id in effective_roles
        if role_id in tenant_roles
        for scope in _string_set(
            tenant_roles[role_id].get("scopes"),
            field_name="role.scopes",
        )
    }
    effective_scopes = tuple(sorted(direct_scopes | role_scopes))
    revision_snapshot = {
        "membership": int(membership.get("revision") or 1),
        "roles": sorted(
            (role_id, int(tenant_roles[role_id].get("revision") or 1))
            for role_id in effective_roles
            if role_id in tenant_roles
        ),
        "groups": sorted(
            (group_id, int(active_groups[group_id].get("revision") or 1))
            for group_id in member_group_ids
        ),
    }
    return {
        "authorization_schema_version": OA_EFFECTIVE_AUTHORIZATION_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "roles": effective_roles,
        "scopes": effective_scopes,
        "group_ids": tuple(sorted(member_group_ids)),
        "unresolved_direct_roles": tuple(sorted(direct_roles - tenant_roles.keys())),
        "revision_hash": sha256(
            json.dumps(revision_snapshot, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "source_counts": {
            "direct_role_count": len(direct_roles),
            "direct_scope_count": len(direct_scopes),
            "group_count": len(member_group_ids),
            "group_role_count": len(group_roles),
            "effective_scope_count": len(effective_scopes),
        },
    }


def require_effective_scopes(
    authorization: Mapping[str, Any],
    required_scopes: Sequence[str],
) -> None:
    granted = _string_set(authorization.get("scopes"), field_name="scopes")
    required = _string_set(required_scopes, field_name="required_scopes")
    missing = sorted(required - granted)
    if missing:
        raise OaAuthorizationError(
            status_code=403,
            error_code="oa.authorization_scope_not_granted",
            detail=f"required scope is not granted: {missing[0]}",
        )


def _membership_record(membership: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = membership.get("membership")
    if nested is None:
        return membership
    if not isinstance(nested, Mapping):
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_membership_invalid",
            detail="membership must be an object.",
        )
    return nested


def _membership_ids(membership: Mapping[str, Any]) -> tuple[str, str]:
    tenant_ref = membership.get("tenant_ref")
    subject_ref = membership.get("subject_ref")
    tenant_id = (
        tenant_ref.get("id")
        if isinstance(tenant_ref, Mapping)
        else membership.get("tenant_id")
    )
    subject_id = (
        subject_ref.get("id")
        if isinstance(subject_ref, Mapping)
        else membership.get("subject_id")
    )
    try:
        return (
            normalize_registry_id(tenant_id, field_name="tenant_id"),
            normalize_registry_id(subject_id, field_name="subject_id"),
        )
    except Exception as exc:
        raise OaAuthorizationError(
            status_code=400,
            error_code="oa.authorization_membership_identity_invalid",
            detail="membership tenant and subject references are required.",
        ) from exc


def _same_tenant(record: Mapping[str, Any], tenant_id: str) -> bool:
    return record.get("tenant_id") == tenant_id


def _string_set(value: object, *, field_name: str) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _grant_list_error(field_name)
    normalized = {
        item.strip().lower()
        for item in value
        if isinstance(item, str) and item.strip()
    }
    if len(normalized) != len(value):
        raise _grant_list_error(field_name)
    return normalized


def _grant_list_error(field_name: str) -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=400,
        error_code="oa.authorization_grant_list_invalid",
        detail=f"{field_name} must be an array of non-empty strings.",
    )


def _inactive_membership() -> OaAuthorizationError:
    return OaAuthorizationError(
        status_code=403,
        error_code="oa.authorization_membership_inactive",
        detail="effective authorization requires an active membership.",
    )
