from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_ae_api.auth_guard import BrowserUserAuthContext
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.uploads import DEFAULT_UPLOAD_HANDOFF_STORE, UploadHandoffStore


AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION = "ae_document_detail_projection.v1"
AE_DOCUMENT_DETAIL_ITEM_SCHEMA_VERSION = "ae_document_detail_item.v1"


class CxDocumentLibraryClient(Protocol):
    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...

    def get_summary(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        ...

    def get_summary_embedding(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class HttpCxDocumentLibraryClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._get_json(
            f"/api/v1/documents/{document_id}",
            params=owner_scope_query_params(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            ),
            request_id=request_id,
            trace_id=trace_id,
            not_found_as_none=False,
        )

    def get_summary(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/documents/{document_id}/summary",
            request_id=request_id,
            trace_id=trace_id,
            not_found_as_none=True,
        )

    def get_summary_embedding(
        self,
        document_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/documents/{document_id}/summary-embedding",
            request_id=request_id,
            trace_id=trace_id,
            not_found_as_none=True,
        )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        request_id: str,
        trace_id: str,
        not_found_as_none: bool,
    ) -> dict[str, Any] | None:
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
            params=params,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404 and not_found_as_none:
            return None
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise DocumentLibraryError(
                status_code=response.status_code,
                error_code=body.get("error_code", "cx.document_library_request_failed"),
                detail=body.get("detail", "CX document library request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass(frozen=True)
class DocumentLibraryError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def build_default_cx_document_library_client() -> HttpCxDocumentLibraryClient:
    return HttpCxDocumentLibraryClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_document_library_routes(
    app: FastAPI,
    *,
    upload_store: UploadHandoffStore | None = None,
    cx_client: CxDocumentLibraryClient | None = None,
) -> None:
    handoffs = upload_store or DEFAULT_UPLOAD_HANDOFF_STORE
    client = cx_client or build_default_cx_document_library_client()

    @app.get("/api/v1/workspaces/{workspace_id}/documents", response_model=None)
    def list_workspace_documents(
        workspace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            items = [
                build_document_library_item_from_cx(
                    client=client,
                    upload_handoff=upload_handoff,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                for upload_handoff in visible_upload_handoffs(
                    handoffs.list_by_workspace(workspace_id),
                    browser_context=auth_context.browser_context,
                )
            ]
        except DocumentLibraryError as exc:
            return _document_problem_response(request, exc)

        return {
            "workspace_id": workspace_id,
            "documents": items,
        }

    @app.get("/api/v1/documents/summary-search", response_model=None)
    def search_document_summaries(
        request: Request,
        authorization: str | None = Header(default=None),
        workspace_id: str = Query(min_length=1),
        query: str = Query(min_length=1),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            items = [
                build_document_library_item_from_cx(
                    client=client,
                    upload_handoff=upload_handoff,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                for upload_handoff in visible_upload_handoffs(
                    handoffs.list_by_workspace(workspace_id),
                    browser_context=auth_context.browser_context,
                )
            ]
            matches = search_summary_items(items, query=query)
        except DocumentLibraryError as exc:
            return _document_problem_response(request, exc)

        return {
            "workspace_id": workspace_id,
            "query": query.strip(),
            "matches": matches,
        }

    @app.get("/api/v1/documents/{document_id}", response_model=None)
    def get_document_detail(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context

        upload_handoff = handoffs.get_by_document_id(document_id)
        if upload_handoff is None:
            return _document_problem_response(
                request,
                DocumentLibraryError(
                    status_code=404,
                    error_code="ae.document_not_found",
                    detail=(
                        "Document detail was not found or is not visible "
                        "in the AE upload handoff scope."
                    ),
                ),
            )

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            ensure_document_handoff_visible_to_browser(
                upload_handoff,
                browser_context=auth_context.browser_context,
            )
            return build_document_detail_from_cx(
                client=client,
                upload_handoff=upload_handoff,
                request_id=request_id,
                trace_id=trace_id,
            )
        except DocumentLibraryError as exc:
            return _document_problem_response(request, exc)


def build_document_library_item_from_cx(
    *,
    client: CxDocumentLibraryClient,
    upload_handoff: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    owner_scope = owner_scope_from_handoff(upload_handoff)
    document_id = upload_handoff["cx_document_ref"]["document_id"]
    return build_document_library_item(
        upload_handoff=upload_handoff,
        cx_document=client.get_document(
            document_id,
            tenant_id=owner_scope["tenant_id"],
            owner_user_id=owner_scope["owner_user_id"],
            request_id=request_id,
            trace_id=trace_id,
        ),
        summary=client.get_summary(
            document_id,
            request_id=request_id,
            trace_id=trace_id,
        ),
        summary_embedding=client.get_summary_embedding(
            document_id,
            request_id=request_id,
            trace_id=trace_id,
        ),
    )


def build_document_detail_from_cx(
    *,
    client: CxDocumentLibraryClient,
    upload_handoff: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    owner_scope = owner_scope_from_handoff(upload_handoff)
    document_id = upload_handoff["cx_document_ref"]["document_id"]
    cx_document = client.get_document(
        document_id,
        tenant_id=owner_scope["tenant_id"],
        owner_user_id=owner_scope["owner_user_id"],
        request_id=request_id,
        trace_id=trace_id,
    )
    return build_document_detail_projection(
        upload_handoff=upload_handoff,
        cx_document=cx_document,
    )


def visible_upload_handoffs(
    upload_handoffs: list[dict[str, Any]],
    *,
    browser_context: BrowserUserAuthContext | None,
) -> list[dict[str, Any]]:
    if browser_context is None:
        return upload_handoffs
    return [
        upload_handoff
        for upload_handoff in upload_handoffs
        if handoff_matches_browser_context(upload_handoff, browser_context)
    ]


def ensure_document_handoff_visible_to_browser(
    upload_handoff: dict[str, Any],
    *,
    browser_context: BrowserUserAuthContext | None,
) -> None:
    if browser_context is None:
        return
    if not handoff_matches_browser_context(upload_handoff, browser_context):
        raise DocumentLibraryError(
            status_code=403,
            error_code="ae.browser_owner_scope_mismatch",
            detail="Document owner scope must match the authenticated browser claim.",
            retryable=False,
        )


def handoff_matches_browser_context(
    upload_handoff: dict[str, Any],
    browser_context: BrowserUserAuthContext,
) -> bool:
    try:
        owner_scope = owner_scope_from_handoff(upload_handoff)
    except DocumentLibraryError:
        return False
    return (
        owner_scope["tenant_id"] == browser_context.tenant_id
        and owner_scope["owner_user_id"] == browser_context.user_id
    )


def build_document_detail_projection(
    *,
    upload_handoff: dict[str, Any],
    cx_document: dict[str, Any],
) -> dict[str, Any]:
    document_ref = upload_handoff["cx_document_ref"]
    cx_detail = cx_document_detail_item(cx_document)
    cx_summary = _mapping_copy(cx_detail.get("summary"))
    cx_summary_embedding = _mapping_copy(cx_detail.get("summary_embedding"))
    processing = _project_processing(cx_detail.get("processing"))
    source_lineage = _project_source_lineage(
        cx_detail.get("source_lineage"),
        upload_handoff=upload_handoff,
    )
    return {
        "projection_schema_version": AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
        "service_id": "nex-ae-api",
        "workspace_id": upload_handoff["workspace_id"],
        "tenant_id": upload_handoff["tenant_id"],
        "owner_user_id": upload_handoff["owner_user_id"],
        "document": {
            "document_detail_schema_version": AE_DOCUMENT_DETAIL_ITEM_SCHEMA_VERSION,
            "document_id": document_ref["document_id"],
            "upload_handoff_id": upload_handoff["upload_handoff_id"],
            "filename": upload_handoff["source"]["filename"],
            "content_type": upload_handoff["source"]["content_type"],
            "size_bytes": upload_handoff["source"]["size_bytes"],
            "source_sha256": upload_handoff["source"]["source_sha256"],
            "status": {
                "dedupe_status": document_ref["dedupe_status"],
                "extraction_status": extraction_status(cx_document, document_ref),
                "markdown_available": markdown_available(cx_document, document_ref),
                "summary_status": _cx_status(cx_summary),
                "summary_embedding_status": _cx_status(cx_summary_embedding),
                "processing_status": processing["status"],
            },
            "summary": _project_detail_summary(cx_summary, cx_summary_embedding),
            "processing": processing,
            "source_lineage": source_lineage,
            "links": {
                "upload_handoff": (
                    f"/api/v1/uploads/{upload_handoff['upload_handoff_id']}"
                ),
                "cx_document": f"/api/v1/documents/{document_ref['document_id']}",
                "cx_summary": f"/api/v1/documents/{document_ref['document_id']}/summary",
                "cx_summary_embedding": (
                    f"/api/v1/documents/{document_ref['document_id']}"
                    "/summary-embedding"
                ),
                "cx_processing": (
                    f"/api/v1/documents/{document_ref['document_id']}/processing"
                ),
            },
            "metadata": {
                "raw_source_stored_in_ae": False,
                "raw_summary_stored_in_ae": False,
                "embedding_vector_stored_in_ae": False,
                "cx_storage_redacted": True,
            },
        },
        "cx": {
            "projection_schema_version": cx_document.get("projection_schema_version"),
            "document_detail_schema_version": cx_detail.get(
                "document_detail_schema_version"
            ),
            "source_kind": _mapping_copy(cx_document.get("source")).get("source_kind"),
            "owner_scoped": _mapping_copy(cx_document.get("metadata")).get(
                "owner_scoped"
            )
            is True,
            "not_found_and_not_authorized_collapsed": _mapping_copy(
                cx_document.get("metadata")
            ).get("not_found_and_not_authorized_collapsed")
            is True,
        },
        "metadata": {
            "raw_source_stored_in_ae": False,
            "raw_summary_stored_in_ae": False,
            "embedding_vector_stored_in_ae": False,
            "cx_storage_redacted": True,
            "cx_detail_passthrough": False,
        },
    }


def cx_document_detail_item(cx_document: dict[str, Any]) -> dict[str, Any]:
    document = cx_document.get("document")
    if isinstance(document, dict):
        return document
    return cx_document


def owner_scope_from_handoff(upload_handoff: dict[str, Any]) -> dict[str, str]:
    return owner_scope_query_params(
        tenant_id=upload_handoff.get("tenant_id"),
        owner_user_id=upload_handoff.get("owner_user_id"),
    )


def owner_scope_query_params(
    *,
    tenant_id: object,
    owner_user_id: object,
) -> dict[str, str]:
    return {
        "tenant_id": _required_owner_scope_text(tenant_id, field_name="tenant_id"),
        "owner_user_id": _required_owner_scope_text(
            owner_user_id,
            field_name="owner_user_id",
        ),
    }


def _project_detail_summary(
    summary: dict[str, Any],
    summary_embedding: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary_available": summary.get("available") is True,
        "summary_text_sha256": summary.get("summary_text_sha256"),
        "summary_preview": summary.get("summary_preview"),
        "summary_char_count": _non_negative_int(summary.get("summary_char_count")),
        "summary_embedding_available": summary_embedding.get("available") is True,
        "summary_embedding_model": summary_embedding.get("model_profile_id"),
        "summary_embedding_dimension": _positive_int_or_none(
            summary_embedding.get("vector_dimension")
        ),
    }


def _project_processing(processing: object) -> dict[str, Any]:
    payload = _mapping_copy(processing)
    status = payload.get("status")
    return {
        "available": payload.get("available") is True,
        "latest_pipeline_run_id": payload.get("latest_pipeline_run_id"),
        "status": status if isinstance(status, str) else "NOT_READY",
        "step_total": _non_negative_int(payload.get("step_total")),
        "step_failed": _non_negative_int(payload.get("step_failed")),
        "updated_at": payload.get("updated_at"),
    }


def _project_source_lineage(
    source_lineage: object,
    *,
    upload_handoff: dict[str, Any],
) -> dict[str, Any]:
    payload = _mapping_copy(source_lineage)
    return {
        "source_file_id": payload.get("source_file_id"),
        "source_sha256": payload.get(
            "source_sha256",
            upload_handoff["source"]["source_sha256"],
        ),
        "content_type": payload.get(
            "content_type",
            upload_handoff["source"]["content_type"],
        ),
        "size_bytes": _non_negative_int(
            payload.get("size_bytes", upload_handoff["source"]["size_bytes"])
        ),
        "storage_key_included": False,
        "storage_uri_included": False,
        "storage_path_included": False,
    }


def _cx_status(payload: dict[str, Any]) -> str:
    if payload.get("available") is False:
        return "NOT_READY"
    status = payload.get("status")
    if isinstance(status, str) and status:
        return status
    return "NOT_READY"


def _mapping_copy(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def build_document_library_item(
    *,
    upload_handoff: dict[str, Any],
    cx_document: dict[str, Any],
    summary: dict[str, Any] | None,
    summary_embedding: dict[str, Any] | None,
) -> dict[str, Any]:
    document_ref = upload_handoff["cx_document_ref"]
    return {
        "document_library_schema_version": "ae_document_library_item.v1",
        "workspace_id": upload_handoff["workspace_id"],
        "tenant_id": upload_handoff["tenant_id"],
        "owner_user_id": upload_handoff["owner_user_id"],
        "document_id": document_ref["document_id"],
        "upload_handoff_id": upload_handoff["upload_handoff_id"],
        "filename": upload_handoff["source"]["filename"],
        "content_type": upload_handoff["source"]["content_type"],
        "size_bytes": upload_handoff["source"]["size_bytes"],
        "source_sha256": upload_handoff["source"]["source_sha256"],
        "status": {
            "dedupe_status": document_ref["dedupe_status"],
            "extraction_status": extraction_status(cx_document, document_ref),
            "markdown_available": markdown_available(cx_document, document_ref),
            "summary_status": summary["status"] if summary else "NOT_READY",
            "summary_embedding_status": summary_embedding["status"]
            if summary_embedding
            else "NOT_READY",
        },
        "summary": build_summary_projection(summary, summary_embedding),
        "links": {
            "upload_handoff": f"/api/v1/uploads/{upload_handoff['upload_handoff_id']}",
            "cx_document": f"/api/v1/documents/{document_ref['document_id']}",
            "cx_summary": f"/api/v1/documents/{document_ref['document_id']}/summary",
            "cx_summary_embedding": (
                f"/api/v1/documents/{document_ref['document_id']}/summary-embedding"
            ),
        },
        "metadata": {
            "raw_source_stored_in_ae": False,
            "raw_summary_stored_in_ae": False,
            "cx_storage_redacted": True,
        },
    }


def build_summary_projection(
    summary: dict[str, Any] | None,
    summary_embedding: dict[str, Any] | None,
) -> dict[str, Any]:
    if summary is None:
        return {
            "summary_available": False,
            "summary_text_sha256": None,
            "summary_preview": None,
            "summary_char_count": 0,
            "summary_embedding_model": None,
            "summary_embedding_dimension": None,
        }

    return {
        "summary_available": True,
        "summary_text_sha256": summary["summary_text_sha256"],
        "summary_preview": summary["summary_preview"],
        "summary_char_count": summary["summary_char_count"],
        "summary_embedding_model": summary_embedding["model_profile_id"]
        if summary_embedding
        else None,
        "summary_embedding_dimension": summary_embedding["dimension"]
        if summary_embedding
        else None,
    }


def search_summary_items(
    items: list[dict[str, Any]],
    *,
    query: str,
) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return []
    matches = []
    for item in items:
        haystack = " ".join(
            [
                item["filename"],
                item["summary"]["summary_preview"] or "",
                item["status"]["summary_status"],
            ]
        ).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            matches.append({"score": score, "document": item})
    return sorted(matches, key=lambda match: (-match["score"], match["document"]["filename"]))


def extraction_status(cx_document: dict[str, Any], document_ref: dict[str, Any]) -> str:
    extraction = cx_document.get("extraction")
    if not isinstance(extraction, dict):
        document = cx_document.get("document")
        if isinstance(document, dict):
            extraction = document.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("status"), str):
        return extraction["status"]
    return document_ref["extraction_status"]


def markdown_available(cx_document: dict[str, Any], document_ref: dict[str, Any]) -> bool:
    extraction = cx_document.get("extraction")
    if not isinstance(extraction, dict):
        document = cx_document.get("document")
        if isinstance(document, dict):
            extraction = document.get("extraction")
    if isinstance(extraction, dict) and isinstance(extraction.get("markdown_available"), bool):
        return extraction["markdown_available"]
    return bool(document_ref["markdown_available"])


def _required_owner_scope_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentLibraryError(
            status_code=422,
            error_code="ae.document_owner_scope_invalid",
            detail=f"{field_name} must be a non-empty string.",
            retryable=False,
        )
    return value.strip()


def _document_problem_response(
    request: Request,
    exc: DocumentLibraryError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Document library request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/document-library-request-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}
