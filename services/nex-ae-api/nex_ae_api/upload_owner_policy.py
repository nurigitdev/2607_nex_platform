from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import RUNTIME_PROFILES


UPLOAD_OWNER_POLICY_SCHEMA_VERSION = "ae_upload_owner_policy.v1"
LOCAL_MOCK_PROFILE = "local_mock"
LOCAL_OWNER_PLACEHOLDERS = frozenset({"local-tenant", "local-user"})


@dataclass(frozen=True)
class UploadOwnerPolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def normalize_upload_runtime_profile(value: str | None) -> str:
    profile = (value or LOCAL_MOCK_PROFILE).strip().lower()
    if profile not in RUNTIME_PROFILES:
        raise UploadOwnerPolicyError(
            error_code="ae.upload_runtime_profile_invalid",
            detail=f"Unsupported AE upload runtime profile: {profile}",
        )
    return profile


def enforce_upload_owner_policy(
    payload: Mapping[str, Any],
    *,
    runtime_profile: str,
) -> dict[str, Any]:
    normalized = dict(payload)
    profile = normalize_upload_runtime_profile(runtime_profile)
    if profile == LOCAL_MOCK_PROFILE:
        return normalized

    tenant_id, owner_user_id = explicit_upload_owner_scope(normalized)
    if tenant_id is None or owner_user_id is None:
        raise UploadOwnerPolicyError(
            error_code="ae.upload_owner_scope_required",
            detail=(
                "Protected AE upload profiles require tenant and owner scope "
                "from authenticated claims or an explicit service payload."
            ),
        )
    if (
        tenant_id in LOCAL_OWNER_PLACEHOLDERS
        or owner_user_id in LOCAL_OWNER_PLACEHOLDERS
    ):
        raise UploadOwnerPolicyError(
            error_code="ae.upload_owner_scope_placeholder_forbidden",
            detail="Protected AE upload profiles reject local owner placeholders.",
        )
    return normalized


def explicit_upload_owner_scope(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    tenant_id = _text(payload.get("tenant_id"))
    owner_user_id = _text(payload.get("owner_user_id")) or _text(
        payload.get("user_id")
    )
    ownership_ref = payload.get("ownership_ref")
    if not isinstance(ownership_ref, Mapping):
        return tenant_id, owner_user_id

    tenant_ref = ownership_ref.get("tenant_ref")
    owner_ref = ownership_ref.get("owner_subject_ref")
    legacy = ownership_ref.get("legacy")
    if isinstance(tenant_ref, Mapping):
        tenant_id = _text(tenant_ref.get("id")) or tenant_id
    if isinstance(owner_ref, Mapping):
        owner_user_id = _text(owner_ref.get("id")) or owner_user_id
    if isinstance(legacy, Mapping):
        tenant_id = tenant_id or _text(legacy.get("tenant_id"))
        owner_user_id = owner_user_id or _text(legacy.get("owner_user_id"))
    return tenant_id, owner_user_id


def upload_owner_policy_projection(runtime_profile: str) -> dict[str, Any]:
    profile = normalize_upload_runtime_profile(runtime_profile)
    protected = profile != LOCAL_MOCK_PROFILE
    return {
        "policy_schema_version": UPLOAD_OWNER_POLICY_SCHEMA_VERSION,
        "runtime_profile": profile,
        "protected": protected,
        "browser_owner_authority": "oa_claim",
        "service_owner_authority": "explicit_payload",
        "local_owner_fallback_allowed": not protected,
        "local_owner_placeholders_allowed": not protected,
    }


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
