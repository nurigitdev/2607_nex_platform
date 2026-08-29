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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

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

AE_CHAT_RETRIEVAL_QUALITY_WARNING_CONTRACT_VERSION = (
    "ae_chat_retrieval_quality_warning.v1"
)
AE_CHAT_GENERATION_QUALITY_REJECTION_CONTRACT_VERSION = (
    "ae_chat_generation_quality_rejection.v1"
)
AE_CHAT_GROUNDED_RESPONSE_QUALITY_CONTRACT_VERSION = (
    "ae_chat_grounded_response_quality.v1"
)
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.2
DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_USER_ID = "local-user"
GENERATION_QUALITY_REJECTION_ERROR_CODES = {
    "cx.retrieval_package_not_ready",
    "cx.retrieval_package_quality_blocked",
}
CHAT_INTERACTION_JSON_FIELDS = (
    "retrieval_summary",
    "generation_summary",
    "failure_summary",
)
CHAT_ARTIFACT_REF_JSON_FIELDS = (
    "available_formats",
    "download_routes",
    "quality_summary",
    "actions",
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


class SqlAlchemyChatInteractionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                _persist_chat_interaction_record(session, record)
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise ChatInteractionError(
                status_code=503,
                error_code="ae.chat_store_unavailable",
                detail="AE chat interaction store is unavailable.",
                retryable=True,
            ) from exc

    def get(self, interaction_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_chat_interaction_record(session, interaction_id)
        except SQLAlchemyError as exc:
            raise ChatInteractionError(
                status_code=503,
                error_code="ae.chat_store_unavailable",
                detail="AE chat interaction store is unavailable.",
                retryable=True,
            ) from exc

    def attach_artifact_ref(
        self,
        *,
        interaction_id: str,
        artifact_ref: dict[str, Any],
        updated_at: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                record = _load_chat_interaction_record(session, interaction_id)
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
                _persist_chat_interaction_record(session, record)
                session.commit()
                return record
        except SQLAlchemyError as exc:
            raise ChatInteractionError(
                status_code=503,
                error_code="ae.chat_store_unavailable",
                detail="AE chat interaction store is unavailable.",
                retryable=True,
            ) from exc

    def delete(self, interaction_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        """
                        DELETE FROM ae_chat_interactions
                        WHERE chat_interaction_id = :interaction_id
                        """
                    ),
                    {"interaction_id": interaction_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise ChatInteractionError(
                status_code=503,
                error_code="ae.chat_store_unavailable",
                detail="AE chat interaction store is unavailable.",
                retryable=True,
            ) from exc


@dataclass(frozen=True)
class ChatInteractionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_CHAT_STORE = ChatInteractionStore()


def build_default_chat_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyChatInteractionStore(session_factory)
    return DEFAULT_CHAT_STORE


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
    store: Any | None = None,
    cx_client: CxGenerationClient | None = None,
    retrieval_client: CxRetrievalClient | None = None,
    analytics_store: PromptAnalyticsStore | None = None,
) -> None:
    chat_store = store or build_default_chat_store(app)
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
            try:
                cx_record = client.create_generation(
                    cx_payload,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except ChatInteractionError as exc:
                if is_generation_quality_rejection(exc) and retrieval_package is not None:
                    saved_quality_rejection = chat_store.save(
                        build_generation_quality_rejected_chat_interaction_record(
                            source_payload=payload,
                            cx_payload=cx_payload,
                            retrieval_package=retrieval_package,
                            failure=exc,
                            request_id=request_id,
                            trace_id=trace_id,
                        )
                    )
                    record_chat_prompt_analytics(
                        analytics_store,
                        source_payload=payload,
                        chat_record=saved_quality_rejection,
                        retrieval_used=True,
                    )
                    return saved_quality_rejection
                raise
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
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
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
            "grounded_response_quality": grounded_response_quality_contract(cx_record),
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
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": retrieval_payload["metadata"]["ae_retrieval_interaction_id"],
        "chat_document_id": retrieval_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
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


def build_generation_quality_rejected_chat_interaction_record(
    *,
    source_payload: dict[str, Any],
    cx_payload: dict[str, Any],
    retrieval_package: dict[str, Any],
    failure: ChatInteractionError,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "status": "FAILED",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": None,
        "cx_status": "FAILED",
        "generation": None,
        "failure": generation_quality_rejection_failure_summary(
            failure,
            retrieval_package,
        ),
        "retrieval": retrieval_summary(retrieval_package),
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def generation_quality_rejection_failure_summary(
    failure: ChatInteractionError,
    retrieval_package: dict[str, Any],
) -> dict[str, Any]:
    quality_warnings = retrieval_quality_warning_contract(retrieval_package)
    return {
        "failure_schema_version": AE_CHAT_GENERATION_QUALITY_REJECTION_CONTRACT_VERSION,
        "error_code": failure.error_code,
        "failed_stage": generation_quality_rejection_stage(failure.error_code),
        "owner_service": "nex-cx",
        "retryable": failure.retryable,
        "retrieval_quality_recommended_action": quality_warnings[
            "recommended_action"
        ],
        "recommended_action": generation_quality_rejection_action(
            failure.error_code,
            quality_warnings,
        ),
        "raw_error_detail_included": False,
    }


def generation_quality_rejection_stage(error_code: str) -> str:
    if error_code == "cx.retrieval_package_not_ready":
        return "retrieval_package_status"
    if error_code == "cx.retrieval_package_quality_blocked":
        return "retrieval_package_quality"
    return "generation_quality_rejection"


def generation_quality_rejection_action(
    error_code: str,
    quality_warnings: dict[str, Any],
) -> str:
    if error_code == "cx.retrieval_package_not_ready":
        action = quality_warnings.get("recommended_action")
        return action if isinstance(action, str) else "show_error"
    return "show_error"


def is_generation_quality_rejection(failure: ChatInteractionError) -> bool:
    return failure.error_code in GENERATION_QUALITY_REJECTION_ERROR_CODES


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
    quality_warnings = retrieval_quality_warning_contract(retrieval_package)
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
            "retrieval_warning_count": quality_warnings["warning_count"],
            "retrieval_warning_kinds": quality_warnings["warning_kinds"],
            "retrieval_quality_flag_kinds": quality_warnings["quality_flag_kinds"],
            "retrieval_quality_recommended_action": quality_warnings[
                "recommended_action"
            ],
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
    quality_warnings = retrieval_quality_warning_contract(retrieval_package)
    return {
        "cx_retrieval_package_id": retrieval_package["retrieval_package_id"],
        "cx_package_hash": retrieval_package["package_hash"],
        "cx_status": retrieval_package["status"],
        "evidence_count": len(retrieval_package["evidence_items"]),
        "best_score": retrieval_package["score_summary"]["best_score"],
        "confidence_bucket": retrieval_package["score_summary"]["confidence_bucket"],
        "no_answer_reason": retrieval_package.get("no_answer_reason"),
        "warnings": quality_warnings["warning_kinds"],
        "quality_warnings": quality_warnings,
    }


def retrieval_quality_warning_contract(retrieval_package: dict[str, Any]) -> dict[str, Any]:
    score_summary = _mapping_value(retrieval_package.get("score_summary"))
    status = _optional_text(retrieval_package.get("status")) or "UNKNOWN"
    confidence_bucket = _optional_text(score_summary.get("confidence_bucket"))
    best_score = _number_or_none(score_summary.get("best_score"))
    low_confidence_threshold = _low_confidence_threshold(retrieval_package)
    warning_kinds = _warning_kinds(retrieval_package.get("warnings"))
    quality_flag_kinds = _quality_flag_kinds(retrieval_package.get("evidence_items"))
    best_score_below_threshold = (
        best_score is not None
        and low_confidence_threshold is not None
        and best_score < low_confidence_threshold
    )
    recommended_action = _retrieval_quality_recommended_action(
        status=status,
        confidence_bucket=confidence_bucket,
        best_score_below_threshold=best_score_below_threshold,
        warning_kinds=warning_kinds,
        quality_flag_kinds=quality_flag_kinds,
    )
    return {
        "contract_schema_version": AE_CHAT_RETRIEVAL_QUALITY_WARNING_CONTRACT_VERSION,
        "warning_count": len(_string_list_value(retrieval_package.get("warnings"))),
        "warning_kinds": warning_kinds,
        "quality_flag_count": _quality_flag_count(retrieval_package.get("evidence_items")),
        "quality_flag_kinds": quality_flag_kinds,
        "low_confidence_threshold": low_confidence_threshold,
        "best_score_below_threshold": best_score_below_threshold,
        "status_caveat_required": recommended_action != "proceed",
        "recommended_action": recommended_action,
        "raw_warning_details_included": False,
    }


def grounded_response_quality_contract(cx_record: dict[str, Any]) -> dict[str, Any]:
    request_metadata = _mapping_value(cx_record.get("request_metadata"))
    grounding_required = bool(request_metadata.get("grounding_required"))
    audit_schema_version = _optional_text(
        request_metadata.get("grounded_response_quality_audit_schema_version")
    )
    boundary_status = _grounded_response_quality_boundary_status(
        request_metadata.get("grounded_response_quality_status"),
        grounding_required=grounding_required,
    )
    issue_count = _non_negative_int(
        request_metadata.get("grounded_response_quality_issue_count")
    )
    citation_status = _grounded_response_quality_citation_status(
        request_metadata.get("draft_validation_status"),
        boundary_status=boundary_status,
    )
    recommended_action = _grounded_response_quality_recommended_action(
        boundary_status=boundary_status,
        issue_count=issue_count,
    )
    return {
        "contract_schema_version": AE_CHAT_GROUNDED_RESPONSE_QUALITY_CONTRACT_VERSION,
        "source_audit_schema_version": audit_schema_version,
        "boundary_status": boundary_status,
        "citation_status": citation_status,
        "issue_count": issue_count,
        "recommended_action": recommended_action,
        "grounding_required": grounding_required,
        "retrieval_package_id": _optional_text(
            request_metadata.get("retrieval_package_id")
        ),
        "retrieval_package_hash": _optional_text(
            request_metadata.get("retrieval_package_hash")
        ),
        "structured_draft_id": _optional_text(
            request_metadata.get("structured_draft_id")
        ),
        "raw_output_included": False,
        "evidence_text_included": False,
        "prompt_text_included": False,
        "provider_detail_included": False,
    }


def _grounded_response_quality_boundary_status(
    value: Any,
    *,
    grounding_required: bool,
) -> str:
    status = _optional_text(value)
    if status in {"PASS", "WARN", "FAIL", "NOT_REQUIRED"}:
        return status
    if not grounding_required:
        return "NOT_REQUIRED"
    return "UNKNOWN"


def _grounded_response_quality_citation_status(
    value: Any,
    *,
    boundary_status: str,
) -> str:
    status = _optional_text(value)
    if status in {"VALIDATED", "INVALID", "NOT_REQUIRED", "UNKNOWN"}:
        return status
    if boundary_status == "NOT_REQUIRED":
        return "NOT_REQUIRED"
    return "UNKNOWN"


def _grounded_response_quality_recommended_action(
    *,
    boundary_status: str,
    issue_count: int,
) -> str:
    if boundary_status == "FAIL":
        return "show_error"
    if boundary_status == "WARN" or boundary_status == "UNKNOWN" or issue_count > 0:
        return "proceed_with_caveat"
    return "proceed"


def _retrieval_quality_recommended_action(
    *,
    status: str,
    confidence_bucket: str | None,
    best_score_below_threshold: bool,
    warning_kinds: list[str],
    quality_flag_kinds: list[str],
) -> str:
    if status == "FAILED":
        return "show_error"
    if status == "NO_ANSWER":
        return "show_no_answer"
    if (
        status == "LOW_CONFIDENCE"
        or confidence_bucket == "LOW_CONFIDENCE"
        or best_score_below_threshold
    ):
        return "ask_confirmation"
    if status == "PARTIAL" or warning_kinds or quality_flag_kinds:
        return "proceed_with_caveat"
    return "proceed"


def _low_confidence_threshold(retrieval_package: dict[str, Any]) -> float | None:
    score_summary = _mapping_value(retrieval_package.get("score_summary"))
    score_threshold = _number_or_none(score_summary.get("low_confidence_threshold"))
    if score_threshold is not None:
        return score_threshold
    retrieval_profile = _mapping_value(retrieval_package.get("retrieval_profile"))
    confidence_policy = _mapping_value(retrieval_profile.get("confidence_policy"))
    profile_threshold = _number_or_none(
        confidence_policy.get("low_confidence_threshold")
    )
    if profile_threshold is not None:
        return profile_threshold
    return DEFAULT_LOW_CONFIDENCE_THRESHOLD


def _warning_kinds(value: Any) -> list[str]:
    return sorted({_warning_kind(item) for item in _string_list_value(value)})


def _quality_flag_kinds(value: Any) -> list[str]:
    kinds: set[str] = set()
    for item in _list_value(value):
        if not isinstance(item, dict):
            continue
        kinds.update(
            _warning_kind(flag)
            for flag in _string_list_value(item.get("quality_flags"))
        )
    return sorted(kinds)


def _quality_flag_count(value: Any) -> int:
    count = 0
    for item in _list_value(value):
        if isinstance(item, dict):
            count += len(_string_list_value(item.get("quality_flags")))
    return count


def _warning_kind(value: str) -> str:
    return value.split(":", 1)[0].strip()


def _mapping_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list_value(value: Any) -> list[str]:
    return [item for item in _list_value(value) if isinstance(item, str)]


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def user_message_from_payload(payload: dict[str, Any]) -> str:
    user_message = payload.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise ChatInteractionError(
            status_code=400,
            error_code="ae.chat_request_invalid",
            detail="user_message is required.",
        )
    return user_message.strip()


def chat_owner_scope_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    tenant_id = _optional_text(payload.get("tenant_id")) or DEFAULT_TENANT_ID
    user_id = _optional_text(payload.get("user_id")) or DEFAULT_USER_ID
    return tenant_id, user_id


def _persist_chat_interaction_record(
    session: Session,
    record: dict[str, Any],
) -> None:
    dialect_name = _dialect_name(session)
    session.execute(
        text(_chat_interaction_upsert_sql(dialect_name)),
        _chat_interaction_params(record),
    )
    session.execute(
        text(
            """
            DELETE FROM ae_chat_artifact_refs
            WHERE chat_interaction_id = :interaction_id
            """
        ),
        {"interaction_id": record["interaction_id"]},
    )
    for artifact_ref in record.get("artifact_refs", []):
        session.execute(
            text(_chat_artifact_ref_insert_sql(dialect_name)),
            _chat_artifact_ref_params(record, artifact_ref),
        )


def _load_chat_interaction_record(
    session: Session,
    interaction_id: str,
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(_chat_interaction_select_sql("chat_interaction_id = :interaction_id")),
            {"interaction_id": interaction_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    ref_rows = (
        session.execute(
            text(
                """
                SELECT
                    artifact_id,
                    artifact_version_id,
                    display_title,
                    artifact_type,
                    artifact_status,
                    primary_format,
                    available_formats,
                    preview_route,
                    download_routes,
                    source_generation_id,
                    source_content_hash,
                    quality_summary,
                    actions
                FROM ae_chat_artifact_refs
                WHERE chat_interaction_id = :interaction_id
                ORDER BY created_at ASC, artifact_id ASC, artifact_version_id ASC
                """
            ),
            {"interaction_id": interaction_id},
        )
        .mappings()
        .all()
    )
    return _chat_interaction_from_row(row, [_chat_artifact_ref_from_row(ref) for ref in ref_rows])


def _chat_interaction_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(CHAT_INTERACTION_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_chat_interactions (
            chat_interaction_id,
            interaction_schema_version,
            tenant_id,
            user_id,
            chat_document_id,
            status,
            trace_id,
            request_id,
            user_message_hash,
            user_message_preview,
            cx_retrieval_package_id,
            cx_retrieval_package_hash,
            cx_generation_id,
            cx_generation_status,
            retrieval_summary,
            generation_summary,
            failure_summary,
            created_at,
            updated_at
        )
        VALUES (
            :interaction_id,
            :interaction_schema_version,
            :tenant_id,
            :user_id,
            :chat_document_id,
            :status,
            :trace_id,
            :request_id,
            :user_message_hash,
            :user_message_preview,
            :cx_retrieval_package_id,
            :cx_retrieval_package_hash,
            :cx_generation_id,
            :cx_status,
            {json_exprs["retrieval_summary"]},
            {json_exprs["generation_summary"]},
            {json_exprs["failure_summary"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (chat_interaction_id) DO UPDATE SET
            interaction_schema_version = excluded.interaction_schema_version,
            tenant_id = excluded.tenant_id,
            user_id = excluded.user_id,
            chat_document_id = excluded.chat_document_id,
            status = excluded.status,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            user_message_hash = excluded.user_message_hash,
            user_message_preview = excluded.user_message_preview,
            cx_retrieval_package_id = excluded.cx_retrieval_package_id,
            cx_retrieval_package_hash = excluded.cx_retrieval_package_hash,
            cx_generation_id = excluded.cx_generation_id,
            cx_generation_status = excluded.cx_generation_status,
            retrieval_summary = excluded.retrieval_summary,
            generation_summary = excluded.generation_summary,
            failure_summary = excluded.failure_summary,
            updated_at = excluded.updated_at
    """


def _chat_interaction_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            interaction_schema_version,
            chat_interaction_id,
            tenant_id,
            user_id,
            chat_document_id,
            status,
            trace_id,
            request_id,
            user_message_hash,
            user_message_preview,
            cx_retrieval_package_id,
            cx_retrieval_package_hash,
            cx_generation_id,
            cx_generation_status,
            retrieval_summary,
            generation_summary,
            failure_summary,
            created_at,
            updated_at
        FROM ae_chat_interactions
        WHERE {where_clause}
    """


def _chat_artifact_ref_insert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(CHAT_ARTIFACT_REF_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_chat_artifact_refs (
            chat_artifact_ref_id,
            chat_interaction_id,
            chat_document_id,
            tenant_id,
            user_id,
            artifact_id,
            artifact_version_id,
            display_title,
            artifact_type,
            artifact_status,
            primary_format,
            available_formats,
            preview_route,
            download_routes,
            source_generation_id,
            source_content_hash,
            quality_summary,
            actions,
            created_at,
            updated_at
        )
        VALUES (
            :chat_artifact_ref_id,
            :interaction_id,
            :chat_document_id,
            :tenant_id,
            :user_id,
            :artifact_id,
            :artifact_version_id,
            :display_title,
            :artifact_type,
            :artifact_status,
            :primary_format,
            {json_exprs["available_formats"]},
            :preview_route,
            {json_exprs["download_routes"]},
            :source_generation_id,
            :source_content_hash,
            {json_exprs["quality_summary"]},
            {json_exprs["actions"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (chat_interaction_id, artifact_id, artifact_version_id)
        DO UPDATE SET
            display_title = excluded.display_title,
            artifact_type = excluded.artifact_type,
            artifact_status = excluded.artifact_status,
            primary_format = excluded.primary_format,
            available_formats = excluded.available_formats,
            preview_route = excluded.preview_route,
            download_routes = excluded.download_routes,
            source_generation_id = excluded.source_generation_id,
            source_content_hash = excluded.source_content_hash,
            quality_summary = excluded.quality_summary,
            actions = excluded.actions,
            updated_at = excluded.updated_at
    """


def _chat_interaction_params(record: dict[str, Any]) -> dict[str, Any]:
    retrieval = record.get("retrieval")
    generation = record.get("generation")
    failure = record.get("failure")
    return {
        "interaction_schema_version": record.get(
            "interaction_schema_version",
            "ae_chat_interaction.v1",
        ),
        "interaction_id": record["interaction_id"],
        "tenant_id": record.get("tenant_id") or DEFAULT_TENANT_ID,
        "user_id": record.get("user_id") or DEFAULT_USER_ID,
        "chat_document_id": record["chat_document_id"],
        "status": record["status"],
        "trace_id": record["trace_id"],
        "request_id": record["request_id"],
        "user_message_hash": record["user_message_hash"],
        "user_message_preview": record["user_message_preview"],
        "cx_retrieval_package_id": retrieval.get("cx_retrieval_package_id")
        if isinstance(retrieval, dict)
        else None,
        "cx_retrieval_package_hash": retrieval.get("cx_package_hash")
        if isinstance(retrieval, dict)
        else None,
        "cx_generation_id": record.get("cx_generation_id"),
        "cx_status": record.get("cx_status"),
        "retrieval_summary": json.dumps(retrieval or {}, ensure_ascii=False, sort_keys=True),
        "generation_summary": json.dumps(generation or {}, ensure_ascii=False, sort_keys=True),
        "failure_summary": json.dumps(failure or {}, ensure_ascii=False, sort_keys=True),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _chat_artifact_ref_params(
    record: dict[str, Any],
    artifact_ref: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chat_artifact_ref_id": str(
            uuid5(
                NAMESPACE_URL,
                "ae-chat-artifact-ref:"
                f"{record['interaction_id']}:{artifact_ref['artifact_id']}:"
                f"{artifact_ref['artifact_version_id']}",
            )
        ),
        "interaction_id": record["interaction_id"],
        "chat_document_id": record["chat_document_id"],
        "tenant_id": record.get("tenant_id") or DEFAULT_TENANT_ID,
        "user_id": record.get("user_id") or DEFAULT_USER_ID,
        "artifact_id": artifact_ref["artifact_id"],
        "artifact_version_id": artifact_ref["artifact_version_id"],
        "display_title": artifact_ref["display_title"],
        "artifact_type": artifact_ref["artifact_type"],
        "artifact_status": artifact_ref["artifact_status"],
        "primary_format": artifact_ref["primary_format"],
        "available_formats": json.dumps(
            artifact_ref["available_formats"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "preview_route": artifact_ref.get("preview_route"),
        "download_routes": json.dumps(
            artifact_ref["download_routes"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "source_generation_id": artifact_ref["source_generation_id"],
        "source_content_hash": artifact_ref["source_content_hash"],
        "quality_summary": json.dumps(
            artifact_ref["quality_summary"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "actions": json.dumps(artifact_ref["actions"], ensure_ascii=False, sort_keys=True),
        "created_at": record["updated_at"],
        "updated_at": record["updated_at"],
    }


def _chat_interaction_from_row(
    row: Any,
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    data = dict(row)
    retrieval = _json_value(data["retrieval_summary"], {})
    generation = _json_value(data["generation_summary"], {})
    failure = _json_value(data["failure_summary"], {})
    record = {
        "interaction_schema_version": data["interaction_schema_version"],
        "interaction_id": str(data["chat_interaction_id"]),
        "chat_document_id": str(data["chat_document_id"]),
        "tenant_id": data["tenant_id"],
        "user_id": data["user_id"],
        "status": data["status"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "user_message_hash": data["user_message_hash"],
        "user_message_preview": data["user_message_preview"],
        "cx_generation_id": data["cx_generation_id"],
        "cx_status": data["cx_generation_status"],
        "generation": generation or None,
        "retrieval": retrieval or None,
        "artifact_refs": artifact_refs,
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }
    if failure:
        record["failure"] = failure
    return record


def _chat_artifact_ref_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "artifact_id": data["artifact_id"],
        "artifact_version_id": data["artifact_version_id"],
        "display_title": data["display_title"],
        "artifact_type": data["artifact_type"],
        "artifact_status": data["artifact_status"],
        "primary_format": data["primary_format"],
        "available_formats": _json_value(data["available_formats"], []),
        "preview_route": data["preview_route"],
        "download_routes": _json_value(data["download_routes"], {}),
        "source_generation_id": data["source_generation_id"],
        "source_content_hash": data["source_content_hash"],
        "quality_summary": _json_value(data["quality_summary"], {}),
        "actions": _json_value(data["actions"], []),
    }


def _json_param_exprs(names: tuple[str, ...], dialect_name: str) -> dict[str, str]:
    return {name: _json_param_expr(name, dialect_name) for name in names}


def _json_param_expr(name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    if value is None:
        return default
    return value


def _datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


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
