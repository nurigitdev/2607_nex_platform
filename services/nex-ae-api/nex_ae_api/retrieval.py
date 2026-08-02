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


class CxRetrievalClient(Protocol):
    def create_retrieval_context(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class HttpCxRetrievalClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def create_retrieval_context(
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
            f"{self.base_url}/api/v1/retrieval/context",
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
            raise RetrievalInteractionError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.retrieval_request_failed"),
                detail=body.get("detail", "CX retrieval request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class RetrievalInteractionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["retrieval_interaction_id"]] = record
        return record

    def get(self, retrieval_interaction_id: str) -> dict[str, Any] | None:
        return self.records.get(retrieval_interaction_id)


@dataclass(frozen=True)
class RetrievalInteractionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_RETRIEVAL_STORE = RetrievalInteractionStore()


def build_default_cx_retrieval_client() -> HttpCxRetrievalClient:
    return HttpCxRetrievalClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_retrieval_routes(
    app: FastAPI,
    *,
    store: RetrievalInteractionStore | None = None,
    cx_client: CxRetrievalClient | None = None,
) -> None:
    retrieval_store = store or DEFAULT_RETRIEVAL_STORE
    client = cx_client or build_default_cx_retrieval_client()

    @app.post("/api/v1/retrieval/contexts", response_model=None)
    def create_retrieval_interaction(
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
            cx_payload = build_cx_retrieval_payload(payload, trace_id=trace_id)
            cx_package = client.create_retrieval_context(
                cx_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            return retrieval_store.save(
                build_retrieval_interaction_record(
                    source_payload=payload,
                    cx_payload=cx_payload,
                    cx_package=cx_package,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except RetrievalInteractionError as exc:
            return _retrieval_problem_response(request, exc)

    @app.get("/api/v1/retrieval/contexts/{retrieval_interaction_id}", response_model=None)
    def get_retrieval_interaction(
        retrieval_interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = retrieval_store.get(retrieval_interaction_id)
        if record is None:
            return _retrieval_problem_response(
                request,
                RetrievalInteractionError(
                    status_code=404,
                    error_code="ae.retrieval_interaction_not_found",
                    detail=f"Retrieval interaction was not found: {retrieval_interaction_id}",
                ),
            )
        return record


def build_cx_retrieval_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    message_hash = sha256_text(user_message)
    retrieval_interaction_id = source_payload.get("retrieval_interaction_id") or str(
        uuid5(NAMESPACE_URL, f"ae-retrieval:{trace_id}:{message_hash}")
    )
    chat_document_id = source_payload.get("chat_document_id") or str(
        uuid5(NAMESPACE_URL, f"ae-chat-document:{trace_id}")
    )
    retrieval = source_payload.get("retrieval", {})
    if not isinstance(retrieval, dict):
        raise RetrievalInteractionError(
            status_code=400,
            error_code="ae.retrieval_request_invalid",
            detail="retrieval must be an object when supplied.",
        )

    return {
        "trace_id": trace_id,
        "request_id": retrieval_interaction_id,
        "actor_claims_ref": source_payload.get(
            "actor_claims_ref",
            {"actor_type": "service", "actor_id": "nex-ae-api"},
        ),
        "chat_document_id": chat_document_id,
        "execution_mode": retrieval.get("execution_mode", "DOCUMENT_SEARCH"),
        "user_prompt": user_message,
        "query_text": retrieval.get("query_text", user_message),
        "document_scope": retrieval.get("document_scope"),
        "retrieval_profile": retrieval.get("retrieval_profile", {"search_strategy": "hybrid"}),
        "top_k": retrieval.get("top_k", 5),
        "include_neighbors": retrieval.get("include_neighbors", False),
        "include_source_preview": retrieval.get("include_source_preview", True),
        "purpose": retrieval.get("purpose", "search"),
        "metadata": {
            "ae_retrieval_interaction_id": retrieval_interaction_id,
            "chat_document_id": chat_document_id,
            "user_message_hash": message_hash,
        },
    }


def build_retrieval_interaction_record(
    *,
    source_payload: dict[str, Any],
    cx_payload: dict[str, Any],
    cx_package: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    now = _utc_now()
    return {
        "retrieval_interaction_schema_version": "ae_retrieval_interaction.v1",
        "retrieval_interaction_id": cx_payload["metadata"]["ae_retrieval_interaction_id"],
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_retrieval_package_id": cx_package["retrieval_package_id"],
        "cx_package_hash": cx_package["package_hash"],
        "cx_status": cx_package["status"],
        "purpose": cx_package["purpose"],
        "retrieval": {
            "evidence_count": len(cx_package["evidence_items"]),
            "best_score": cx_package["score_summary"]["best_score"],
            "confidence_bucket": cx_package["score_summary"]["confidence_bucket"],
            "no_answer_reason": cx_package.get("no_answer_reason"),
            "warnings": cx_package.get("warnings", []),
        },
        "created_at": now,
        "updated_at": now,
    }


def user_message_from_payload(payload: dict[str, Any]) -> str:
    user_message = payload.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise RetrievalInteractionError(
            status_code=400,
            error_code="ae.retrieval_request_invalid",
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


def _retrieval_problem_response(
    request: Request,
    exc: RetrievalInteractionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Retrieval interaction failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/retrieval-interaction-failed",
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
