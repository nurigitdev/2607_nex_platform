from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.operations import (
    AG_OPERATIONS_SOURCE_MODE_ENV,
    AG_OPERATIONS_SOURCE_PROFILE_ENV,
    AG_OPERATIONS_SOURCE_SERVICES_ENV,
    AgOperationsSourceRuntime,
    OperationQueryOptions,
    OperationsQueryError,
    ag_operations_source_database_env,
    build_operation_query_options,
    normalize_ag_operations_source_mode,
    normalize_ag_operations_source_profile,
    select_ag_operations_source_service_ids,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    build_engine,
    build_session_factory,
    database_pool_settings,
    problem_response,
    redact_database_url,
    required_database_url,
    trace_id_from_headers,
    validate_authorization_header,
)


AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION = (
    "ag_retrieval_package_operations_projection.v1"
)
AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_retrieval_package_detail_projection.v1"
)
RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID = "nex-cx"
RETRIEVAL_PACKAGE_STATUSES = ("READY", "LOW_CONFIDENCE", "NO_ANSWER")
DEFAULT_RETRIEVAL_PACKAGE_LIMIT = 50
MAX_RETRIEVAL_PACKAGE_SCAN_LIMIT = 500


class RetrievalPackageOperationsStore(Protocol):
    source_kind: str
    database_env: str | None
    redacted_database_url: str | None

    def list_retrieval_packages(
        self,
        *,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        retrieval_policy_id: str | None = None,
        limit: int = MAX_RETRIEVAL_PACKAGE_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        ...

    def get_retrieval_package(
        self,
        *,
        retrieval_package_id: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class RetrievalPackageOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503


@dataclass
class InMemoryRetrievalPackageOperationsStore:
    records: list[dict[str, Any]] = field(default_factory=list)
    source_kind: str = "memory"
    database_env: str | None = None
    redacted_database_url: str | None = None

    def list_retrieval_packages(
        self,
        *,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        retrieval_policy_id: str | None = None,
        limit: int = MAX_RETRIEVAL_PACKAGE_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for record in self.records:
            if status is not None and record.get("status") != status:
                continue
            if trace_id is not None and record.get("trace_id") != trace_id:
                continue
            if request_id is not None and record.get("request_id") != request_id:
                continue
            if (
                retrieval_policy_id is not None
                and record.get("retrieval_policy_id") != retrieval_policy_id
            ):
                continue
            filtered.append(deepcopy(record))
        return filtered[:limit]

    def get_retrieval_package(
        self,
        *,
        retrieval_package_id: str,
    ) -> dict[str, Any] | None:
        for record in self.records:
            if record.get("retrieval_package_id") == retrieval_package_id:
                return deepcopy(record)
        return None


class SqlAlchemyRetrievalPackageOperationsStore:
    source_kind = "postgres-read"

    def __init__(
        self,
        session_factory: Any,
        *,
        database_env: str | None = None,
        redacted_database_url: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.database_env = database_env
        self.redacted_database_url = redacted_database_url

    def list_retrieval_packages(
        self,
        *,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        retrieval_policy_id: str | None = None,
        limit: int = MAX_RETRIEVAL_PACKAGE_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        if trace_id is not None:
            conditions.append("trace_id = :trace_id")
            params["trace_id"] = trace_id
        if request_id is not None:
            conditions.append("request_id = :request_id")
            params["request_id"] = request_id
        if retrieval_policy_id is not None:
            conditions.append("retrieval_policy_id = :retrieval_policy_id")
            params["retrieval_policy_id"] = retrieval_policy_id
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = text(
            f"""
            SELECT
                retrieval_package_id,
                package_hash,
                status,
                trace_id,
                request_id,
                query_text_sha256,
                query_text_preview,
                query_embedding_provided,
                query_embedding_sha256,
                query_embedding_dimension,
                purpose,
                retrieval_policy_id,
                retrieval_policy_version,
                retrieval_policy_hash,
                retrieval_policy_source,
                ranker_mix,
                rerank_state,
                permission_snapshot_hash,
                source_summary,
                score_summary,
                warning_count,
                evidence_count,
                no_answer_reason,
                created_at,
                updated_at
            FROM cx_retrieval_packages
            {where_clause}
            ORDER BY created_at DESC, retrieval_package_id DESC
            LIMIT :limit
            """
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(query, params).mappings().all()
        except SQLAlchemyError as exc:
            raise RetrievalPackageOperationsError(
                error_code="ag.retrieval_package_source_unavailable",
                detail="Retrieval package operations source could not be read.",
            ) from exc
        return [_retrieval_package_from_row(row) for row in rows]

    def get_retrieval_package(
        self,
        *,
        retrieval_package_id: str,
    ) -> dict[str, Any] | None:
        package_query = text(
            """
            SELECT
                retrieval_package_id,
                package_hash,
                status,
                trace_id,
                request_id,
                query_text_sha256,
                query_text_preview,
                query_embedding_provided,
                query_embedding_sha256,
                query_embedding_dimension,
                purpose,
                retrieval_policy_id,
                retrieval_policy_version,
                retrieval_policy_hash,
                retrieval_policy_source,
                ranker_mix,
                rerank_state,
                permission_snapshot_hash,
                source_summary,
                score_summary,
                warning_count,
                evidence_count,
                no_answer_reason,
                created_at,
                updated_at
            FROM cx_retrieval_packages
            WHERE retrieval_package_id = :retrieval_package_id
            """
        )
        evidence_query = text(
            """
            SELECT
                retrieval_package_id,
                evidence_id,
                rank,
                content_object_id,
                content_version_id,
                chunk_id,
                chunk_policy_id,
                source_anchor,
                citation_label,
                evidence_text_sha256,
                evidence_text_preview,
                final_score,
                scores,
                matched_terms,
                permission_result,
                neighbor_context,
                quality_flags,
                created_at
            FROM cx_retrieval_evidence_items
            WHERE retrieval_package_id = :retrieval_package_id
            ORDER BY rank ASC
            """
        )
        try:
            with self._session_factory() as session:
                package_row = session.execute(
                    package_query,
                    {"retrieval_package_id": retrieval_package_id},
                ).mappings().first()
                if package_row is None:
                    return None
                evidence_rows = session.execute(
                    evidence_query,
                    {"retrieval_package_id": retrieval_package_id},
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RetrievalPackageOperationsError(
                error_code="ag.retrieval_package_source_unavailable",
                detail="Retrieval package operations source could not be read.",
            ) from exc
        package = _retrieval_package_from_row(package_row)
        package["evidence_items"] = [
            _retrieval_evidence_from_row(row) for row in evidence_rows
        ]
        return package


def build_retrieval_package_operation_stores(
    *,
    runtime: AgOperationsSourceRuntime | None = None,
    environ: Mapping[str, str] | None = None,
    engine_factory: Any = build_engine,
    session_factory_builder: Any = build_session_factory,
) -> dict[str, RetrievalPackageOperationsStore]:
    env = environ if environ is not None else os.environ
    selected_runtime = runtime or _retrieval_runtime_from_environment(env)
    if RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID not in selected_runtime.selected_service_ids:
        return {}
    if selected_runtime.mode == "memory":
        return {
            RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID: InMemoryRetrievalPackageOperationsStore()
        }

    database_env = ag_operations_source_database_env(
        RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID,
        profile=selected_runtime.profile,
    )
    database_url = required_database_url(database_env, env)
    engine = engine_factory(
        database_url,
        pool_settings=database_pool_settings(
            RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID,
            workload="api",
            environ=env,
        ),
    )
    return {
        RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID: SqlAlchemyRetrievalPackageOperationsStore(
            session_factory_builder(engine),
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
        )
    }


def register_retrieval_package_operation_routes(
    app: FastAPI,
    *,
    stores: Mapping[str, RetrievalPackageOperationsStore] | None = None,
    runtime: AgOperationsSourceRuntime | None = None,
) -> None:
    configured_stores = dict(stores) if stores is not None else None

    @app.get("/admin/v1/operations/retrieval-packages", response_model=None)
    def list_retrieval_package_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        retrieval_policy_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=DEFAULT_RETRIEVAL_PACKAGE_LIMIT, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_retrieval_package_filters(
            request,
            service_id=service_id,
            status=status,
        )
        if filter_problem is not None:
            return filter_problem
        query_options = _build_query_options_or_problem(
            request,
            limit=limit,
            since=since,
            until=until,
            sort=sort,
            cursor=cursor,
        )
        if isinstance(query_options, JSONResponse):
            return query_options
        selected_stores = configured_stores
        if selected_stores is None:
            selected_runtime = runtime or getattr(
                request.app.state,
                "nex_ag_operations_source_runtime",
                None,
            )
            selected_stores = build_retrieval_package_operation_stores(
                runtime=selected_runtime
            )
        return build_retrieval_package_operations_projection(
            stores=selected_stores,
            service_id=service_id,
            status=status.upper() if status is not None else None,
            trace_id=trace_id,
            request_id=request_id,
            retrieval_policy_id=retrieval_policy_id,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get(
        "/admin/v1/operations/retrieval-packages/{retrieval_package_id}",
        response_model=None,
    )
    def get_retrieval_package_operation_detail(
        retrieval_package_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_retrieval_package_filters(
            request,
            service_id=service_id,
            status=None,
        )
        if filter_problem is not None:
            return filter_problem
        selected_service_id = service_id or RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID
        selected_stores = configured_stores
        if selected_stores is None:
            selected_runtime = runtime or getattr(
                request.app.state,
                "nex_ag_operations_source_runtime",
                None,
            )
            selected_stores = build_retrieval_package_operation_stores(
                runtime=selected_runtime
            )
        store = selected_stores.get(selected_service_id)
        if store is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.retrieval_package_source_not_configured",
                title="Retrieval package source not configured",
                detail=(
                    "Retrieval package operations source is not configured for "
                    f"{selected_service_id}."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "retrieval-package-source-not-configured"
                ),
            )
        try:
            package = store.get_retrieval_package(
                retrieval_package_id=retrieval_package_id
            )
        except RetrievalPackageOperationsError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Retrieval package source unavailable",
                detail=exc.detail,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "retrieval-package-source-unavailable"
                ),
            )
        if package is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.retrieval_package_not_found",
                title="Retrieval package not found",
                detail=f"Retrieval package {retrieval_package_id} was not found.",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "retrieval-package-not-found"
                ),
            )
        return build_retrieval_package_detail_projection(
            service_id=selected_service_id,
            store=store,
            package=package,
            request_trace_id=trace_id_from_headers(request),
        )


def build_retrieval_package_operations_projection(
    *,
    stores: Mapping[str, RetrievalPackageOperationsStore],
    service_id: str | None = None,
    status: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    retrieval_policy_id: str | None = None,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(
        limit=DEFAULT_RETRIEVAL_PACKAGE_LIMIT
    )
    selected_service_ids = (
        [service_id] if service_id is not None else [RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID]
    )
    packages: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = _retrieval_source_status(
                service_id=selected_service_id,
                store=None,
                package_count=0,
            )
            continue
        try:
            records = store.list_retrieval_packages(
                status=status,
                trace_id=trace_id,
                request_id=request_id,
                retrieval_policy_id=retrieval_policy_id,
                limit=MAX_RETRIEVAL_PACKAGE_SCAN_LIMIT,
            )
        except RetrievalPackageOperationsError as exc:
            source_statuses[selected_service_id] = _retrieval_source_status(
                service_id=selected_service_id,
                store=store,
                package_count=0,
                error=exc,
            )
            continue
        records = _filter_packages_by_time(records, options)
        source_statuses[selected_service_id] = _retrieval_source_status(
            service_id=selected_service_id,
            store=store,
            package_count=len(records),
        )
        packages.extend(
            _project_retrieval_package(selected_service_id, record)
            for record in records
        )

    page = _apply_retrieval_package_query_options(packages, options)
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": (
            AG_RETRIEVAL_PACKAGE_OPERATIONS_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "status": status,
            "trace_id": trace_id,
            "request_id": request_id,
            "retrieval_policy_id": retrieval_policy_id,
            **options.to_filter_dict(),
        },
        "retrieval_packages": page["items"],
        "summary": summarize_retrieval_package_operations(page["items"]),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_retrieval_package_operations(
    packages: list[dict[str, Any]],
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_policy: dict[str, int] = {}
    for package in packages:
        status = str(package["status"])
        policy_id = str(package["retrieval_policy_id"])
        by_status[status] = by_status.get(status, 0) + 1
        by_policy[policy_id] = by_policy.get(policy_id, 0) + 1
    return {
        "total": len(packages),
        "by_status": by_status,
        "by_policy": by_policy,
        "low_confidence": by_status.get("LOW_CONFIDENCE", 0),
        "no_answer": by_status.get("NO_ANSWER", 0),
        "evidence_count": sum(int(package["evidence_count"]) for package in packages),
    }


def build_retrieval_package_detail_projection(
    *,
    service_id: str,
    store: RetrievalPackageOperationsStore,
    package: Mapping[str, Any],
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    evidence_items = [
        _project_retrieval_evidence_item(service_id, item)
        for item in _list_value(package.get("evidence_items"))
    ]
    projection = {
        "projection_schema_version": (
            AG_RETRIEVAL_PACKAGE_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "checked_at": _utc_now(),
        "service_id": service_id,
        "retrieval_package": _project_retrieval_package(service_id, package),
        "evidence_items": evidence_items,
        "summary": summarize_retrieval_package_detail(package, evidence_items),
        "source_status": _retrieval_source_status(
            service_id=service_id,
            store=store,
            package_count=1,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_retrieval_package_detail(
    package: Mapping[str, Any],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    scores = [
        score
        for item in evidence_items
        if (score := _number_or_none(item.get("final_score"))) is not None
    ]
    content_object_ids = {
        item["content_object_id"]
        for item in evidence_items
        if item.get("content_object_id") is not None
    }
    quality_flags = [
        flag
        for item in evidence_items
        for flag in _list_value(item.get("quality_flags"))
    ]
    permission_denied_count = sum(
        1 for item in evidence_items if item.get("permission_allowed") is False
    )
    score_range = {"min": min(scores), "max": max(scores)} if scores else None
    return {
        "retrieval_package_id": package["retrieval_package_id"],
        "status": package["status"],
        "trace_id": package["trace_id"],
        "request_id": package["request_id"],
        "retrieval_policy_id": package["retrieval_policy_id"],
        "evidence_count": int(package["evidence_count"]),
        "returned_evidence_items": len(evidence_items),
        "content_object_count": len(content_object_ids),
        "permission_denied_count": permission_denied_count,
        "quality_flag_count": len(quality_flags),
        "score_range": score_range,
        "evidence_text_preview_redacted": True,
    }


def _retrieval_runtime_from_environment(
    env: Mapping[str, str],
) -> AgOperationsSourceRuntime:
    mode = normalize_ag_operations_source_mode(env.get(AG_OPERATIONS_SOURCE_MODE_ENV))
    profile = normalize_ag_operations_source_profile(
        env.get(AG_OPERATIONS_SOURCE_PROFILE_ENV)
    )
    selected_service_ids = select_ag_operations_source_service_ids(
        env.get(AG_OPERATIONS_SOURCE_SERVICES_ENV)
    )
    return AgOperationsSourceRuntime(
        mode=mode,
        profile=profile,
        selected_service_ids=selected_service_ids,
        registry=None,
    )


def _retrieval_package_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "retrieval_package_id": str(row["retrieval_package_id"]),
        "package_hash": row["package_hash"],
        "status": row["status"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "query_text_sha256": row["query_text_sha256"],
        "query_text_preview": row["query_text_preview"],
        "query_embedding_provided": _bool_value(row["query_embedding_provided"]),
        "query_embedding_sha256": row["query_embedding_sha256"],
        "query_embedding_dimension": int(row["query_embedding_dimension"]),
        "purpose": row["purpose"],
        "retrieval_policy_id": row["retrieval_policy_id"],
        "retrieval_policy_version": row["retrieval_policy_version"],
        "retrieval_policy_hash": row["retrieval_policy_hash"],
        "retrieval_policy_source": row["retrieval_policy_source"],
        "ranker_mix": row["ranker_mix"],
        "rerank_state": row["rerank_state"],
        "permission_snapshot_hash": row["permission_snapshot_hash"],
        "source_summary": _json_loads(row["source_summary"], default={}),
        "score_summary": _json_loads(row["score_summary"], default={}),
        "warning_count": int(row["warning_count"]),
        "evidence_count": int(row["evidence_count"]),
        "no_answer_reason": row["no_answer_reason"],
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _retrieval_evidence_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "retrieval_package_id": str(row["retrieval_package_id"]),
        "evidence_id": str(row["evidence_id"]),
        "rank": int(row["rank"]),
        "content_object_id": str(row["content_object_id"]),
        "content_version_id": row["content_version_id"],
        "chunk_id": str(row["chunk_id"]),
        "chunk_policy_id": row["chunk_policy_id"],
        "source_anchor": _json_loads(row["source_anchor"], default={}),
        "citation_label": row["citation_label"],
        "evidence_text_sha256": row["evidence_text_sha256"],
        "final_score": float(row["final_score"]),
        "scores": _json_loads(row["scores"], default={}),
        "matched_terms": _json_loads(row["matched_terms"], default=[]),
        "permission_result": _json_loads(row["permission_result"], default={}),
        "neighbor_context": _json_loads(row["neighbor_context"], default=[]),
        "quality_flags": _json_loads(row["quality_flags"], default=[]),
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _project_retrieval_package(
    service_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    score_summary = _mapping_value(record.get("score_summary"))
    source_summary = _mapping_value(record.get("source_summary"))
    return {
        "service_id": service_id,
        "operation_type": "retrieval_package",
        "operation_timestamp": record["created_at"],
        "retrieval_package_id": record["retrieval_package_id"],
        "package_hash": record["package_hash"],
        "status": record["status"],
        "trace_id": record["trace_id"],
        "request_id": record["request_id"],
        "query_text_sha256": record["query_text_sha256"],
        "query_text_preview": record.get("query_text_preview"),
        "query_embedding_provided": _bool_value(record["query_embedding_provided"]),
        "query_embedding_dimension": int(record["query_embedding_dimension"]),
        "purpose": record["purpose"],
        "retrieval_policy_id": record["retrieval_policy_id"],
        "retrieval_policy_version": record.get("retrieval_policy_version"),
        "retrieval_policy_hash": record.get("retrieval_policy_hash"),
        "retrieval_policy_source": record["retrieval_policy_source"],
        "ranker_mix": record["ranker_mix"],
        "rerank_state": record["rerank_state"],
        "permission_snapshot_hash": record["permission_snapshot_hash"],
        "evidence_count": int(record["evidence_count"]),
        "warning_count": int(record["warning_count"]),
        "no_answer_reason": record.get("no_answer_reason"),
        "best_score": _number_or_none(score_summary.get("best_score")),
        "source_count": _integer_or_none(source_summary.get("source_count")),
        "document_count": _integer_or_none(source_summary.get("document_count")),
        "chunk_count": _integer_or_none(source_summary.get("chunk_count")),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _project_retrieval_evidence_item(
    service_id: str,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    scores = _mapping_value(item.get("scores"))
    matched_terms = _list_value(item.get("matched_terms"))
    permission_result = _mapping_value(item.get("permission_result"))
    neighbor_context = _list_value(item.get("neighbor_context"))
    quality_flags = _list_value(item.get("quality_flags"))
    return {
        "service_id": service_id,
        "retrieval_package_id": item["retrieval_package_id"],
        "evidence_id": item["evidence_id"],
        "rank": int(item["rank"]),
        "content_object_id": item["content_object_id"],
        "content_version_id": item.get("content_version_id"),
        "chunk_id": item["chunk_id"],
        "chunk_policy_id": item.get("chunk_policy_id"),
        "source_anchor": deepcopy(_mapping_value(item.get("source_anchor"))),
        "citation_label": item.get("citation_label"),
        "evidence_text_sha256": item.get("evidence_text_sha256"),
        "evidence_text_preview_redacted": True,
        "final_score": _number_or_none(item.get("final_score")),
        "scores": deepcopy(scores),
        "score_keys": sorted(str(key) for key in scores),
        "matched_term_count": len(matched_terms),
        "permission_allowed": _permission_allowed(permission_result),
        "permission_result": _safe_permission_result(permission_result),
        "neighbor_count": len(neighbor_context),
        "quality_flags": deepcopy(quality_flags),
        "created_at": item["created_at"],
    }


def _retrieval_source_status(
    *,
    service_id: str,
    store: RetrievalPackageOperationsStore | None,
    package_count: int,
    error: RetrievalPackageOperationsError | None = None,
) -> dict[str, Any]:
    if store is None:
        return {
            "status": "NOT_CONFIGURED",
            "service_id": service_id,
            "source_kind": "none",
            "package_count": 0,
            "database_env": None,
            "redacted_database_url": None,
        }
    status = "UNAVAILABLE" if error is not None else "READY"
    source = {
        "status": status,
        "service_id": service_id,
        "source_kind": store.source_kind,
        "package_count": package_count,
        "database_env": store.database_env,
        "redacted_database_url": store.redacted_database_url,
    }
    if error is not None:
        source["error_code"] = error.error_code
        source["detail"] = error.detail
    return source


def _validate_retrieval_package_filters(
    request: Request,
    *,
    service_id: str | None,
    status: str | None,
) -> JSONResponse | None:
    if (
        service_id is not None
        and service_id != RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.retrieval_package_service_invalid",
            title="Invalid retrieval package service filter",
            detail=(
                "Retrieval package operations are currently available only for "
                f"{RETRIEVAL_PACKAGE_SOURCE_SERVICE_ID}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "retrieval-package-service-invalid"
            ),
        )
    if status is not None and status.upper() not in RETRIEVAL_PACKAGE_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.retrieval_package_status_invalid",
            title="Invalid retrieval package status filter",
            detail=f"Unsupported retrieval package status: {status}",
            type_uri=(
                "https://nex-platform.local/problems/"
                "retrieval-package-status-invalid"
            ),
        )
    return None


def _build_query_options_or_problem(
    request: Request,
    *,
    limit: int,
    since: str | None,
    until: str | None,
    sort: str | None,
    cursor: str | None,
) -> OperationQueryOptions | JSONResponse:
    try:
        return build_operation_query_options(
            limit=limit,
            since=since,
            until=until,
            sort=sort,
            cursor=cursor,
        )
    except OperationsQueryError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Invalid retrieval package operations query",
            detail=exc.detail,
            type_uri=(
                "https://nex-platform.local/problems/"
                "retrieval-package-query-invalid"
            ),
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


def _filter_packages_by_time(
    records: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> list[dict[str, Any]]:
    since_dt = _parse_timestamp(options.since) if options.since is not None else None
    until_dt = _parse_timestamp(options.until) if options.until is not None else None
    filtered = []
    for record in records:
        created_at = _parse_timestamp(str(record["created_at"]))
        if since_dt is not None and created_at < since_dt:
            continue
        if until_dt is not None and created_at > until_dt:
            continue
        filtered.append(record)
    return filtered


def _apply_retrieval_package_query_options(
    packages: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> dict[str, Any]:
    reverse = options.sort == "desc"
    sorted_packages = sorted(
        packages,
        key=lambda package: (
            _parse_timestamp(str(package["created_at"])),
            str(package["retrieval_package_id"]),
        ),
        reverse=reverse,
    )
    page_items = sorted_packages[options.offset : options.offset + options.limit]
    return {
        "items": page_items,
        "pagination": options.pagination(
            total=len(sorted_packages),
            returned=len(page_items),
        ),
    }


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _permission_allowed(value: Mapping[str, Any]) -> bool | None:
    if "allowed" not in value:
        return None
    return _bool_value(value["allowed"])


def _safe_permission_result(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    if "allowed" in value:
        safe["allowed"] = _bool_value(value["allowed"])
    for key in ("reason", "policy_id", "principal_type", "permission"):
        if key in value:
            safe[key] = value[key]
    return safe


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
