from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

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
from nex_ae_api.uploads import DEFAULT_UPLOAD_HANDOFF_STORE, UploadHandoffStore


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
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

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
                for upload_handoff in handoffs.list_by_workspace(workspace_id)
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
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

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
                for upload_handoff in handoffs.list_by_workspace(workspace_id)
            ]
            matches = search_summary_items(items, query=query)
        except DocumentLibraryError as exc:
            return _document_problem_response(request, exc)

        return {
            "workspace_id": workspace_id,
            "query": query.strip(),
            "matches": matches,
        }


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
