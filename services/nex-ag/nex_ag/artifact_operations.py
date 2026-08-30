from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_collection_projection.v1"
)
AE_ARTIFACT_SOURCE_SERVICE_ID = "nex-ae-api"
NEX_AG_AE_ARTIFACT_BASE_URL_ENV = "NEX_AG_AE_ARTIFACT_BASE_URL"
NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV = "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN"
NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV = "NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS"
DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS = 10.0
SAFE_ARTIFACT_FILE_ROUTE_PREFIX = "/api/v1/artifact-files/"
SAFE_ARTIFACT_ROUTE_PREFIX = "/api/v1/artifacts/"
SAFE_STORAGE_REF_PREFIX = "ae://artifacts/"
DEFAULT_ARTIFACT_COLLECTION_LIMIT = 20
MAX_ARTIFACT_COLLECTION_LIMIT = 100
SUPPORTED_ARTIFACT_STATUSES = {
    "DRAFT",
    "RENDERING",
    "READY",
    "FAILED",
    "ARCHIVED",
    "DELETED",
}


class AeArtifactOperationsClient(Protocol):
    source_kind: str
    base_url: str | None

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        ...

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        ...

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class AeArtifactOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503


@dataclass
class InMemoryAeArtifactOperationsClient:
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_collections: dict[str, dict[str, Any]] = field(default_factory=dict)
    handoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    chat_artifact_refs: dict[str, list[dict[str, Any]] | dict[str, Any]] = field(
        default_factory=dict
    )
    source_kind: str = "memory"
    base_url: str | None = None

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_collection_cache_key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if collection_key in self.artifact_collections:
            return deepcopy(self.artifact_collections[collection_key])

        normalized_status = _normalized_status(status)
        records = [
            artifact
            for artifact in self.artifacts.values()
            if _artifact_matches_collection_filter(
                artifact,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                status=normalized_status,
            )
        ]
        records.sort(
            key=lambda artifact: str(artifact.get("updated_at") or ""),
            reverse=True,
        )
        items = [_artifact_to_collection_item(artifact) for artifact in records[:limit]]
        return {
            "artifact_collection_schema_version": "ae_artifact_collection.v1",
            "filter": {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "status": normalized_status,
                "limit": limit,
            },
            "count": len(items),
            "limit": limit,
            "next_cursor": None,
            "items": items,
        }

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(self.artifacts.get(artifact_id))

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(self.handoffs.get(artifact_handoff_id))

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        raw_value = self.chat_artifact_refs.get(interaction_id, [])
        if isinstance(raw_value, Mapping):
            raw_value = _list_value(raw_value.get("artifact_refs"))
        return deepcopy(list(raw_value))


@dataclass(frozen=True)
class HttpAeArtifactOperationsClient:
    base_url: str
    service_token: str | None = None
    timeout_seconds: float = DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    source_kind: str = "http"

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/artifacts/{artifact_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifacts",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"status": status} if status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/artifact-handoffs/{artifact_handoff_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
            request_id=request_id,
            trace_id=trace_id,
        )
        if payload is None:
            return []
        return _list_value(payload.get("artifact_refs"))

    def _get_json(
        self,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}{path}",
                headers=self._headers(request_id=request_id, trace_id=trace_id),
                params=dict(params or {}),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_unreachable",
                detail="AE artifact source could not be reached.",
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise AeArtifactOperationsError(
                error_code=body.get(
                    "error_code",
                    "ag.ae_artifact_source_request_failed",
                ),
                detail=body.get("detail", "AE artifact source request failed."),
                status_code=response.status_code,
            )
        return response.json()

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-ag",
            audience=AE_ARTIFACT_SOURCE_SERVICE_ID,
        ).access_token
        return {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
            "X-Service-ID": "nex-ag",
        }


def build_default_ae_artifact_operations_client(
    environ: Mapping[str, str] | None = None,
) -> HttpAeArtifactOperationsClient:
    env = environ if environ is not None else os.environ
    service_spec = SERVICE_SPECS[AE_ARTIFACT_SOURCE_SERVICE_ID]
    base_url = env.get(
        NEX_AG_AE_ARTIFACT_BASE_URL_ENV,
        f"http://127.0.0.1:{service_spec.default_port}",
    )
    return HttpAeArtifactOperationsClient(
        base_url=base_url.rstrip("/"),
        service_token=env.get(NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV),
        timeout_seconds=_timeout_seconds(
            env.get(NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV)
        ),
    )


def register_artifact_operation_routes(
    app: FastAPI,
    *,
    client: AeArtifactOperationsClient | None = None,
) -> None:
    configured_client = client

    @app.get("/admin/v1/operations/artifacts", response_model=None)
    def list_artifact_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_collection_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = configured_client or build_default_ae_artifact_operations_client()
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifacts(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                status=filter_result["status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get("/admin/v1/operations/artifacts/{artifact_id}", response_model=None)
    def get_artifact_operation_detail(
        artifact_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        interaction_id: str | None = None,
        include_handoff: bool = True,
        include_chat_links: bool = True,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = configured_client or build_default_ae_artifact_operations_client()
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            artifact = selected_client.get_artifact(
                artifact_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if artifact is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.ae_artifact_not_found",
                title="AE artifact not found",
                detail=f"AE artifact {artifact_id} was not found.",
                type_uri="https://nex-platform.local/problems/ae-artifact-not-found",
            )

        source_errors: list[AeArtifactOperationsError] = []
        handoff = None
        handoff_id = _handoff_id_from_artifact(artifact)
        if include_handoff and handoff_id is not None:
            try:
                handoff = selected_client.get_artifact_handoff(
                    handoff_id,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except AeArtifactOperationsError as exc:
                source_errors.append(exc)

        chat_artifact_refs: list[dict[str, Any]] = []
        if include_chat_links and interaction_id:
            try:
                chat_artifact_refs = selected_client.list_chat_artifact_refs(
                    interaction_id,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except AeArtifactOperationsError as exc:
                source_errors.append(exc)

        return build_artifact_operation_detail_projection(
            artifact=artifact,
            handoff=handoff,
            chat_artifact_refs=chat_artifact_refs,
            source_client=selected_client,
            source_errors=source_errors,
            request_trace_id=trace_id,
        )


def build_artifact_operation_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_artifact_collection_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_collection",
        "filter": _project_collection_filter(collection.get("filter")),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "next_cursor": _text_or_none(collection.get("next_cursor")),
        "items": items,
        "summary": summarize_artifact_operation_collection(items),
        "source_status": _artifact_collection_source_status(
            source_client=source_client,
            item_count=len(items),
            errors=errors,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_detail_projection(
    *,
    artifact: Mapping[str, Any],
    handoff: Mapping[str, Any] | None = None,
    chat_artifact_refs: list[dict[str, Any]] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_artifact = _project_artifact(artifact)
    projected_handoff = _project_handoff(handoff) if handoff is not None else None
    projected_chat_refs = [
        _project_chat_artifact_ref(ref) for ref in (chat_artifact_refs or [])
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact",
        "artifact": projected_artifact,
        "handoff": projected_handoff,
        "chat_artifact_refs": projected_chat_refs,
        "summary": summarize_artifact_operation_detail(
            projected_artifact,
            projected_handoff,
            projected_chat_refs,
        ),
        "source_status": _artifact_source_status(
            source_client=source_client,
            artifact_loaded=True,
            handoff_loaded=projected_handoff is not None,
            chat_artifact_ref_count=len(projected_chat_refs),
            errors=errors,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def summarize_artifact_operation_detail(
    artifact: Mapping[str, Any],
    handoff: Mapping[str, Any] | None,
    chat_artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    render_jobs = _list_value(artifact.get("render_jobs"))
    latest_render_job = render_jobs[0] if render_jobs else None
    return {
        "artifact_status": artifact.get("artifact_status"),
        "artifact_type": artifact.get("artifact_type"),
        "version_count": len(_list_value(artifact.get("versions"))),
        "render_job_count": len(render_jobs),
        "file_count": len(_list_value(artifact.get("files"))),
        "link_count": len(_list_value(artifact.get("links"))),
        "source_ref_count": len(_list_value(artifact.get("source_refs"))),
        "chat_artifact_ref_count": len(chat_artifact_refs),
        "handoff_loaded": handoff is not None,
        "latest_render_status": (
            latest_render_job.get("render_status")
            if isinstance(latest_render_job, Mapping)
            else None
        ),
    }


def summarize_artifact_operation_collection(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    downloadable_count = 0
    previewable_count = 0
    latest_updated_at: str | None = None
    for item in items:
        status = item.get("artifact_status")
        if isinstance(status, str) and status:
            status_counts[status] = status_counts.get(status, 0) + 1
        if item.get("downloadable_formats"):
            downloadable_count += 1
        if item.get("previewable_formats"):
            previewable_count += 1
        updated_at = item.get("updated_at")
        if isinstance(updated_at, str) and (
            latest_updated_at is None or updated_at > latest_updated_at
        ):
            latest_updated_at = updated_at
    return {
        "item_count": len(items),
        "ready_count": status_counts.get("READY", 0),
        "draft_count": status_counts.get("DRAFT", 0),
        "failed_count": status_counts.get("FAILED", 0),
        "downloadable_count": downloadable_count,
        "previewable_count": previewable_count,
        "status_counts": status_counts,
        "latest_updated_at": latest_updated_at,
    }


def assert_artifact_operation_projection_redacted(projection: Mapping[str, Any]) -> None:
    serialized = str(projection)
    forbidden_fragments = (
        "/data/nex-platform",
        "content_base64",
        "database_url",
        "PRIVATE_MARKDOWN",
        "SECRET_SOURCE_TEXT",
        "SECRET_SYSTEM_PROMPT",
        "hidden prompt",
        "nuri1004",
        "raw source",
        "rendered_markdown",
    )
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError("AG artifact operation projection contains private data.")


def _project_artifact(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_schema_version": _text_or_none(
            record.get("artifact_schema_version")
        ),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "display_title": _text_or_none(
            record.get("display_title") or record.get("artifact_title")
        ),
        "current_version_id": _text_or_none(record.get("current_version_id")),
        "artifact_handoff_id": _handoff_id_from_artifact(record),
        "artifact_request_id": _text_or_none(record.get("artifact_request_id")),
        "trace_id": _text_or_none(record.get("trace_id")),
        "request_id": _text_or_none(record.get("request_id")),
        "owner_scope": _owner_scope(record.get("owner_actor_ref")),
        "workspace_ref": _select_mapping(
            record.get("workspace_ref"),
            ("workspace_id", "document_group_id", "chat_document_id"),
        ),
        "target_formats": _text_list(record.get("target_formats")),
        "source_refs": [
            _project_source_ref(ref) for ref in _list_value(record.get("source_refs"))
        ],
        "versions": [
            _project_version(version)
            for version in _list_value(record.get("versions"))
        ],
        "render_jobs": [
            _project_render_job(render_job)
            for render_job in _list_value(record.get("render_jobs"))
        ],
        "files": [_project_file(file) for file in _list_value(record.get("files"))],
        "links": [_project_link(link) for link in _list_value(record.get("links"))],
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_artifact_collection_item(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_collection_item_schema_version": _text_or_none(
            record.get("artifact_collection_item_schema_version")
        ),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "display_title": _text_or_none(record.get("display_title")),
        "language": _text_or_none(record.get("language")),
        "artifact_intent": _text_or_none(record.get("artifact_intent")),
        "target_formats": _text_list(record.get("target_formats")),
        "available_formats": _text_list(record.get("available_formats")),
        "downloadable_formats": _text_list(record.get("downloadable_formats")),
        "previewable_formats": _text_list(record.get("previewable_formats")),
        "current_version_id": _text_or_none(record.get("current_version_id")),
        "current_version_no": _int_or_zero(record.get("current_version_no")),
        "version_count": _int_or_zero(record.get("version_count")),
        "file_count": _int_or_zero(record.get("file_count")),
        "link_count": _int_or_zero(record.get("link_count")),
        "render_job_count": _int_or_zero(record.get("render_job_count")),
        "latest_render_job": _select_mapping(
            record.get("latest_render_job"),
            (
                "render_job_id",
                "artifact_version_id",
                "render_status",
                "renderer_policy_id",
                "target_formats",
                "started_at",
                "completed_at",
                "created_at",
            ),
        ),
        "source_summary": _select_mapping(
            record.get("source_summary"),
            (
                "cx_generation_id",
                "structured_draft_id",
                "structured_draft_content_hash",
                "generation_response_hash",
                "retrieval_package_id",
                "retrieval_package_hash",
            ),
        ),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "routes": _safe_artifact_route_mapping(record.get("routes")),
        "tenant_id": _text_or_none(record.get("tenant_id")),
        "workspace_id": _text_or_none(record.get("workspace_id")),
        "owner_user_id": _text_or_none(record.get("owner_user_id")),
        "chat_document_id": _text_or_none(record.get("chat_document_id")),
        "interaction_id": _text_or_none(record.get("interaction_id")),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_collection_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "status": _normalized_status(raw_value.get("status")),
        "limit": _int_or_zero(raw_value.get("limit")),
    }


def _project_handoff(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_handoff_id": _text_or_none(record.get("artifact_handoff_id")),
        "handoff_schema_version": _text_or_none(record.get("handoff_schema_version")),
        "handoff_status": _text_or_none(record.get("handoff_status")),
        "artifact_request_id": _text_or_none(record.get("artifact_request_id")),
        "artifact_intent": _text_or_none(record.get("artifact_intent")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_title": _text_or_none(record.get("artifact_title")),
        "cx_generation_id": _text_or_none(record.get("cx_generation_id")),
        "structured_draft_id": _text_or_none(record.get("structured_draft_id")),
        "structured_draft_content_hash": _text_or_none(
            record.get("structured_draft_content_hash")
        ),
        "generation_response_hash": _text_or_none(
            record.get("generation_response_hash")
        ),
        "target_formats": _text_list(record.get("target_formats")),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "workspace_ref": _select_mapping(
            record.get("workspace_ref"),
            ("workspace_id", "document_group_id", "chat_document_id"),
        ),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_chat_artifact_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chat_artifact_ref_id": _text_or_none(record.get("chat_artifact_ref_id")),
        "chat_interaction_id": _text_or_none(record.get("chat_interaction_id")),
        "chat_document_id": _text_or_none(record.get("chat_document_id")),
        "tenant_id": _text_or_none(record.get("tenant_id")),
        "user_id": _text_or_none(record.get("user_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "display_title": _text_or_none(record.get("display_title")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "primary_format": _text_or_none(record.get("primary_format")),
        "available_formats": _text_list(record.get("available_formats")),
        "preview_route": _safe_route(record.get("preview_route")),
        "download_routes": _safe_route_mapping(record.get("download_routes")),
        "source_generation_id": _text_or_none(record.get("source_generation_id")),
        "source_content_hash": _text_or_none(record.get("source_content_hash")),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "actions": _safe_action_mapping(record.get("actions")),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_source_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cx_generation_id": _text_or_none(record.get("cx_generation_id")),
        "structured_draft_id": _text_or_none(record.get("structured_draft_id")),
        "structured_draft_content_hash": _text_or_none(
            record.get("structured_draft_content_hash")
        ),
        "generation_response_hash": _text_or_none(
            record.get("generation_response_hash")
        ),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
    }


def _project_version(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "version_no": _int_or_zero(record.get("version_no")),
        "version_reason": _text_or_none(record.get("version_reason")),
        "source_content_hash": _text_or_none(record.get("source_content_hash")),
        "artifact_content_hash": _text_or_none(record.get("artifact_content_hash")),
        "rendered_formats": _text_list(record.get("rendered_formats")),
        "validation_snapshot": _safe_quality_summary(record.get("validation_snapshot")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_render_job(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "render_job_id": _text_or_none(record.get("render_job_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "render_status": _text_or_none(record.get("render_status")),
        "renderer_policy_id": _text_or_none(record.get("renderer_policy_id")),
        "target_formats": _text_list(record.get("target_formats")),
        "failure_summary": _safe_quality_summary(record.get("failure_summary")),
        "started_at": _text_or_none(record.get("started_at")),
        "completed_at": _text_or_none(record.get("completed_at")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_file(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_file_id": _text_or_none(record.get("artifact_file_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "format": _text_or_none(record.get("format")),
        "mime_type": _text_or_none(record.get("mime_type")),
        "file_name": _text_or_none(record.get("file_name")),
        "file_hash": _text_or_none(record.get("file_hash")),
        "file_size_bytes": _int_or_zero(record.get("file_size_bytes")),
        "storage_ref": _safe_storage_ref(record.get("storage_ref")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_link(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_link_id": _text_or_none(record.get("artifact_link_id")),
        "artifact_file_id": _text_or_none(record.get("artifact_file_id")),
        "link_type": _text_or_none(record.get("link_type")),
        "link_route": _safe_route(record.get("link_route")),
        "expires_at": _text_or_none(record.get("expires_at")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _artifact_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    artifact_loaded: bool,
    handoff_loaded: bool,
    chat_artifact_ref_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    source = {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "artifact_loaded": artifact_loaded,
        "handoff_loaded": handoff_loaded,
        "chat_artifact_ref_count": chat_artifact_ref_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }
    return source


def _artifact_collection_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "collection_loaded": not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _validate_artifact_collection_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_scope_missing",
            title="Artifact collection scope is required",
            detail="Artifact collection queries require tenant, workspace, and owner scope.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-scope-missing"
            ),
        )

    normalized_status = _normalized_status(status)
    if normalized_status is not None and normalized_status not in SUPPORTED_ARTIFACT_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_status_invalid",
            title="Invalid artifact collection status",
            detail="Artifact collection status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_limit_invalid",
            title="Invalid artifact collection limit",
            detail=f"Artifact collection limit must be between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "status": normalized_status,
        "limit": normalized_limit,
    }


def _artifact_collection_cache_key(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (tenant_id, workspace_id, owner_user_id, status or "", str(limit))
    )


def _artifact_matches_collection_filter(
    artifact: Mapping[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
) -> bool:
    if _owner_tenant_id(artifact) != tenant_id:
        return False
    if _workspace_id(artifact) != workspace_id:
        return False
    if _owner_user_id(artifact) != owner_user_id:
        return False
    return status is None or _normalized_status(artifact.get("artifact_status")) == status


def _artifact_to_collection_item(artifact: Mapping[str, Any]) -> dict[str, Any]:
    versions = _list_value(artifact.get("versions"))
    files = _list_value(artifact.get("files"))
    links = _list_value(artifact.get("links"))
    render_jobs = _list_value(artifact.get("render_jobs"))
    source_ref = _first_mapping(artifact.get("source_refs"))
    artifact_id = _text_or_none(artifact.get("artifact_id"))
    return {
        "artifact_collection_item_schema_version": "ae_artifact_collection_item.v1",
        "artifact_id": artifact_id,
        "artifact_type": _text_or_none(artifact.get("artifact_type")),
        "artifact_status": _text_or_none(artifact.get("artifact_status")),
        "display_title": _text_or_none(artifact.get("display_title")),
        "language": _text_or_none(artifact.get("language")),
        "artifact_intent": _text_or_none(artifact.get("artifact_intent")),
        "target_formats": _text_list(artifact.get("target_formats")),
        "available_formats": _available_formats(files),
        "downloadable_formats": _linked_formats(files, links, "download"),
        "previewable_formats": _linked_formats(files, links, "preview"),
        "current_version_id": _text_or_none(artifact.get("current_version_id")),
        "current_version_no": _current_version_no(
            versions,
            _text_or_none(artifact.get("current_version_id")),
        ),
        "version_count": len(versions),
        "file_count": len(files),
        "link_count": len(links),
        "render_job_count": len(render_jobs),
        "latest_render_job": _latest_render_job_summary(render_jobs),
        "source_summary": _source_collection_summary(source_ref),
        "quality_summary": _safe_quality_summary(source_ref.get("quality_summary")),
        "routes": {
            "detail": f"/api/v1/artifacts/{artifact_id}",
            "versions": f"/api/v1/artifacts/{artifact_id}/versions",
        },
        "tenant_id": _owner_tenant_id(artifact),
        "workspace_id": _workspace_id(artifact),
        "owner_user_id": _owner_user_id(artifact),
        "chat_document_id": _text_or_none(artifact.get("chat_document_id")),
        "interaction_id": _text_or_none(artifact.get("interaction_id")),
        "created_at": _text_or_none(artifact.get("created_at")),
        "updated_at": _text_or_none(artifact.get("updated_at")),
    }


def _handoff_id_from_artifact(record: Mapping[str, Any]) -> str | None:
    if record.get("artifact_handoff_id") is not None:
        return _text_or_none(record.get("artifact_handoff_id"))
    handoff_ref = record.get("handoff_ref")
    if isinstance(handoff_ref, Mapping):
        return _text_or_none(handoff_ref.get("artifact_handoff_id"))
    return None


def _owner_scope(raw_value: Any) -> dict[str, str | None]:
    if not isinstance(raw_value, Mapping):
        return {"tenant_id": None, "user_id": None, "actor_type": None}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "user_id": _text_or_none(raw_value.get("user_id")),
        "actor_type": _text_or_none(raw_value.get("actor_type")),
    }


def _select_mapping(raw_value: Any, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        key: _json_safe_value(raw_value.get(key))
        for key in allowed_keys
        if raw_value.get(key) is not None
    }


def _safe_quality_summary(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    allowed = (
        "citation_status",
        "citation_count",
        "validation_error_count",
        "warning_count",
        "grounding_required",
        "retrieval_package_id",
        "retrieval_package_hash",
        "evidence_ref_count",
        "quality_status",
        "error_code",
        "error_detail_sha256",
    )
    return _select_mapping(raw_value, allowed)


def _safe_action_mapping(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        key: value
        for key, value in _select_mapping(
            raw_value,
            ("preview", "download", "copy_link", "open_artifact"),
        ).items()
        if isinstance(value, (bool, str, int, float)) or value is None
    }


def _safe_route_mapping(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, Mapping):
        return {}
    routes: dict[str, str] = {}
    for key, value in raw_value.items():
        safe_route = _safe_route(value)
        if safe_route is not None:
            routes[str(key)] = safe_route
    return routes


def _safe_artifact_route_mapping(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, Mapping):
        return {}
    routes: dict[str, str] = {}
    for key, value in raw_value.items():
        route = _safe_artifact_route(value)
        if route is not None:
            routes[str(key)] = route
    return routes


def _safe_route(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_ARTIFACT_FILE_ROUTE_PREFIX) else None


def _safe_artifact_route(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_ARTIFACT_ROUTE_PREFIX) else None


def _safe_storage_ref(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_STORAGE_REF_PREFIX) else None


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _timeout_seconds(raw_value: str | None) -> float:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError:
        return DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS


def _validate_artifact_service_filter(
    request: Request,
    service_id: str | None,
) -> JSONResponse | None:
    if service_id is None or service_id == AE_ARTIFACT_SOURCE_SERVICE_ID:
        return None
    return problem_response(
        request,
        status_code=400,
        error_code="ag.ae_artifact_service_invalid",
        title="Invalid AE artifact service filter",
        detail=(
            "Artifact operations are currently available only for "
            f"{AE_ARTIFACT_SOURCE_SERVICE_ID}."
        ),
        type_uri="https://nex-platform.local/problems/ae-artifact-service-invalid",
    )


def _collection_limit(raw_value: str | None) -> int | None:
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_ARTIFACT_COLLECTION_LIMIT
    try:
        limit = int(str(raw_value))
    except ValueError:
        return None
    return limit if 1 <= limit <= MAX_ARTIFACT_COLLECTION_LIMIT else None


def _normalized_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().upper()


def _artifact_operations_problem_response(
    request: Request,
    exc: AeArtifactOperationsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="AE artifact source unavailable",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/ae-artifact-source-unavailable",
    )


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


def _deepcopy_or_none(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return deepcopy(value) if value is not None else None


def _list_value(raw_value: Any) -> list[Any]:
    return list(raw_value) if isinstance(raw_value, list) else []


def _first_mapping(raw_value: Any) -> dict[str, Any]:
    for value in _list_value(raw_value):
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _text_list(raw_value: Any) -> list[str]:
    return [str(value) for value in _list_value(raw_value) if value is not None]


def _text_or_none(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    return str(raw_value)


def _present_text(raw_value: Any) -> bool:
    return bool(_text_or_none(raw_value) and str(raw_value).strip())


def _int_or_zero(raw_value: Any) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _owner_tenant_id(record: Mapping[str, Any]) -> str | None:
    owner = record.get("owner_actor_ref")
    if isinstance(owner, Mapping):
        return _text_or_none(owner.get("tenant_id"))
    return _text_or_none(record.get("tenant_id"))


def _owner_user_id(record: Mapping[str, Any]) -> str | None:
    owner = record.get("owner_actor_ref")
    if isinstance(owner, Mapping):
        return _text_or_none(owner.get("actor_id") or owner.get("user_id"))
    return _text_or_none(record.get("owner_user_id") or record.get("user_id"))


def _workspace_id(record: Mapping[str, Any]) -> str | None:
    workspace = record.get("workspace_ref")
    if isinstance(workspace, Mapping):
        return _text_or_none(workspace.get("workspace_id"))
    return _text_or_none(record.get("workspace_id"))


def _available_formats(files: list[Any]) -> list[str]:
    formats = [
        _text_or_none(file.get("format"))
        for file in files
        if isinstance(file, Mapping)
    ]
    return sorted({value for value in formats if value})


def _linked_formats(files: list[Any], links: list[Any], link_type: str) -> list[str]:
    file_formats = {
        file.get("artifact_file_id"): _text_or_none(file.get("format"))
        for file in files
        if isinstance(file, Mapping)
    }
    linked = [
        file_formats.get(link.get("artifact_file_id"))
        for link in links
        if isinstance(link, Mapping)
        and _text_or_none(link.get("link_type")) == link_type
        and _safe_route(link.get("link_route")) is not None
    ]
    return sorted({value for value in linked if value})


def _current_version_no(versions: list[Any], current_version_id: str | None) -> int:
    for version in versions:
        if (
            isinstance(version, Mapping)
            and _text_or_none(version.get("artifact_version_id")) == current_version_id
        ):
            return _int_or_zero(version.get("version_no"))
    return 0


def _latest_render_job_summary(render_jobs: list[Any]) -> dict[str, Any]:
    candidates = [job for job in render_jobs if isinstance(job, Mapping)]
    candidates.sort(key=lambda job: str(job.get("created_at") or ""), reverse=True)
    if not candidates:
        return {}
    return _select_mapping(
        candidates[0],
        (
            "render_job_id",
            "artifact_version_id",
            "render_status",
            "renderer_policy_id",
            "target_formats",
            "started_at",
            "completed_at",
            "created_at",
        ),
    )


def _source_collection_summary(source_ref: Mapping[str, Any]) -> dict[str, Any]:
    return _select_mapping(
        source_ref,
        (
            "cx_generation_id",
            "structured_draft_id",
            "structured_draft_content_hash",
            "generation_response_hash",
            "retrieval_package_id",
            "retrieval_package_hash",
        ),
    )


def _json_safe_value(raw_value: Any) -> Any:
    if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
        return raw_value
    if isinstance(raw_value, list):
        return [_json_safe_value(value) for value in raw_value]
    if isinstance(raw_value, Mapping):
        return {
            str(key): _json_safe_value(value)
            for key, value in raw_value.items()
            if value is not None
        }
    return str(raw_value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
