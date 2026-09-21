from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    OperationalEventEmitter,
    build_subject_ref,
    operational_event_emitter_from_app,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
)
from nex_cx.authorization import (
    CX_SUBJECT_HEADER,
    CX_TENANT_HEADER,
    authorize_cx_owner_request,
)
from nex_cx.access_context import CxAccessContext
from nex_cx.pgvector_store import PgVectorCxVectorStore
from nex_cx.private_content import CxPrivateContentError
from nex_cx.vector_index_freshness import (
    VectorIndexContractError,
    assess_vector_index_freshness,
)
from nex_cx.vector_index_reconciliation import reconcile_vector_index
from nex_cx.vector_index_repository import (
    VectorIndexRepository,
    VectorIndexRepositoryError,
)


CX_VECTOR_INDEX_READINESS_SCHEMA_VERSION = "cx_vector_index_readiness.v1"
CX_VECTOR_INDEX_RECONCILED_EVENT = "cx.vector_index.reconciled"


class VectorIndexOperationsError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        detail: str,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable


def register_vector_index_operations_routes(
    app: FastAPI,
    *,
    repository: VectorIndexRepository | None,
    vector_store: PgVectorCxVectorStore | None,
    event_emitter: OperationalEventEmitter | None = None,
) -> None:
    emitter = event_emitter or operational_event_emitter_from_app(
        app,
        service_id="nex-cx",
    )

    @app.get(
        "/api/v1/vector-indexes/{vector_index_id}/readiness",
        response_model=None,
    )
    def get_vector_index_readiness_route(
        vector_index_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        try:
            return get_vector_index_readiness(
                access_context=access_context,
                vector_index_id=vector_index_id,
                repository=_required_repository(repository),
                vector_store=_required_vector_store(vector_store),
            )
        except VectorIndexOperationsError as exc:
            return _operations_problem_response(request, exc)

    @app.post(
        "/api/v1/vector-indexes/{vector_index_id}/readiness/reconcile",
        response_model=None,
    )
    def reconcile_vector_index_readiness_route(
        vector_index_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        cx_tenant_id: str | None = Header(default=None, alias=CX_TENANT_HEADER),
        cx_subject_id: str | None = Header(default=None, alias=CX_SUBJECT_HEADER),
    ):
        access_context = authorize_cx_owner_request(
            request,
            authorization,
            tenant_id=cx_tenant_id,
            subject_id=cx_subject_id,
        )
        if isinstance(access_context, JSONResponse):
            return access_context
        try:
            result = reconcile_vector_index_readiness(
                access_context=access_context,
                vector_index_id=vector_index_id,
                source_snapshot=payload.get("source_snapshot"),
                embedding_profile=payload.get("embedding_profile"),
                observed_at=payload.get("observed_at"),
                repository=_required_repository(repository),
                vector_store=_required_vector_store(vector_store),
            )
        except VectorIndexOperationsError as exc:
            return _operations_problem_response(request, exc)
        event_result = emitter.safe_emit(
            event_type=CX_VECTOR_INDEX_RECONCILED_EVENT,
            severity="WARNING" if result["rebuild_required"] else "INFO",
            message="CX vector index readiness was reconciled.",
            trace_id=trace_id_from_headers(request),
            request_id=request_id_from_headers(request),
            subject_ref=build_subject_ref("cx.vector_index", vector_index_id),
            details={
                "action": result["action"],
                "status": result["status"],
                "status_reason": result["status_reason"],
                "checkpoint_version": result["checkpoint_version"],
                "retrieval_usable": result["retrieval_usable"],
                "rebuild_required": result["rebuild_required"],
                "vector_count": result["actual_vector_count"],
            },
            event_id=_reconciliation_event_id(
                vector_index_id=vector_index_id,
                checkpoint_version=result["checkpoint_version"],
                action=result["action"],
            ),
        )
        return {**result, "observability": event_result.to_summary()}


def get_vector_index_readiness(
    *,
    access_context: CxAccessContext,
    vector_index_id: str,
    repository: VectorIndexRepository,
    vector_store: PgVectorCxVectorStore,
) -> dict[str, Any]:
    manifest = _owner_manifest(access_context, vector_index_id, repository)
    try:
        snapshot = vector_store.bind_index(manifest).payload_snapshot(
            access_context=access_context
        )
        freshness = assess_vector_index_freshness(
            manifest,
            source_snapshot=manifest["source_snapshot"],
            embedding_profile=manifest["embedding_profile"],
            payload_count=snapshot["payload_count"],
            payload_fingerprint=snapshot["payload_fingerprint"],
        )
    except (CxPrivateContentError, VectorIndexContractError) as exc:
        raise _dependency_error(exc) from exc
    return _readiness_projection(
        manifest=manifest,
        freshness=freshness,
        actual_vector_count=snapshot["payload_count"],
        action="NONE",
    )


def reconcile_vector_index_readiness(
    *,
    access_context: CxAccessContext,
    vector_index_id: str,
    source_snapshot: Mapping[str, Any] | None,
    embedding_profile: Mapping[str, Any] | None,
    observed_at: str | None,
    repository: VectorIndexRepository,
    vector_store: PgVectorCxVectorStore,
) -> dict[str, Any]:
    if not isinstance(source_snapshot, Mapping) or not isinstance(
        embedding_profile, Mapping
    ) or not isinstance(observed_at, str):
        raise VectorIndexOperationsError(
            error_code="CX_VECTOR_RECONCILIATION_REQUEST_INVALID",
            detail="Source snapshot, embedding profile, and observed_at are required.",
            status_code=422,
        )
    manifest = _owner_manifest(access_context, vector_index_id, repository)
    try:
        snapshot = vector_store.bind_index(manifest).payload_snapshot(
            access_context=access_context
        )
        result = reconcile_vector_index(
            manifest=manifest,
            source_snapshot=source_snapshot,
            embedding_profile=embedding_profile,
            payload_count=snapshot["payload_count"],
            payload_fingerprint=snapshot["payload_fingerprint"],
            repository=repository,
            observed_at=observed_at,
        )
    except (CxPrivateContentError, VectorIndexContractError) as exc:
        raise _dependency_error(exc) from exc
    except VectorIndexRepositoryError as exc:
        raise _repository_error(exc) from exc
    return _readiness_projection(
        manifest=result["manifest"],
        freshness=result["freshness"],
        actual_vector_count=snapshot["payload_count"],
        action=result["action"],
    )


def _owner_manifest(
    access_context: CxAccessContext,
    vector_index_id: str,
    repository: VectorIndexRepository,
) -> dict[str, Any]:
    try:
        manifest = repository.get(
            vector_index_id,
            tenant_id=access_context.tenant_id,
            owner_subject_id=access_context.subject_id,
        )
    except VectorIndexRepositoryError as exc:
        raise _repository_error(exc) from exc
    if manifest is None:
        raise VectorIndexOperationsError(
            error_code="CX_VECTOR_INDEX_NOT_FOUND",
            detail="Vector index was not found for the owner scope.",
            status_code=404,
        )
    return manifest


def _readiness_projection(
    *,
    manifest: Mapping[str, Any],
    freshness: Mapping[str, Any],
    actual_vector_count: int,
    action: str,
) -> dict[str, Any]:
    return {
        "readiness_schema_version": CX_VECTOR_INDEX_READINESS_SCHEMA_VERSION,
        "vector_index_id": manifest["vector_index_id"],
        "content_object_id": manifest["content_object_id"],
        "status": manifest["status"],
        "status_reason": manifest.get("status_reason"),
        "freshness_status": freshness["status"],
        "freshness_reason": freshness.get("reason"),
        "checkpoint_version": manifest["checkpoint_version"],
        "expected_vector_count": manifest["payload_count"],
        "actual_vector_count": actual_vector_count,
        "retrieval_usable": freshness["retrieval_usable"],
        "rebuild_required": freshness["rebuild_required"],
        "action": action,
    }


def _required_repository(
    repository: VectorIndexRepository | None,
) -> VectorIndexRepository:
    if repository is None:
        raise _unavailable()
    return repository


def _required_vector_store(
    vector_store: PgVectorCxVectorStore | None,
) -> PgVectorCxVectorStore:
    if vector_store is None:
        raise _unavailable()
    return vector_store


def _repository_error(exc: VectorIndexRepositoryError) -> VectorIndexOperationsError:
    return VectorIndexOperationsError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=503 if exc.retryable else 409,
        retryable=exc.retryable,
    )


def _dependency_error(exc: Exception) -> VectorIndexOperationsError:
    return VectorIndexOperationsError(
        error_code=getattr(exc, "error_code", "CX_VECTOR_READINESS_FAILED"),
        detail=getattr(exc, "detail", "Vector readiness evaluation failed."),
        status_code=getattr(exc, "status_code", 422),
        retryable=getattr(exc, "retryable", False),
    )


def _unavailable() -> VectorIndexOperationsError:
    return VectorIndexOperationsError(
        error_code="CX_VECTOR_OPERATIONS_UNAVAILABLE",
        detail="Vector index operations require PostgreSQL persistence.",
        status_code=503,
        retryable=True,
    )


def _reconciliation_event_id(
    *,
    vector_index_id: str,
    checkpoint_version: int,
    action: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-vector-reconciliation:{vector_index_id}:{checkpoint_version}:{action}",
        )
    )


def _operations_problem_response(
    request: Request,
    exc: VectorIndexOperationsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Vector index operation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/vector-index-operation-failed",
    )
