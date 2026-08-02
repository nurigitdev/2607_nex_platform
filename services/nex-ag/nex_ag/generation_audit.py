from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


SAFE_TIMELINE_FIELDS = {
    "event_id",
    "event_schema_version",
    "event_type",
    "event_source_service",
    "trace_id",
    "request_id",
    "occurred_at",
    "sequence_no",
    "job_status",
    "current_stage",
    "progress_mode",
    "progress_percent",
    "message_key",
    "safe_message",
    "retryable",
    "details",
}
FORBIDDEN_DETAIL_KEYS = {
    "prompt",
    "messages",
    "content",
    "content_text",
    "source_text",
    "output_text",
    "raw_prompt",
    "raw_output",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "storage_path",
    "authorization",
    "cookie",
}
FORBIDDEN_DETAIL_FRAGMENTS = {"api_key", "bearer", "password", "secret"}


class GenerationAuditSourceClient(Protocol):
    def get_cx_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_cx_generation_events(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_ae_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_ae_recovery_request(
        self,
        recovery_request_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpGenerationAuditSourceClient:
    cx_base_url: str = "http://127.0.0.1:8104"
    ae_base_url: str = "http://127.0.0.1:8103"
    cx_service_token: str | None = None
    ae_service_token: str | None = None
    timeout_seconds: float = 5.0

    def get_cx_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            self.cx_base_url,
            f"/api/v1/generations/{cx_generation_id}",
            audience="nex-cx",
            service_token=self.cx_service_token,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_cx_generation_events(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            self.cx_base_url,
            f"/api/v1/generations/{cx_generation_id}/events",
            audience="nex-cx",
            service_token=self.cx_service_token,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_ae_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            self.ae_base_url,
            f"/api/v1/artifact-handoffs/{artifact_handoff_id}",
            audience="nex-ae-api",
            service_token=self.ae_service_token,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_ae_recovery_request(
        self,
        recovery_request_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            self.ae_base_url,
            f"/api/v1/recovery/generation-requests/{recovery_request_id}",
            audience="nex-ae-api",
            service_token=self.ae_service_token,
            request_id=request_id,
            trace_id=trace_id,
        )

    def _get_json(
        self,
        base_url: str,
        path: str,
        *,
        audience: str,
        service_token: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = service_token or issue_mock_service_token(
            service_id="nex-ag",
            audience=audience,
        ).access_token
        response = httpx.get(
            f"{base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ag",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise GenerationAuditError(
                status_code=response.status_code,
                error_code=body.get("error_code", "ag.audit_source_request_failed"),
                detail=body.get("detail", "Audit source request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass(frozen=True)
class GenerationAuditError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def build_default_generation_audit_client() -> HttpGenerationAuditSourceClient:
    return HttpGenerationAuditSourceClient(
        cx_base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        ae_base_url=os.getenv("NEX_AE_API_BASE_URL", "http://127.0.0.1:8103"),
        cx_service_token=os.getenv("NEX_AG_TO_CX_SERVICE_TOKEN"),
        ae_service_token=os.getenv("NEX_AG_TO_AE_SERVICE_TOKEN"),
    )


def register_generation_audit_routes(
    app: FastAPI,
    *,
    source_client: GenerationAuditSourceClient | None = None,
) -> None:
    client = source_client or build_default_generation_audit_client()

    @app.get("/admin/v1/generation-audit/generations/{cx_generation_id}", response_model=None)
    def get_generation_audit_projection(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        artifact_handoff_id: str | None = Query(default=None, min_length=1),
        recovery_request_id: str | None = Query(default=None, min_length=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            return build_generation_audit_projection(
                client,
                cx_generation_id=cx_generation_id,
                artifact_handoff_id=artifact_handoff_id,
                recovery_request_id=recovery_request_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except GenerationAuditError as exc:
            return _audit_problem_response(request, exc)


def build_generation_audit_projection(
    client: GenerationAuditSourceClient,
    *,
    cx_generation_id: str,
    artifact_handoff_id: str | None,
    recovery_request_id: str | None = None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    generation_record = client.get_cx_generation(
        cx_generation_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    progress_payload = client.get_cx_generation_events(
        cx_generation_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    artifact_handoff = (
        client.get_ae_artifact_handoff(
            artifact_handoff_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        if artifact_handoff_id is not None
        else None
    )
    recovery_request = (
        client.get_ae_recovery_request(
            recovery_request_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        if recovery_request_id is not None
        else None
    )
    now = _utc_now()
    audit_event = build_ag_generation_audit_event(
        generation_record=generation_record,
        artifact_handoff=artifact_handoff,
        recovery_request=recovery_request,
        timeline_events=progress_payload.get("events", []),
        occurred_at=now,
    )
    return {
        "projection_schema_version": "ag_generation_audit_projection.v1",
        "cx_generation_id": generation_record["cx_generation_id"],
        "trace_id": generation_record["trace_id"],
        "request_id": generation_record["request_id"],
        "audit_event": audit_event,
        "generation_summary": generation_summary(generation_record),
        "timeline": project_timeline_events(progress_payload),
        "artifact_handoff_summary": artifact_handoff_summary(artifact_handoff),
        "recovery_request_summary": recovery_request_summary(recovery_request),
        "redaction_summary": {
            "raw_content_included": False,
            "excluded_fields": [
                "raw_prompt",
                "messages",
                "source_text",
                "output_text",
                "provider_url",
                "model_path",
                "storage_path",
            ],
        },
        "created_at": now,
    }


def build_ag_generation_audit_event(
    *,
    generation_record: dict[str, Any],
    artifact_handoff: dict[str, Any] | None,
    timeline_events: list[dict[str, Any]],
    recovery_request: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    result_status = "SUCCEEDED" if generation_record.get("status") == "COMPLETED" else "FAILED"
    action_type = audit_action_type(recovery_request)
    actor_ref = (
        artifact_handoff["actor_claims_ref"]
        if artifact_handoff is not None
        else {"actor_type": "service", "actor_id": "nex-cx", "tenant_id": "system"}
    )
    target_id = generation_record["cx_generation_id"]
    return {
        "event_schema_version": "ag_generation_audit_event.v1",
        "audit_event_id": str(
            uuid5(
                NAMESPACE_URL,
                f"ag-generation-audit:{target_id}:{result_status}",
            )
        ),
        "trace_id": generation_record["trace_id"],
        "request_id": generation_record["request_id"],
        "occurred_at": occurred_at or _utc_now(),
        "source_service": "nex-cx",
        "actor_ref": actor_ref,
        "action_type": action_type,
        "target_type": "generation",
        "target_ref": {
            "target_id": target_id,
            "display_summary": generation_record.get("alias", "generation"),
        },
        "result_status": result_status,
        "quality_summary": quality_summary_from_sources(
            generation_record,
            artifact_handoff,
        ),
        "compatibility_summary": compatibility_summary(generation_record),
        "provider_summary": provider_summary(generation_record),
        "details": safe_details(
            {
                "timeline_event_count": len(timeline_events),
                "artifact_handoff_id": artifact_handoff["artifact_handoff_id"]
                if artifact_handoff
                else None,
                "recovery_request_id": recovery_request["recovery_request_id"]
                if recovery_request
                else None,
                "requested_action": recovery_request["requested_action"]
                if recovery_request
                else None,
                "policy_hash_status": recovery_request["policy"]["hash_status"]
                if recovery_request
                else None,
            }
        ),
    }


def generation_summary(generation_record: dict[str, Any]) -> dict[str, Any]:
    metadata = generation_record.get("request_metadata", {})
    response_metadata = generation_record.get("response_metadata", {})
    return {
        "cx_generation_id": generation_record["cx_generation_id"],
        "status": generation_record["status"],
        "alias": generation_record.get("alias"),
        "provider_capability": generation_record.get("provider_capability"),
        "mo_generation_id": generation_record.get("mo_generation_id"),
        "finish_reason": response_metadata.get("finish_reason"),
        "output_hash": response_metadata.get("output_hash"),
        "structured_draft_id": metadata.get("structured_draft_id"),
        "draft_validation_status": metadata.get("draft_validation_status"),
        "failure": failure_summary(generation_record),
    }


def project_timeline_events(progress_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = progress_payload.get("events", [])
    if not isinstance(events, list):
        return []
    return [
        {
            key: safe_details(value) if key == "details" and isinstance(value, dict) else value
            for key, value in event.items()
            if key in SAFE_TIMELINE_FIELDS
        }
        for event in events
        if isinstance(event, dict)
    ]


def artifact_handoff_summary(
    artifact_handoff: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if artifact_handoff is None:
        return None
    return {
        "artifact_handoff_id": artifact_handoff["artifact_handoff_id"],
        "handoff_status": artifact_handoff["handoff_status"],
        "artifact_intent": artifact_handoff["artifact_intent"],
        "target_formats": artifact_handoff["target_formats"],
        "artifact_title": artifact_handoff["artifact_title"],
        "structured_draft_id": artifact_handoff["structured_draft_id"],
        "structured_draft_content_hash": artifact_handoff[
            "structured_draft_content_hash"
        ],
        "quality_summary": artifact_handoff["quality_summary"],
    }


def recovery_request_summary(
    recovery_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if recovery_request is None:
        return None
    dispatch = recovery_request["dispatch"]
    policy = recovery_request["policy"]
    failure = recovery_request["failure"]
    return {
        "recovery_request_id": recovery_request["recovery_request_id"],
        "status": recovery_request["status"],
        "requested_action": recovery_request["requested_action"],
        "cx_generation_id": recovery_request["cx_generation_id"],
        "parent_generation_id": recovery_request["parent_generation_id"],
        "failure_code": failure["failure_code"],
        "failure_class": failure["failure_class"],
        "policy_hash_status": policy["hash_status"],
        "target_service": dispatch["target_service"],
        "endpoint_hint": dispatch["endpoint_hint"],
        "attempt_no": dispatch["attempt_no"],
        "reuse_retrieval_package": dispatch["reuse_retrieval_package"],
        "requires_user_confirmation": dispatch["requires_user_confirmation"],
    }


def failure_summary(generation_record: dict[str, Any]) -> dict[str, Any] | None:
    failure = generation_record.get("failure")
    if not isinstance(failure, dict):
        return None
    return safe_details(
        {
            "failure_code": failure.get("failure_code"),
            "failure_class": failure.get("failure_class"),
            "owner_service": failure.get("owner_service"),
            "failed_stage": failure.get("failed_stage"),
            "retryable": failure.get("retryable"),
            "recovery_policy_id": failure.get("recovery_policy_id"),
            "recovery_policy_hash": failure.get("recovery_policy_hash"),
        }
    )


def audit_action_type(recovery_request: dict[str, Any] | None) -> str:
    if recovery_request is None:
        return "generation_run"
    action = recovery_request.get("requested_action")
    if action in {"repair", "sectional_retry"}:
        return "repair"
    if action in {"manual_accept_with_warning"}:
        return "override"
    if action in {"retry", "regenerate", "fresh_retrieval_regenerate"}:
        return "retry"
    return "override"


def quality_summary_from_sources(
    generation_record: dict[str, Any],
    artifact_handoff: dict[str, Any] | None,
) -> dict[str, Any]:
    if artifact_handoff is not None:
        return artifact_handoff["quality_summary"]
    metadata = generation_record.get("request_metadata", {})
    return {
        "citation_status": metadata.get("draft_validation_status"),
        "grounding_required": bool(metadata.get("grounding_required")),
        "retrieval_package_id": metadata.get("retrieval_package_id"),
        "retrieval_package_hash": metadata.get("retrieval_package_hash"),
        "evidence_ref_count": int(metadata.get("selected_evidence_count") or 0),
    }


def compatibility_summary(generation_record: dict[str, Any]) -> dict[str, Any]:
    metadata = generation_record.get("request_metadata", {})
    return {
        "compatibility_rule_id": metadata.get("compatibility_rule_id"),
        "grounding_required": bool(metadata.get("grounding_required")),
        "generation_request_hash": metadata.get("generation_request_hash"),
        "provider_prompt_package_hash": metadata.get("provider_prompt_package_hash"),
    }


def provider_summary(generation_record: dict[str, Any]) -> dict[str, Any]:
    runtime = generation_record.get("mo_runtime_metadata", {})
    return {
        "alias": generation_record.get("alias"),
        "mo_generation_id": generation_record.get("mo_generation_id"),
        "usage": generation_record.get("usage", {}),
        "finish_reason": generation_record.get("response_metadata", {}).get(
            "finish_reason"
        ),
        "route_id": runtime.get("route_id"),
        "provider_request_id": runtime.get("provider_request_id"),
        "total_ms": runtime.get("total_ms"),
    }


def safe_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_detail_value(value)
        for key, value in details.items()
        if _is_safe_detail_key(key)
    }


def _is_safe_detail_key(key: str) -> bool:
    lowered = key.lower()
    return lowered not in FORBIDDEN_DETAIL_KEYS and not any(
        fragment in lowered for fragment in FORBIDDEN_DETAIL_FRAGMENTS
    )


def _safe_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        return safe_details(value)
    if isinstance(value, list):
        return [_safe_detail_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _authorize_ag_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ag",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "AG requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _audit_problem_response(
    request: Request,
    exc: GenerationAuditError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation audit projection failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/generation-audit-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
