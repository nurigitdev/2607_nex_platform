from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_OPERATIONAL_EVENT_TAXONOMY,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    JOB_STATUSES,
    JobQueue,
    JobQueueError,
    OPERATIONAL_EVENT_SEVERITIES,
    OperationalEventStore,
    OperationalEventError,
    OperationalEventTypeSpec,
    SERVICE_SPECS,
    list_operational_event_taxonomy,
    normalize_job_limit,
    normalize_operational_event_limit,
    problem_response,
    summarize_operational_event_taxonomy,
    summarize_jobs,
    summarize_operational_events,
    trace_id_from_headers,
    validate_authorization_header,
)

DEFAULT_OPERATIONAL_EVENT_STORE = InMemoryOperationalEventStore()
DEFAULT_JOB_QUEUE_STORES = {
    service_id: InMemoryJobQueue()
    for service_id in sorted(SERVICE_SPECS)
}


@dataclass(frozen=True)
class OperationsSource:
    service_id: str
    job_queue: JobQueue | None = None
    operational_event_store: OperationalEventStore | None = None
    source_kind: str = "memory"

    def __post_init__(self) -> None:
        if self.service_id not in SERVICE_SPECS:
            raise ValueError(f"unsupported operations source service: {self.service_id}")
        if not self.source_kind:
            raise ValueError("source_kind must be a non-empty string")

    def to_summary(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "source_kind": self.source_kind,
            "job_queue": (
                self.job_queue.__class__.__name__
                if self.job_queue is not None
                else None
            ),
            "operational_event_store": (
                self.operational_event_store.__class__.__name__
                if self.operational_event_store is not None
                else None
            ),
            "capabilities": {
                "jobs": self.job_queue is not None,
                "events": self.operational_event_store is not None,
            },
        }


@dataclass
class OperationsSourceRegistry:
    sources: dict[str, OperationsSource] = field(default_factory=dict)

    def register(self, source: OperationsSource) -> OperationsSource:
        self.sources[source.service_id] = source
        return source

    def get(self, service_id: str) -> OperationsSource | None:
        if service_id not in SERVICE_SPECS:
            raise ValueError(f"unsupported operations source service: {service_id}")
        return self.sources.get(service_id)

    def service_ids(self) -> list[str]:
        return sorted(self.sources)

    def job_queues(self) -> dict[str, JobQueue]:
        return {
            service_id: source.job_queue
            for service_id, source in self.sources.items()
            if source.job_queue is not None
        }

    def event_stores(self) -> dict[str, OperationalEventStore]:
        return {
            service_id: source.operational_event_store
            for service_id, source in self.sources.items()
            if source.operational_event_store is not None
        }

    def to_summary(self) -> dict[str, Any]:
        source_summaries = {
            service_id: source.to_summary()
            for service_id, source in sorted(self.sources.items())
        }
        return {
            "registry_schema_version": "ag_operations_source_registry.v1",
            "service_count": len(source_summaries),
            "sources": source_summaries,
        }


class RegistryOperationalEventStore:
    def __init__(self, registry: OperationsSourceRegistry) -> None:
        self.registry = registry

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        raise OperationalEventError(
            error_code="ag.operations_registry.read_only",
            detail="AG operations registry event store is read-only.",
            status_code=405,
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        for store in self.registry.event_stores().values():
            event = store.get_event(event_id)
            if event is not None:
                return event
        return None

    def list_events(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_limit = normalize_operational_event_limit(limit)
        event_stores = self.registry.event_stores()
        selected_service_ids = [service_id] if service_id is not None else sorted(SERVICE_SPECS)
        events: list[dict[str, Any]] = []
        for selected_service_id in selected_service_ids:
            store = event_stores.get(selected_service_id)
            if store is None:
                continue
            events.extend(
                store.list_events(
                    service_id=selected_service_id,
                    severity=severity,
                    event_type=event_type,
                    trace_id=trace_id,
                    limit=normalized_limit,
                )
            )
        events.sort(
            key=lambda event: (
                str(event.get("created_at", "")),
                str(event.get("event_id", "")),
            ),
            reverse=True,
        )
        return events[:normalized_limit]


def build_operations_source_registry(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_stores: Mapping[str, OperationalEventStore] | None = None,
    source_kind: str = "memory",
) -> OperationsSourceRegistry:
    queue_map = job_queues or {}
    event_store_map = event_stores or {}
    source_ids = sorted(set(queue_map) | set(event_store_map))
    registry = OperationsSourceRegistry()
    for service_id in source_ids:
        registry.register(
            OperationsSource(
                service_id=service_id,
                job_queue=queue_map.get(service_id),
                operational_event_store=event_store_map.get(service_id),
                source_kind=source_kind,
            )
        )
    return registry


def register_operational_event_routes(
    app: FastAPI,
    *,
    store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
) -> None:
    event_store = store or (
        RegistryOperationalEventStore(registry)
        if registry is not None
        else DEFAULT_OPERATIONAL_EVENT_STORE
    )

    @app.get("/admin/v1/operations/events", response_model=None)
    def list_operational_events(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = Query(default=50, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        if severity is not None and severity.upper() not in OPERATIONAL_EVENT_SEVERITIES:
            return problem_response(
                request,
                status_code=400,
                error_code="ag.operational_event_severity_invalid",
                title="Invalid operational event severity",
                detail=f"Unsupported operational event severity: {severity}",
                type_uri="https://nex-platform.local/problems/operational-event-severity-invalid",
            )

        return build_operational_event_projection(
            event_store,
            service_id=service_id,
            severity=severity,
            event_type=event_type,
            trace_id=trace_id,
            limit=limit,
            request_trace_id=trace_id_from_headers(request),
        )


def register_operational_event_taxonomy_routes(
    app: FastAPI,
    *,
    taxonomy: tuple[OperationalEventTypeSpec, ...] = DEFAULT_OPERATIONAL_EVENT_TAXONOMY,
) -> None:
    @app.get("/admin/v1/operations/event-taxonomy", response_model=None)
    def list_operational_event_taxonomy_route(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        event_type: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        if service_id is not None and service_id not in SERVICE_SPECS:
            return problem_response(
                request,
                status_code=400,
                error_code="ag.event_taxonomy_service_invalid",
                title="Invalid event taxonomy service filter",
                detail=f"Unsupported event taxonomy service: {service_id}",
                type_uri="https://nex-platform.local/problems/event-taxonomy-service-invalid",
            )
        return build_operational_event_taxonomy_projection(
            service_id=service_id,
            event_type=event_type,
            taxonomy=taxonomy,
            request_trace_id=trace_id_from_headers(request),
        )


def register_job_operation_routes(
    app: FastAPI,
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    registry: OperationsSourceRegistry | None = None,
) -> None:
    queue_stores = (
        registry.job_queues()
        if registry is not None
        else job_queues or DEFAULT_JOB_QUEUE_STORES
    )

    @app.get("/admin/v1/operations/jobs", response_model=None)
    def list_operational_jobs(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = Query(default=50, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        filter_problem = _validate_job_operation_filters(
            request,
            service_id=service_id,
            status=status,
        )
        if filter_problem is not None:
            return filter_problem

        return build_job_operations_projection(
            queue_stores,
            service_id=service_id,
            status=status,
            job_type=job_type,
            limit=limit,
            request_trace_id=trace_id_from_headers(request),
        )


def register_unified_operation_routes(
    app: FastAPI,
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
) -> None:
    @app.get("/admin/v1/operations", response_model=None)
    def list_unified_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        job_status: str | None = None,
        job_type: str | None = None,
        event_severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = Query(default=50, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        filter_problem = _validate_unified_operation_filters(
            request,
            service_id=service_id,
            job_status=job_status,
            event_severity=event_severity,
        )
        if filter_problem is not None:
            return filter_problem

        return build_unified_operations_projection(
            job_queues=job_queues,
            event_store=event_store,
            registry=registry,
            service_id=service_id,
            job_status=job_status,
            job_type=job_type,
            event_severity=event_severity,
            event_type=event_type,
            trace_id=trace_id,
            limit=limit,
            request_trace_id=trace_id_from_headers(request),
        )


def build_operational_event_projection(
    store: OperationalEventStore,
    *,
    service_id: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int = 50,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_operational_event_limit(limit)
    events = store.list_events(
        service_id=service_id,
        severity=severity,
        event_type=event_type,
        trace_id=trace_id,
        limit=normalized_limit,
    )
    projection = {
        "projection_schema_version": "ag_operational_event_projection.v1",
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "severity": severity.upper() if severity is not None else None,
            "event_type": event_type,
            "trace_id": trace_id,
            "limit": normalized_limit,
        },
        "events": events,
        "summary": summarize_operational_events(events),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_operational_event_taxonomy_projection(
    *,
    service_id: str | None = None,
    event_type: str | None = None,
    taxonomy: tuple[OperationalEventTypeSpec, ...] = DEFAULT_OPERATIONAL_EVENT_TAXONOMY,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    event_types = list_operational_event_taxonomy(
        service_id=service_id,
        event_type=event_type,
        taxonomy=taxonomy,
    )
    projection = {
        "projection_schema_version": "ag_operational_event_taxonomy_projection.v1",
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "event_type": event_type,
        },
        "event_types": event_types,
        "summary": summarize_operational_event_taxonomy(event_types),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_unified_operations_projection(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    job_status: str | None = None,
    job_type: str | None = None,
    event_severity: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    limit: int = 50,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_job_limit(limit)
    queue_stores = (
        registry.job_queues()
        if registry is not None
        else job_queues or DEFAULT_JOB_QUEUE_STORES
    )
    selected_event_store = (
        RegistryOperationalEventStore(registry)
        if registry is not None
        else event_store or DEFAULT_OPERATIONAL_EVENT_STORE
    )
    job_projection = build_job_operations_projection(
        queue_stores,
        service_id=service_id,
        status=job_status,
        job_type=job_type,
        limit=normalized_limit,
    )
    event_projection = build_operational_event_projection(
        selected_event_store,
        service_id=service_id,
        severity=event_severity,
        event_type=event_type,
        trace_id=trace_id,
        limit=normalized_limit,
    )
    projection_status = (
        "DEGRADED"
        if job_projection["projection_status"] == "DEGRADED"
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_unified_operations_projection.v1",
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "job_status": job_status.upper() if job_status is not None else None,
            "job_type": job_type,
            "event_severity": (
                event_severity.upper() if event_severity is not None else None
            ),
            "event_type": event_type,
            "trace_id": trace_id,
            "limit": normalized_limit,
        },
        "jobs": job_projection,
        "events": event_projection,
        "summary": {
            "jobs": job_projection["summary"],
            "events": event_projection["summary"],
            "source_statuses": job_projection["source_statuses"],
        },
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_job_operations_projection(
    job_queues: Mapping[str, JobQueue],
    *,
    service_id: str | None = None,
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 50,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_limit = normalize_job_limit(limit)
    normalized_status = status.upper() if status is not None else None
    selected_service_ids = [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    projected_jobs: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}

    for selected_service_id in selected_service_ids:
        queue = job_queues.get(selected_service_id)
        if queue is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "job_count": 0,
            }
            continue
        try:
            service_jobs = queue.list_jobs(job_type=job_type, status=normalized_status)
        except JobQueueError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "job_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        source_statuses[selected_service_id] = {
            "status": "READY",
            "job_count": len(service_jobs),
        }
        projected_jobs.extend(
            _project_job_for_service(selected_service_id, job)
            for job in service_jobs
        )

    projected_jobs = _sort_projected_jobs(projected_jobs)[:normalized_limit]
    projection_status = (
        "DEGRADED"
        if any(source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"} for source in source_statuses.values())
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_job_operations_projection.v1",
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "status": normalized_status,
            "job_type": job_type,
            "limit": normalized_limit,
        },
        "jobs": projected_jobs,
        "summary": summarize_job_operations(projected_jobs),
        "source_statuses": source_statuses,
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_job_operations(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_jobs(jobs)
    service_counts: dict[str, int] = {}
    job_type_counts: dict[str, int] = {}
    for job in jobs:
        service_id = str(job.get("service_id", "unknown"))
        job_type = str(job.get("job_type", "unknown"))
        service_counts[service_id] = service_counts.get(service_id, 0) + 1
        job_type_counts[job_type] = job_type_counts.get(job_type, 0) + 1
    return {
        **summary,
        "by_service": service_counts,
        "by_job_type": job_type_counts,
    }


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


def _validate_job_operation_filters(
    request: Request,
    *,
    service_id: str | None,
    status: str | None,
) -> JSONResponse | None:
    if service_id is not None and service_id not in SERVICE_SPECS:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.job_service_invalid",
            title="Invalid job service filter",
            detail=f"Unsupported job service: {service_id}",
            type_uri="https://nex-platform.local/problems/job-service-invalid",
        )
    if status is not None and status.upper() not in JOB_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.job_status_invalid",
            title="Invalid job status filter",
            detail=f"Unsupported job status: {status}",
            type_uri="https://nex-platform.local/problems/job-status-invalid",
        )
    return None


def _validate_unified_operation_filters(
    request: Request,
    *,
    service_id: str | None,
    job_status: str | None,
    event_severity: str | None,
) -> JSONResponse | None:
    job_problem = _validate_job_operation_filters(
        request,
        service_id=service_id,
        status=job_status,
    )
    if job_problem is not None:
        return job_problem
    if event_severity is not None and event_severity.upper() not in OPERATIONAL_EVENT_SEVERITIES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.operational_event_severity_invalid",
            title="Invalid operational event severity",
            detail=f"Unsupported operational event severity: {event_severity}",
            type_uri="https://nex-platform.local/problems/operational-event-severity-invalid",
        )
    return None


def _project_job_for_service(service_id: str, job: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(job)
    projected["service_id"] = service_id
    return projected


def _sort_projected_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        jobs,
        key=lambda job: (
            str(job.get("updated_at", "")),
            str(job.get("created_at", "")),
            str(job.get("service_id", "")),
            str(job.get("job_id", "")),
        ),
        reverse=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
