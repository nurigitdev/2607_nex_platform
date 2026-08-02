from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_OWNER_USER_ID = "local-user"
DEFAULT_TARGET_FORMATS = ["MD", "HTML_PREVIEW"]
DEFAULT_RETENTION_POLICY_REF = "generated-artifact-retention-local-v1"
SUPPORTED_ARTIFACT_INTENTS = {
    "preview_only",
    "create_artifact",
    "create_and_export",
}
SUPPORTED_TARGET_FORMATS = {"MD", "HTML_PREVIEW", "DOCX", "PDF"}


class CxArtifactSourceClient(Protocol):
    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpCxArtifactSourceClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def get_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            f"/api/v1/generations/{cx_generation_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            f"/api/v1/generations/{cx_generation_id}/structured-draft",
            request_id=request_id,
            trace_id=trace_id,
        )

    def _get_json(
        self,
        path: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
        ).access_token
        response = httpx.get(
            f"{self.base_url}{path}",
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
            raise ArtifactHandoffError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.artifact_source_request_failed"),
                detail=body.get("detail", "CX artifact source request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class ArtifactHandoffStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["artifact_handoff_id"]] = record
        return record

    def get(self, artifact_handoff_id: str) -> dict[str, Any] | None:
        return self.records.get(artifact_handoff_id)


@dataclass(frozen=True)
class ArtifactHandoffError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_ARTIFACT_HANDOFF_STORE = ArtifactHandoffStore()


def build_default_cx_artifact_source_client() -> HttpCxArtifactSourceClient:
    return HttpCxArtifactSourceClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_artifact_handoff_routes(
    app: FastAPI,
    *,
    store: ArtifactHandoffStore | None = None,
    cx_client: CxArtifactSourceClient | None = None,
) -> None:
    handoff_store = store or DEFAULT_ARTIFACT_HANDOFF_STORE
    client = cx_client or build_default_cx_artifact_source_client()

    @app.post("/api/v1/artifact-handoffs", response_model=None)
    def create_artifact_handoff(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            cx_generation_id = required_string(
                payload,
                "cx_generation_id",
                "ae.cx_generation_id_required",
            )
            generation_record = client.get_generation(
                cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            structured_draft = client.get_structured_draft(
                cx_generation_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            return handoff_store.save(
                build_artifact_handoff_record(
                    source_payload=payload,
                    generation_record=generation_record,
                    structured_draft=structured_draft,
                    artifact_request_id=idempotency_key
                    or optional_text(payload.get("artifact_request_id")),
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except ArtifactHandoffError as exc:
            return _artifact_problem_response(request, exc)

    @app.get("/api/v1/artifact-handoffs/{artifact_handoff_id}", response_model=None)
    def get_artifact_handoff(
        artifact_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = handoff_store.get(artifact_handoff_id)
        if record is None:
            return _artifact_problem_response(
                request,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_handoff_not_found",
                    detail=f"Artifact handoff was not found: {artifact_handoff_id}",
                ),
            )
        return record


def build_artifact_handoff_record(
    *,
    source_payload: dict[str, Any],
    generation_record: dict[str, Any],
    structured_draft: dict[str, Any],
    artifact_request_id: str | None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    validate_source_generation(generation_record, structured_draft)
    chat_document_id = required_string(
        source_payload,
        "chat_document_id",
        "ae.chat_document_id_required",
    )
    interaction_id = required_string(
        source_payload,
        "interaction_id",
        "ae.interaction_id_required",
    )
    normalized_artifact_request_id = artifact_request_id or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-request:"
                f"{chat_document_id}:{interaction_id}:{generation_record['cx_generation_id']}"
            ),
        )
    )
    artifact_handoff_id = source_payload.get("artifact_handoff_id") or str(
        uuid5(NAMESPACE_URL, f"ae-artifact-handoff:{normalized_artifact_request_id}")
    )
    now = _utc_now()
    citation_claims_hash = sha256_json({"citations": structured_draft["citations"]})
    validation_result_hash = sha256_json(structured_draft["validation"])
    request_metadata = generation_record.get("request_metadata", {})
    return {
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "artifact_handoff_id": artifact_handoff_id,
        "artifact_request_id": normalized_artifact_request_id,
        "handoff_status": "READY_FOR_RENDERING",
        "trace_id": trace_id,
        "request_id": request_id,
        "chat_document_id": chat_document_id,
        "interaction_id": interaction_id,
        "actor_claims_ref": actor_claims_ref_from_payload(source_payload),
        "workspace_ref": workspace_ref_from_payload(source_payload),
        "cx_generation_id": generation_record["cx_generation_id"],
        "structured_draft_id": structured_draft["structured_draft_id"],
        "draft_schema_version": structured_draft["structured_draft_schema_version"],
        "structured_draft_content_hash": structured_draft["content_hash"],
        "citation_claims_hash": citation_claims_hash,
        "validation_result_hash": validation_result_hash,
        "template_id": optional_text(source_payload.get("template_id")),
        "template_version": optional_text(source_payload.get("template_version")),
        "rendering_template_id": optional_text(source_payload.get("rendering_template_id")),
        "artifact_intent": artifact_intent_from_payload(source_payload),
        "target_formats": target_formats_from_payload(source_payload),
        "artifact_title": artifact_title_from_payload(source_payload, structured_draft),
        "language": language_from_payload(source_payload),
        "retention_policy_ref": optional_text(source_payload.get("retention_policy_ref"))
        or DEFAULT_RETENTION_POLICY_REF,
        "quality_summary": {
            "citation_status": structured_draft["validation"]["citation_status"],
            "citation_count": len(structured_draft["citations"]),
            "validation_error_count": len(structured_draft["validation"]["errors"]),
            "warning_count": len(structured_draft["validation"]["warnings"]),
            "grounding_required": bool(request_metadata.get("grounding_required")),
            "retrieval_package_id": request_metadata.get("retrieval_package_id"),
            "retrieval_package_hash": request_metadata.get("retrieval_package_hash"),
            "evidence_ref_count": int(request_metadata.get("selected_evidence_count") or 0),
        },
        "created_at": now,
        "updated_at": now,
    }


def validate_source_generation(
    generation_record: dict[str, Any],
    structured_draft: dict[str, Any],
) -> None:
    if generation_record.get("status") != "COMPLETED":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.source_generation_not_ready",
            detail="CX generation must be COMPLETED before artifact handoff.",
        )
    if structured_draft.get("status") != "VALIDATED":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.citation_validation_required",
            detail="Structured draft must be validated before artifact handoff.",
        )
    if structured_draft.get("validation", {}).get("citation_status") != "VALIDATED":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.citation_validation_required",
            detail="Citation validation must pass before artifact handoff.",
        )
    if structured_draft.get("cx_generation_id") != generation_record.get("cx_generation_id"):
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.source_draft_hash_mismatch",
            detail="Structured draft does not belong to the CX generation record.",
        )
    expected_draft_id = generation_record.get("request_metadata", {}).get(
        "structured_draft_id"
    )
    if expected_draft_id and expected_draft_id != structured_draft.get("structured_draft_id"):
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.source_draft_hash_mismatch",
            detail="Structured draft ID does not match the CX generation record.",
        )


def actor_claims_ref_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    actor_ref = payload.get("actor_claims_ref")
    if actor_ref is not None and not isinstance(actor_ref, dict):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.actor_claims_ref_invalid",
            detail="actor_claims_ref must be an object when supplied.",
        )
    source = actor_ref or payload
    return {
        "actor_type": optional_text(source.get("actor_type")) or "user",
        "actor_id": optional_text(source.get("actor_id"))
        or optional_text(source.get("owner_user_id"))
        or DEFAULT_OWNER_USER_ID,
        "tenant_id": optional_text(source.get("tenant_id")) or DEFAULT_TENANT_ID,
    }


def workspace_ref_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    tenant_id = optional_text(payload.get("tenant_id")) or DEFAULT_TENANT_ID
    owner_user_id = optional_text(payload.get("owner_user_id")) or DEFAULT_OWNER_USER_ID
    workspace_id = optional_text(payload.get("workspace_id")) or str(
        uuid5(NAMESPACE_URL, f"ae-workspace:{tenant_id}:{owner_user_id}:default")
    )
    return {
        "workspace_id": workspace_id,
        "tenant_id": tenant_id,
    }


def artifact_intent_from_payload(payload: dict[str, Any]) -> str:
    artifact_intent = optional_text(payload.get("artifact_intent")) or "create_artifact"
    if artifact_intent not in SUPPORTED_ARTIFACT_INTENTS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_intent_invalid",
            detail=f"Unsupported artifact intent: {artifact_intent}",
        )
    return artifact_intent


def target_formats_from_payload(payload: dict[str, Any]) -> list[str]:
    formats = payload.get("target_formats", DEFAULT_TARGET_FORMATS)
    if not isinstance(formats, list) or not formats:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.target_formats_invalid",
            detail="target_formats must be a non-empty list.",
        )
    normalized: list[str] = []
    for value in formats:
        if not isinstance(value, str) or value not in SUPPORTED_TARGET_FORMATS:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.render_format_unsupported",
                detail=f"Unsupported render format: {value}",
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def artifact_title_from_payload(
    payload: dict[str, Any],
    structured_draft: dict[str, Any],
) -> str:
    return optional_text(payload.get("artifact_title")) or structured_draft["title"]


def language_from_payload(payload: dict[str, Any]) -> str:
    language = optional_text(payload.get("language")) or "ko"
    if language not in {"ko", "en"}:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.language_invalid",
            detail="language must be ko or en.",
        )
    return language


def required_string(payload: dict[str, Any], field_name: str, error_code: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required.",
        )
    return value.strip()


def optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def sha256_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _authorize_ae_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AE API requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _artifact_problem_response(
    request: Request,
    exc: ArtifactHandoffError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Artifact handoff failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/artifact-handoff-failed",
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
