from __future__ import annotations

import hashlib
import json
import os
import re
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


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_OWNER_USER_ID = "local-user"
DEFAULT_TARGET_FORMATS = ["MD", "HTML_PREVIEW"]
DEFAULT_RETENTION_POLICY_REF = "generated-artifact-retention-local-v1"
DEFAULT_ARTIFACT_TYPE = "generated_document"
MARKDOWN_RENDERER_POLICY_ID = "ae-markdown-renderer-v1"
ARTIFACT_HANDOFF_JSON_FIELDS = (
    "actor_claims_ref",
    "workspace_ref",
    "target_formats",
    "quality_summary",
)
ARTIFACT_RECORD_JSON_FIELDS = (
    "owner_actor_ref",
    "workspace_ref",
    "target_formats",
    "template_ref",
    "handoff_ref",
)
ARTIFACT_SOURCE_REF_JSON_FIELDS = ("quality_summary",)
ARTIFACT_VERSION_JSON_FIELDS = ("rendered_formats", "validation_snapshot")
ARTIFACT_LINK_JSON_FIELDS = ("created_by_actor_ref",)
SUPPORTED_ARTIFACT_INTENTS = {
    "preview_only",
    "create_artifact",
    "create_and_export",
}
SUPPORTED_ARTIFACT_TYPES = {"generated_document", "summary", "answer_export"}
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


@dataclass
class ArtifactRecordStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    render_jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    rendered_markdown: dict[str, str] = field(default_factory=dict)
    artifact_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_links: dict[str, dict[str, Any]] = field(default_factory=dict)

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        existing = self.records.get(record["artifact_id"])
        if existing is not None:
            return existing
        self.records[record["artifact_id"]] = record
        return record

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.records[record["artifact_id"]] = record
        return record

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        return self.records.get(artifact_id)

    def list_versions(self, artifact_id: str) -> list[dict[str, Any]] | None:
        record = self.get(artifact_id)
        if record is None:
            return None
        return list(record["versions"])

    def get_render_job(self, render_job_id: str) -> dict[str, Any] | None:
        return self.render_jobs.get(render_job_id)

    def get_rendered_markdown(self, artifact_version_id: str) -> str | None:
        return self.rendered_markdown.get(artifact_version_id)

    def get_file(self, artifact_file_id: str) -> dict[str, Any] | None:
        return self.artifact_files.get(artifact_file_id)

    def get_file_link(
        self,
        artifact_file_id: str,
        link_type: str,
    ) -> dict[str, Any] | None:
        for link in self.artifact_links.values():
            if (
                link["artifact_file_id"] == artifact_file_id
                and link["link_type"] == link_type
            ):
                return link
        return None

    def apply_markdown_render(
        self,
        *,
        artifact_id: str,
        artifact_version: dict[str, Any],
        render_job: dict[str, Any],
        markdown: str,
        artifact_files: list[dict[str, Any]],
        artifact_links: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record = self.records[artifact_id]
        record["versions"].append(artifact_version)
        record["render_jobs"].append(render_job)
        record["files"].extend(artifact_files)
        record["links"].extend(artifact_links)
        record["artifact_status"] = "READY"
        record["current_version_id"] = artifact_version["artifact_version_id"]
        record["updated_at"] = render_job["completed_at"]
        self.render_jobs[render_job["render_job_id"]] = render_job
        self.rendered_markdown[artifact_version["artifact_version_id"]] = markdown
        for artifact_file in artifact_files:
            self.artifact_files[artifact_file["artifact_file_id"]] = artifact_file
        for artifact_link in artifact_links:
            self.artifact_links[artifact_link["artifact_link_id"]] = artifact_link
        return record


class SqlAlchemyArtifactHandoffStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        validate_artifact_handoff_record(record)
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_artifact_handoff_upsert_sql(_dialect_name(session))),
                    _artifact_handoff_params(record),
                )
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_handoff_store_unavailable",
                detail="AE artifact handoff store is unavailable.",
                retryable=True,
            ) from exc

    def get(self, artifact_handoff_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_artifact_handoff_select_sql()),
                        {"artifact_handoff_id": artifact_handoff_id},
                    )
                    .mappings()
                    .first()
                )
            return _artifact_handoff_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_handoff_store_unavailable",
                detail="AE artifact handoff store is unavailable.",
                retryable=True,
            ) from exc

    def delete(self, artifact_handoff_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        """
                        DELETE FROM ae_artifact_handoffs
                        WHERE artifact_handoff_id = :artifact_handoff_id
                        """
                    ),
                    {"artifact_handoff_id": artifact_handoff_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_handoff_store_unavailable",
                detail="AE artifact handoff store is unavailable.",
                retryable=True,
            ) from exc


class SqlAlchemyArtifactRecordStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.rendered_markdown: dict[str, str] = {}

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        existing = self.get(record["artifact_id"])
        if existing is not None:
            return existing
        return self.save(record)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                _persist_artifact_record(session, record)
                session.commit()
            return record
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_artifact_record(session, artifact_id)
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc

    def list_versions(self, artifact_id: str) -> list[dict[str, Any]] | None:
        record = self.get(artifact_id)
        if record is None:
            return None
        return list(record["versions"])

    def get_render_job(self, render_job_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_artifact_render_job_select_sql("render_job_id = :render_job_id")),
                        {"render_job_id": render_job_id},
                    )
                    .mappings()
                    .first()
                )
            return _artifact_render_job_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc

    def get_rendered_markdown(self, artifact_version_id: str) -> str | None:
        return self.rendered_markdown.get(artifact_version_id)

    def get_file(self, artifact_file_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_artifact_file_select_sql("artifact_file_id = :artifact_file_id")),
                        {"artifact_file_id": artifact_file_id},
                    )
                    .mappings()
                    .first()
                )
            return _artifact_file_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc

    def get_file_link(
        self,
        artifact_file_id: str,
        link_type: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            _artifact_link_select_sql(
                                "artifact_file_id = :artifact_file_id "
                                "AND link_type = :link_type"
                            )
                        ),
                        {
                            "artifact_file_id": artifact_file_id,
                            "link_type": link_type,
                        },
                    )
                    .mappings()
                    .first()
                )
            return _artifact_link_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc

    def apply_markdown_render(
        self,
        *,
        artifact_id: str,
        artifact_version: dict[str, Any],
        render_job: dict[str, Any],
        markdown: str,
        artifact_files: list[dict[str, Any]],
        artifact_links: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record = self.get(artifact_id)
        if record is None:
            raise ArtifactHandoffError(
                status_code=404,
                error_code="ae.artifact_not_found",
                detail=f"Artifact was not found: {artifact_id}",
            )
        record["versions"].append(artifact_version)
        record["render_jobs"].append(render_job)
        record["files"].extend(artifact_files)
        record["links"].extend(artifact_links)
        record["artifact_status"] = "READY"
        record["current_version_id"] = artifact_version["artifact_version_id"]
        record["updated_at"] = render_job["completed_at"]
        self.rendered_markdown[artifact_version["artifact_version_id"]] = markdown
        return self.save(record)

    def delete(self, artifact_id: str) -> int:
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        """
                        DELETE FROM ae_artifacts
                        WHERE artifact_id = :artifact_id
                        """
                    ),
                    {"artifact_id": artifact_id},
                )
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise ArtifactHandoffError(
                status_code=503,
                error_code="ae.artifact_store_unavailable",
                detail="AE artifact store is unavailable.",
                retryable=True,
            ) from exc


@dataclass(frozen=True)
class ArtifactHandoffError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


DEFAULT_ARTIFACT_HANDOFF_STORE = ArtifactHandoffStore()
DEFAULT_ARTIFACT_RECORD_STORE = ArtifactRecordStore()


def build_default_cx_artifact_source_client() -> HttpCxArtifactSourceClient:
    return HttpCxArtifactSourceClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_artifact_handoff_routes(
    app: FastAPI,
    *,
    store: ArtifactHandoffStore | None = None,
    artifact_store: ArtifactRecordStore | None = None,
    cx_client: CxArtifactSourceClient | None = None,
) -> None:
    handoff_store = store or DEFAULT_ARTIFACT_HANDOFF_STORE
    artifact_record_store = artifact_store or DEFAULT_ARTIFACT_RECORD_STORE
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

    @app.post("/api/v1/artifacts", response_model=None)
    def create_artifact(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            artifact_handoff_id = required_string(
                payload,
                "artifact_handoff_id",
                "ae.artifact_handoff_id_required",
            )
            handoff_record = handoff_store.get(artifact_handoff_id)
            if handoff_record is None:
                raise ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_handoff_not_found",
                    detail=f"Artifact handoff was not found: {artifact_handoff_id}",
                )
            record = build_artifact_record_from_handoff(
                source_payload=payload,
                handoff_record=handoff_record,
                artifact_request_id=idempotency_key
                or optional_text(payload.get("artifact_request_id")),
                request_id=request_id_from_headers(request),
                trace_id=payload.get("trace_id") or trace_id_from_headers(request),
            )
            return artifact_record_store.create(record)
        except ArtifactHandoffError as exc:
            return _artifact_problem_response(request, exc)

    @app.get("/api/v1/artifacts/{artifact_id}", response_model=None)
    def get_artifact(
        artifact_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = artifact_record_store.get(artifact_id)
        if record is None:
            return _artifact_problem_response(
                request,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_not_found",
                    detail=f"Artifact was not found: {artifact_id}",
                ),
            )
        return record

    @app.get("/api/v1/artifacts/{artifact_id}/versions", response_model=None)
    def list_artifact_versions(
        artifact_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = artifact_record_store.get(artifact_id)
        if record is None:
            return _artifact_problem_response(
                request,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_not_found",
                    detail=f"Artifact was not found: {artifact_id}",
                ),
            )
        return {
            "artifact_id": record["artifact_id"],
            "current_version_id": record["current_version_id"],
            "versions": artifact_record_store.list_versions(artifact_id) or [],
        }

    @app.post("/api/v1/artifacts/{artifact_id}/render-jobs", response_model=None)
    def create_artifact_render_job(
        artifact_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            record = artifact_record_store.get(artifact_id)
            if record is None:
                raise ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_not_found",
                    detail=f"Artifact was not found: {artifact_id}",
                )
            render_request_id = idempotency_key or required_string(
                payload,
                "render_request_id",
                "ae.render_request_id_required",
            )
            render_job_id = deterministic_render_job_id(artifact_id, render_request_id)
            existing_job = artifact_record_store.get_render_job(render_job_id)
            if existing_job is not None:
                return {
                    "render_result_schema_version": "ae_markdown_render_result.v1",
                    "render_job": existing_job,
                    "artifact": record,
                }
            target_formats = markdown_target_formats_from_payload(payload, record)
            source_ref = record["source_refs"][0]
            structured_draft = client.get_structured_draft(
                source_ref["cx_generation_id"],
                request_id=request_id_from_headers(request),
                trace_id=payload.get("trace_id") or trace_id_from_headers(request),
            )
            render_result = build_markdown_render_result(
                artifact_record=record,
                structured_draft=structured_draft,
                target_formats=target_formats,
                render_request_id=render_request_id,
                render_job_id=render_job_id,
            )
            updated_record = artifact_record_store.apply_markdown_render(
                artifact_id=artifact_id,
                artifact_version=render_result["artifact_version"],
                render_job=render_result["render_job"],
                markdown=render_result["markdown"],
                artifact_files=render_result["artifact_files"],
                artifact_links=render_result["artifact_links"],
            )
            return {
                "render_result_schema_version": "ae_markdown_render_result.v1",
                "render_job": render_result["render_job"],
                "artifact": updated_record,
            }
        except ArtifactHandoffError as exc:
            return _artifact_problem_response(request, exc)

    @app.get("/api/v1/artifact-render-jobs/{render_job_id}", response_model=None)
    def get_artifact_render_job(
        render_job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        render_job = artifact_record_store.get_render_job(render_job_id)
        if render_job is None:
            return _artifact_problem_response(
                request,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.render_job_not_found",
                    detail=f"Artifact render job was not found: {render_job_id}",
                ),
            )
        return render_job

    @app.get("/api/v1/artifact-files/{artifact_file_id}", response_model=None)
    def get_artifact_file(
        artifact_file_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        artifact_file = artifact_record_store.get_file(artifact_file_id)
        if artifact_file is None:
            return _artifact_problem_response(
                request,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.artifact_file_not_found",
                    detail=f"Artifact file was not found: {artifact_file_id}",
                ),
            )
        return artifact_file

    @app.get("/api/v1/artifact-files/{artifact_file_id}/preview", response_model=None)
    def preview_artifact_file(
        artifact_file_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            artifact_file, preview_link, markdown = resolve_artifact_file_payload(
                artifact_record_store,
                artifact_file_id=artifact_file_id,
                link_type="preview",
            )
            preview_text = markdown[:2000]
            return {
                "preview_schema_version": "ae_artifact_file_preview.v1",
                "artifact_file": artifact_file,
                "artifact_link": preview_link,
                "content_type": artifact_file["mime_type"],
                "text_preview": preview_text,
                "truncated": len(markdown) > len(preview_text),
            }
        except ArtifactHandoffError as exc:
            return _artifact_problem_response(request, exc)

    @app.get("/api/v1/artifact-files/{artifact_file_id}/download", response_model=None)
    def download_artifact_file(
        artifact_file_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            artifact_file, download_link, markdown = resolve_artifact_file_payload(
                artifact_record_store,
                artifact_file_id=artifact_file_id,
                link_type="download",
            )
            return {
                "download_schema_version": "ae_artifact_file_download.v1",
                "artifact_file": artifact_file,
                "artifact_link": download_link,
                "download_file_name": artifact_file["file_name"],
                "content_type": artifact_file["mime_type"],
                "content_hash": artifact_file["file_hash"],
                "content": markdown,
            }
        except ArtifactHandoffError as exc:
            return _artifact_problem_response(request, exc)


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


def build_artifact_record_from_handoff(
    *,
    source_payload: dict[str, Any],
    handoff_record: dict[str, Any],
    artifact_request_id: str | None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    validate_artifact_handoff_record(handoff_record)
    normalized_artifact_request_id = artifact_request_id or required_string(
        source_payload,
        "artifact_request_id",
        "ae.artifact_request_id_required",
    )
    artifact_id = optional_text(source_payload.get("artifact_id")) or str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact:"
                f"{normalized_artifact_request_id}:{handoff_record['artifact_handoff_id']}"
            ),
        )
    )
    now = _utc_now()
    return {
        "artifact_schema_version": "ae_artifact_record.v1",
        "artifact_id": artifact_id,
        "artifact_type": artifact_type_from_payload(source_payload),
        "artifact_status": "DRAFT",
        "current_version_id": None,
        "trace_id": trace_id,
        "request_id": request_id,
        "chat_document_id": handoff_record["chat_document_id"],
        "interaction_id": handoff_record["interaction_id"],
        "owner_actor_ref": dict(handoff_record["actor_claims_ref"]),
        "workspace_ref": dict(handoff_record["workspace_ref"]),
        "display_title": optional_text(source_payload.get("display_title"))
        or handoff_record["artifact_title"],
        "language": handoff_record["language"],
        "artifact_intent": handoff_record["artifact_intent"],
        "target_formats": list(handoff_record["target_formats"]),
        "retention_policy_ref": handoff_record["retention_policy_ref"],
        "template_ref": {
            "template_id": handoff_record["template_id"],
            "template_version": handoff_record["template_version"],
            "rendering_template_id": handoff_record["rendering_template_id"],
        },
        "handoff_ref": {
            "artifact_handoff_id": handoff_record["artifact_handoff_id"],
            "artifact_request_id": handoff_record["artifact_request_id"],
            "handoff_schema_version": handoff_record["handoff_schema_version"],
        },
        "source_refs": [artifact_source_ref_from_handoff(artifact_id, handoff_record)],
        "versions": [],
        "render_jobs": [],
        "files": [],
        "links": [],
        "created_at": now,
        "updated_at": now,
    }


def artifact_source_ref_from_handoff(
    artifact_id: str,
    handoff_record: dict[str, Any],
) -> dict[str, Any]:
    quality_summary = dict(handoff_record["quality_summary"])
    evidence_ref_count = int(quality_summary.get("evidence_ref_count") or 0)
    source_ref_id = str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-source-ref:"
                f"{artifact_id}:{handoff_record['cx_generation_id']}:"
                f"{handoff_record['structured_draft_id']}"
            ),
        )
    )
    return {
        "source_ref_id": source_ref_id,
        "cx_generation_id": handoff_record["cx_generation_id"],
        "structured_draft_id": handoff_record["structured_draft_id"],
        "draft_schema_version": handoff_record["draft_schema_version"],
        "structured_draft_content_hash": handoff_record[
            "structured_draft_content_hash"
        ],
        "citation_claims_hash": handoff_record["citation_claims_hash"],
        "validation_result_hash": handoff_record["validation_result_hash"],
        "retrieval_package_id": quality_summary["retrieval_package_id"],
        "retrieval_package_hash": quality_summary["retrieval_package_hash"],
        "evidence_ref_count": evidence_ref_count,
        "source_anchor_count": evidence_ref_count,
        "quality_summary": quality_summary,
    }


def build_markdown_render_result(
    *,
    artifact_record: dict[str, Any],
    structured_draft: dict[str, Any],
    target_formats: list[str],
    render_request_id: str,
    render_job_id: str,
) -> dict[str, Any]:
    validate_structured_draft_for_markdown_render(artifact_record, structured_draft)
    markdown = render_markdown_from_structured_draft(structured_draft)
    now = _utc_now()
    artifact_content_hash = sha256_text(markdown)
    source_ref = artifact_record["source_refs"][0]
    artifact_version_id = str(
        uuid5(
            NAMESPACE_URL,
            (
                "ae-artifact-version:"
                f"{artifact_record['artifact_id']}:{len(artifact_record['versions']) + 1}:"
                f"{artifact_content_hash}"
            ),
        )
    )
    artifact_version = {
        "artifact_version_id": artifact_version_id,
        "artifact_id": artifact_record["artifact_id"],
        "version_no": len(artifact_record["versions"]) + 1,
        "version_reason": "initial_render"
        if not artifact_record["versions"]
        else "rerender",
        "source_generation_id": source_ref["cx_generation_id"],
        "source_structured_draft_id": source_ref["structured_draft_id"],
        "source_content_hash": source_ref["structured_draft_content_hash"],
        "source_citation_claims_hash": source_ref["citation_claims_hash"],
        "render_policy_hash": sha256_json(
            {
                "renderer_policy_id": MARKDOWN_RENDERER_POLICY_ID,
                "target_formats": target_formats,
                "template_ref": artifact_record["template_ref"],
            }
        ),
        "artifact_content_hash": artifact_content_hash,
        "rendered_formats": target_formats,
        "validation_snapshot": dict(source_ref["quality_summary"]),
        "created_at": now,
    }
    render_job = {
        "render_job_id": render_job_id,
        "artifact_id": artifact_record["artifact_id"],
        "artifact_version_id": artifact_version_id,
        "job_status": "COMPLETED",
        "current_stage": "FINALIZING",
        "progress_mode": "DETERMINATE",
        "progress_percent": 100,
        "retryable": False,
        "failure_code": None,
        "started_at": now,
        "completed_at": now,
    }
    artifact_files = build_markdown_artifact_files(
        artifact_record=artifact_record,
        artifact_version=artifact_version,
        markdown=markdown,
    )
    artifact_links = build_artifact_links(
        artifact_file=artifact_files[0],
        created_by_actor_ref=artifact_record["owner_actor_ref"],
        created_at=now,
    )
    return {
        "render_request_id": render_request_id,
        "render_job": render_job,
        "artifact_version": artifact_version,
        "artifact_files": artifact_files,
        "artifact_links": artifact_links,
        "markdown": markdown,
    }


def build_markdown_artifact_files(
    *,
    artifact_record: dict[str, Any],
    artifact_version: dict[str, Any],
    markdown: str,
) -> list[dict[str, Any]]:
    artifact_file_id = str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-file:{artifact_version['artifact_version_id']}:MD",
        )
    )
    file_name = f"{safe_file_stem(artifact_record['display_title'])}.md"
    return [
        {
            "artifact_file_id": artifact_file_id,
            "artifact_version_id": artifact_version["artifact_version_id"],
            "format": "MD",
            "mime_type": "text/markdown",
            "file_name": file_name,
            "storage_ref": (
                "ae://artifacts/"
                f"{artifact_record['artifact_id']}/versions/"
                f"{artifact_version['artifact_version_id']}/{file_name}"
            ),
            "file_size_bytes": len(markdown.encode("utf-8")),
            "file_hash": sha256_text(markdown),
            "source_version_hash": artifact_version["artifact_content_hash"],
            "created_at": artifact_version["created_at"],
        }
    ]


def build_artifact_links(
    *,
    artifact_file: dict[str, Any],
    created_by_actor_ref: dict[str, str],
    created_at: str,
) -> list[dict[str, Any]]:
    return [
        build_artifact_link(
            artifact_file=artifact_file,
            link_type="preview",
            created_by_actor_ref=created_by_actor_ref,
            created_at=created_at,
        ),
        build_artifact_link(
            artifact_file=artifact_file,
            link_type="download",
            created_by_actor_ref=created_by_actor_ref,
            created_at=created_at,
        ),
    ]


def build_artifact_link(
    *,
    artifact_file: dict[str, Any],
    link_type: str,
    created_by_actor_ref: dict[str, str],
    created_at: str,
) -> dict[str, Any]:
    artifact_file_id = artifact_file["artifact_file_id"]
    return {
        "artifact_link_id": str(
            uuid5(NAMESPACE_URL, f"ae-artifact-link:{artifact_file_id}:{link_type}")
        ),
        "artifact_file_id": artifact_file_id,
        "link_type": link_type,
        "access_policy": "owner_only",
        "link_route": f"/api/v1/artifact-files/{artifact_file_id}/{link_type}",
        "expires_at": None,
        "created_by_actor_ref": dict(created_by_actor_ref),
        "download_count": 0,
        "revoked_at": None,
    }


def resolve_artifact_file_payload(
    store: ArtifactRecordStore,
    *,
    artifact_file_id: str,
    link_type: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    artifact_file = store.get_file(artifact_file_id)
    if artifact_file is None:
        raise ArtifactHandoffError(
            status_code=404,
            error_code="ae.artifact_file_not_found",
            detail=f"Artifact file was not found: {artifact_file_id}",
        )
    artifact_link = store.get_file_link(artifact_file_id, link_type)
    if artifact_link is None:
        raise ArtifactHandoffError(
            status_code=404,
            error_code="ae.artifact_link_not_found",
            detail=f"Artifact {link_type} link was not found: {artifact_file_id}",
        )
    markdown = store.get_rendered_markdown(artifact_file["artifact_version_id"])
    if markdown is None:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.artifact_file_not_ready",
            detail="Artifact file content is not ready.",
        )
    return artifact_file, artifact_link, markdown


def safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    return normalized.strip(".-_")[:64] or "artifact"


def render_markdown_from_structured_draft(structured_draft: dict[str, Any]) -> str:
    lines: list[str] = [f"# {structured_draft['title'].strip()}"]
    summary = optional_text(structured_draft.get("summary"))
    if summary:
        lines.extend(["", summary])

    for section in sorted(
        structured_draft.get("sections", []),
        key=lambda item: int(item.get("ordinal") or 0),
    ):
        heading = optional_text(section.get("heading"))
        if heading:
            lines.extend(["", f"## {heading}"])
        for block in section.get("blocks", []):
            if block.get("block_type") != "paragraph":
                continue
            text_preview = optional_text(block.get("text_preview"))
            if text_preview:
                lines.extend(["", text_preview])

    valid_citations = [
        citation
        for citation in structured_draft.get("citations", [])
        if citation.get("valid") and optional_text(citation.get("citation_label"))
    ]
    if valid_citations:
        lines.extend(["", "## Citations"])
        for citation in valid_citations:
            evidence_id = optional_text(citation.get("evidence_id")) or "unknown"
            retrieval_package_id = (
                optional_text(citation.get("retrieval_package_id")) or "unknown"
            )
            lines.append(
                "- "
                f"{citation['citation_label']} evidence `{evidence_id}` "
                f"from retrieval package `{retrieval_package_id}`."
            )

    return "\n".join(lines).strip() + "\n"


def validate_structured_draft_for_markdown_render(
    artifact_record: dict[str, Any],
    structured_draft: dict[str, Any],
) -> None:
    if artifact_record["artifact_status"] in {"ARCHIVED", "DELETED"}:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.artifact_not_renderable",
            detail="Archived or deleted artifacts cannot be rendered.",
        )
    if structured_draft.get("status") != "VALIDATED":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.citation_validation_required",
            detail="Structured draft must be validated before rendering.",
        )
    if structured_draft.get("validation", {}).get("citation_status") != "VALIDATED":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.citation_validation_required",
            detail="Citation validation must pass before rendering.",
        )
    source_ref = artifact_record["source_refs"][0]
    if structured_draft.get("structured_draft_id") != source_ref["structured_draft_id"]:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.source_draft_hash_mismatch",
            detail="Structured draft ID does not match the artifact source ref.",
        )
    if structured_draft.get("content_hash") != source_ref["structured_draft_content_hash"]:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.source_draft_hash_mismatch",
            detail="Structured draft content hash does not match the artifact source ref.",
        )


def markdown_target_formats_from_payload(
    payload: dict[str, Any],
    artifact_record: dict[str, Any],
) -> list[str]:
    requested_formats = (
        payload["target_formats"] if "target_formats" in payload else ["MD"]
    )
    if not isinstance(requested_formats, list) or not requested_formats:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.target_formats_invalid",
            detail="target_formats must be a non-empty list.",
        )
    normalized: list[str] = []
    for value in requested_formats:
        if value != "MD":
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.render_format_unsupported",
                detail="Slice 0042 supports Markdown rendering only.",
            )
        if value not in normalized:
            normalized.append(value)
    if "MD" not in artifact_record["target_formats"]:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.render_format_not_requested",
            detail="The artifact handoff did not request Markdown output.",
        )
    return normalized


def deterministic_render_job_id(artifact_id: str, render_request_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ae-render-job:{artifact_id}:{render_request_id}"))


def validate_artifact_handoff_record(handoff_record: dict[str, Any]) -> None:
    for field_name in (
        "handoff_schema_version",
        "artifact_handoff_id",
        "artifact_request_id",
        "handoff_status",
        "chat_document_id",
        "interaction_id",
        "actor_claims_ref",
        "workspace_ref",
        "cx_generation_id",
        "structured_draft_id",
        "draft_schema_version",
        "structured_draft_content_hash",
        "citation_claims_hash",
        "validation_result_hash",
        "artifact_intent",
        "target_formats",
        "artifact_title",
        "language",
        "retention_policy_ref",
        "quality_summary",
    ):
        if field_name not in handoff_record:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_handoff_invalid",
                detail=f"Artifact handoff is missing {field_name}.",
            )
    if handoff_record["handoff_status"] != "READY_FOR_RENDERING":
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.artifact_handoff_not_ready",
            detail="Artifact handoff must be READY_FOR_RENDERING.",
        )


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


def artifact_type_from_payload(payload: dict[str, Any]) -> str:
    artifact_type = optional_text(payload.get("artifact_type")) or DEFAULT_ARTIFACT_TYPE
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_type_invalid",
            detail=f"Unsupported artifact type: {artifact_type}",
        )
    return artifact_type


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


def _artifact_handoff_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(ARTIFACT_HANDOFF_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_artifact_handoffs (
            artifact_handoff_id,
            handoff_schema_version,
            artifact_request_id,
            handoff_status,
            trace_id,
            request_id,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            cx_generation_id,
            structured_draft_id,
            draft_schema_version,
            structured_draft_content_hash,
            citation_claims_hash,
            validation_result_hash,
            template_id,
            template_version,
            rendering_template_id,
            artifact_intent,
            target_formats,
            artifact_title,
            language,
            retention_policy_ref,
            actor_claims_ref,
            workspace_ref,
            quality_summary,
            created_at,
            updated_at
        )
        VALUES (
            :artifact_handoff_id,
            :handoff_schema_version,
            :artifact_request_id,
            :handoff_status,
            :trace_id,
            :request_id,
            :tenant_id,
            :workspace_id,
            :owner_user_id,
            :chat_document_id,
            :interaction_id,
            :cx_generation_id,
            :structured_draft_id,
            :draft_schema_version,
            :structured_draft_content_hash,
            :citation_claims_hash,
            :validation_result_hash,
            :template_id,
            :template_version,
            :rendering_template_id,
            :artifact_intent,
            {json_exprs["target_formats"]},
            :artifact_title,
            :language,
            :retention_policy_ref,
            {json_exprs["actor_claims_ref"]},
            {json_exprs["workspace_ref"]},
            {json_exprs["quality_summary"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (artifact_handoff_id) DO UPDATE SET
            artifact_request_id = excluded.artifact_request_id,
            handoff_status = excluded.handoff_status,
            target_formats = excluded.target_formats,
            artifact_title = excluded.artifact_title,
            retention_policy_ref = excluded.retention_policy_ref,
            actor_claims_ref = excluded.actor_claims_ref,
            workspace_ref = excluded.workspace_ref,
            quality_summary = excluded.quality_summary,
            updated_at = excluded.updated_at
    """


def _artifact_handoff_select_sql() -> str:
    return """
        SELECT
            artifact_handoff_id,
            handoff_schema_version,
            artifact_request_id,
            handoff_status,
            trace_id,
            request_id,
            chat_document_id,
            interaction_id,
            actor_claims_ref,
            workspace_ref,
            cx_generation_id,
            structured_draft_id,
            draft_schema_version,
            structured_draft_content_hash,
            citation_claims_hash,
            validation_result_hash,
            template_id,
            template_version,
            rendering_template_id,
            artifact_intent,
            target_formats,
            artifact_title,
            language,
            retention_policy_ref,
            quality_summary,
            created_at,
            updated_at
        FROM ae_artifact_handoffs
        WHERE artifact_handoff_id = :artifact_handoff_id
    """


def _artifact_handoff_params(record: dict[str, Any]) -> dict[str, Any]:
    actor = dict(record["actor_claims_ref"])
    workspace = dict(record["workspace_ref"])
    params = dict(record)
    params["tenant_id"] = actor["tenant_id"]
    params["workspace_id"] = workspace["workspace_id"]
    params["owner_user_id"] = actor["actor_id"]
    return _json_params(params, ARTIFACT_HANDOFF_JSON_FIELDS)


def _artifact_handoff_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "handoff_schema_version": data["handoff_schema_version"],
        "artifact_handoff_id": data["artifact_handoff_id"],
        "artifact_request_id": data["artifact_request_id"],
        "handoff_status": data["handoff_status"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "chat_document_id": data["chat_document_id"],
        "interaction_id": data["interaction_id"],
        "actor_claims_ref": _json_value(data["actor_claims_ref"], {}),
        "workspace_ref": _json_value(data["workspace_ref"], {}),
        "cx_generation_id": data["cx_generation_id"],
        "structured_draft_id": data["structured_draft_id"],
        "draft_schema_version": data["draft_schema_version"],
        "structured_draft_content_hash": data["structured_draft_content_hash"],
        "citation_claims_hash": data["citation_claims_hash"],
        "validation_result_hash": data["validation_result_hash"],
        "template_id": data["template_id"],
        "template_version": data["template_version"],
        "rendering_template_id": data["rendering_template_id"],
        "artifact_intent": data["artifact_intent"],
        "target_formats": _json_value(data["target_formats"], []),
        "artifact_title": data["artifact_title"],
        "language": data["language"],
        "retention_policy_ref": data["retention_policy_ref"],
        "quality_summary": _json_value(data["quality_summary"], {}),
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }


def _persist_artifact_record(session: Session, record: dict[str, Any]) -> None:
    dialect_name = _dialect_name(session)
    session.execute(
        text(_artifact_upsert_sql(dialect_name)),
        _artifact_params(record),
    )
    for source_ref in record.get("source_refs", []):
        session.execute(
            text(_artifact_source_ref_upsert_sql(dialect_name)),
            _artifact_source_ref_params(record["artifact_id"], source_ref),
        )
    for version in record.get("versions", []):
        session.execute(
            text(_artifact_version_upsert_sql(dialect_name)),
            _artifact_version_params(version),
        )
    for render_job in record.get("render_jobs", []):
        session.execute(
            text(_artifact_render_job_upsert_sql()),
            _artifact_render_job_params(render_job),
        )
    for artifact_file in record.get("files", []):
        session.execute(
            text(_artifact_file_upsert_sql()),
            _artifact_file_params(record["artifact_id"], artifact_file),
        )
    for artifact_link in record.get("links", []):
        session.execute(
            text(_artifact_link_upsert_sql(dialect_name)),
            _artifact_link_params(artifact_link),
        )


def _artifact_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(ARTIFACT_RECORD_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_artifacts (
            artifact_id,
            artifact_schema_version,
            artifact_type,
            artifact_status,
            current_version_id,
            artifact_handoff_id,
            artifact_request_id,
            tenant_id,
            workspace_id,
            owner_user_id,
            chat_document_id,
            interaction_id,
            trace_id,
            request_id,
            display_title,
            language,
            artifact_intent,
            target_formats,
            retention_policy_ref,
            owner_actor_ref,
            workspace_ref,
            template_ref,
            handoff_ref,
            created_at,
            updated_at
        )
        VALUES (
            :artifact_id,
            :artifact_schema_version,
            :artifact_type,
            :artifact_status,
            :current_version_id,
            :artifact_handoff_id,
            :artifact_request_id,
            :tenant_id,
            :workspace_id,
            :owner_user_id,
            :chat_document_id,
            :interaction_id,
            :trace_id,
            :request_id,
            :display_title,
            :language,
            :artifact_intent,
            {json_exprs["target_formats"]},
            :retention_policy_ref,
            {json_exprs["owner_actor_ref"]},
            {json_exprs["workspace_ref"]},
            {json_exprs["template_ref"]},
            {json_exprs["handoff_ref"]},
            :created_at,
            :updated_at
        )
        ON CONFLICT (artifact_id) DO UPDATE SET
            artifact_type = excluded.artifact_type,
            artifact_status = excluded.artifact_status,
            current_version_id = excluded.current_version_id,
            display_title = excluded.display_title,
            target_formats = excluded.target_formats,
            retention_policy_ref = excluded.retention_policy_ref,
            owner_actor_ref = excluded.owner_actor_ref,
            workspace_ref = excluded.workspace_ref,
            template_ref = excluded.template_ref,
            handoff_ref = excluded.handoff_ref,
            updated_at = excluded.updated_at
    """


def _artifact_params(record: dict[str, Any]) -> dict[str, Any]:
    owner = dict(record["owner_actor_ref"])
    workspace = dict(record["workspace_ref"])
    handoff_ref = dict(record["handoff_ref"])
    params = dict(record)
    params["artifact_handoff_id"] = handoff_ref["artifact_handoff_id"]
    params["artifact_request_id"] = handoff_ref["artifact_request_id"]
    params["tenant_id"] = owner["tenant_id"]
    params["workspace_id"] = workspace["workspace_id"]
    params["owner_user_id"] = owner["actor_id"]
    return _json_params(params, ARTIFACT_RECORD_JSON_FIELDS)


def _load_artifact_record(session: Session, artifact_id: str) -> dict[str, Any] | None:
    artifact_row = (
        session.execute(
            text(_artifact_select_sql("artifact_id = :artifact_id")),
            {"artifact_id": artifact_id},
        )
        .mappings()
        .first()
    )
    if artifact_row is None:
        return None
    return _artifact_record_from_row(
        artifact_row,
        source_refs=[
            _artifact_source_ref_from_row(row)
            for row in session.execute(
                text(
                    _artifact_source_ref_select_sql(
                        "artifact_id = :artifact_id ORDER BY source_ref_id ASC"
                    )
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .all()
        ],
        versions=[
            _artifact_version_from_row(row)
            for row in session.execute(
                text(
                    _artifact_version_select_sql(
                        "artifact_id = :artifact_id ORDER BY version_no ASC"
                    )
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .all()
        ],
        render_jobs=[
            _artifact_render_job_from_row(row)
            for row in session.execute(
                text(
                    _artifact_render_job_select_sql(
                        "artifact_id = :artifact_id "
                        "ORDER BY created_at ASC, render_job_id ASC"
                    )
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .all()
        ],
        files=[
            _artifact_file_from_row(row)
            for row in session.execute(
                text(
                    _artifact_file_select_sql(
                        "artifact_id = :artifact_id "
                        "ORDER BY created_at ASC, artifact_file_id ASC"
                    )
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .all()
        ],
        links=[
            _artifact_link_from_row(row)
            for row in session.execute(
                text(
                    _artifact_link_select_sql(
                        "artifact_file_id IN ("
                        "SELECT artifact_file_id FROM ae_artifact_files "
                        "WHERE artifact_id = :artifact_id"
                        ") ORDER BY CASE link_type "
                        "WHEN 'preview' THEN 0 ELSE 1 END, artifact_link_id ASC"
                    )
                ),
                {"artifact_id": artifact_id},
            )
            .mappings()
            .all()
        ],
    )


def _artifact_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            artifact_id,
            artifact_schema_version,
            artifact_type,
            artifact_status,
            current_version_id,
            trace_id,
            request_id,
            chat_document_id,
            interaction_id,
            owner_actor_ref,
            workspace_ref,
            display_title,
            language,
            artifact_intent,
            target_formats,
            retention_policy_ref,
            template_ref,
            handoff_ref,
            created_at,
            updated_at
        FROM ae_artifacts
        WHERE {where_clause}
    """


def _artifact_record_from_row(
    row: Any,
    *,
    source_refs: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    render_jobs: list[dict[str, Any]],
    files: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, Any]:
    data = dict(row)
    return {
        "artifact_schema_version": data["artifact_schema_version"],
        "artifact_id": data["artifact_id"],
        "artifact_type": data["artifact_type"],
        "artifact_status": data["artifact_status"],
        "current_version_id": data["current_version_id"],
        "trace_id": data["trace_id"],
        "request_id": data["request_id"],
        "chat_document_id": data["chat_document_id"],
        "interaction_id": data["interaction_id"],
        "owner_actor_ref": _json_value(data["owner_actor_ref"], {}),
        "workspace_ref": _json_value(data["workspace_ref"], {}),
        "display_title": data["display_title"],
        "language": data["language"],
        "artifact_intent": data["artifact_intent"],
        "target_formats": _json_value(data["target_formats"], []),
        "retention_policy_ref": data["retention_policy_ref"],
        "template_ref": _json_value(data["template_ref"], {}),
        "handoff_ref": _json_value(data["handoff_ref"], {}),
        "source_refs": source_refs,
        "versions": versions,
        "render_jobs": render_jobs,
        "files": files,
        "links": links,
        "created_at": _datetime_value(data["created_at"]),
        "updated_at": _datetime_value(data["updated_at"]),
    }


def _artifact_source_ref_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(ARTIFACT_SOURCE_REF_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_artifact_source_refs (
            source_ref_id,
            artifact_id,
            cx_generation_id,
            structured_draft_id,
            draft_schema_version,
            structured_draft_content_hash,
            citation_claims_hash,
            validation_result_hash,
            retrieval_package_id,
            retrieval_package_hash,
            evidence_ref_count,
            source_anchor_count,
            quality_summary,
            created_at
        )
        VALUES (
            :source_ref_id,
            :artifact_id,
            :cx_generation_id,
            :structured_draft_id,
            :draft_schema_version,
            :structured_draft_content_hash,
            :citation_claims_hash,
            :validation_result_hash,
            :retrieval_package_id,
            :retrieval_package_hash,
            :evidence_ref_count,
            :source_anchor_count,
            {json_exprs["quality_summary"]},
            :created_at
        )
        ON CONFLICT (source_ref_id) DO UPDATE SET
            retrieval_package_id = excluded.retrieval_package_id,
            retrieval_package_hash = excluded.retrieval_package_hash,
            evidence_ref_count = excluded.evidence_ref_count,
            source_anchor_count = excluded.source_anchor_count,
            quality_summary = excluded.quality_summary
    """


def _artifact_source_ref_params(
    artifact_id: str,
    source_ref: dict[str, Any],
) -> dict[str, Any]:
    params = dict(source_ref)
    params["artifact_id"] = artifact_id
    params["created_at"] = params.get("created_at") or _utc_now()
    return _json_params(params, ARTIFACT_SOURCE_REF_JSON_FIELDS)


def _artifact_source_ref_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            source_ref_id,
            cx_generation_id,
            structured_draft_id,
            draft_schema_version,
            structured_draft_content_hash,
            citation_claims_hash,
            validation_result_hash,
            retrieval_package_id,
            retrieval_package_hash,
            evidence_ref_count,
            source_anchor_count,
            quality_summary
        FROM ae_artifact_source_refs
        WHERE {where_clause}
    """


def _artifact_source_ref_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "source_ref_id": data["source_ref_id"],
        "cx_generation_id": data["cx_generation_id"],
        "structured_draft_id": data["structured_draft_id"],
        "draft_schema_version": data["draft_schema_version"],
        "structured_draft_content_hash": data["structured_draft_content_hash"],
        "citation_claims_hash": data["citation_claims_hash"],
        "validation_result_hash": data["validation_result_hash"],
        "retrieval_package_id": data["retrieval_package_id"],
        "retrieval_package_hash": data["retrieval_package_hash"],
        "evidence_ref_count": data["evidence_ref_count"],
        "source_anchor_count": data["source_anchor_count"],
        "quality_summary": _json_value(data["quality_summary"], {}),
    }


def _artifact_version_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(ARTIFACT_VERSION_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_artifact_versions (
            artifact_version_id,
            artifact_id,
            version_no,
            version_reason,
            source_generation_id,
            source_structured_draft_id,
            source_content_hash,
            source_citation_claims_hash,
            render_policy_hash,
            artifact_content_hash,
            rendered_formats,
            validation_snapshot,
            created_at
        )
        VALUES (
            :artifact_version_id,
            :artifact_id,
            :version_no,
            :version_reason,
            :source_generation_id,
            :source_structured_draft_id,
            :source_content_hash,
            :source_citation_claims_hash,
            :render_policy_hash,
            :artifact_content_hash,
            {json_exprs["rendered_formats"]},
            {json_exprs["validation_snapshot"]},
            :created_at
        )
        ON CONFLICT (artifact_version_id) DO UPDATE SET
            artifact_content_hash = excluded.artifact_content_hash,
            rendered_formats = excluded.rendered_formats,
            validation_snapshot = excluded.validation_snapshot
    """


def _artifact_version_params(version: dict[str, Any]) -> dict[str, Any]:
    return _json_params(dict(version), ARTIFACT_VERSION_JSON_FIELDS)


def _artifact_version_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            artifact_version_id,
            artifact_id,
            version_no,
            version_reason,
            source_generation_id,
            source_structured_draft_id,
            source_content_hash,
            source_citation_claims_hash,
            render_policy_hash,
            artifact_content_hash,
            rendered_formats,
            validation_snapshot,
            created_at
        FROM ae_artifact_versions
        WHERE {where_clause}
    """


def _artifact_version_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "artifact_version_id": data["artifact_version_id"],
        "artifact_id": data["artifact_id"],
        "version_no": data["version_no"],
        "version_reason": data["version_reason"],
        "source_generation_id": data["source_generation_id"],
        "source_structured_draft_id": data["source_structured_draft_id"],
        "source_content_hash": data["source_content_hash"],
        "source_citation_claims_hash": data["source_citation_claims_hash"],
        "render_policy_hash": data["render_policy_hash"],
        "artifact_content_hash": data["artifact_content_hash"],
        "rendered_formats": _json_value(data["rendered_formats"], []),
        "validation_snapshot": _json_value(data["validation_snapshot"], {}),
        "created_at": _datetime_value(data["created_at"]),
    }


def _artifact_render_job_upsert_sql() -> str:
    return """
        INSERT INTO ae_artifact_render_jobs (
            render_job_id,
            artifact_id,
            artifact_version_id,
            job_status,
            current_stage,
            progress_mode,
            progress_percent,
            retryable,
            failure_code,
            started_at,
            completed_at,
            created_at,
            updated_at
        )
        VALUES (
            :render_job_id,
            :artifact_id,
            :artifact_version_id,
            :job_status,
            :current_stage,
            :progress_mode,
            :progress_percent,
            :retryable,
            :failure_code,
            :started_at,
            :completed_at,
            :created_at,
            :updated_at
        )
        ON CONFLICT (render_job_id) DO UPDATE SET
            artifact_version_id = excluded.artifact_version_id,
            job_status = excluded.job_status,
            current_stage = excluded.current_stage,
            progress_percent = excluded.progress_percent,
            retryable = excluded.retryable,
            failure_code = excluded.failure_code,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
    """


def _artifact_render_job_params(render_job: dict[str, Any]) -> dict[str, Any]:
    params = dict(render_job)
    params["created_at"] = params.get("created_at") or params.get("started_at") or _utc_now()
    params["updated_at"] = params.get("updated_at") or params.get("completed_at") or _utc_now()
    return params


def _artifact_render_job_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            render_job_id,
            artifact_id,
            artifact_version_id,
            job_status,
            current_stage,
            progress_mode,
            progress_percent,
            retryable,
            failure_code,
            started_at,
            completed_at
        FROM ae_artifact_render_jobs
        WHERE {where_clause}
    """


def _artifact_render_job_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "render_job_id": data["render_job_id"],
        "artifact_id": data["artifact_id"],
        "artifact_version_id": data["artifact_version_id"],
        "job_status": data["job_status"],
        "current_stage": data["current_stage"],
        "progress_mode": data["progress_mode"],
        "progress_percent": data["progress_percent"],
        "retryable": bool(data["retryable"]),
        "failure_code": data["failure_code"],
        "started_at": _datetime_value(data["started_at"]),
        "completed_at": _datetime_value(data["completed_at"]),
    }


def _artifact_file_upsert_sql() -> str:
    return """
        INSERT INTO ae_artifact_files (
            artifact_file_id,
            artifact_version_id,
            artifact_id,
            format,
            mime_type,
            file_name,
            storage_ref,
            file_size_bytes,
            file_hash,
            source_version_hash,
            created_at
        )
        VALUES (
            :artifact_file_id,
            :artifact_version_id,
            :artifact_id,
            :format,
            :mime_type,
            :file_name,
            :storage_ref,
            :file_size_bytes,
            :file_hash,
            :source_version_hash,
            :created_at
        )
        ON CONFLICT (artifact_file_id) DO UPDATE SET
            storage_ref = excluded.storage_ref,
            file_size_bytes = excluded.file_size_bytes,
            file_hash = excluded.file_hash,
            source_version_hash = excluded.source_version_hash
    """


def _artifact_file_params(
    artifact_id: str,
    artifact_file: dict[str, Any],
) -> dict[str, Any]:
    params = dict(artifact_file)
    params["artifact_id"] = artifact_id
    return params


def _artifact_file_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            artifact_file_id,
            artifact_version_id,
            format,
            mime_type,
            file_name,
            storage_ref,
            file_size_bytes,
            file_hash,
            source_version_hash,
            created_at
        FROM ae_artifact_files
        WHERE {where_clause}
    """


def _artifact_file_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "artifact_file_id": data["artifact_file_id"],
        "artifact_version_id": data["artifact_version_id"],
        "format": data["format"],
        "mime_type": data["mime_type"],
        "file_name": data["file_name"],
        "storage_ref": data["storage_ref"],
        "file_size_bytes": data["file_size_bytes"],
        "file_hash": data["file_hash"],
        "source_version_hash": data["source_version_hash"],
        "created_at": _datetime_value(data["created_at"]),
    }


def _artifact_link_upsert_sql(dialect_name: str) -> str:
    json_exprs = _json_param_exprs(ARTIFACT_LINK_JSON_FIELDS, dialect_name)
    return f"""
        INSERT INTO ae_artifact_links (
            artifact_link_id,
            artifact_file_id,
            link_type,
            access_policy,
            link_route,
            expires_at,
            created_by_actor_ref,
            download_count,
            revoked_at,
            created_at
        )
        VALUES (
            :artifact_link_id,
            :artifact_file_id,
            :link_type,
            :access_policy,
            :link_route,
            :expires_at,
            {json_exprs["created_by_actor_ref"]},
            :download_count,
            :revoked_at,
            :created_at
        )
        ON CONFLICT (artifact_link_id) DO UPDATE SET
            access_policy = excluded.access_policy,
            link_route = excluded.link_route,
            expires_at = excluded.expires_at,
            created_by_actor_ref = excluded.created_by_actor_ref,
            download_count = excluded.download_count,
            revoked_at = excluded.revoked_at
    """


def _artifact_link_params(artifact_link: dict[str, Any]) -> dict[str, Any]:
    params = dict(artifact_link)
    params["created_at"] = params.get("created_at") or _utc_now()
    return _json_params(params, ARTIFACT_LINK_JSON_FIELDS)


def _artifact_link_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            artifact_link_id,
            artifact_file_id,
            link_type,
            access_policy,
            link_route,
            expires_at,
            created_by_actor_ref,
            download_count,
            revoked_at
        FROM ae_artifact_links
        WHERE {where_clause}
    """


def _artifact_link_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "artifact_link_id": data["artifact_link_id"],
        "artifact_file_id": data["artifact_file_id"],
        "link_type": data["link_type"],
        "access_policy": data["access_policy"],
        "link_route": data["link_route"],
        "expires_at": _nullable_datetime_value(data["expires_at"]),
        "created_by_actor_ref": _json_value(data["created_by_actor_ref"], {}),
        "download_count": data["download_count"],
        "revoked_at": _nullable_datetime_value(data["revoked_at"]),
    }


def _json_param_exprs(
    field_names: tuple[str, ...],
    dialect_name: str,
) -> dict[str, str]:
    return {
        field_name: _json_param_expr(field_name, dialect_name)
        for field_name in field_names
    }


def _json_param_expr(name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _json_params(
    params: dict[str, Any],
    field_names: tuple[str, ...],
) -> dict[str, Any]:
    updated = dict(params)
    for field_name in field_names:
        updated[field_name] = json.dumps(updated[field_name])
    return updated


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _datetime_value(value: Any) -> str:
    if value is None:
        return _utc_now()
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _nullable_datetime_value(value: Any) -> str | None:
    return None if value is None else _datetime_value(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
