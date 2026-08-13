from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    SubjectRegistryResolver,
    SubjectRegistryResolverError,
    build_default_subject_registry_resolver,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)

if TYPE_CHECKING:
    from nex_ae_api.auth_guard import BrowserUserAuthContext
    from nex_ae_api.oa_session_client import OaUserSessionClient


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_OWNER_USER_ID = "local-user"
OWNERSHIP_REF_SCHEMA_VERSION = "cx_source_ownership_ref.v1"
OA_TENANT_REF_TYPE = "oa.tenant"
OA_USER_SUBJECT_REF_TYPE = "oa.user"
OWNERSHIP_COMPATIBILITY_MODE = "legacy_owner_fields_mapped_to_oa_subject_refs"
UPLOAD_OWNER_RESOLVER_DISABLED = "disabled"
UPLOAD_OWNER_RESOLVER_VERIFY = "verify"
UPLOAD_OWNER_RESOLVER_ENSURE = "ensure"
UPLOAD_OWNER_RESOLVER_MODES = frozenset(
    {
        UPLOAD_OWNER_RESOLVER_DISABLED,
        UPLOAD_OWNER_RESOLVER_VERIFY,
        UPLOAD_OWNER_RESOLVER_ENSURE,
    }
)
UPLOAD_OWNER_RESOLVER_MODE_ENV = "NEX_AE_UPLOAD_OWNER_RESOLVER_MODE"


class CxUploadClient(Protocol):
    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpCxUploadClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def register_upload(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        request_payload = {**payload, "trace_id": payload.get("trace_id", trace_id)}
        if "ownership_ref" not in request_payload:
            request_payload = build_cx_upload_payload(request_payload, trace_id=trace_id)
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/documents/uploads",
            json=request_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ae-api",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise UploadHandoffError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.upload_request_failed"),
                detail=body.get("detail", "CX upload registration failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class UploadHandoffStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["upload_handoff_id"]] = record
        return record

    def get(self, upload_handoff_id: str) -> dict[str, Any] | None:
        return self.records.get(upload_handoff_id)

    def get_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        for record in self.records.values():
            document_ref = record.get("cx_document_ref")
            if (
                isinstance(document_ref, dict)
                and document_ref.get("document_id") == document_id
            ):
                return record
        return None

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records.values()
            if record["workspace_id"] == workspace_id
        ]


@dataclass(frozen=True)
class UploadHandoffError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_UPLOAD_HANDOFF_STORE = UploadHandoffStore()


def build_default_cx_upload_client() -> HttpCxUploadClient:
    return HttpCxUploadClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_upload_routes(
    app: FastAPI,
    *,
    store: UploadHandoffStore | None = None,
    cx_client: CxUploadClient | None = None,
    owner_resolver: SubjectRegistryResolver | None = None,
    owner_resolver_mode: str | None = None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    upload_store = store or DEFAULT_UPLOAD_HANDOFF_STORE
    client = cx_client or build_default_cx_upload_client()
    resolver_mode = normalize_upload_owner_resolver_mode(
        owner_resolver_mode or os.getenv(UPLOAD_OWNER_RESOLVER_MODE_ENV)
    )
    resolved_session_mode = session_mode
    if resolved_session_mode is None:
        from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_ENV

        resolved_session_mode = os.getenv(AUTH_SESSION_MODE_ENV)
    resolver = owner_resolver
    if resolver is None and resolver_mode != UPLOAD_OWNER_RESOLVER_DISABLED:
        resolver = build_default_subject_registry_resolver(
            caller_service_id="nex-ae-api"
        )

    @app.post("/api/v1/uploads", response_model=None)
    def create_upload_handoff(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        from nex_ae_api.route_auth import authorize_ae_facade_route_request

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        from nex_ae_api.auth_guard import BrowserAuthError, browser_auth_problem_response

        try:
            auth_context = authorize_ae_facade_route_request(
                request,
                authorization,
                oa_session_client=oa_session_client,
                session_mode=resolved_session_mode,
            )
            if isinstance(auth_context, JSONResponse):
                return auth_context
            source_payload = _browser_owner_scoped_payload(
                payload,
                auth_context.browser_context,
            )
            cx_payload = build_cx_upload_payload(source_payload, trace_id=trace_id)
            resolve_upload_ownership(
                cx_payload["ownership_ref"],
                owner_resolver=resolver,
                owner_resolver_mode=resolver_mode,
                request_id=request_id,
                trace_id=trace_id,
            )
            cx_record = client.register_upload(
                cx_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            status_code = 200 if cx_record["dedupe"]["status"] == "ALREADY_EXISTS" else 202
            return JSONResponse(
                status_code=status_code,
                content=upload_store.save(
                    build_upload_handoff_record(
                        source_payload=source_payload,
                        cx_payload=cx_payload,
                        cx_record=cx_record,
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                ),
            )
        except BrowserAuthError as exc:
            return browser_auth_problem_response(request, exc)
        except UploadHandoffError as exc:
            return _upload_problem_response(request, exc)

    @app.get("/api/v1/uploads/{upload_handoff_id}", response_model=None)
    def get_upload_handoff(
        upload_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        from nex_ae_api.route_auth import authorize_ae_facade_route_request

        auth_context = authorize_ae_facade_route_request(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=resolved_session_mode,
        )
        if isinstance(auth_context, JSONResponse):
            return auth_context

        record = upload_store.get(upload_handoff_id)
        if record is None:
            return _upload_problem_response(
                request,
                UploadHandoffError(
                    status_code=404,
                    error_code="ae.upload_handoff_not_found",
                    detail=f"Upload handoff was not found: {upload_handoff_id}",
                ),
            )
        if auth_context.browser_context is not None:
            from nex_ae_api.auth_guard import (
                BrowserAuthError,
                browser_auth_problem_response,
            )

            try:
                ensure_upload_handoff_visible_to_browser(
                    record,
                    auth_context.browser_context,
                )
            except BrowserAuthError as exc:
                return browser_auth_problem_response(request, exc)
        return record


def build_cx_upload_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    ownership_ref = build_upload_ownership_ref(source_payload)
    tenant_id = ownership_ref["legacy"]["tenant_id"]
    owner_user_id = ownership_ref["legacy"]["owner_user_id"]
    filename = required_string(source_payload, "filename", "ae.upload_filename_required")
    content_type = optional_string(
        source_payload,
        "content_type",
        "application/octet-stream",
    )
    content_text = source_payload.get("content_text")
    if content_text is not None and not isinstance(content_text, str):
        raise UploadHandoffError(
            status_code=422,
            error_code="ae.upload_content_text_invalid",
            detail="content_text must be a string when supplied.",
        )

    payload: dict[str, Any] = {
        "trace_id": trace_id,
        "filename": filename,
        "content_type": content_type,
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "ownership_ref": ownership_ref,
    }
    if isinstance(content_text, str):
        payload["content_text"] = content_text
    if "source_sha256" in source_payload:
        payload["source_sha256"] = required_hash(source_payload["source_sha256"])
    if "size_bytes" in source_payload:
        payload["size_bytes"] = non_negative_int(source_payload["size_bytes"])
    return payload


def resolve_upload_ownership(
    ownership_ref: dict[str, Any],
    *,
    owner_resolver: SubjectRegistryResolver | None,
    owner_resolver_mode: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    mode = normalize_upload_owner_resolver_mode(owner_resolver_mode)
    if mode == UPLOAD_OWNER_RESOLVER_DISABLED:
        return None
    if owner_resolver is None:
        raise UploadHandoffError(
            status_code=503,
            error_code="ae.upload_owner_resolver_unavailable",
            detail="AE upload owner resolver is enabled but not configured.",
            retryable=True,
        )
    try:
        return owner_resolver.resolve_ownership_ref(
            ownership_ref,
            request_id=request_id,
            trace_id=trace_id,
            ensure=mode == UPLOAD_OWNER_RESOLVER_ENSURE,
        )
    except SubjectRegistryResolverError as exc:
        raise UploadHandoffError(
            status_code=exc.status_code,
            error_code="ae.upload_owner_unresolved",
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc


def normalize_upload_owner_resolver_mode(value: str | None) -> str:
    mode = (value or UPLOAD_OWNER_RESOLVER_DISABLED).strip().lower()
    if mode not in UPLOAD_OWNER_RESOLVER_MODES:
        raise UploadHandoffError(
            status_code=422,
            error_code="ae.upload_owner_resolver_mode_invalid",
            detail=(
                f"{UPLOAD_OWNER_RESOLVER_MODE_ENV} must be one of: "
                f"{', '.join(sorted(UPLOAD_OWNER_RESOLVER_MODES))}."
            ),
        )
    return mode


def build_upload_ownership_ref(source_payload: dict[str, Any]) -> dict[str, Any]:
    ownership_ref = source_payload.get("ownership_ref")
    if ownership_ref is not None and not isinstance(ownership_ref, dict):
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail="ownership_ref must be an object when supplied.",
        )
    ownership_payload = ownership_ref or {}
    tenant_ref = subject_ref_from_payload(
        source_payload,
        ownership_payload,
        field_name="tenant_ref",
        expected_type=OA_TENANT_REF_TYPE,
        legacy_fields=("tenant_id",),
        default_id=DEFAULT_TENANT_ID,
    )
    owner_subject_ref = subject_ref_from_payload(
        source_payload,
        ownership_payload,
        field_name="owner_subject_ref",
        expected_type=OA_USER_SUBJECT_REF_TYPE,
        legacy_fields=("owner_user_id", "user_id"),
        default_id=DEFAULT_OWNER_USER_ID,
    )
    uploaded_by_subject_ref = subject_ref_from_payload(
        source_payload,
        ownership_payload,
        field_name="uploaded_by_subject_ref",
        expected_type=OA_USER_SUBJECT_REF_TYPE,
        legacy_fields=("uploaded_by_user_id",),
        default_id=owner_subject_ref["id"],
    )
    return {
        "ownership_schema_version": OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": tenant_ref,
        "owner_subject_ref": owner_subject_ref,
        "uploaded_by_subject_ref": uploaded_by_subject_ref,
        "legacy": {
            "tenant_id": tenant_ref["id"],
            "owner_user_id": owner_subject_ref["id"],
        },
        "compatibility_mode": OWNERSHIP_COMPATIBILITY_MODE,
    }


def build_upload_handoff_record(
    *,
    source_payload: dict[str, Any],
    cx_payload: dict[str, Any],
    cx_record: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    tenant_id = cx_payload["tenant_id"]
    owner_user_id = cx_payload["owner_user_id"]
    workspace_id = source_payload.get("workspace_id") or str(
        uuid5(NAMESPACE_URL, f"ae-workspace:{tenant_id}:{owner_user_id}:default")
    )
    source_sha256 = cx_record["source_sha256"]
    upload_handoff_id = source_payload.get("upload_handoff_id") or str(
        uuid5(NAMESPACE_URL, f"ae-upload-handoff:{workspace_id}:{source_sha256}")
    )
    now = _utc_now()
    return {
        "upload_handoff_schema_version": "ae_upload_handoff.v1",
        "upload_handoff_id": upload_handoff_id,
        "workspace_id": workspace_id,
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "ownership_ref": cx_payload["ownership_ref"],
        "status": upload_handoff_status(cx_record),
        "trace_id": trace_id,
        "request_id": request_id,
        "source": {
            "filename": cx_record["filename"],
            "content_type": cx_record["content_type"],
            "size_bytes": cx_record["size_bytes"],
            "source_sha256": source_sha256,
            "source_text_hash": sha256_text(cx_payload["content_text"])
            if "content_text" in cx_payload
            else None,
        },
        "cx_document_ref": {
            "document_id": cx_record["document_id"],
            "upload_id": cx_record["upload_id"],
            "ingestion_job_id": cx_record["extraction"]["job_id"],
            "extraction_status": cx_record["extraction"]["status"],
            "markdown_available": cx_record["extraction"]["markdown_available"],
            "dedupe_status": cx_record["dedupe"]["status"],
            "existing_document_id": cx_record["dedupe"]["existing_document_id"],
        },
        "links": {
            "cx_document": f"/api/v1/documents/{cx_record['document_id']}",
            "cx_ingestion_job": f"/api/v1/jobs/{cx_record['extraction']['job_id']}",
        },
        "metadata": {
            "raw_source_stored_in_ae": False,
            "cx_storage_redacted": True,
        },
        "created_at": now,
        "updated_at": now,
    }


def upload_handoff_status(cx_record: dict[str, Any]) -> str:
    if cx_record["dedupe"]["status"] == "ALREADY_EXISTS":
        return "ALREADY_EXISTS"
    return "QUEUED"


def owner_scope_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    ownership_ref = build_upload_ownership_ref(payload)
    return (
        ownership_ref["legacy"]["tenant_id"],
        ownership_ref["legacy"]["owner_user_id"],
    )


def ensure_upload_handoff_visible_to_browser(
    upload_handoff: dict[str, Any],
    context: BrowserUserAuthContext,
) -> None:
    from nex_ae_api.auth_guard import apply_claim_owner_scope

    apply_claim_owner_scope(
        {
            "tenant_id": upload_handoff.get("tenant_id"),
            "owner_user_id": upload_handoff.get("owner_user_id"),
        },
        context,
    )


def _browser_owner_scoped_payload(
    payload: dict[str, Any],
    context: BrowserUserAuthContext | None,
) -> dict[str, Any]:
    if context is None:
        return payload
    from nex_ae_api.auth_guard import apply_claim_owner_scope

    return apply_claim_owner_scope(payload, context)


def subject_ref_from_payload(
    source_payload: dict[str, Any],
    ownership_payload: dict[str, Any],
    *,
    field_name: str,
    expected_type: str,
    legacy_fields: tuple[str, ...],
    default_id: str,
) -> dict[str, str]:
    if field_name in ownership_payload:
        subject_ref = required_subject_ref(
            ownership_payload[field_name],
            field_name=f"ownership_ref.{field_name}",
            expected_type=expected_type,
        )
    elif field_name in source_payload:
        subject_ref = required_subject_ref(
            source_payload[field_name],
            field_name=field_name,
            expected_type=expected_type,
        )
    else:
        subject_ref = {
            "type": expected_type,
            "id": first_legacy_subject_id(
                source_payload,
                legacy_fields=legacy_fields,
                default_id=default_id,
            ),
        }

    if field_name in ownership_payload and field_name in source_payload:
        direct_ref = required_subject_ref(
            source_payload[field_name],
            field_name=field_name,
            expected_type=expected_type,
        )
        ensure_matching_subject_ref(
            subject_ref,
            direct_ref,
            field_name=field_name,
        )
    for legacy_field in legacy_fields:
        if legacy_field in source_payload:
            legacy_id = optional_string(source_payload, legacy_field, subject_ref["id"])
            if legacy_id != subject_ref["id"]:
                raise UploadHandoffError(
                    status_code=400,
                    error_code="ae.upload_owner_invalid",
                    detail=(
                        f"{legacy_field} must match {field_name}.id when both "
                        "are supplied."
                    ),
                )
    return subject_ref


def first_legacy_subject_id(
    payload: dict[str, Any],
    *,
    legacy_fields: tuple[str, ...],
    default_id: str,
) -> str:
    for legacy_field in legacy_fields:
        if legacy_field in payload:
            return optional_string(payload, legacy_field, default_id)
    return optional_string({legacy_fields[0]: default_id}, legacy_fields[0], default_id)


def required_subject_ref(
    value: Any,
    *,
    field_name: str,
    expected_type: str,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail=f"{field_name} must be an object.",
        )
    subject_type = required_owner_string(value, "type", field_name=field_name)
    if subject_type != expected_type:
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail=f"{field_name}.type must be {expected_type}.",
        )
    return {
        "type": subject_type,
        "id": required_owner_string(value, "id", field_name=field_name),
    }


def required_owner_string(
    value: dict[str, Any],
    key: str,
    *,
    field_name: str,
) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail=f"{field_name}.{key} must be a non-empty string.",
        )
    return raw.strip()


def ensure_matching_subject_ref(
    expected_ref: dict[str, str],
    actual_ref: dict[str, str],
    *,
    field_name: str,
) -> None:
    if expected_ref != actual_ref:
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail=f"{field_name} must match ownership_ref.{field_name}.",
        )


def required_string(payload: dict[str, Any], field_name: str, error_code: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise UploadHandoffError(
            status_code=400,
            error_code=error_code,
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def optional_string(payload: dict[str, Any], field_name: str, default: str) -> str:
    value = payload.get(field_name, default)
    if not isinstance(value, str) or not value.strip():
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_owner_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def required_hash(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_source_hash_invalid",
            detail="source_sha256 must be a lowercase SHA-256 hex string.",
        )
    normalized = value.strip()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_source_hash_invalid",
            detail="source_sha256 must be a lowercase SHA-256 hex string.",
        )
    return normalized


def non_negative_int(value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise UploadHandoffError(
            status_code=400,
            error_code="ae.upload_size_invalid",
            detail="size_bytes must be a non-negative integer.",
        )
    return value


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _upload_problem_response(
    request: Request,
    exc: UploadHandoffError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Upload handoff failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/upload-handoff-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
