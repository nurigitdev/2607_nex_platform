from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    OperationalEventEmitter,
    issue_mock_service_token,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_runtime.prompts import PromptRegistryError, render_prompt_from_binding
from nex_ae_api.generation_policy import (
    GenerationPolicyPackageError,
    build_generation_policy_package,
)
from nex_ae_api.generation_lifecycle import (
    AeGenerationLifecycleError,
    orchestrate_generation_cancellation,
    orchestrate_generation_lifecycle,
)
from nex_ae_api.generation_lifecycle_observability import (
    observe_generation_lifecycle_action,
)
from nex_ae_api.generation_progress import build_generation_progress_projection
from nex_ae_api.generation_recovery import (
    AeGenerationRecoveryError,
    prepare_generation_retry,
)
from nex_ae_api.generated_response_api import build_generated_response_owner_view
from nex_ae_api.generated_response_lineage import (
    AeGeneratedResponseLineageError,
    generated_response_lineage_from_record,
    generated_response_storage_metadata_from_lineage,
)
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    build_default_generated_response_storage,
)
from nex_ae_api.async_generation import (
    ASYNCHRONOUS,
    AeAsyncGenerationError,
    build_async_generation_projection,
    refresh_async_generation_projection,
    refresh_async_generation_job_projection,
    resolve_execution_strategy,
)
from nex_ae_api.cx_async_generation_client import (
    CxAsyncGenerationClient,
    CxAsyncGenerationClientError,
    HttpCxAsyncGenerationClient,
)
from nex_ae_api.citation_quality_workflow import (
    AeCitationQualityWorkflowError,
    build_citation_quality_workflow_from_handoff,
    build_grounded_response_quality_contract,
    validate_citation_quality_workflow,
)
from nex_ae_api.citation_quality_observability import (
    observe_citation_quality_workflow,
)
from nex_ae_api.intent_policy import IntentPolicyError
from nex_ae_api.prompt_persistence import PromptRepositoryError
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE
from nex_ae_api.retrieval import (
    CxRetrievalClient,
    HttpCxRetrievalClient,
    RetrievalInteractionError,
    build_cx_retrieval_payload,
)
from nex_ae_api.cx_owner_context import cx_owner_headers, cx_owner_scope_from_payload
from nex_ae_api.analytics import (
    PromptAnalyticsError,
    PromptAnalyticsStore,
    owner_scope_from_payload,
    record_chat_prompt_analytics,
)
from nex_ae_api.route_auth import (
    AeFacadeRouteAuthContext,
    authorize_ae_facade_route_request,
)
from nex_ae_api.runtime_policy import RuntimePolicyError, resolve_runtime_policy
from nex_ae_api.runtime_policy_api import (
    RuntimePolicyApiError,
    resolve_safe_prompt_binding,
)
from nex_ae_api.workspace_chat_auth import (
    WorkspaceChatOwnerError,
    browser_owner_scope,
    owner_scoped_payload,
    record_matches_owner,
)
from nex_ae_api.workspace_chat_orchestration import (
    WorkspaceChatBinding,
    WorkspaceChatOrchestrationError,
    append_workspace_chat_activity,
    append_persisted_workspace_chat_activity,
    bind_workspace_chat_request,
    idempotent_chat_record,
)
from nex_ae_api.workspace_chat_observability import observe_workspace_chat_state

AE_CHAT_RETRIEVAL_QUALITY_WARNING_CONTRACT_VERSION = (
    "ae_chat_retrieval_quality_warning.v1"
)
AE_CHAT_GENERATION_QUALITY_REJECTION_CONTRACT_VERSION = (
    "ae_chat_generation_quality_rejection.v1"
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
                **cx_owner_headers(*cx_owner_scope_from_payload(payload)),
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

    def get_for_owner(
        self,
        interaction_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        record = self.get(interaction_id)
        if record is None:
            return None
        if (
            record.get("tenant_id") != tenant_id
            or record.get("user_id") != owner_user_id
        ):
            return None
        return record

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

    def get_for_owner(
        self,
        interaction_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_chat_interaction_record(
                    session,
                    interaction_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                )
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


def build_default_cx_async_generation_client() -> HttpCxAsyncGenerationClient:
    return HttpCxAsyncGenerationClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_chat_routes(
    app: FastAPI,
    *,
    store: Any | None = None,
    cx_client: CxGenerationClient | None = None,
    cx_async_client: CxAsyncGenerationClient | None = None,
    retrieval_client: CxRetrievalClient | None = None,
    analytics_store: PromptAnalyticsStore | None = None,
    event_emitter: OperationalEventEmitter | None = None,
    prompt_store: Any | None = None,
    generated_response_storage: Any | None = None,
) -> None:
    chat_store = store or build_default_chat_store(app)
    app.state.ae_chat_store = chat_store
    client = cx_client or build_default_cx_client()
    async_client = cx_async_client or build_default_cx_async_generation_client()
    retrieval = retrieval_client or build_default_cx_retrieval_client()
    prompts = (
        prompt_store
        or getattr(app.state, "ae_prompt_store", None)
        or DEFAULT_AE_PROMPT_STORE
    )
    emitter = event_emitter or operational_event_emitter_from_app(
        app,
        service_id="nex-ae-api",
    )
    response_storage = (
        generated_response_storage or build_default_generated_response_storage()
    )
    app.state.ae_generated_response_storage = response_storage

    @app.post("/api/v1/chat/interactions", response_model=None)
    def create_chat_interaction(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        binding: WorkspaceChatBinding | None = None
        pending_record: dict[str, Any] | None = None
        workspace_store = getattr(request.app.state, "ae_workspace_store", None)
        try:
            payload = _owner_scoped_chat_payload(payload, auth_context)
            if analytics_store is not None:
                owner_scope_from_payload(payload)
            binding = bind_workspace_chat_request(
                payload,
                trace_id=trace_id,
                workspace_store=workspace_store,
            )
            payload = binding.payload
            existing = idempotent_chat_record(binding, chat_store=chat_store)
            if existing is not None:
                return existing

            runtime_policy = resolve_runtime_policy(payload)
            execution_strategy = resolve_execution_strategy(payload)
            prompt_binding = resolve_safe_prompt_binding(
                prompts,
                binding_key=runtime_policy["prompt_contract_ref"][
                    "prompt_binding_key"
                ],
                prompt_version=runtime_policy["prompt_contract_ref"]["prompt_version"],
            )
            prompt_render_event = render_prompt_from_binding(
                prompts,
                binding_key=prompt_binding["binding_key"],
                variables={},
                request_id=request_id,
                trace_id=trace_id,
                user_prompt=user_message_from_payload(payload),
            )["render_event"]
            retrieval_enabled = runtime_policy["intent_decision"][
                "retrieval_required"
            ]
            cx_payload = build_cx_generation_payload(
                payload,
                trace_id=trace_id,
                runtime_policy=runtime_policy,
            )
            pending_record = chat_store.save(
                build_pending_chat_interaction_record(
                    source_payload=payload,
                    cx_payload=cx_payload,
                    runtime_policy=runtime_policy,
                    prompt_binding=prompt_binding,
                    prompt_render_event=prompt_render_event,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
            observe_workspace_chat_state(emitter, pending_record)
            append_workspace_chat_activity(
                binding,
                workspace_store=workspace_store,
                activity_type="chat.interaction.started",
                status="PENDING",
                request_id=request_id,
                trace_id=trace_id,
            )
            retrieval_package = None
            if retrieval_enabled:
                retrieval_payload = build_cx_retrieval_payload(payload, trace_id=trace_id)
                retrieval_package = retrieval.create_retrieval_context(
                    retrieval_payload,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                if retrieval_package["status"] == "NO_ANSWER":
                    saved_no_answer = chat_store.save(
                        _terminal_chat_record(
                            build_no_answer_chat_interaction_record(
                                source_payload=payload,
                                retrieval_payload=retrieval_payload,
                                retrieval_package=retrieval_package,
                                runtime_policy=runtime_policy,
                                prompt_binding=prompt_binding,
                                prompt_render_event=prompt_render_event,
                                request_id=request_id,
                                trace_id=trace_id,
                            ),
                            pending_record,
                        )
                    )
                    observe_workspace_chat_state(emitter, saved_no_answer)
                    record_chat_prompt_analytics(
                        analytics_store,
                        source_payload=payload,
                        chat_record=saved_no_answer,
                        retrieval_used=True,
                    )
                    append_workspace_chat_activity(
                        binding,
                        workspace_store=workspace_store,
                        activity_type="chat.interaction.no_answer",
                        status="NO_ANSWER",
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                    return saved_no_answer

            if retrieval_package is not None:
                cx_payload = attach_retrieval_package_to_generation_payload(
                    cx_payload,
                    retrieval_package,
                )
            policy_package = build_generation_policy_package(
                payload,
                runtime_policy=runtime_policy,
                prompt_binding=prompt_binding,
                prompt_render_event=prompt_render_event,
                retrieval_package=retrieval_package,
            )
            cx_payload = attach_generation_policy_package(
                cx_payload,
                policy_package,
            )
            if execution_strategy == ASYNCHRONOUS:
                try:
                    admission = async_client.admit_generation(
                        cx_payload,
                        request_id=request_id,
                        trace_id=trace_id,
                        idempotency_key=f"ae-chat:{binding.interaction_id}",
                    )
                    projection = build_async_generation_projection(admission)
                except CxAsyncGenerationClientError as exc:
                    raise ChatInteractionError(
                        status_code=exc.status_code,
                        error_code=exc.error_code,
                        detail=exc.detail,
                        retryable=exc.retryable,
                    ) from exc
                saved_async_record = chat_store.save(
                    build_async_admitted_chat_interaction_record(
                        pending_record=pending_record,
                        retrieval_package=retrieval_package,
                        runtime_policy=runtime_policy,
                        prompt_binding=prompt_binding,
                        prompt_render_event=prompt_render_event,
                        policy_package=policy_package,
                        projection=projection,
                    )
                )
                observe_workspace_chat_state(emitter, saved_async_record)
                append_workspace_chat_activity(
                    binding,
                    workspace_store=workspace_store,
                    activity_type="chat.async.admitted",
                    status=saved_async_record["status"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
                return JSONResponse(
                    status_code=202,
                    content=jsonable_encoder(saved_async_record),
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
                        _terminal_chat_record(
                            build_generation_quality_rejected_chat_interaction_record(
                                source_payload=payload,
                                cx_payload=cx_payload,
                                retrieval_package=retrieval_package,
                                failure=exc,
                                runtime_policy=runtime_policy,
                                prompt_binding=prompt_binding,
                                prompt_render_event=prompt_render_event,
                                policy_package=policy_package,
                                request_id=request_id,
                                trace_id=trace_id,
                            ),
                            pending_record,
                        )
                    )
                    observe_workspace_chat_state(emitter, saved_quality_rejection)
                    record_chat_prompt_analytics(
                        analytics_store,
                        source_payload=payload,
                        chat_record=saved_quality_rejection,
                        retrieval_used=True,
                    )
                    append_workspace_chat_activity(
                        binding,
                        workspace_store=workspace_store,
                        activity_type="chat.interaction.failed",
                        status="FAILED",
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                    return saved_quality_rejection
                raise
            saved_record = chat_store.save(
                _terminal_chat_record(
                    build_chat_interaction_record(
                        source_payload=payload,
                        cx_payload=cx_payload,
                        cx_record=cx_record,
                        retrieval_package=retrieval_package,
                        runtime_policy=runtime_policy,
                        prompt_binding=prompt_binding,
                        prompt_render_event=prompt_render_event,
                        policy_package=policy_package,
                        request_id=request_id,
                        trace_id=trace_id,
                    ),
                    pending_record,
                )
            )
            observe_workspace_chat_state(emitter, saved_record)
            record_chat_prompt_analytics(
                analytics_store,
                source_payload=payload,
                chat_record=saved_record,
                retrieval_used=retrieval_package is not None,
            )
            append_workspace_chat_activity(
                binding,
                workspace_store=workspace_store,
                activity_type="chat.interaction.completed",
                status="COMPLETED",
                request_id=request_id,
                trace_id=trace_id,
            )
            return saved_record
        except PromptAnalyticsError as exc:
            chat_error = ChatInteractionError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
            )
            _persist_failed_chat_attempt(
                chat_store=chat_store,
                workspace_store=workspace_store,
                binding=binding,
                pending_record=pending_record,
                failure=chat_error,
                request_id=request_id,
                trace_id=trace_id,
                event_emitter=emitter,
            )
            return _chat_problem_response(
                request,
                chat_error,
            )
        except (
            AeAsyncGenerationError,
            IntentPolicyError,
            RuntimePolicyError,
            RuntimePolicyApiError,
            GenerationPolicyPackageError,
            PromptRegistryError,
            PromptRepositoryError,
        ) as exc:
            chat_error = _policy_error_to_chat(exc)
            _persist_failed_chat_attempt(
                chat_store=chat_store,
                workspace_store=workspace_store,
                binding=binding,
                pending_record=pending_record,
                failure=chat_error,
                request_id=request_id,
                trace_id=trace_id,
                event_emitter=emitter,
            )
            return _chat_problem_response(request, chat_error)
        except RetrievalInteractionError as exc:
            chat_error = ChatInteractionError(
                status_code=exc.status_code,
                error_code=exc.error_code,
                detail=exc.detail,
                retryable=exc.retryable,
            )
            _persist_failed_chat_attempt(
                chat_store=chat_store,
                workspace_store=workspace_store,
                binding=binding,
                pending_record=pending_record,
                failure=chat_error,
                request_id=request_id,
                trace_id=trace_id,
                event_emitter=emitter,
            )
            return _chat_problem_response(
                request,
                chat_error,
            )
        except ChatInteractionError as exc:
            _persist_failed_chat_attempt(
                chat_store=chat_store,
                workspace_store=workspace_store,
                binding=binding,
                pending_record=pending_record,
                failure=exc,
                request_id=request_id,
                trace_id=trace_id,
                event_emitter=emitter,
            )
            return _chat_problem_response(request, exc)
        except WorkspaceChatOwnerError as exc:
            return _chat_problem_response(request, exc)
        except WorkspaceChatOrchestrationError as exc:
            _persist_failed_chat_attempt(
                chat_store=chat_store,
                workspace_store=workspace_store,
                binding=binding,
                pending_record=pending_record,
                failure=exc,
                request_id=request_id,
                trace_id=trace_id,
                event_emitter=emitter,
            )
            return _chat_problem_response(request, exc)

    @app.get("/api/v1/chat/interactions/{interaction_id}", response_model=None)
    def get_chat_interaction(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        try:
            record = _get_visible_chat_record(chat_store, interaction_id, auth_context)
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)
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
        "/api/v1/chat/interactions/{interaction_id}/refresh",
        response_model=None,
    )
    def refresh_chat_interaction(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            record = _get_visible_chat_record(
                chat_store, interaction_id, auth_context
            )
            if record is None:
                raise ChatInteractionError(
                    status_code=404,
                    error_code="ae.chat_interaction_not_found",
                    detail=f"Chat interaction was not found: {interaction_id}",
                )
            projection = _async_projection_from_record(record)
            handoff = async_client.get_handoff(
                projection["job_id"],
                tenant_id=record["tenant_id"],
                subject_id=record["owner_user_id"],
                request_id=request_id,
                trace_id=trace_id,
            )
            refreshed, transient_result = refresh_async_generation_projection(
                projection, handoff
            )
            citation_workflow = _citation_workflow_from_ready_handoff(
                handoff,
                interaction_id=interaction_id,
                projection=projection,
            )
            saved = chat_store.save(
                refresh_async_chat_interaction_record(
                    record,
                    refreshed,
                    citation_workflow=citation_workflow,
                )
            )
            _observe_citation_workflow_if_present(
                emitter,
                citation_workflow,
                request_id=request_id,
                trace_id=trace_id,
            )
            observe_workspace_chat_state(emitter, saved)
            append_persisted_workspace_chat_activity(
                saved,
                workspace_store=getattr(
                    request.app.state, "ae_workspace_store", None
                ),
                activity_type="chat.async.refreshed",
                request_id=request_id,
                trace_id=trace_id,
            )
            return {
                "refresh_schema_version": "ae_async_chat_refresh.v1",
                "interaction": saved,
                "result": transient_result,
                "content_persisted_by_ae": False,
            }
        except CxAsyncGenerationClientError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except AeAsyncGenerationError as exc:
            return _chat_problem_response(request, _policy_error_to_chat(exc))
        except WorkspaceChatOrchestrationError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/response",
        response_model=None,
    )
    def get_chat_interaction_response(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            record = _get_visible_chat_record(
                chat_store, interaction_id, auth_context
            )
            if record is None:
                raise ChatInteractionError(
                    status_code=404,
                    error_code="ae.chat_interaction_not_found",
                    detail=f"Chat interaction was not found: {interaction_id}",
                )
            lineage = generated_response_lineage_from_record(record)
            if lineage is None:
                raise ChatInteractionError(
                    status_code=409,
                    error_code="ae.generated_response_not_ready",
                    detail="Generated response is not ready for this chat interaction.",
                    retryable=True,
                )
            metadata = generated_response_storage_metadata_from_lineage(lineage)
            content = response_storage.load(metadata)
            if content is None:
                raise ChatInteractionError(
                    status_code=503,
                    error_code="ae.generated_response_content_unavailable",
                    detail="Generated response content is temporarily unavailable.",
                    retryable=True,
                )
            return build_generated_response_owner_view(record, lineage, content)
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)
        except (AeGeneratedResponseLineageError, GeneratedResponseStorageError) as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    status_code=503,
                    error_code=exc.error_code,
                    detail=exc.detail,
                    retryable=exc.retryable,
                ),
            )
        except ValueError:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    status_code=503,
                    error_code="ae.generated_response_integrity_failed",
                    detail="Generated response content integrity verification failed.",
                ),
            )

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/citation-quality",
        response_model=None,
    )
    def get_chat_interaction_citation_quality(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            record = _required_visible_async_record(
                chat_store, interaction_id, auth_context
            )
            projection = _async_projection_from_record(record)
            persisted_workflow = _citation_workflow_from_record(
                record,
                projection=projection,
            )
            if persisted_workflow is not None:
                return persisted_workflow
            handoff = async_client.get_handoff(
                projection["job_id"],
                tenant_id=record["tenant_id"],
                subject_id=record["owner_user_id"],
                request_id=request_id,
                trace_id=trace_id,
            )
            return build_citation_quality_workflow_from_handoff(
                handoff,
                interaction_id=interaction_id,
                expected_job_id=projection["job_id"],
                expected_cx_generation_id=projection["cx_generation_id"],
            )
        except CxAsyncGenerationClientError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except AeCitationQualityWorkflowError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/progress",
        response_model=None,
    )
    def get_chat_interaction_progress(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            record = _required_visible_async_record(
                chat_store, interaction_id, auth_context
            )
            lifecycle = orchestrate_generation_lifecycle(
                record,
                client=async_client,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            if lifecycle["changed"]:
                saved = chat_store.save(
                    refresh_async_chat_interaction_record(
                        record,
                        lifecycle["async_generation"],
                        citation_workflow=lifecycle.get("citation_workflow"),
                    )
                )
                _observe_citation_workflow_if_present(
                    emitter,
                    lifecycle.get("citation_workflow"),
                    request_id=request_id_from_headers(request),
                    trace_id=trace_id_from_headers(request),
                )
                observe_workspace_chat_state(emitter, saved)
                append_persisted_workspace_chat_activity(
                    saved,
                    workspace_store=getattr(
                        request.app.state, "ae_workspace_store", None
                    ),
                    activity_type="chat.async.progressed",
                    request_id=request_id_from_headers(request),
                    trace_id=trace_id_from_headers(request),
                )
            observe_generation_lifecycle_action(
                emitter,
                action="PROGRESS_OBSERVED",
                progress=lifecycle["progress"],
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            return lifecycle["progress"]
        except AeGenerationLifecycleError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/cancel",
        response_model=None,
    )
    def cancel_chat_interaction(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            record = _required_visible_async_record(
                chat_store, interaction_id, auth_context
            )
            cancellation = orchestrate_generation_cancellation(
                record,
                client=async_client,
                request_id=request_id,
                trace_id=trace_id,
            )
            if cancellation["changed"] is not True:
                return record
            saved = chat_store.save(
                refresh_async_chat_interaction_record(
                    record,
                    cancellation["async_generation"],
                    citation_workflow=cancellation.get("citation_workflow"),
                )
            )
            _observe_citation_workflow_if_present(
                emitter,
                cancellation.get("citation_workflow"),
                request_id=request_id,
                trace_id=trace_id,
            )
            observe_workspace_chat_state(emitter, saved)
            append_persisted_workspace_chat_activity(
                saved,
                workspace_store=getattr(
                    request.app.state, "ae_workspace_store", None
                ),
                activity_type=(
                    "chat.async.cancelled"
                    if cancellation["outcome"] == "CANCELLED"
                    else "chat.async.cancel_reconciled"
                ),
                request_id=request_id,
                trace_id=trace_id,
            )
            observe_generation_lifecycle_action(
                emitter,
                action=(
                    "CANCELLATION_ACCEPTED"
                    if cancellation["outcome"] == "CANCELLED"
                    else "CANCELLATION_RECONCILED"
                ),
                progress=cancellation["progress"],
                request_id=request_id,
                trace_id=trace_id,
            )
            return saved
        except AeGenerationLifecycleError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except AeAsyncGenerationError as exc:
            return _chat_problem_response(request, _policy_error_to_chat(exc))
        except WorkspaceChatOrchestrationError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.get(
        "/api/v1/chat/interactions/{interaction_id}/recovery",
        response_model=None,
    )
    def get_chat_interaction_recovery(
        interaction_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            record = _required_visible_async_record(
                chat_store, interaction_id, auth_context
            )
            lifecycle = orchestrate_generation_lifecycle(
                record,
                client=async_client,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            if lifecycle["changed"]:
                saved = chat_store.save(
                    refresh_async_chat_interaction_record(
                        record,
                        lifecycle["async_generation"],
                        citation_workflow=lifecycle.get("citation_workflow"),
                    )
                )
                _observe_citation_workflow_if_present(
                    emitter,
                    lifecycle.get("citation_workflow"),
                    request_id=request_id_from_headers(request),
                    trace_id=trace_id_from_headers(request),
                )
                observe_workspace_chat_state(emitter, saved)
                append_persisted_workspace_chat_activity(
                    saved,
                    workspace_store=getattr(
                        request.app.state, "ae_workspace_store", None
                    ),
                    activity_type="chat.async.recovery_planned",
                    request_id=request_id_from_headers(request),
                    trace_id=trace_id_from_headers(request),
                )
            observe_generation_lifecycle_action(
                emitter,
                action="RECOVERY_PLANNED",
                progress=lifecycle["progress"],
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            return lifecycle["progress"]["recovery"]
        except AeGenerationLifecycleError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

    @app.post(
        "/api/v1/chat/interactions/{interaction_id}/retry",
        response_model=None,
    )
    def retry_chat_interaction(
        interaction_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        try:
            parent = _required_visible_async_record(
                chat_store, interaction_id, auth_context
            )
            projection = _async_projection_from_record(parent)
            recovery = prepare_generation_retry(
                parent,
                payload,
                submitted_input_hash=sha256_text(user_message_from_payload(payload)),
            )
            response = create_chat_interaction(
                recovery["retry_payload"],
                request,
                authorization,
            )
            return _attach_async_retry_lineage(
                response,
                chat_store=chat_store,
                parent=parent,
                projection=projection,
                lineage=recovery["lineage"],
                event_emitter=emitter,
            )
        except AeGenerationRecoveryError as exc:
            return _chat_problem_response(
                request,
                ChatInteractionError(
                    exc.status_code,
                    exc.error_code,
                    exc.detail,
                    exc.retryable,
                ),
            )
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)

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
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        try:
            record = _get_visible_chat_record(chat_store, interaction_id, auth_context)
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
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        try:
            record = _get_visible_chat_record(chat_store, interaction_id, auth_context)
        except ChatInteractionError as exc:
            return _chat_problem_response(request, exc)
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
    runtime_policy: dict[str, Any] | None = None,
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

    tenant_id, subject_id = chat_owner_scope_from_payload(source_payload)
    resolved_intent = (runtime_policy or {}).get("intent_decision", {})
    resolved_parameters = (runtime_policy or {}).get("generation_parameters", {})
    resolved_template = (runtime_policy or {}).get("template_ref", {})
    resolved_prompt = (runtime_policy or {}).get("prompt_contract_ref", {})
    resolved_output = (runtime_policy or {}).get("output_contract", {})
    return {
        "trace_id": trace_id,
        "client_request_id": interaction_id,
        "cx_generation_id": source_payload.get("cx_generation_id"),
        "ownership_ref": {
            "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
            "owner_subject_ref": {"type": "oa.user", "id": subject_id},
        },
        "execution_mode": resolved_intent.get(
            "execution_mode",
            generation.get(
                "execution_mode",
                "GROUNDED_ANSWER" if retrieval_enabled else "GENERAL_ANSWER",
            ),
        ),
        "template_id": resolved_template.get(
            "template_id", generation.get("template_id", "none")
        ),
        "prompt_binding_id": resolved_prompt.get(
            "prompt_binding_key",
            generation.get(
            "prompt_binding_id",
            "ae.grounded_chat.default",
            ),
        ),
        "output_contract_id": resolved_output.get(
            "output_contract_id",
            generation.get("output_contract_id", "text_answer_v1"),
        ),
        "alias": generation.get("alias", "general-llm-default"),
        "provider_capability": (runtime_policy or {}).get(
            "provider_capability",
            generation.get("provider_capability", "generation"),
        ),
        "generation_profile": (runtime_policy or {}).get(
            "generation_profile",
            generation.get(
                "generation_profile",
                "grounded-answer" if retrieval_enabled else "general-answer",
            ),
        ),
        "messages": [{"role": "user", "content": user_message}],
        "response_format": generation.get("response_format", {"type": "text"}),
        "max_output_tokens": resolved_parameters.get(
            "max_output_tokens", generation.get("max_output_tokens", 256)
        ),
        "temperature": resolved_parameters.get(
            "temperature", generation.get("temperature", 0.0)
        ),
        "metadata": {
            "ae_interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "user_message_hash": message_hash,
            "policy_snapshot_hash": (runtime_policy or {}).get(
                "policy_snapshot_hash"
            ),
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
    runtime_policy: dict[str, Any] | None = None,
    prompt_binding: dict[str, Any] | None = None,
    prompt_render_event: dict[str, Any] | None = None,
    policy_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    generation = {
        "alias": cx_record["alias"],
        "provider_capability": cx_record["provider_capability"],
        "mo_generation_id": cx_record["mo_generation_id"],
        "finish_reason": cx_record["response_metadata"]["finish_reason"],
        "output_preview": cx_record["response_metadata"]["output_preview"],
        "usage": cx_record["usage"],
        "grounded_response_quality": grounded_response_quality_contract(cx_record),
    }
    policy_summary = build_policy_generation_summary(
        runtime_policy=runtime_policy,
        prompt_binding=prompt_binding,
        prompt_render_event=prompt_render_event,
        policy_package=policy_package,
    )
    if policy_summary is not None:
        generation["policy"] = policy_summary
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "workspace_id": _optional_text(source_payload.get("workspace_id")),
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "owner_user_id": user_id,
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": cx_record["cx_generation_id"],
        "cx_status": cx_record["status"],
        "generation": generation,
        "retrieval": retrieval_summary(retrieval_package),
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def build_pending_chat_interaction_record(
    *,
    source_payload: dict[str, Any],
    cx_payload: dict[str, Any],
    request_id: str,
    trace_id: str,
    runtime_policy: dict[str, Any] | None = None,
    prompt_binding: dict[str, Any] | None = None,
    prompt_render_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    policy_summary = build_policy_generation_summary(
        runtime_policy=runtime_policy,
        prompt_binding=prompt_binding,
        prompt_render_event=prompt_render_event,
    )
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "workspace_id": _optional_text(source_payload.get("workspace_id")),
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "owner_user_id": user_id,
        "status": "PENDING",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": None,
        "cx_status": "PENDING",
        "generation": {"policy": policy_summary} if policy_summary else None,
        "retrieval": None,
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def build_async_admitted_chat_interaction_record(
    *,
    pending_record: dict[str, Any],
    retrieval_package: dict[str, Any] | None,
    runtime_policy: dict[str, Any],
    prompt_binding: dict[str, Any],
    prompt_render_event: dict[str, Any],
    policy_package: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    policy_summary = build_policy_generation_summary(
        runtime_policy=runtime_policy,
        prompt_binding=prompt_binding,
        prompt_render_event=prompt_render_event,
        policy_package=policy_package,
    )
    lifecycle_status = projection["lifecycle_status"]
    return {
        **pending_record,
        "status": "PENDING" if lifecycle_status == "PENDING" else "FAILED",
        "cx_generation_id": projection["cx_generation_id"],
        "cx_status": projection["cx_job_status"],
        "generation": {
            "policy": policy_summary,
            "async_generation": projection,
        },
        "retrieval": retrieval_summary(retrieval_package),
        "updated_at": _utc_now(),
    }


def refresh_async_chat_interaction_record(
    record: dict[str, Any],
    projection: dict[str, Any],
    *,
    citation_workflow: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        raise ChatInteractionError(
            409,
            "ae.async_generation.interaction_invalid",
            "Chat interaction has no asynchronous generation metadata.",
        )
    lifecycle_status = projection["lifecycle_status"]
    refreshed_generation = {**generation, "async_generation": projection}
    if citation_workflow is not None:
        refreshed_generation["citation_workflow"] = (
            validate_citation_quality_workflow(citation_workflow)
        )
    return {
        **record,
        "status": {
            "PENDING": "PENDING",
            "COMPLETED": "COMPLETED",
            "BLOCKED": "FAILED",
        }[lifecycle_status],
        "cx_generation_id": projection["cx_generation_id"],
        "cx_status": projection["cx_job_status"],
        "generation": refreshed_generation,
        "failure": (
            {
                "failure_schema_version": "ae_chat_execution_failure.v1",
                "error_code": (
                    projection["error"]["error_code"]
                    if projection["error"] is not None
                    else "cx.async_generation.blocked"
                ),
                "failed_stage": "cx_async_generation",
                "retryable": projection["retryable"],
                "raw_error_detail_included": False,
            }
            if lifecycle_status == "BLOCKED"
            else None
        ),
        "updated_at": _utc_now(),
    }


def _async_projection_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    generation = record.get("generation")
    projection = (
        generation.get("async_generation")
        if isinstance(generation, Mapping)
        else None
    )
    if not isinstance(projection, Mapping):
        raise ChatInteractionError(
            409,
            "ae.async_generation.interaction_invalid",
            "Chat interaction is not bound to asynchronous generation.",
        )
    return dict(projection)


def _citation_workflow_from_ready_handoff(
    handoff: Mapping[str, Any],
    *,
    interaction_id: str,
    projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    if handoff.get("handoff_status") != "READY":
        return None
    return build_citation_quality_workflow_from_handoff(
        handoff,
        interaction_id=interaction_id,
        expected_job_id=str(projection["job_id"]),
        expected_cx_generation_id=str(projection["cx_generation_id"]),
    )


def _citation_workflow_from_record(
    record: Mapping[str, Any],
    *,
    projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    generation = record.get("generation")
    workflow = (
        generation.get("citation_workflow")
        if isinstance(generation, Mapping)
        else None
    )
    if workflow is None:
        return None
    validated = validate_citation_quality_workflow(workflow)
    if (
        validated["interaction_id"] != record.get("interaction_id")
        or validated["cx_generation_id"] != projection.get("cx_generation_id")
    ):
        raise AeCitationQualityWorkflowError(
            error_code="ae.citation_quality_workflow.invalid",
            detail="Persisted citation quality workflow lineage is inconsistent.",
        )
    return validated


def _observe_citation_workflow_if_present(
    emitter: OperationalEventEmitter,
    workflow: Mapping[str, Any] | None,
    *,
    request_id: str | None,
    trace_id: str | None,
) -> None:
    if workflow is None:
        return
    observe_citation_quality_workflow(
        emitter,
        workflow,
        request_id=request_id,
        trace_id=trace_id,
    )


def _required_visible_async_record(
    store: Any,
    interaction_id: str,
    auth_context: AeFacadeRouteAuthContext,
) -> dict[str, Any]:
    record = _get_visible_chat_record(store, interaction_id, auth_context)
    if record is None:
        raise ChatInteractionError(
            404,
            "ae.chat_interaction_not_found",
            f"Chat interaction was not found: {interaction_id}",
        )
    _async_projection_from_record(record)
    return record


def _attach_async_retry_lineage(
    response: object,
    *,
    chat_store: Any,
    parent: Mapping[str, Any],
    projection: Mapping[str, Any],
    lineage: Mapping[str, Any] | None = None,
    event_emitter: OperationalEventEmitter | None = None,
) -> object:
    if isinstance(response, JSONResponse):
        if response.status_code >= 400:
            return response
        record = json.loads(bytes(response.body).decode("utf-8"))
        response_status = response.status_code
    elif isinstance(response, dict):
        record = dict(response)
        response_status = 200
    else:
        return response
    generation = record.get("generation")
    if not isinstance(generation, dict) or "async_generation" not in generation:
        return response
    resolved_lineage = dict(lineage) if lineage is not None else {
        "retry_lineage_schema_version": "ae_async_generation_retry_lineage.v1",
        "parent_interaction_id": parent["interaction_id"],
        "parent_job_id": projection["job_id"],
        "parent_cx_generation_id": projection["cx_generation_id"],
        "raw_input_included": False,
    }
    saved = chat_store.save(
        {**record, "generation": {**generation, "retry_lineage": resolved_lineage}}
    )
    if event_emitter is not None:
        observe_workspace_chat_state(event_emitter, saved)
        observe_generation_lifecycle_action(
            event_emitter,
            action="RETRY_ADMITTED",
            progress=build_generation_progress_projection(
                interaction_id=str(saved["interaction_id"]),
                async_generation=generation["async_generation"],
            ),
            request_id=_optional_text(saved.get("request_id")),
            trace_id=_optional_text(saved.get("trace_id")),
        )
    if response_status == 200:
        return saved
    return JSONResponse(status_code=response_status, content=jsonable_encoder(saved))


def build_failed_chat_interaction_record(
    pending_record: dict[str, Any],
    failure: Any,
) -> dict[str, Any]:
    return {
        **pending_record,
        "status": "FAILED",
        "cx_status": "FAILED",
        "generation": pending_record.get("generation"),
        "failure": {
            "failure_schema_version": "ae_chat_execution_failure.v1",
            "error_code": failure.error_code,
            "failed_stage": "workspace_chat_orchestration",
            "retryable": bool(getattr(failure, "retryable", False)),
            "raw_error_detail_included": False,
        },
        "updated_at": _utc_now(),
    }


def _terminal_chat_record(
    record: dict[str, Any],
    pending_record: dict[str, Any],
) -> dict[str, Any]:
    return {**record, "created_at": pending_record["created_at"]}


def build_no_answer_chat_interaction_record(
    *,
    source_payload: dict[str, Any],
    retrieval_payload: dict[str, Any],
    retrieval_package: dict[str, Any],
    request_id: str,
    trace_id: str,
    runtime_policy: dict[str, Any] | None = None,
    prompt_binding: dict[str, Any] | None = None,
    prompt_render_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    policy_summary = build_policy_generation_summary(
        runtime_policy=runtime_policy,
        prompt_binding=prompt_binding,
        prompt_render_event=prompt_render_event,
    )
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": retrieval_payload["metadata"]["ae_retrieval_interaction_id"],
        "workspace_id": _optional_text(source_payload.get("workspace_id")),
        "chat_document_id": retrieval_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "owner_user_id": user_id,
        "status": "NO_ANSWER",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": retrieval_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": None,
        "cx_status": retrieval_package["status"],
        "generation": {"policy": policy_summary} if policy_summary else None,
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
    runtime_policy: dict[str, Any] | None = None,
    prompt_binding: dict[str, Any] | None = None,
    prompt_render_event: dict[str, Any] | None = None,
    policy_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_message = user_message_from_payload(source_payload)
    tenant_id, user_id = chat_owner_scope_from_payload(source_payload)
    now = _utc_now()
    policy_summary = build_policy_generation_summary(
        runtime_policy=runtime_policy,
        prompt_binding=prompt_binding,
        prompt_render_event=prompt_render_event,
        policy_package=policy_package,
    )
    return {
        "interaction_schema_version": "ae_chat_interaction.v1",
        "interaction_id": cx_payload["client_request_id"],
        "workspace_id": _optional_text(source_payload.get("workspace_id")),
        "chat_document_id": cx_payload["metadata"]["chat_document_id"],
        "tenant_id": tenant_id,
        "user_id": user_id,
        "owner_user_id": user_id,
        "status": "FAILED",
        "trace_id": trace_id,
        "request_id": request_id,
        "user_message_hash": cx_payload["metadata"]["user_message_hash"],
        "user_message_preview": user_message[:120],
        "cx_generation_id": None,
        "cx_status": "FAILED",
        "generation": {"policy": policy_summary} if policy_summary else None,
        "failure": generation_quality_rejection_failure_summary(
            failure,
            retrieval_package,
        ),
        "retrieval": retrieval_summary(retrieval_package),
        "artifact_refs": [],
        "created_at": now,
        "updated_at": now,
    }


def build_policy_generation_summary(
    *,
    runtime_policy: dict[str, Any] | None,
    prompt_binding: dict[str, Any] | None,
    prompt_render_event: dict[str, Any] | None,
    policy_package: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    values = (runtime_policy, prompt_binding, prompt_render_event)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ChatInteractionError(
            status_code=500,
            error_code="ae.runtime_policy_summary_incomplete",
            detail="Runtime policy persistence summary is incomplete.",
        )
    return {
        "policy_summary_schema_version": "ae_chat_runtime_policy_summary.v1",
        "runtime_policy_snapshot": dict(runtime_policy),
        "prompt_binding": dict(prompt_binding),
        "prompt_render_event_ref": {
            "prompt_render_event_id": prompt_render_event["prompt_render_event_id"],
            "rendered_prompt_hash": prompt_render_event["rendered_prompt_hash"],
            "user_prompt_hash": prompt_render_event["user_prompt_hash"],
        },
        "generation_policy_package": (
            dict(policy_package) if policy_package is not None else None
        ),
        "raw_prompt_included": False,
        "provider_runtime_included": False,
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


def attach_generation_policy_package(
    cx_payload: dict[str, Any],
    policy_package: dict[str, Any],
) -> dict[str, Any]:
    return {
        **cx_payload,
        "generation_policy_package": policy_package,
        "client_package_hash": policy_package["client_package_hash"],
        "metadata": {
            **cx_payload["metadata"],
            "policy_snapshot_hash": policy_package["policy_snapshot_hash"],
            "client_package_hash": policy_package["client_package_hash"],
            "prompt_binding_key": policy_package["prompt_contract_ref"][
                "prompt_binding_key"
            ],
            "prompt_version": policy_package["prompt_contract_ref"][
                "prompt_version"
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
    return build_grounded_response_quality_contract(cx_record)


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
    *,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
) -> dict[str, Any] | None:
    where_clause = "chat_interaction_id = :interaction_id"
    params = {"interaction_id": interaction_id}
    if tenant_id is not None and owner_user_id is not None:
        where_clause += " AND tenant_id = :tenant_id AND user_id = :owner_user_id"
        params.update({"tenant_id": tenant_id, "owner_user_id": owner_user_id})
    row = (
        session.execute(
            text(_chat_interaction_select_sql(where_clause)),
            params,
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
            workspace_id,
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
            :workspace_id,
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
            workspace_id = excluded.workspace_id,
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
            workspace_id,
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
        "workspace_id": record.get("workspace_id"),
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
        "workspace_id": (
            str(data["workspace_id"]) if data.get("workspace_id") is not None else None
        ),
        "chat_document_id": str(data["chat_document_id"]),
        "tenant_id": data["tenant_id"],
        "user_id": data["user_id"],
        "owner_user_id": data["user_id"],
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


def _owner_scoped_chat_payload(
    payload: dict[str, Any],
    auth_context: AeFacadeRouteAuthContext,
) -> dict[str, Any]:
    if auth_context.browser_context is not None:
        return owner_scoped_payload(payload, auth_context)[0]
    explicit_tenant = isinstance(payload.get("tenant_id"), str) and bool(
        payload["tenant_id"].strip()
    )
    explicit_owner = any(
        isinstance(payload.get(key), str) and bool(payload[key].strip())
        for key in ("owner_user_id", "user_id")
    )
    if isinstance(payload.get("ownership_ref"), dict) or (
        explicit_tenant and explicit_owner
    ):
        return owner_scoped_payload(payload, auth_context)[0]
    return dict(payload)


def _get_visible_chat_record(
    store: Any,
    interaction_id: str,
    auth_context: AeFacadeRouteAuthContext,
) -> dict[str, Any] | None:
    scope = browser_owner_scope(auth_context)
    if scope is None:
        return store.get(interaction_id)
    get_for_owner = getattr(store, "get_for_owner", None)
    if callable(get_for_owner):
        return get_for_owner(
            interaction_id,
            tenant_id=scope.tenant_id,
            owner_user_id=scope.owner_user_id,
        )
    record = store.get(interaction_id)
    return record if record is not None and record_matches_owner(record, scope) else None


def _persist_failed_chat_attempt(
    *,
    chat_store: Any,
    workspace_store: Any | None,
    binding: WorkspaceChatBinding | None,
    pending_record: dict[str, Any] | None,
    failure: Any,
    request_id: str,
    trace_id: str,
    event_emitter: OperationalEventEmitter,
) -> None:
    if binding is None or pending_record is None:
        return
    try:
        failed_record = chat_store.save(
            build_failed_chat_interaction_record(pending_record, failure)
        )
        observe_workspace_chat_state(event_emitter, failed_record)
    except ChatInteractionError:
        pass
    try:
        append_workspace_chat_activity(
            binding,
            workspace_store=workspace_store,
            activity_type="chat.interaction.failed",
            status="FAILED",
            request_id=request_id,
            trace_id=trace_id,
        )
    except WorkspaceChatOrchestrationError:
        pass


def _policy_error_to_chat(exc: Any) -> ChatInteractionError:
    return ChatInteractionError(
        status_code=getattr(exc, "status_code", 503),
        error_code=exc.error_code,
        detail=exc.detail,
        retryable=bool(getattr(exc, "retryable", False)),
    )


def _chat_problem_response(
    request: Request,
    exc: (
        ChatInteractionError
        | WorkspaceChatOwnerError
        | WorkspaceChatOrchestrationError
    ),
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Chat interaction failed",
        detail=exc.detail,
        retryable=getattr(exc, "retryable", False),
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
