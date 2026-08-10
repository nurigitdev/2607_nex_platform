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


AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION = (
    "ag_cx_processing_run_operations_projection.v1"
)
AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_cx_processing_run_detail_projection.v1"
)
CX_PROCESSING_RUN_SOURCE_SERVICE_ID = "nex-cx"
CX_PROCESSING_RUN_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
DEFAULT_CX_PROCESSING_RUN_LIMIT = 50
MAX_CX_PROCESSING_RUN_SCAN_LIMIT = 500


class CxProcessingRunOperationsStore(Protocol):
    source_kind: str
    database_env: str | None
    redacted_database_url: str | None

    def list_processing_runs(
        self,
        *,
        document_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        include_steps: bool = False,
        limit: int = MAX_CX_PROCESSING_RUN_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        ...

    def get_processing_run(
        self,
        *,
        pipeline_run_id: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class CxProcessingRunOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503


@dataclass
class InMemoryCxProcessingRunOperationsStore:
    records: list[dict[str, Any]] = field(default_factory=list)
    source_kind: str = "memory"
    database_env: str | None = None
    redacted_database_url: str | None = None

    def list_processing_runs(
        self,
        *,
        document_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        include_steps: bool = False,
        limit: int = MAX_CX_PROCESSING_RUN_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for record in self.records:
            if document_id is not None and record.get("document_id") != document_id:
                continue
            if status is not None and record.get("status") != status:
                continue
            if trace_id is not None and record.get("trace_id") != trace_id:
                continue
            if request_id is not None and record.get("request_id") != request_id:
                continue
            if job_id is not None and record.get("job_id") != job_id:
                continue
            projected = deepcopy(record)
            if not include_steps:
                projected["steps"] = []
            filtered.append(projected)
        return filtered[:limit]

    def get_processing_run(
        self,
        *,
        pipeline_run_id: str,
    ) -> dict[str, Any] | None:
        for record in self.records:
            if record.get("pipeline_run_id") == pipeline_run_id:
                return deepcopy(record)
        return None


class SqlAlchemyCxProcessingRunOperationsStore:
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

    def list_processing_runs(
        self,
        *,
        document_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        include_steps: bool = False,
        limit: int = MAX_CX_PROCESSING_RUN_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if document_id is not None:
            conditions.append("document_id = :document_id")
            params["document_id"] = document_id
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        if trace_id is not None:
            conditions.append("trace_id = :trace_id")
            params["trace_id"] = trace_id
        if request_id is not None:
            conditions.append("request_id = :request_id")
            params["request_id"] = request_id
        if job_id is not None:
            conditions.append("job_id = :job_id")
            params["job_id"] = job_id
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = text(
            f"""
            SELECT
                pipeline_run_id,
                pipeline_schema_version,
                document_id,
                status,
                trace_id,
                request_id,
                job_id,
                job_type,
                job_status,
                job_attempt_count,
                job_max_attempts,
                job_retryable,
                job_subject_ref,
                job_links,
                step_total,
                step_succeeded,
                step_skipped,
                step_failed,
                queued_at,
                started_at,
                completed_at,
                updated_at
            FROM cx_document_processing_runs
            {where_clause}
            ORDER BY updated_at DESC, pipeline_run_id DESC
            LIMIT :limit
            """
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(query, params).mappings().all()
                records = [_processing_run_from_row(row) for row in rows]
                if include_steps:
                    for record in records:
                        record["steps"] = _processing_steps_for_run(
                            session,
                            pipeline_run_id=record["pipeline_run_id"],
                        )
        except SQLAlchemyError as exc:
            raise CxProcessingRunOperationsError(
                error_code="ag.cx_processing_run_source_unavailable",
                detail="CX processing run operations source could not be read.",
            ) from exc
        return records

    def get_processing_run(
        self,
        *,
        pipeline_run_id: str,
    ) -> dict[str, Any] | None:
        query = text(
            """
            SELECT
                pipeline_run_id,
                pipeline_schema_version,
                document_id,
                status,
                trace_id,
                request_id,
                job_id,
                job_type,
                job_status,
                job_attempt_count,
                job_max_attempts,
                job_retryable,
                job_subject_ref,
                job_links,
                step_total,
                step_succeeded,
                step_skipped,
                step_failed,
                queued_at,
                started_at,
                completed_at,
                updated_at
            FROM cx_document_processing_runs
            WHERE pipeline_run_id = :pipeline_run_id
            """
        )
        try:
            with self._session_factory() as session:
                row = session.execute(
                    query,
                    {"pipeline_run_id": pipeline_run_id},
                ).mappings().first()
                if row is None:
                    return None
                record = _processing_run_from_row(row)
                record["steps"] = _processing_steps_for_run(
                    session,
                    pipeline_run_id=record["pipeline_run_id"],
                )
        except SQLAlchemyError as exc:
            raise CxProcessingRunOperationsError(
                error_code="ag.cx_processing_run_source_unavailable",
                detail="CX processing run operations source could not be read.",
            ) from exc
        return record


def build_cx_processing_run_operation_stores(
    *,
    runtime: AgOperationsSourceRuntime | None = None,
    environ: Mapping[str, str] | None = None,
    engine_factory: Any = build_engine,
    session_factory_builder: Any = build_session_factory,
) -> dict[str, CxProcessingRunOperationsStore]:
    env = environ if environ is not None else os.environ
    selected_runtime = runtime or _processing_runtime_from_environment(env)
    if CX_PROCESSING_RUN_SOURCE_SERVICE_ID not in selected_runtime.selected_service_ids:
        return {}
    if selected_runtime.mode == "memory":
        return {
            CX_PROCESSING_RUN_SOURCE_SERVICE_ID: InMemoryCxProcessingRunOperationsStore()
        }

    database_env = ag_operations_source_database_env(
        CX_PROCESSING_RUN_SOURCE_SERVICE_ID,
        profile=selected_runtime.profile,
    )
    database_url = required_database_url(database_env, env)
    engine = engine_factory(
        database_url,
        pool_settings=database_pool_settings(
            CX_PROCESSING_RUN_SOURCE_SERVICE_ID,
            workload="api",
            environ=env,
        ),
    )
    return {
        CX_PROCESSING_RUN_SOURCE_SERVICE_ID: SqlAlchemyCxProcessingRunOperationsStore(
            session_factory_builder(engine),
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
        )
    }


def register_cx_processing_run_operation_routes(
    app: FastAPI,
    *,
    stores: Mapping[str, CxProcessingRunOperationsStore] | None = None,
    runtime: AgOperationsSourceRuntime | None = None,
) -> None:
    configured_stores = dict(stores) if stores is not None else None

    @app.get("/admin/v1/operations/cx-processing-runs", response_model=None)
    def list_cx_processing_run_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        document_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        include_steps: bool = False,
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=DEFAULT_CX_PROCESSING_RUN_LIMIT, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_processing_run_filters(
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
            selected_stores = build_cx_processing_run_operation_stores(
                runtime=selected_runtime
            )
        return build_cx_processing_run_operations_projection(
            stores=selected_stores,
            service_id=service_id,
            document_id=document_id,
            status=status.upper() if status is not None else None,
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            include_steps=include_steps,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get(
        "/admin/v1/operations/cx-processing-runs/{pipeline_run_id}",
        response_model=None,
    )
    def get_cx_processing_run_operation_detail(
        pipeline_run_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_processing_run_filters(
            request,
            service_id=service_id,
            status=None,
        )
        if filter_problem is not None:
            return filter_problem
        selected_service_id = service_id or CX_PROCESSING_RUN_SOURCE_SERVICE_ID
        selected_stores = configured_stores
        if selected_stores is None:
            selected_runtime = runtime or getattr(
                request.app.state,
                "nex_ag_operations_source_runtime",
                None,
            )
            selected_stores = build_cx_processing_run_operation_stores(
                runtime=selected_runtime
            )
        store = selected_stores.get(selected_service_id)
        if store is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.cx_processing_run_source_not_configured",
                title="CX processing run source not configured",
                detail=(
                    "CX processing run operations source is not configured for "
                    f"{selected_service_id}."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "cx-processing-run-source-not-configured"
                ),
            )
        try:
            run = store.get_processing_run(pipeline_run_id=pipeline_run_id)
        except CxProcessingRunOperationsError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="CX processing run source unavailable",
                detail=exc.detail,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "cx-processing-run-source-unavailable"
                ),
            )
        if run is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.cx_processing_run_not_found",
                title="CX processing run not found",
                detail=f"CX processing run {pipeline_run_id} was not found.",
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "cx-processing-run-not-found"
                ),
            )
        return build_cx_processing_run_detail_projection(
            service_id=selected_service_id,
            store=store,
            run=run,
            request_trace_id=trace_id_from_headers(request),
        )


def build_cx_processing_run_operations_projection(
    *,
    stores: Mapping[str, CxProcessingRunOperationsStore],
    service_id: str | None = None,
    document_id: str | None = None,
    status: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    include_steps: bool = False,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(
        limit=DEFAULT_CX_PROCESSING_RUN_LIMIT
    )
    selected_service_ids = (
        [service_id] if service_id is not None else [CX_PROCESSING_RUN_SOURCE_SERVICE_ID]
    )
    processing_runs: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = _processing_run_source_status(
                service_id=selected_service_id,
                store=None,
                run_count=0,
            )
            continue
        try:
            records = store.list_processing_runs(
                document_id=document_id,
                status=status,
                trace_id=trace_id,
                request_id=request_id,
                job_id=job_id,
                include_steps=include_steps,
                limit=MAX_CX_PROCESSING_RUN_SCAN_LIMIT,
            )
        except CxProcessingRunOperationsError as exc:
            source_statuses[selected_service_id] = _processing_run_source_status(
                service_id=selected_service_id,
                store=store,
                run_count=0,
                error=exc,
            )
            continue
        records = _filter_runs_by_time(records, options)
        source_statuses[selected_service_id] = _processing_run_source_status(
            service_id=selected_service_id,
            store=store,
            run_count=len(records),
        )
        processing_runs.extend(
            _project_processing_run(
                selected_service_id,
                record,
                include_steps=include_steps,
            )
            for record in records
        )

    page = _apply_processing_run_query_options(processing_runs, options)
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
            AG_CX_PROCESSING_RUN_OPERATIONS_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "document_id": document_id,
            "status": status,
            "trace_id": trace_id,
            "request_id": request_id,
            "job_id": job_id,
            "include_steps": bool(include_steps),
            **options.to_filter_dict(),
        },
        "processing_runs": page["items"],
        "summary": summarize_cx_processing_run_operations(page["items"]),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_cx_processing_run_operations(
    processing_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for run in processing_runs:
        status = str(run["status"])
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(processing_runs),
        "by_status": by_status,
        "failed_count": by_status.get("FAILED", 0),
        "running_count": by_status.get("RUNNING", 0),
        "retryable_failed_count": sum(
            1
            for run in processing_runs
            if run["status"] == "FAILED" and run.get("job_retryable") is True
        ),
        "step_failed_count": sum(int(run["step_failed"]) for run in processing_runs),
    }


def build_cx_processing_run_detail_projection(
    *,
    service_id: str,
    store: CxProcessingRunOperationsStore,
    run: Mapping[str, Any],
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_run = _project_processing_run(service_id, run, include_steps=True)
    projection = {
        "projection_schema_version": (
            AG_CX_PROCESSING_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY",
        "checked_at": _utc_now(),
        "service_id": service_id,
        "processing_run": projected_run,
        "summary": summarize_cx_processing_run_detail(projected_run),
        "source_status": _processing_run_source_status(
            service_id=service_id,
            store=store,
            run_count=1,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_cx_processing_run_detail(run: Mapping[str, Any]) -> dict[str, Any]:
    steps = _list_value(run.get("steps"))
    failed_steps = [step for step in steps if step.get("status") == "FAILED"]
    error_hash_count = sum(
        1 for step in steps if step.get("error_detail_sha256") is not None
    )
    return {
        "pipeline_run_id": run["pipeline_run_id"],
        "document_id": run["document_id"],
        "status": run["status"],
        "trace_id": run["trace_id"],
        "request_id": run["request_id"],
        "job_id": run["job_id"],
        "step_total": int(run["step_total"]),
        "returned_step_count": len(steps),
        "failed_step_count": len(failed_steps),
        "error_hash_count": error_hash_count,
        "raw_payload_redacted": True,
    }


def _processing_runtime_from_environment(
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


def _processing_run_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pipeline_run_id": str(row["pipeline_run_id"]),
        "pipeline_schema_version": row["pipeline_schema_version"],
        "document_id": str(row["document_id"]),
        "status": row["status"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "job_id": row["job_id"],
        "job_type": row["job_type"],
        "job_status": row["job_status"],
        "job_attempt_count": int(row["job_attempt_count"]),
        "job_max_attempts": int(row["job_max_attempts"]),
        "job_retryable": _nullable_bool(row["job_retryable"]),
        "job_subject_ref": _json_loads(row["job_subject_ref"], default={}),
        "job_links": _json_loads(row["job_links"], default={}),
        "step_total": int(row["step_total"]),
        "step_succeeded": int(row["step_succeeded"]),
        "step_skipped": int(row["step_skipped"]),
        "step_failed": int(row["step_failed"]),
        "queued_at": _timestamp_to_wire_or_none(row["queued_at"]),
        "started_at": _timestamp_to_wire_or_none(row["started_at"]),
        "completed_at": _timestamp_to_wire_or_none(row["completed_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
        "steps": [],
    }


def _processing_steps_for_run(session: Any, *, pipeline_run_id: str) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            pipeline_run_id,
            step_order,
            step_id,
            status,
            output_ref_type,
            output_ref_id,
            output_ref_document_id,
            output_ref_hash,
            error_code,
            error_detail_sha256,
            error_retryable,
            created_at
        FROM cx_document_processing_steps
        WHERE pipeline_run_id = :pipeline_run_id
        ORDER BY step_order ASC
        """
    )
    rows = session.execute(query, {"pipeline_run_id": pipeline_run_id}).mappings().all()
    return [_processing_step_from_row(row) for row in rows]


def _processing_step_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pipeline_run_id": str(row["pipeline_run_id"]),
        "step_order": int(row["step_order"]),
        "step_id": row["step_id"],
        "status": row["status"],
        "output_ref_type": row["output_ref_type"],
        "output_ref_id": row["output_ref_id"],
        "output_ref_document_id": (
            str(row["output_ref_document_id"])
            if row["output_ref_document_id"] is not None
            else None
        ),
        "output_ref_hash": row["output_ref_hash"],
        "error_code": row["error_code"],
        "error_detail_sha256": row["error_detail_sha256"],
        "error_retryable": _nullable_bool(row["error_retryable"]),
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _project_processing_run(
    service_id: str,
    record: Mapping[str, Any],
    *,
    include_steps: bool,
) -> dict[str, Any]:
    steps = [
        _project_processing_step(step)
        for step in _list_value(record.get("steps"))
        if isinstance(step, Mapping)
    ]
    return {
        "service_id": service_id,
        "operation_type": "cx_processing_run",
        "operation_timestamp": _timestamp_to_wire(record["updated_at"]),
        "processing_run_schema_version": "cx_document_processing_run.persistence.v1",
        "pipeline_run_id": str(record["pipeline_run_id"]),
        "pipeline_schema_version": record["pipeline_schema_version"],
        "document_id": str(record["document_id"]),
        "status": record["status"],
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "job_id": record.get("job_id"),
        "job_type": record.get("job_type"),
        "job_status": record.get("job_status"),
        "job_attempt_count": _int_value(record.get("job_attempt_count")),
        "job_max_attempts": _int_value(record.get("job_max_attempts")),
        "job_retryable": _nullable_bool(record.get("job_retryable")),
        "job_subject_ref": deepcopy(_mapping_value(record.get("job_subject_ref"))),
        "job_links": _string_mapping(record.get("job_links")),
        "step_total": _int_value(record.get("step_total")),
        "step_succeeded": _int_value(record.get("step_succeeded")),
        "step_skipped": _int_value(record.get("step_skipped")),
        "step_failed": _int_value(record.get("step_failed")),
        "queued_at": _timestamp_to_wire_or_none(record.get("queued_at")),
        "started_at": _timestamp_to_wire_or_none(record.get("started_at")),
        "completed_at": _timestamp_to_wire_or_none(record.get("completed_at")),
        "updated_at": _timestamp_to_wire(record["updated_at"]),
        "steps_included": include_steps,
        "steps": steps if include_steps else [],
    }


def _project_processing_step(step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "processing_step_schema_version": "cx_document_processing_step.persistence.v1",
        "pipeline_run_id": str(step["pipeline_run_id"]),
        "step_order": _int_value(step.get("step_order")),
        "step_id": step["step_id"],
        "status": step["status"],
        "output_ref_type": step.get("output_ref_type"),
        "output_ref_id": step.get("output_ref_id"),
        "output_ref_document_id": (
            str(step["output_ref_document_id"])
            if step.get("output_ref_document_id") is not None
            else None
        ),
        "output_ref_hash": step.get("output_ref_hash"),
        "error_code": step.get("error_code"),
        "error_detail_sha256": step.get("error_detail_sha256"),
        "error_retryable": _nullable_bool(step.get("error_retryable")),
        "created_at": _timestamp_to_wire(step["created_at"]),
    }


def _processing_run_source_status(
    *,
    service_id: str,
    store: CxProcessingRunOperationsStore | None,
    run_count: int,
    error: CxProcessingRunOperationsError | None = None,
) -> dict[str, Any]:
    if store is None:
        return {
            "status": "NOT_CONFIGURED",
            "service_id": service_id,
            "source_kind": "none",
            "processing_run_count": 0,
            "database_env": None,
            "redacted_database_url": None,
        }
    status = "UNAVAILABLE" if error is not None else "READY"
    source = {
        "status": status,
        "service_id": service_id,
        "source_kind": store.source_kind,
        "processing_run_count": run_count,
        "database_env": store.database_env,
        "redacted_database_url": store.redacted_database_url,
    }
    if error is not None:
        source["error_code"] = error.error_code
        source["detail"] = error.detail
    return source


def _validate_processing_run_filters(
    request: Request,
    *,
    service_id: str | None,
    status: str | None,
) -> JSONResponse | None:
    if service_id is not None and service_id != CX_PROCESSING_RUN_SOURCE_SERVICE_ID:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.cx_processing_run_service_invalid",
            title="Invalid CX processing run service filter",
            detail=(
                "CX processing run operations are currently available only for "
                f"{CX_PROCESSING_RUN_SOURCE_SERVICE_ID}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "cx-processing-run-service-invalid"
            ),
        )
    if status is not None and status.upper() not in CX_PROCESSING_RUN_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.cx_processing_run_status_invalid",
            title="Invalid CX processing run status filter",
            detail=f"Unsupported CX processing run status: {status}",
            type_uri=(
                "https://nex-platform.local/problems/"
                "cx-processing-run-status-invalid"
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
            title="Invalid CX processing run operations query",
            detail=exc.detail,
            type_uri=(
                "https://nex-platform.local/problems/"
                "cx-processing-run-query-invalid"
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


def _filter_runs_by_time(
    records: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> list[dict[str, Any]]:
    since_dt = _parse_timestamp(options.since) if options.since is not None else None
    until_dt = _parse_timestamp(options.until) if options.until is not None else None
    filtered = []
    for record in records:
        updated_at = _parse_timestamp(str(record["updated_at"]))
        if since_dt is not None and updated_at < since_dt:
            continue
        if until_dt is not None and updated_at > until_dt:
            continue
        filtered.append(record)
    return filtered


def _apply_processing_run_query_options(
    processing_runs: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> dict[str, Any]:
    reverse = options.sort == "desc"
    sorted_runs = sorted(
        processing_runs,
        key=lambda run: (
            _parse_timestamp(str(run["updated_at"])),
            str(run["pipeline_run_id"]),
        ),
        reverse=reverse,
    )
    page_items = sorted_runs[options.offset : options.offset + options.limit]
    return {
        "items": page_items,
        "pagination": options.pagination(
            total=len(sorted_runs),
            returned=len(page_items),
        ),
    }


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _timestamp_to_wire_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return _timestamp_to_wire(value)


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


def _string_mapping(value: Any) -> dict[str, str]:
    mapping = _mapping_value(value)
    return {str(key): str(item) for key, item in mapping.items()}


def _list_value(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _nullable_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
