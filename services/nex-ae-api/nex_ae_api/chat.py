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
from nex_ae_api.retrieval import (
    CxRetrievalClient,
    HttpCxRetrievalClient,
    RetrievalInteractionError,
    build_cx_retrieval_payload,
)
from nex_ae_api.analytics import (
    PromptAnalyticsError,
    PromptAnalyticsStore,
    owner_scope_from_payload,
    record_chat_prompt_analytics,
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

    def attach_artifact_ref(
        self,
        *,
        interaction_id: str,
        artifact_ref: dict[str, Any],
        updated_at: str,
    ) -> dict[str, Any] | None:
        record = self.get(interaction_id)
        if record is None:
            return None
        for existing_ref in record["artifact_refs"]:
            if (
                existing_ref["artifact_id"] == artifact_ref["artifact_id"]
                and existing_ref["artifact_version_id"]
                == artifact_ref["artifact_version_id"]
            ):
                return record
        record["artifact_refs"].append(artifact_ref)
        record["updated_at"] = updated_at
        return record


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


def build_default_cx_retrieval_client() -> HttpCxRetrievalClient:
    return HttpCxRetrievalClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_chat_routes(
    app: FastAPI,
    *,
    store: ChatInteractionStore | None = None,
    cx_client: CxGenerationClient | None = None,
    retrieval_client: CxRetrievalClient | None = None,
    analytics_store: PromptAnalyticsStore | None = None,
) -> None:
    chat_store = store or DEFAULT_CHAT_STORE
    client = cx_client or build_default_cx_client()
    retrieval = retrieval_client or build_default_cx_retrieval_client()

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
            if analytics_store is not None:
                owner_scope_from_payload(payload)
            retrieval_package = None
            if should_use_retrieval(payload):
                retrieval_payload = build_cx_retrieval_payload(payload, trace_id=trace_id)
                retrieval_package = retrieval.create_retrieval_context(
                    retrieval_payload,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                if retrieval_package["status"] == "NO_ANSWER":
                    saved_no_answer = chat_store.save(
                        build_no_answer_chat_interaction_record(
                            source_payload=payload,
                            retrieval_payload=retrieval_payload,
                            retrieval_package=retrieval_package,
                            request_id=request_id,
                            trace_id=trace_id,
                        )
                    )
                    record_chat_prompt_analytics(
                        analytics_store,
                        source_payload=payload,
                        chat_record=saved_no_answer,
                        retrieval_used=True,
                    )
                    return saved_no_answer

            cx_payload = build_cx_generation_payload(payload, trace_id=trace_id)
            if retrieval_package is not None:
                cx_payload = attach_retrieval_package_to_generation_payload(
                    cx_payload,
                    retrieval_package,
                )
            cx_record = client.create_generation(
                cx_payload,
                request_id=request_id,
                trace_id=trace_id,
            )
            saved_record = chat_store.save(
                build_chat_interaction_record(
                    source_payload=payload,
                    cx_payload=cx_payload,
                    cx_record=cx_record,
                    retrieval_package=retrieval_package,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
            record_chat_prompt_analytics(
                analytics_store,
                source_payload=payload,
                chat_record=saved_record,
                retrieval_used=retrieval_package is not None,
            )
            return saved_record
        except PromptAnalyticsError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    detail=exc.detail,
                ),
            )
        except RetrievalInteractionError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    detail=exc.detail,
                    retryable=exc.retryable,
                ),
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

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/artifact-links",
        response_model=None,
    )
    def attach_chat_artifact_link(
        interaction_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            record = chat_store.get(interaction_id)
            if record is None:
                raise ChatInteractionError(
                    status_code=404,
                    error_code="ae.chat_interaction_not_found",
                    detail=f"Chat interaction was not found: {interaction_id}",
                )
            artifact_record = artifact_record_from_payload(payload)
            if artifact_record["chat_document_id"] != record["chat_document_id"]:
                raise ChatInteractionError(
                    status_code=409,
                    error_code="ae.artifact_link_scope_mismatch",
                    detail="Artifact chat document does not match the interaction.",
                )
            if artifact_record["interaction_id"] != interaction_id:
                raise ChatInteractionError(
                    status_code=409,
                    error_code="ae.artifact_link_scope_mismatch",
                    detail="Artifact interaction does not match the target interaction.",
                )
            updated = chat_store.attach_artifact_ref(
                interaction_id=interaction_id,
                artifact_ref=build_chat_artifact_ref(artifact_record),
                updated_at=_utc_now(),
            )
            return updated
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/artifact-links",
        response_model=None,
    )
    def list_chat_artifact_links(
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
        return {
            "interaction_id": interaction_id,
            "chat_document_id": record["chat_document_id"],
            "artifact_refs": record["artifact_refs"],
        }


def build_cx_generation_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    message_hash = sha256_text(user_message)
    retrieval_enabled = _retrieval_enabled_for_defaults(source_payload)
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
        "execution_mode": generation.get(
            "execution_mode",
            "GROUNDED_ANSWER" if retrieval_enabled else "GENERAL_ANSWER",
        ),
        "template_id": generation.get("template_id", "none"),
        "prompt_binding_id": generation.get(
            "prompt_binding_id",
            "ae.grounded_chat.default",
        ),
        "output_contract_id": generation.get("output_contract_id", "text_answer_v1"),
        "alias": generation.get("alias", "general-llm-default"),
        "provider_capability": generation.get("provider_capability", "generation"),
        "generation_profile": generation.get(
            "generation_profile",
            "grounded-answer" if retrieval_enabled else "general-answer",
        ),
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
    retrieval_package: dict[str, Any] | None = None,
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
        "retrieval": retrieval_summary(retrieval_package),
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def build_no_answer_chat_interaction_record(
    *,
    source_payload: dict[str, Any],
    retrieval_payload: dict[str, Any],
    retrieval_package: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    now = _utc_now()
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": retrieval_payload["metadata"]["ae_retrieval_interaction_id"],
        "chat_document_id": retrieval_payload["metadata"]["chat_document_id"],
        "status": "NO_ANSWER",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": retrieval_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": None,
        "cx_status": retrieval_package["status"],
        "generation": None,
        "retrieval": retrieval_summary(retrieval_package),
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def artifact_record_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    artifact_record = payload.get("artifact")
    if not isinstance(artifact_record, dict):
        raise ChatInteractionError(
            status_code=422,
            error_code="ae.artifact_record_required",
            detail="artifact must be supplied as an object.",
        )
    return artifact_record


def build_chat_artifact_ref(artifact_record: dict[str, Any]) -> dict[str, Any]:
    current_version = current_artifact_version(artifact_record)
    source_ref = artifact_record["source_refs"][0]
    available_formats = [
        artifact_file["format"] for artifact_file in artifact_record.get("files", [])
    ]
    return {
        "artifact_id": required_text(
            artifact_record,
            "artifact_id",
            "ae.artifact_record_invalid",
        ),
        "artifact_version_id": current_version["artifact_version_id"],
        "display_title": required_text(
            artifact_record,
            "display_title",
            "ae.artifact_record_invalid",
        ),
        "artifact_type": required_text(
            artifact_record,
            "artifact_type",
            "ae.artifact_record_invalid",
        ),
        "artifact_status": required_text(
            artifact_record,
            "artifact_status",
            "ae.artifact_record_invalid",
        ),
        "primary_format": available_formats[0]
        if available_formats
        else first_target_format(artifact_record),
        "available_formats": available_formats,
        "preview_route": link_route_for_type(artifact_record, "preview"),
        "download_routes": download_routes_by_format(artifact_record),
        "source_generation_id": source_ref["cx_generation_id"],
        "source_content_hash": current_version["source_content_hash"],
        "quality_summary": dict(source_ref["quality_summary"]),
        "actions": artifact_actions_for_record(artifact_record),
    }


def current_artifact_version(artifact_record: dict[str, Any]) -> dict[str, Any]:
    current_version_id = artifact_record.get("current_version_id")
    if not isinstance(current_version_id, str) or not current_version_id.strip():
        raise ChatInteractionError(
            status_code=409,
            error_code="ae.artifact_link_version_required",
            detail="Artifact must have a current version before linking to chat.",
        )
    for version in artifact_record.get("versions", []):
        if version.get("artifact_version_id") == current_version_id:
            return version
    raise ChatInteractionError(
        status_code=409,
        error_code="ae.artifact_link_version_required",
        detail="Artifact current version metadata was not found.",
    )


def first_target_format(artifact_record: dict[str, Any]) -> str:
    target_formats = artifact_record.get("target_formats", [])
    if not target_formats:
        raise ChatInteractionError(
            status_code=422,
            error_code="ae.artifact_record_invalid",
            detail="Artifact target formats are required.",
        )
    return target_formats[0]


def link_route_for_type(
    artifact_record: dict[str, Any],
    link_type: str,
) -> str | None:
    for link in artifact_record.get("links", []):
        if link.get("link_type") == link_type and isinstance(link.get("link_route"), str):
            return link["link_route"]
    return None


def download_routes_by_format(artifact_record: dict[str, Any]) -> dict[str, str]:
    download_route = link_route_for_type(artifact_record, "download")
    if download_route is None:
        return {}
    return {
        artifact_file["format"]: download_route
        for artifact_file in artifact_record.get("files", [])
        if isinstance(artifact_file.get("format"), str)
    }


def artifact_actions_for_record(artifact_record: dict[str, Any]) -> list[str]:
    status = artifact_record.get("artifact_status")
    actions = ["view_sources", "view_lineage"]
    if status == "READY":
        if link_route_for_type(artifact_record, "preview") is not None:
            actions.insert(0, "preview")
        download_routes = download_routes_by_format(artifact_record)
        for render_format in sorted(download_routes):
            actions.append(f"download_{render_format.lower()}")
    if status == "FAILED":
        actions.append("retry_render")
    return actions


def required_text(
    payload: dict[str, Any],
    field_name: str,
    error_code: str,
) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ChatInteractionError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required.",
        )
    return value.strip()


def should_use_retrieval(payload: dict[str, Any]) -> bool:
    retrieval = payload.get("retrieval")
    if retrieval is None:
        return False
    if not isinstance(retrieval, dict):
        raise ChatInteractionError(
            status_code=400,
            error_code="ae.chat_request_invalid",
            detail="retrieval must be an object when supplied.",
        )
    return bool(retrieval.get("enabled", True))


def attach_retrieval_package_to_generation_payload(
    cx_payload: dict[str, Any],
    retrieval_package: dict[str, Any],
) -> dict[str, Any]:
    grounded_message = build_grounded_user_message(
        cx_payload["messages"][0]["content"],
        retrieval_package,
    )
    return {
        **cx_payload,
        "retrieval_package_ref": {
            "retrieval_package_id": retrieval_package["retrieval_package_id"],
            "package_hash": retrieval_package["package_hash"],
            "status": retrieval_package["status"],
        },
        "selected_evidence_ids": [
            item["evidence_id"]
            for item in retrieval_package.get("evidence_items", [])
            if isinstance(item.get("evidence_id"), str)
        ],
        "messages": [{"role": "user", "content": grounded_message}],
        "metadata": {
            **cx_payload["metadata"],
            "retrieval_package_id": retrieval_package["retrieval_package_id"],
            "retrieval_package_hash": retrieval_package["package_hash"],
            "retrieval_status": retrieval_package["status"],
            "retrieval_evidence_count": len(retrieval_package["evidence_items"]),
        },
    }


def _retrieval_enabled_for_defaults(payload: dict[str, Any]) -> bool:
    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict):
        return False
    return bool(retrieval.get("enabled", True))


def build_grounded_user_message(
    user_message: str,
    retrieval_package: dict[str, Any],
) -> str:
    evidence_lines = [
        f"{item['citation_label']} {item['text']}"
        for item in retrieval_package.get("evidence_items", [])
    ]
    evidence_text = "\n".join(evidence_lines) or "No supporting evidence returned."
    return (
        "Answer using only the supporting evidence below.\n\n"
        f"User request:\n{user_message}\n\n"
        f"Supporting evidence:\n{evidence_text}"
    )


def retrieval_summary(retrieval_package: dict[str, Any] | None) -> dict[str, Any] | None:
    if retrieval_package is None:
        return None
    return {
        "cx_retrieval_package_id": retrieval_package["retrieval_package_id"],
        "cx_package_hash": retrieval_package["package_hash"],
        "cx_status": retrieval_package["status"],
        "evidence_count": len(retrieval_package["evidence_items"]),
        "best_score": retrieval_package["score_summary"]["best_score"],
        "confidence_bucket": retrieval_package["score_summary"]["confidence_bucket"],
        "no_answer_reason": retrieval_package.get("no_answer_reason"),
        "warnings": retrieval_package.get("warnings", []),
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
