from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from nex_runtime import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from nex_cx.source_ownership import (
    OA_TENANT_SUBJECT_TYPE,
    OA_USER_SUBJECT_TYPE,
    build_source_ownership_ref,
)


CX_ACCESS_CONTEXT_SCHEMA_VERSION = "cx_access_context.v1"
CX_ACCESS_CONTEXT_PROPAGATION_MODE = "trusted_service_asserted_subject"
CX_ACCESS_CONTEXT_ALLOWED_CALLERS = frozenset(
    {"nex-ae-api", "nex-ag", "nex-cx"}
)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class CxAccessContextError(ValueError):
    def __init__(self, *, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class CxAccessContext:
    caller_service_id: str
    tenant_id: str
    subject_id: str
    request_id: str
    trace_id: str
    scopes: tuple[str, ...]

    @property
    def ownership_key(self) -> tuple[str, str]:
        return (self.tenant_id, self.subject_id)

    def to_wire(self) -> dict[str, Any]:
        return {
            "access_context_schema_version": CX_ACCESS_CONTEXT_SCHEMA_VERSION,
            "propagation_mode": CX_ACCESS_CONTEXT_PROPAGATION_MODE,
            "caller_service_ref": {
                "type": "platform.service",
                "id": self.caller_service_id,
            },
            "tenant_ref": {
                "type": OA_TENANT_SUBJECT_TYPE,
                "id": self.tenant_id,
            },
            "subject_ref": {
                "type": OA_USER_SUBJECT_TYPE,
                "id": self.subject_id,
            },
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "scopes": list(self.scopes),
        }


def resolve_cx_access_context(
    *,
    authorization: str | None,
    tenant_id: object,
    subject_id: object,
    request_id: object,
    trace_id: object,
    allowed_callers: Collection[str] = CX_ACCESS_CONTEXT_ALLOWED_CALLERS,
    now: datetime | None = None,
) -> CxAccessContext:
    validation = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
        now=now,
    )
    if not validation.ok or validation.claims is None:
        raise CxAccessContextError(
            status_code=401,
            error_code=validation.error_code or "SERVICE_CLAIM_INVALID",
            detail=validation.detail or "CX requires a valid service claim.",
        )

    caller_service_id = validation.claims.service_id
    if caller_service_id not in allowed_callers:
        raise CxAccessContextError(
            status_code=403,
            error_code="CX_CALLER_SERVICE_FORBIDDEN",
            detail="The calling service is not allowed to assert CX ownership context.",
        )

    return CxAccessContext(
        caller_service_id=caller_service_id,
        tenant_id=_normalize_identifier(tenant_id, field_name="tenant_id"),
        subject_id=_normalize_identifier(subject_id, field_name="subject_id"),
        request_id=_normalize_identifier(request_id, field_name="request_id"),
        trace_id=_normalize_identifier(trace_id, field_name="trace_id"),
        scopes=tuple(validation.claims.scopes),
    )


def build_access_context_ownership_ref(
    access_context: CxAccessContext,
) -> dict[str, Any]:
    return build_source_ownership_ref(
        tenant_id=access_context.tenant_id,
        owner_user_id=access_context.subject_id,
        uploaded_by_user_id=access_context.subject_id,
    )


def ownership_ref_matches_access_context(
    access_context: CxAccessContext,
    ownership_ref: object,
) -> bool:
    if not isinstance(ownership_ref, Mapping):
        return False
    tenant_ref = ownership_ref.get("tenant_ref")
    owner_ref = ownership_ref.get("owner_subject_ref")
    if not isinstance(tenant_ref, Mapping) or not isinstance(owner_ref, Mapping):
        return False
    return (
        tenant_ref.get("type") == OA_TENANT_SUBJECT_TYPE
        and tenant_ref.get("id") == access_context.tenant_id
        and owner_ref.get("type") == OA_USER_SUBJECT_TYPE
        and owner_ref.get("id") == access_context.subject_id
    )


def _normalize_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise CxAccessContextError(
            status_code=422,
            error_code="CX_ACCESS_CONTEXT_INVALID",
            detail=f"{field_name} must be a valid identifier.",
        )
    normalized = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise CxAccessContextError(
            status_code=422,
            error_code="CX_ACCESS_CONTEXT_INVALID",
            detail=f"{field_name} must be a valid identifier.",
        )
    return normalized
