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

FORBIDDEN_PROVIDER_FIELDS = {"provider_url", "model_path", "provider_endpoint", "api_key"}


class MoGenerationClient(Protocol):
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpMoGenerationClient:
    base_url: str = "http://127.0.0.1:8105"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-cx",
            audience="nex-mo",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/generations",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-cx",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise GenerationFacadeError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.request_failed"),
                detail=body.get("detail", "MO generation request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class GenerationExecutionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["cx_generation_id"]] = record
        return record

    def get(self, cx_generation_id: str) -> dict[str, Any] | None:
        return self.records.get(cx_generation_id)


@dataclass(frozen=True)
class GenerationFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_GENERATION_STORE = GenerationExecutionStore()


def build_default_mo_client() -> HttpMoGenerationClient:
    return HttpMoGenerationClient(
        base_url=os.getenv("NEX_MO_BASE_URL", "http://127.0.0.1:8105"),
        service_token=os.getenv("NEX_CX_TO_MO_SERVICE_TOKEN"),
    )


def register_generation_routes(
    app: FastAPI,
    *,
    store: GenerationExecutionStore | None = None,
    mo_client: MoGenerationClient | None = None,
) -> None:
    generation_store = store or DEFAULT_GENERATION_STORE
    client = mo_client or build_default_mo_client()

    @app.post("/api/v1/generations", response_model=None)
    def create_generation(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            mo_payload = build_mo_generation_payload(payload, trace_id=trace_id)
            mo_response = client.create_generation(
                mo_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            return generation_store.save(
                build_generation_execution_record(
                    source_payload=payload,
                    mo_payload=mo_payload,
                    mo_response=mo_response,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except GenerationFacadeError as exc:
            return _generation_problem_response(request, exc)

    @app.get("/api/v1/generations/{cx_generation_id}", response_model=None)
    def get_generation(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = generation_store.get(cx_generation_id)
        if record is None:
            return _generation_problem_response(
                request,
                GenerationFacadeError(
                    status_code=404,
                    error_code="cx.generation_not_found",
                    detail=f"Generation record was not found: {cx_generation_id}",
                ),
            )
        return record


def build_mo_generation_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    leaked = sorted(FORBIDDEN_PROVIDER_FIELDS & set(source_payload))
    if leaked:
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.provider_field_forbidden",
            detail=f"Provider-private field is not allowed: {leaked[0]}",
        )

    prompt_text = prompt_text_from_payload(source_payload)
    provider_prompt_package_hash = source_payload.get(
        "provider_prompt_package_hash",
        sha256_text(prompt_text),
    )
    request_hash = sha256_json(
        {
            "trace_id": trace_id,
            "alias": source_payload.get("alias", "general-llm-default"),
            "provider_capability": source_payload.get("provider_capability", "generation"),
            "provider_prompt_package_hash": provider_prompt_package_hash,
            "response_format": source_payload.get("response_format", {"type": "text"}),
            "metadata": source_payload.get("metadata", {}),
        }
    )
    cx_generation_id = source_payload.get("cx_generation_id") or str(
        uuid5(NAMESPACE_URL, f"cx-generation:{request_hash}")
    )

    return {
        "request_schema_version": "cx_mo_generation_request.v1",
        "client_request_id": source_payload.get("client_request_id", cx_generation_id),
        "trace_id": trace_id,
        "cx_generation_id": cx_generation_id,
        "provider_prompt_package_hash": provider_prompt_package_hash,
        "alias": source_payload.get("alias", "general-llm-default"),
        "provider_capability": source_payload.get("provider_capability", "generation"),
        "workload_class": source_payload.get("workload_class", "LLM_INTERACTIVE"),
        "generation_profile": source_payload.get("generation_profile", "grounded-answer"),
        "messages": source_payload.get("messages"),
        "prompt": source_payload.get("prompt"),
        "response_format": source_payload.get("response_format", {"type": "text"}),
        "max_output_tokens": source_payload.get("max_output_tokens", 256),
        "temperature": source_payload.get("temperature", 0.0),
        "stream": source_payload.get("stream", False),
        "timeout_ms": source_payload.get("timeout_ms", 5000),
        "metadata": {
            **source_payload.get("metadata", {}),
            "generation_request_hash": request_hash,
        },
    }


def build_generation_execution_record(
    *,
    source_payload: dict[str, Any],
    mo_payload: dict[str, Any],
    mo_response: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    now = _utc_now()
    output = mo_response.get("output", {})
    output_text = output.get("text", "") if isinstance(output, dict) else ""
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": mo_payload["cx_generation_id"],
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "alias": mo_response["alias"],
        "provider_capability": mo_payload["provider_capability"],
        "mo_generation_id": mo_response["mo_generation_id"],
        "request_metadata": {
            "provider_prompt_package_hash": mo_payload["provider_prompt_package_hash"],
            "generation_request_hash": mo_payload["metadata"]["generation_request_hash"],
            "response_format_type": mo_payload["response_format"]["type"],
            "source_has_messages": bool(source_payload.get("messages")),
            "source_has_prompt": bool(source_payload.get("prompt")),
        },
        "response_metadata": {
            "finish_reason": mo_response.get("finish_reason"),
            "output_hash": sha256_text(output_text) if output_text else None,
            "output_preview": output_text[:120],
        },
        "mo_runtime_metadata": _safe_runtime_metadata(
            mo_response.get("runtime_metadata", {})
        ),
        "usage": mo_response.get("usage", {}),
        "created_at": now,
        "updated_at": now,
    }


def prompt_text_from_payload(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt:
        return prompt

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        parts = [
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and message.get("content")
        ]
        if parts:
            return "\n".join(parts)

    raise GenerationFacadeError(
        status_code=400,
        error_code="cx.generation_request_invalid",
        detail="prompt or messages are required.",
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: dict[str, Any]) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _safe_runtime_metadata(runtime_metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "request_id",
        "trace_id",
        "queue_ms",
        "provider_ms",
        "total_ms",
        "route_id",
        "admission_decision",
        "provider_request_id",
    }
    return {
        key: runtime_metadata[key]
        for key in allowed
        if key in runtime_metadata
    }


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _generation_problem_response(
    request: Request,
    exc: GenerationFacadeError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/generation-request-failed",
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
