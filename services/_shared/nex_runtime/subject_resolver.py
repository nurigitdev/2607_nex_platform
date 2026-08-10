from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .auth import issue_mock_service_token


OA_SUBJECT_RESOLVER_SCHEMA_VERSION = "oa_subject_registry_resolver.v1"
OA_TENANT_REF_TYPE = "oa.tenant"
OA_USER_REF_TYPE = "oa.user"
OWNERSHIP_REF_SCHEMA_VERSION = "cx_source_ownership_ref.v1"
OWNERSHIP_COMPATIBILITY_MODE = "legacy_owner_fields_mapped_to_oa_subject_refs"
SUBJECT_REF_ALLOWED_FIELDS = frozenset({"type", "id"})
OWNERSHIP_REF_ALLOWED_FIELDS = frozenset(
    {
        "ownership_schema_version",
        "tenant_ref",
        "owner_subject_ref",
        "uploaded_by_subject_ref",
        "legacy",
        "compatibility_mode",
    }
)
CALLER_SERVICE_TO_OA_TOKEN_ENV = {
    "nex-ae-api": "NEX_AE_TO_OA_SERVICE_TOKEN",
    "nex-cx": "NEX_CX_TO_OA_SERVICE_TOKEN",
    "nex-ag": "NEX_AG_TO_OA_SERVICE_TOKEN",
    "nex-mo": "NEX_MO_TO_OA_SERVICE_TOKEN",
}


class SubjectRegistryResolver(Protocol):
    def resolve_ownership_ref(
        self,
        ownership_ref: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class SubjectRegistryResolverError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpSubjectRegistryResolver:
    base_url: str = "http://127.0.0.1:8101"
    caller_service_id: str = "nex-cx"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def resolve_ownership_ref(
        self,
        ownership_ref: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, Any]:
        normalized = normalize_ownership_ref_for_resolution(ownership_ref)
        if ensure:
            owner_snapshot = self.ensure_subject(
                tenant_ref=normalized["tenant_ref"],
                subject_ref=normalized["owner_subject_ref"],
                request_id=request_id,
                trace_id=trace_id,
            )
            uploaded_by_snapshot = owner_snapshot
            if normalized["uploaded_by_subject_ref"] != normalized["owner_subject_ref"]:
                uploaded_by_snapshot = self.ensure_subject(
                    tenant_ref=normalized["tenant_ref"],
                    subject_ref=normalized["uploaded_by_subject_ref"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
        else:
            self.get_tenant(
                normalized["tenant_ref"],
                request_id=request_id,
                trace_id=trace_id,
            )
            owner_snapshot = self.get_subject(
                tenant_ref=normalized["tenant_ref"],
                subject_ref=normalized["owner_subject_ref"],
                request_id=request_id,
                trace_id=trace_id,
            )
            uploaded_by_snapshot = owner_snapshot
            if normalized["uploaded_by_subject_ref"] != normalized["owner_subject_ref"]:
                uploaded_by_snapshot = self.get_subject(
                    tenant_ref=normalized["tenant_ref"],
                    subject_ref=normalized["uploaded_by_subject_ref"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
        return build_subject_resolution_result(
            normalized,
            resolver_mode="http",
            ensure=ensure,
            owner_snapshot=owner_snapshot,
            uploaded_by_snapshot=uploaded_by_snapshot,
        )

    def ensure_subject(
        self,
        *,
        tenant_ref: Mapping[str, str],
        subject_ref: Mapping[str, str],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/v1/subject-registry/ensure",
            request_id=request_id,
            trace_id=trace_id,
            json={
                "tenant_id": tenant_ref["id"],
                "subject_id": subject_ref["id"],
            },
        )

    def get_tenant(
        self,
        tenant_ref: Mapping[str, str],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/internal/v1/subject-registry/tenants/{_quote_path_value(tenant_ref['id'])}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_subject(
        self,
        *,
        tenant_ref: Mapping[str, str],
        subject_ref: Mapping[str, str],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            (
                "/internal/v1/subject-registry/tenants/"
                f"{_quote_path_value(tenant_ref['id'])}/subjects/"
                f"{_quote_path_value(subject_ref['id'])}"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id=self.caller_service_id,
            audience="nex-oa",
        ).access_token
        try:
            response = httpx.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                    "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                    "X-Service-ID": self.caller_service_id,
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SubjectRegistryResolverError(
                status_code=503,
                error_code="oa.subject_resolver_unavailable",
                detail=str(exc),
                retryable=True,
            ) from exc

        body = _safe_response_json(response)
        if response.status_code >= 400:
            raise SubjectRegistryResolverError(
                status_code=response.status_code,
                error_code=str(
                    body.get("error_code", "oa.subject_resolver_request_failed")
                ),
                detail=str(body.get("detail", "Subject registry request failed.")),
                retryable=bool(body.get("retryable", response.status_code >= 500)),
            )
        return body


def build_default_subject_registry_resolver(
    *,
    caller_service_id: str,
    environ: Mapping[str, str] | None = None,
) -> HttpSubjectRegistryResolver:
    env = environ or os.environ
    return HttpSubjectRegistryResolver(
        base_url=env.get("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
        caller_service_id=caller_service_id,
        service_token=env.get(_service_token_env(caller_service_id)),
        timeout_seconds=_positive_float_env(
            env,
            "NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS",
            default=5.0,
        ),
    )


def build_subject_resolution_result(
    ownership_ref: Mapping[str, Any],
    *,
    resolver_mode: str,
    ensure: bool,
    owner_snapshot: Mapping[str, Any],
    uploaded_by_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "resolver_schema_version": OA_SUBJECT_RESOLVER_SCHEMA_VERSION,
        "resolver_mode": resolver_mode,
        "action": "ensure" if ensure else "verify",
        "resolution_status": "RESOLVED",
        "tenant_ref": dict(ownership_ref["tenant_ref"]),
        "owner_subject_ref": dict(ownership_ref["owner_subject_ref"]),
        "uploaded_by_subject_ref": dict(ownership_ref["uploaded_by_subject_ref"]),
        "owner_snapshot_ref": _snapshot_ref(owner_snapshot),
        "uploaded_by_snapshot_ref": _snapshot_ref(uploaded_by_snapshot),
    }


def normalize_ownership_ref_for_resolution(
    ownership_ref: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(ownership_ref, Mapping):
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail="ownership_ref must be an object.",
        )
    unknown_fields = sorted(set(ownership_ref) - OWNERSHIP_REF_ALLOWED_FIELDS)
    if unknown_fields:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=(
                "ownership_ref contains unsupported fields: "
                f"{', '.join(unknown_fields)}."
            ),
        )
    schema_version = ownership_ref.get("ownership_schema_version")
    if schema_version is not None and schema_version != OWNERSHIP_REF_SCHEMA_VERSION:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"ownership_schema_version must be {OWNERSHIP_REF_SCHEMA_VERSION}.",
        )
    compatibility_mode = ownership_ref.get("compatibility_mode")
    if compatibility_mode is not None and compatibility_mode != OWNERSHIP_COMPATIBILITY_MODE:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"compatibility_mode must be {OWNERSHIP_COMPATIBILITY_MODE}.",
        )
    tenant_ref = required_resolver_subject_ref(
        ownership_ref.get("tenant_ref"),
        field_name="tenant_ref",
        expected_type=OA_TENANT_REF_TYPE,
    )
    owner_subject_ref = required_resolver_subject_ref(
        ownership_ref.get("owner_subject_ref"),
        field_name="owner_subject_ref",
        expected_type=OA_USER_REF_TYPE,
    )
    uploaded_by_subject_ref = ownership_ref.get("uploaded_by_subject_ref")
    if uploaded_by_subject_ref is None:
        uploaded_by_subject_ref = owner_subject_ref
    else:
        uploaded_by_subject_ref = required_resolver_subject_ref(
            uploaded_by_subject_ref,
            field_name="uploaded_by_subject_ref",
            expected_type=OA_USER_REF_TYPE,
        )
    return {
        "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": tenant_ref,
        "owner_subject_ref": owner_subject_ref,
        "uploaded_by_subject_ref": uploaded_by_subject_ref,
        "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
    }


def required_resolver_subject_ref(
    value: Any,
    *,
    field_name: str,
    expected_type: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"{field_name} must be an object.",
        )
    unknown_fields = sorted(set(value) - SUBJECT_REF_ALLOWED_FIELDS)
    if unknown_fields:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"{field_name} contains unsupported fields: {', '.join(unknown_fields)}.",
        )
    subject_type = _non_empty_string(value.get("type"), field_name=f"{field_name}.type")
    if subject_type != expected_type:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"{field_name}.type must be {expected_type}.",
        )
    return {
        "type": subject_type,
        "id": _non_empty_string(value.get("id"), field_name=f"{field_name}.id"),
    }


def _snapshot_ref(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    subject = snapshot.get("subject", {})
    if not isinstance(subject, Mapping):
        subject = {}
    return {
        "tenant_ref": dict(snapshot.get("tenant_ref", {})),
        "subject_ref": dict(snapshot.get("subject_ref", {})),
        "status": str(subject.get("status", "UNKNOWN")),
    }


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SubjectRegistryResolverError(
            status_code=response.status_code,
            error_code="oa.subject_resolver_response_invalid",
            detail="Subject registry endpoint did not return valid JSON.",
            retryable=response.status_code >= 500,
        ) from exc
    if not isinstance(payload, dict):
        raise SubjectRegistryResolverError(
            status_code=response.status_code,
            error_code="oa.subject_resolver_response_invalid",
            detail="Subject registry endpoint did not return a JSON object.",
            retryable=response.status_code >= 500,
        )
    return payload


def _service_token_env(caller_service_id: str) -> str:
    try:
        return CALLER_SERVICE_TO_OA_TOKEN_ENV[caller_service_id]
    except KeyError as exc:
        raise SubjectRegistryResolverError(
            status_code=400,
            error_code="oa.subject_resolver_caller_invalid",
            detail=f"Unsupported subject resolver caller service: {caller_service_id}",
        ) from exc


def _positive_float_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: float,
) -> float:
    raw_value = env.get(key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_timeout_invalid",
            detail=f"{key} must be a positive number.",
        ) from exc
    if value <= 0:
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_timeout_invalid",
            detail=f"{key} must be a positive number.",
        )
    return value


def _non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SubjectRegistryResolverError(
            status_code=422,
            error_code="oa.subject_resolver_owner_ref_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _quote_path_value(value: str) -> str:
    return quote(value, safe="")
