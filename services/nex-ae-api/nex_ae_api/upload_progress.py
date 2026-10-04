from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import problem_response, request_id_from_headers, trace_id_from_headers
from nex_ae_api.cx_owner_context import cx_owner_headers
from nex_ae_api.route_auth import authorize_ae_facade_route_request
from nex_ae_api.service_auth import resolve_ae_outbound_service_token
from nex_ae_api.upload_handoff_persistence import UploadHandoffRepositoryError
from nex_ae_api.uploads import (
    DEFAULT_UPLOAD_HANDOFF_STORE,
    UploadHandoffRepository,
)


AE_UPLOAD_PROGRESS_SCHEMA_VERSION = "ae_upload_ingestion_progress.v1"
VECTOR_OUTPUT_PREFIX = "cx.vector_index:"


class CxUploadProgressClient(Protocol):
    def list_ingestion_runs(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_vector_readiness(
        self,
        vector_index_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class UploadProgressError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class HttpCxUploadProgressClient:
    base_url: str = "http://127.0.0.1:8104"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def list_ingestion_runs(
        self,
        document_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        result = self._get_json(
            f"/api/v1/documents/{document_id}/ingestion-runs",
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
            not_found_as_none=False,
        )
        return result

    def get_vector_readiness(
        self,
        vector_index_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/vector-indexes/{vector_index_id}/readiness",
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
            not_found_as_none=True,
        )

    def _get_json(
        self,
        path: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
        not_found_as_none: bool,
    ) -> dict[str, Any] | None:
        token = resolve_ae_outbound_service_token(
            self.service_token,
            audience="nex-cx",
        )
        response = httpx.get(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-ae-api",
                **cx_owner_headers(tenant_id, owner_user_id),
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404 and not_found_as_none:
            return None
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise UploadProgressError(
                status_code=response.status_code,
                error_code=body.get(
                    "error_code",
                    "cx.upload_progress_request_failed",
                ),
                detail=body.get(
                    "detail",
                    "CX upload progress is unavailable.",
                ),
                retryable=body.get("retryable", response.status_code >= 500),
            )
        body = _safe_response_json(response)
        if not body:
            raise _invalid_dependency_response()
        return body


def build_default_cx_upload_progress_client() -> HttpCxUploadProgressClient:
    return HttpCxUploadProgressClient(
        base_url=os.getenv("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
        service_token=os.getenv("NEX_AE_TO_CX_SERVICE_TOKEN"),
    )


def register_upload_progress_routes(
    app: FastAPI,
    *,
    upload_store: UploadHandoffRepository | None = None,
    cx_client: CxUploadProgressClient | None = None,
) -> None:
    handoffs = upload_store or getattr(
        app.state,
        "ae_upload_handoff_store",
        DEFAULT_UPLOAD_HANDOFF_STORE,
    )
    client = cx_client or build_default_cx_upload_progress_client()

    @app.get(
        "/api/v1/uploads/{upload_handoff_id}/progress",
        response_model=None,
    )
    def get_upload_progress(
        upload_handoff_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_context = authorize_ae_facade_route_request(request, authorization)
        if isinstance(auth_context, JSONResponse):
            return auth_context
        owner = auth_context.browser_context
        try:
            handoff = handoffs.get(
                upload_handoff_id,
                tenant_id=owner.tenant_id if owner is not None else None,
                owner_user_id=owner.user_id if owner is not None else None,
            )
        except UploadHandoffRepositoryError as exc:
            return _problem(
                request,
                UploadProgressError(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    detail=exc.detail,
                    retryable=exc.retryable,
                ),
            )
        if handoff is None:
            return _problem(request, _not_found())
        try:
            return load_upload_progress(
                handoff,
                client=client,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except UploadProgressError as exc:
            return _problem(request, exc)


def load_upload_progress(
    handoff: Mapping[str, Any],
    *,
    client: CxUploadProgressClient,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    tenant_id = _required(handoff.get("tenant_id"), "tenant_id")
    owner_user_id = _required(handoff.get("owner_user_id"), "owner_user_id")
    document_ref = handoff.get("cx_document_ref")
    if not isinstance(document_ref, Mapping):
        raise _invalid_handoff("cx_document_ref")
    document_id = _required(document_ref.get("document_id"), "document_id")
    collection = client.list_ingestion_runs(
        document_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    latest = _latest_run(collection, document_id=document_id)
    vector_index_id = _vector_index_id(latest)
    readiness = (
        client.get_vector_readiness(
            vector_index_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        if vector_index_id is not None
        else None
    )
    return build_upload_progress_projection(
        handoff=handoff,
        latest_run=latest,
        vector_index_id=vector_index_id,
        readiness=readiness,
    )


def build_upload_progress_projection(
    *,
    handoff: Mapping[str, Any],
    latest_run: Mapping[str, Any] | None,
    vector_index_id: str | None,
    readiness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    document_ref = handoff.get("cx_document_ref")
    if not isinstance(document_ref, Mapping):
        raise _invalid_handoff("cx_document_ref")
    ingestion = _ingestion_projection(latest_run)
    vector = _vector_projection(vector_index_id, readiness)
    return {
        "progress_schema_version": AE_UPLOAD_PROGRESS_SCHEMA_VERSION,
        "upload_handoff_id": _required(
            handoff.get("upload_handoff_id"),
            "upload_handoff_id",
        ),
        "workspace_id": _required(handoff.get("workspace_id"), "workspace_id"),
        "document_id": _required(document_ref.get("document_id"), "document_id"),
        "status": _journey_status(ingestion, vector),
        "progress_percent": _progress_percent(ingestion),
        "ingestion": ingestion,
        "failure": _failure_projection(latest_run),
        "retry": _retry_projection(latest_run),
        "vector_index": vector,
        "links": {
            "upload_handoff": (
                f"/api/v1/uploads/{handoff['upload_handoff_id']}"
            ),
            "document": f"/api/v1/documents/{document_ref['document_id']}",
            "progress": (
                f"/api/v1/uploads/{handoff['upload_handoff_id']}/progress"
            ),
        },
        "metadata": {
            "owner_scoped": True,
            "raw_source_included": False,
            "markdown_included": False,
            "chunk_text_included": False,
            "embedding_vector_included": False,
            "provider_credentials_included": False,
        },
    }


def _latest_run(
    collection: Mapping[str, Any],
    *,
    document_id: str,
) -> dict[str, Any] | None:
    if collection.get("document_id") != document_id:
        raise _invalid_dependency_response()
    runs = collection.get("runs")
    if not isinstance(runs, list):
        raise _invalid_dependency_response()
    if not runs:
        return None
    latest = runs[0]
    if not isinstance(latest, Mapping) or latest.get("document_id") != document_id:
        raise _invalid_dependency_response()
    return dict(latest)


def _vector_index_id(latest_run: Mapping[str, Any] | None) -> str | None:
    if latest_run is None:
        return None
    steps = latest_run.get("steps")
    if not isinstance(steps, list):
        raise _invalid_dependency_response()
    for step in steps:
        if not isinstance(step, Mapping) or step.get("step_id") != "embedding_index":
            continue
        output_ref = step.get("output_ref")
        if output_ref is None:
            return None
        if not isinstance(output_ref, str) or not output_ref.startswith(
            VECTOR_OUTPUT_PREFIX
        ):
            raise _invalid_dependency_response()
        return _required(output_ref.removeprefix(VECTOR_OUTPUT_PREFIX), "vector_index_id")
    return None


def _ingestion_projection(latest_run: Mapping[str, Any] | None) -> dict[str, Any]:
    if latest_run is None:
        return {
            "available": False,
            "run_id": None,
            "status": "QUEUED",
            "current_step": None,
            "step_total": 0,
            "step_completed": 0,
            "attempt_count": 0,
            "max_attempts": 0,
            "checkpoint_version": 0,
            "updated_at": None,
        }
    return {
        "available": True,
        "run_id": _required(latest_run.get("run_id"), "run_id"),
        "status": _required(latest_run.get("status"), "status"),
        "current_step": latest_run.get("current_step"),
        "step_total": _non_negative(latest_run.get("step_total")),
        "step_completed": _non_negative(latest_run.get("step_completed")),
        "attempt_count": _non_negative(latest_run.get("attempt_count")),
        "max_attempts": _non_negative(latest_run.get("max_attempts")),
        "checkpoint_version": _non_negative(
            latest_run.get("checkpoint_version")
        ),
        "updated_at": latest_run.get("updated_at"),
    }


def _failure_projection(
    latest_run: Mapping[str, Any] | None,
) -> dict[str, Any]:
    error = latest_run.get("last_error") if latest_run is not None else None
    if not isinstance(error, Mapping):
        return {
            "present": False,
            "error_code": None,
            "failed_step": None,
            "retryable": False,
            "failed_at": None,
        }
    return {
        "present": True,
        "error_code": _required(error.get("error_code"), "error_code"),
        "failed_step": _required(error.get("failed_step"), "failed_step"),
        "retryable": error.get("retryable") is True,
        "failed_at": error.get("failed_at"),
    }


def _retry_projection(latest_run: Mapping[str, Any] | None) -> dict[str, Any]:
    if latest_run is None:
        return {
            "available": False,
            "retry_at": None,
            "attempts_remaining": 0,
        }
    attempts = _non_negative(latest_run.get("attempt_count"))
    maximum = _non_negative(latest_run.get("max_attempts"))
    error = latest_run.get("last_error")
    retryable = isinstance(error, Mapping) and error.get("retryable") is True
    return {
        "available": latest_run.get("status") == "WAITING_RETRY" and retryable,
        "retry_at": latest_run.get("retry_at"),
        "attempts_remaining": max(0, maximum - attempts),
    }


def _vector_projection(
    vector_index_id: str | None,
    readiness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if vector_index_id is None:
        return {
            "available": False,
            "vector_index_id": None,
            "status": "MISSING",
            "freshness_status": "MISSING",
            "freshness_reason": "INDEX_NOT_PUBLISHED",
            "retrieval_usable": False,
            "rebuild_required": False,
            "expected_vector_count": 0,
            "actual_vector_count": 0,
        }
    if readiness is None:
        return {
            "available": False,
            "vector_index_id": vector_index_id,
            "status": "MISSING",
            "freshness_status": "MISSING",
            "freshness_reason": "INDEX_NOT_FOUND",
            "retrieval_usable": False,
            "rebuild_required": True,
            "expected_vector_count": 0,
            "actual_vector_count": 0,
        }
    if readiness.get("vector_index_id") != vector_index_id:
        raise _invalid_dependency_response()
    return {
        "available": True,
        "vector_index_id": vector_index_id,
        "status": _required(readiness.get("status"), "vector_status"),
        "freshness_status": _required(
            readiness.get("freshness_status"),
            "freshness_status",
        ),
        "freshness_reason": readiness.get("freshness_reason"),
        "retrieval_usable": readiness.get("retrieval_usable") is True,
        "rebuild_required": readiness.get("rebuild_required") is True,
        "expected_vector_count": _non_negative(
            readiness.get("expected_vector_count")
        ),
        "actual_vector_count": _non_negative(
            readiness.get("actual_vector_count")
        ),
    }


def _journey_status(
    ingestion: Mapping[str, Any],
    vector: Mapping[str, Any],
) -> str:
    status = ingestion["status"]
    if status == "SUCCEEDED":
        return "INDEX_READY" if vector["retrieval_usable"] is True else "INDEX_NOT_READY"
    return {
        "RUNNING": "PROCESSING",
        "WAITING_RETRY": "WAITING_RETRY",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }.get(str(status), "QUEUED")


def _progress_percent(ingestion: Mapping[str, Any]) -> int:
    if ingestion["status"] == "SUCCEEDED":
        return 100
    total = int(ingestion["step_total"])
    completed = int(ingestion["step_completed"])
    return min(99, (completed * 100) // total) if total else 0


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UploadProgressError(
            status_code=502,
            error_code="ae.upload_progress_dependency_invalid",
            detail=f"CX upload progress metadata is invalid: {field}.",
            retryable=True,
        )
    return value.strip()


def _non_negative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_dependency_response()
    return value


def _invalid_dependency_response() -> UploadProgressError:
    return UploadProgressError(
        status_code=502,
        error_code="ae.upload_progress_dependency_invalid",
        detail="CX upload progress response is invalid.",
        retryable=True,
    )


def _invalid_handoff(field: str) -> UploadProgressError:
    return UploadProgressError(
        status_code=409,
        error_code="ae.upload_progress_handoff_invalid",
        detail=f"AE upload handoff metadata is invalid: {field}.",
    )


def _not_found() -> UploadProgressError:
    return UploadProgressError(
        status_code=404,
        error_code="ae.upload_progress_not_found",
        detail="Upload progress was not found or is not visible to the owner.",
    )


def _problem(request: Request, exc: UploadProgressError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Upload progress unavailable",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/upload-progress-unavailable",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
