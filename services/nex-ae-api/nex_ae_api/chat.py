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


class CxGenerationClient(Protocol):
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpCxGenerationClient:
    base_url: str = "http://127.0.0.1:8104"
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
            service_id="nex-ae-api",
            audience="nex-cx",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/generations",
            json=payload,
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
            raise ChatInteractionError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.request_failed"),
                detail=body.get("detail", "CX generation request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class ChatInteractionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["interaction_id"]] = record
        return record

    def get(self, interaction_id: str) -> dict[str, Any] | None:
        return self.records.get(interaction_id)


@dataclass(frozen=True)
class ChatInteractionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_CHAT_STORE = ChatInteractionStore()


def build_default_cx_client() -> HttpCxGenerationClient:
    return HttpCxGenerationClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_chat_routes(
    app: FastAPI,
    *,
    store: ChatInteractionStore | None = None,
    cx_client: CxGenerationClient | None = None,
) -> None:
    chat_store = store or DEFAULT_CHAT_STORE
    client = cx_client or build_default_cx_client()

    @app.post("/api/v1/chat/interactions", response_model=None)
    def create_chat_interaction(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            cx_payload = build_cx_generation_payload(payload, trace_id=trace_id)
            cx_record = client.create_generation(
                cx_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            return chat_store.save(
                build_chat_interaction_record(
                    source_payload=payload,
                    cx_payload=cx_payload,
                    cx_record=cx_record,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.get("/api/v1/chat/interactions/{interaction_id}", response_model=None)
    def get_chat_interaction(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = chat_store.get(interaction_id)
        if record is None:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    status_code=404,
                    error_code="ae.chat_interaction_not_found",
                    detail=f"Chat interaction was not found: {interaction_id}",
                ),
            )
        return record


def build_cx_generation_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    message_hash = sha256_text(user_message)
    interaction_id = source_payload.get("interaction_id") or str(
        uuid5(NAMESPACE_URL, f"ae-interaction:{trace_id}:{message_hash}")
    )
    chat_document_id = source_payload.get("chat_document_id") or str(
        uuid5(NAMESPACE_URL, f"ae-chat-document:{trace_id}")
    )
    generation = source_payload.get("generation", {})
    if not isinstance(generation, dict):
        raise ChatInteractionError(
            status_code=400,
            error_code="ae.chat_request_invalid",
            detail="generation must be an object when supplied.",
        )

    return {
        "trace_id": trace_id,
        "client_request_id": interaction_id,
        "cx_generation_id": source_payload.get("cx_generation_id"),
        "alias": generation.get("alias", "general-llm-default"),
        "provider_capability": generation.get("provider_capability", "generation"),
        "generation_profile": generation.get("generation_profile", "grounded-answer"),
        "messages": [{"role": "user", "content": user_message}],
        "response_format": generation.get("response_format", {"type": "text"}),
        "max_output_tokens": generation.get("max_output_tokens", 256),
        "temperature": generation.get("temperature", 0.0),
        "metadata": {
            "ae_interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "user_message_hash": message_hash,
        },
    }


def build_chat_interaction_record(
    *,
    source_payload: dict[str, Any],
    cx_payload: dict[str, Any],
    cx_record: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    now = _utc_now()
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": cx_record["cx_generation_id"],
        "cx_status": cx_record["status"],
        "generation": {
            "alias": cx_record["alias"],
            "provider_capability": cx_record["provider_capability"],
            "mo_generation_id": cx_record["mo_generation_id"],
            "finish_reason": cx_record["response_metadata"]["finish_reason"],
            "output_preview": cx_record["response_metadata"]["output_preview"],
            "usage": cx_record["usage"],
        },
        "created_at": now,
        "updated_at": now,
    }


def user_message_from_payload(payload: dict[str, Any]) -> str:
    user_message = payload.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise ChatInteractionError(
            status_code=400,
            error_code="ae.chat_request_invalid",
            detail="user_message is required.",
        )
    return user_message.strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _chat_problem_response(
    request: Request,
    exc: ChatInteractionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Chat interaction failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/chat-interaction-failed",
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
