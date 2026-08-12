from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_USER_SCOPE,
    UserClaims,
    problem_response,
    validate_user_authorization_header,
)
from nex_ae_api.uploads import (
    OA_TENANT_REF_TYPE,
    OA_USER_SUBJECT_REF_TYPE,
    OWNERSHIP_COMPATIBILITY_MODE,
    OWNERSHIP_REF_SCHEMA_VERSION,
)


AE_BROWSER_USER_AUTH_CONTEXT_SCHEMA_VERSION = "ae_browser_user_auth_context.v1"


@dataclass(frozen=True)
class BrowserAuthError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class BrowserUserAuthContext:
    tenant_id: str
    user_id: str
    scopes: tuple[str, ...]
    roles: tuple[str, ...]
    audience: str = "nex-ae-api"
    token_use: str = "user"

    def to_wire(self) -> dict[str, Any]:
        return {
            "auth_context_schema_version": AE_BROWSER_USER_AUTH_CONTEXT_SCHEMA_VERSION,
            "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": self.tenant_id},
            "subject_ref": {"type": OA_USER_SUBJECT_REF_TYPE, "id": self.user_id},
            "audience": self.audience,
            "token_use": self.token_use,
            "scopes": list(self.scopes),
            "roles": list(self.roles),
            "owner_scope_authority": "claim",
            "metadata": {
                "service_token_accepted": False,
                "browser_payload_owner_authoritative": False,
                "claim_owner_authoritative": True,
                "raw_token_included": False,
            },
        }


def authorize_browser_user_request(
    request: Request,
    authorization: str | None,
    *,
    required_scopes: tuple[str, ...] | list[str] = (DEFAULT_USER_SCOPE,),
) -> BrowserUserAuthContext | JSONResponse:
    result = validate_user_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=required_scopes,
    )
    if result.ok and result.claims is not None:
        return build_browser_user_auth_context(result.claims)

    return browser_auth_problem_response(
        request,
        BrowserAuthError(
            status_code=401,
            error_code=result.error_code or "USER_CLAIM_INVALID",
            detail=result.detail or "AE API requires a valid browser user claim.",
        ),
    )


def build_browser_user_auth_context(claims: UserClaims) -> BrowserUserAuthContext:
    if claims.token_use != "user":
        raise BrowserAuthError(
            status_code=401,
            error_code="ae.browser_token_use_invalid",
            detail="Browser routes require token_use=user.",
        )
    if claims.audience != "nex-ae-api":
        raise BrowserAuthError(
            status_code=401,
            error_code="ae.browser_token_audience_invalid",
            detail="Browser routes require audience=nex-ae-api.",
        )
    return BrowserUserAuthContext(
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        scopes=claims.scopes,
        roles=claims.roles,
        audience=claims.audience,
        token_use=claims.token_use,
    )


def owner_scope_from_browser_context(
    context: BrowserUserAuthContext,
) -> dict[str, Any]:
    return {
        "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": {"type": OA_TENANT_REF_TYPE, "id": context.tenant_id},
        "owner_subject_ref": {"type": OA_USER_SUBJECT_REF_TYPE, "id": context.user_id},
        "uploaded_by_subject_ref": {
            "type": OA_USER_SUBJECT_REF_TYPE,
            "id": context.user_id,
        },
        "legacy": {
            "tenant_id": context.tenant_id,
            "owner_user_id": context.user_id,
        },
        "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
    }


def apply_claim_owner_scope(
    payload: Mapping[str, Any],
    context: BrowserUserAuthContext,
    *,
    reject_mismatch: bool = True,
) -> dict[str, Any]:
    normalized = dict(payload)
    if reject_mismatch:
        _reject_owner_scope_mismatch(normalized, context)
    normalized["tenant_id"] = context.tenant_id
    normalized["owner_user_id"] = context.user_id
    normalized["user_id"] = context.user_id
    normalized["ownership_ref"] = owner_scope_from_browser_context(context)
    normalized["actor_claims_ref"] = {
        "actor_type": "user",
        "actor_id": context.user_id,
        "tenant_id": context.tenant_id,
    }
    return normalized


def build_browser_auth_summary(context: BrowserUserAuthContext) -> dict[str, Any]:
    wire = context.to_wire()
    return {
        "auth_context_schema_version": wire["auth_context_schema_version"],
        "tenant_ref": wire["tenant_ref"],
        "subject_ref": wire["subject_ref"],
        "token_use": wire["token_use"],
        "scope_count": len(wire["scopes"]),
        "role_count": len(wire["roles"]),
        "owner_scope_authority": wire["owner_scope_authority"],
        "metadata": wire["metadata"],
    }


def browser_auth_problem_response(
    request: Request,
    exc: BrowserAuthError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Browser authentication failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/browser-authentication-failed",
    )


def _reject_owner_scope_mismatch(
    payload: Mapping[str, Any],
    context: BrowserUserAuthContext,
) -> None:
    tenant_id = _payload_text(payload, "tenant_id")
    owner_user_id = _payload_text(payload, "owner_user_id") or _payload_text(
        payload,
        "user_id",
    )
    ownership_ref = payload.get("ownership_ref")
    if isinstance(ownership_ref, Mapping):
        tenant_ref = ownership_ref.get("tenant_ref")
        owner_ref = ownership_ref.get("owner_subject_ref")
        if isinstance(tenant_ref, Mapping):
            tenant_id = _payload_text(tenant_ref, "id") or tenant_id
        if isinstance(owner_ref, Mapping):
            owner_user_id = _payload_text(owner_ref, "id") or owner_user_id
    if tenant_id is not None and tenant_id != context.tenant_id:
        raise BrowserAuthError(
            status_code=403,
            error_code="ae.browser_owner_scope_mismatch",
            detail="Browser tenant scope must match the authenticated claim.",
        )
    if owner_user_id is not None and owner_user_id != context.user_id:
        raise BrowserAuthError(
            status_code=403,
            error_code="ae.browser_owner_scope_mismatch",
            detail="Browser owner scope must match the authenticated claim.",
        )


def _payload_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
