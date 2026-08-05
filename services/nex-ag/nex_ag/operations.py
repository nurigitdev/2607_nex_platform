from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

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
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_session_factory,
    database_pool_settings,
    list_operational_event_taxonomy,
    normalize_job_limit,
    normalize_operational_event_limit,
    problem_response,
    redact_database_url,
    required_database_url,
    service_database_env_prefix,
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

AG_OPERATIONS_SOURCE_MODE_ENV = "NEX_AG_OPERATIONS_SOURCE_MODE"
AG_OPERATIONS_SOURCE_PROFILE_ENV = "NEX_AG_OPERATIONS_SOURCE_PROFILE"
AG_OPERATIONS_SOURCE_SERVICES_ENV = "NEX_AG_OPERATIONS_SOURCE_SERVICES"
AG_OPERATIONS_SOURCE_MODES = ("memory", "postgres")
AG_OPERATIONS_SOURCE_PROFILES = ("dev", "test")
AG_OPERATION_SORT_ORDERS = ("desc", "asc")
MAX_OPERATION_EVENT_QUERY_LENGTH = 128

_AG_OPERATIONS_SOURCE_MODE_ALIASES = {
    "": "memory",
    "inmemory": "memory",
    "in-memory": "memory",
    "in_memory": "memory",
    "local_mock": "memory",
    "mock": "memory",
    "memory": "memory",
    "db": "postgres",
    "persistent": "postgres",
    "postgres": "postgres",
    "postgresql": "postgres",
    "sqlalchemy": "postgres",
}

EngineFactory = Callable[..., Any]
SessionFactoryBuilder = Callable[[Any], Any]


class OperationsSourceConfigError(ValueError):
    pass


class OperationsQueryError(ValueError):
    def __init__(
        self,
        *,
        error_code: str,
        detail: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class OperationQueryOptions:
    limit: int
    since: str | None = None
    until: str | None = None
    sort: str = "desc"
    cursor: str | None = None

    @property
    def offset(self) -> int:
        return int(self.cursor or "0")

    def to_filter_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "since": self.since,
            "until": self.until,
            "sort": self.sort,
            "cursor": self.cursor,
        }

    def pagination(self, *, total: int, returned: int) -> dict[str, Any]:
        next_offset = self.offset + returned
        return {
            "limit": self.limit,
            "cursor": self.cursor,
            "returned": returned,
            "total_after_filters": total,
            "next_cursor": str(next_offset) if next_offset < total else None,
        }


class ReadOnlyJobQueue:
    def __init__(self, delegate: JobQueue) -> None:
        self.delegate = delegate

    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.delegate.get_job(job_id)

    def start_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def complete_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def claim_next_job(
        self,
        worker_id: str,
        *,
        job_type: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        raise _operations_source_read_only_job_error()

    def list_jobs(
        self,
        *,
        job_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.delegate.list_jobs(job_type=job_type, status=status)


class ReadOnlyOperationalEventStore:
    def __init__(self, delegate: OperationalEventStore) -> None:
        self.delegate = delegate

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        raise OperationalEventError(
            error_code="ag.operations_source.read_only",
            detail="AG operations source registry is read-only.",
            status_code=405,
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        return self.delegate.get_event(event_id)

    def list_events(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.delegate.list_events(
            service_id=service_id,
            severity=severity,
            event_type=event_type,
            trace_id=trace_id,
            limit=limit,
        )


@dataclass(frozen=True)
class OperationsSource:
    service_id: str
    job_queue: JobQueue | None = None
    operational_event_store: OperationalEventStore | None = None
    source_kind: str = "memory"
    database_env: str | None = None
    redacted_database_url: str | None = None

    def __post_init__(self) -> None:
        if self.service_id not in SERVICE_SPECS:
            raise ValueError(f"unsupported operations source service: {self.service_id}")
        if not self.source_kind:
            raise ValueError("source_kind must be a non-empty string")
        if self.database_env is not None and not self.database_env:
            raise ValueError("database_env must be a non-empty string when provided")
        if self.redacted_database_url is not None and not self.redacted_database_url:
            raise ValueError(
                "redacted_database_url must be a non-empty string when provided"
            )

    def to_summary(self) -> dict[str, Any]:
        summary = {
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
        if self.database_env is not None:
            summary["database_env"] = self.database_env
        if self.redacted_database_url is not None:
            summary["redacted_database_url"] = self.redacted_database_url
        return summary


@dataclass(frozen=True)
class AgOperationsSourceRuntime:
    mode: str
    profile: str
    selected_service_ids: tuple[str, ...]
    registry: OperationsSourceRegistry | None = field(default=None, repr=False)

    def to_summary(self) -> dict[str, Any]:
        return {
            "runtime_schema_version": "ag_operations_source_runtime.v1",
            "mode": self.mode,
            "profile": self.profile,
            "selected_service_ids": list(self.selected_service_ids),
            "registry": (
                self.registry.to_summary()
                if self.registry is not None
                else None
            ),
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


def attach_ag_operations_source_runtime(
    app: FastAPI,
    *,
    environ: Mapping[str, str] | None = None,
    mode: str | None = None,
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> AgOperationsSourceRuntime:
    runtime = build_ag_operations_source_runtime(
        environ=environ,
        mode=mode,
        engine_factory=engine_factory,
        session_factory_builder=session_factory_builder,
    )
    app.state.nex_ag_operations_source_runtime = runtime
    return runtime


def build_ag_operations_source_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    mode: str | None = None,
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> AgOperationsSourceRuntime:
    env = environ if environ is not None else os.environ
    resolved_mode = normalize_ag_operations_source_mode(
        mode or env.get(AG_OPERATIONS_SOURCE_MODE_ENV)
    )
    profile = normalize_ag_operations_source_profile(
        env.get(AG_OPERATIONS_SOURCE_PROFILE_ENV)
    )
    selected_service_ids = select_ag_operations_source_service_ids(
        env.get(AG_OPERATIONS_SOURCE_SERVICES_ENV)
    )
    if resolved_mode == "memory":
        return AgOperationsSourceRuntime(
            mode=resolved_mode,
            profile=profile,
            selected_service_ids=selected_service_ids,
            registry=None,
        )

    registry = OperationsSourceRegistry()
    for service_id in selected_service_ids:
        registry.register(
            _build_postgres_operations_source(
                service_id=service_id,
                profile=profile,
                environ=env,
                engine_factory=engine_factory,
                session_factory_builder=session_factory_builder,
            )
        )
    return AgOperationsSourceRuntime(
        mode=resolved_mode,
        profile=profile,
        selected_service_ids=selected_service_ids,
        registry=registry,
    )


def normalize_ag_operations_source_mode(value: str | None) -> str:
    raw_value = "" if value is None else value.strip().lower()
    try:
        return _AG_OPERATIONS_SOURCE_MODE_ALIASES[raw_value]
    except KeyError as exc:
        raise OperationsSourceConfigError(
            "unsupported AG operations source mode: "
            f"{value}; expected one of {', '.join(AG_OPERATIONS_SOURCE_MODES)}"
        ) from exc


def normalize_ag_operations_source_profile(value: str | None) -> str:
    raw_value = "dev" if value is None or not value.strip() else value.strip().lower()
    if raw_value not in AG_OPERATIONS_SOURCE_PROFILES:
        raise OperationsSourceConfigError(
            "unsupported AG operations source profile: "
            f"{value}; expected one of {', '.join(AG_OPERATIONS_SOURCE_PROFILES)}"
        )
    return raw_value


def select_ag_operations_source_service_ids(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None or not raw_value.strip():
        return tuple(sorted(SERVICE_SPECS))
    selected = sorted(
        {
            service_id.strip()
            for service_id in raw_value.split(",")
            if service_id.strip()
        }
    )
    if not selected:
        raise OperationsSourceConfigError(
            f"{AG_OPERATIONS_SOURCE_SERVICES_ENV} selected no services"
        )
    unknown_services = [
        service_id
        for service_id in selected
        if service_id not in SERVICE_SPECS
    ]
    if unknown_services:
        raise OperationsSourceConfigError(
            f"unknown AG operations source services: {', '.join(unknown_services)}"
        )
    return tuple(selected)


def ag_operations_source_database_env(service_id: str, *, profile: str = "dev") -> str:
    if service_id not in SERVICE_SPECS:
        raise OperationsSourceConfigError(
            f"unknown AG operations source service: {service_id}"
        )
    normalized_profile = normalize_ag_operations_source_profile(profile)
    if normalized_profile == "dev":
        return SERVICE_SPECS[service_id].database_env
    try:
        return f"{service_database_env_prefix(service_id)}_TEST_DATABASE_URL"
    except ValueError as exc:
        raise OperationsSourceConfigError(str(exc)) from exc


def build_operation_query_options(
    *,
    limit: int,
    since: str | None = None,
    until: str | None = None,
    sort: str | None = None,
    cursor: str | None = None,
) -> OperationQueryOptions:
    normalized_limit = normalize_job_limit(limit)
    normalized_sort = normalize_operation_sort(sort)
    normalized_cursor = normalize_operation_cursor(cursor)
    normalized_since = normalize_operation_timestamp(since, field_name="since")
    normalized_until = normalize_operation_timestamp(until, field_name="until")
    if (
        normalized_since is not None
        and normalized_until is not None
        and _parse_operation_timestamp(normalized_since)
        > _parse_operation_timestamp(normalized_until)
    ):
        raise OperationsQueryError(
            error_code="ag.operation_time_window_invalid",
            detail="since must be less than or equal to until.",
        )
    return OperationQueryOptions(
        limit=normalized_limit,
        since=normalized_since,
        until=normalized_until,
        sort=normalized_sort,
        cursor=normalized_cursor,
    )


def normalize_operation_sort(value: str | None) -> str:
    normalized = "desc" if value is None or not value.strip() else value.strip().lower()
    if normalized not in AG_OPERATION_SORT_ORDERS:
        raise OperationsQueryError(
            error_code="ag.operation_sort_invalid",
            detail=(
                f"Unsupported operation sort: {value}; expected one of "
                f"{', '.join(AG_OPERATION_SORT_ORDERS)}."
            ),
        )
    return normalized


def normalize_operation_cursor(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw_value = value.strip()
    try:
        offset = int(raw_value)
    except ValueError as exc:
        raise OperationsQueryError(
            error_code="ag.operation_cursor_invalid",
            detail="cursor must be a non-negative integer offset.",
        ) from exc
    if offset < 0:
        raise OperationsQueryError(
            error_code="ag.operation_cursor_invalid",
            detail="cursor must be a non-negative integer offset.",
        )
    return str(offset)


def normalize_operation_timestamp(value: str | None, *, field_name: str) -> str | None:
    if value is None or not value.strip():
        return None
    raw_value = value.strip()
    parsed = _parse_operation_timestamp(raw_value, field_name=field_name)
    return parsed.isoformat().replace("+00:00", "Z")


def _build_postgres_operations_source(
    *,
    service_id: str,
    profile: str,
    environ: Mapping[str, str],
    engine_factory: EngineFactory,
    session_factory_builder: SessionFactoryBuilder,
) -> OperationsSource:
    database_env = ag_operations_source_database_env(service_id, profile=profile)
    try:
        database_url = required_database_url(database_env, environ)
        api_engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(
                service_id,
                workload="api",
                environ=environ,
            ),
        )
        worker_engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(
                service_id,
                workload="worker",
                environ=environ,
            ),
        )
    except ValueError as exc:
        raise OperationsSourceConfigError(
            f"invalid AG operations source database config for {service_id}: {exc}"
        ) from exc

    return OperationsSource(
        service_id=service_id,
        job_queue=ReadOnlyJobQueue(
            SqlAlchemyJobQueue(session_factory_builder(worker_engine))
        ),
        operational_event_store=ReadOnlyOperationalEventStore(
            SqlAlchemyOperationalEventStore(session_factory_builder(api_engine))
        ),
        source_kind="postgres-read",
        database_env=database_env,
        redacted_database_url=redact_database_url(database_url),
    )


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
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
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
        normalized_query = _normalize_event_search_query_or_problem(request, q)
        if isinstance(normalized_query, JSONResponse):
            return normalized_query

        return build_operational_event_projection(
            event_store,
            service_id=service_id,
            severity=severity,
            event_type=event_type,
            trace_id=trace_id,
            q=normalized_query,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/events/{event_id}", response_model=None)
    def get_operational_event_detail(
        event_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        event = event_store.get_event(event_id)
        if event is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.operational_event_not_found",
                title="Operational event not found",
                detail=f"Operational event was not found: {event_id}",
                type_uri="https://nex-platform.local/problems/operational-event-not-found",
            )
        return build_operational_event_detail_projection(
            event,
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


def register_operation_source_readiness_routes(
    app: FastAPI,
    *,
    runtime: AgOperationsSourceRuntime | None = None,
) -> None:
    @app.get("/admin/v1/operations/sources", response_model=None)
    def list_operation_source_readiness(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        if service_id is not None and service_id not in SERVICE_SPECS:
            return problem_response(
                request,
                status_code=400,
                error_code="ag.operation_source_service_invalid",
                title="Invalid operation source service filter",
                detail=f"Unsupported operation source service: {service_id}",
                type_uri="https://nex-platform.local/problems/operation-source-service-invalid",
            )
        selected_runtime = runtime or getattr(
            request.app.state,
            "nex_ag_operations_source_runtime",
            None,
        )
        return build_operation_source_readiness_projection(
            runtime=selected_runtime,
            service_id=service_id,
            request_trace_id=trace_id_from_headers(request),
        )


def register_job_operation_routes(
    app: FastAPI,
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
) -> None:
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

    @app.get("/admin/v1/operations/jobs", response_model=None)
    def list_operational_jobs(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
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

        return build_job_operations_projection(
            queue_stores,
            service_id=service_id,
            status=status,
            job_type=job_type,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/jobs/{service_id}/{job_id}", response_model=None)
    def get_operational_job_detail(
        service_id: str,
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        filter_problem = _validate_job_operation_filters(
            request,
            service_id=service_id,
            status=None,
        )
        if filter_problem is not None:
            return filter_problem

        queue = queue_stores.get(service_id)
        if queue is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.job_source_not_configured",
                title="Job source not configured",
                detail=f"AG has no job source configured for service: {service_id}",
                type_uri="https://nex-platform.local/problems/job-source-not-configured",
            )
        try:
            job = queue.get_job(job_id)
        except JobQueueError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Job source unavailable",
                detail=exc.detail,
                type_uri="https://nex-platform.local/problems/job-source-unavailable",
            )
        if job is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.job_not_found",
                title="Job not found",
                detail=f"Job was not found for {service_id}: {job_id}",
                type_uri="https://nex-platform.local/problems/job-not-found",
            )
        return build_job_operation_detail_projection(
            job,
            service_id=service_id,
            event_store=selected_event_store,
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
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
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
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )


def build_operational_event_projection(
    store: OperationalEventStore,
    *,
    service_id: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    trace_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
    events = store.list_events(
        service_id=service_id,
        severity=severity,
        event_type=event_type,
        trace_id=trace_id,
        limit=normalize_operational_event_limit(500),
    )
    if q is not None:
        events = [
            event
            for event in events
            if _operational_event_matches_query(event, q)
        ]
    events = _apply_operation_query_options(
        events,
        options,
        timestamp_field="created_at",
        tie_breaker_fields=("event_id",),
    )
    projection = {
        "projection_schema_version": "ag_operational_event_projection.v1",
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "severity": severity.upper() if severity is not None else None,
            "event_type": event_type,
            "trace_id": trace_id,
            "q": q,
            **options.to_filter_dict(),
        },
        "events": events["items"],
        "summary": summarize_operational_events(events["items"]),
        "pagination": events["pagination"],
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_operational_event_detail_projection(
    event: dict[str, Any],
    *,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projection = {
        "projection_schema_version": "ag_operational_event_detail_projection.v1",
        "checked_at": _utc_now(),
        "event": deepcopy(event),
        "summary": {
            "event_id": event["event_id"],
            "service_id": event["service_id"],
            "event_type": event["event_type"],
            "severity": event["severity"],
            "trace_id": event.get("trace_id"),
            "subject_ref": deepcopy(event.get("subject_ref")),
            "created_at": event["created_at"],
        },
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


def build_operation_source_readiness_projection(
    *,
    runtime: AgOperationsSourceRuntime | None,
    service_id: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    selected_runtime = runtime or AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=tuple(sorted(SERVICE_SPECS)),
        registry=None,
    )
    source_statuses = _operation_source_statuses(
        selected_runtime,
        service_id=service_id,
    )
    projection = {
        "projection_schema_version": "ag_operation_source_readiness_projection.v1",
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
        },
        "runtime": selected_runtime.to_summary(),
        "sources": source_statuses,
        "summary": summarize_operation_source_readiness(source_statuses),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_operation_source_readiness(
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_source_kind: dict[str, int] = {}
    read_only_count = 0
    for source in sources:
        status = str(source["readiness_status"])
        source_kind = str(source["source_kind"])
        by_status[status] = by_status.get(status, 0) + 1
        by_source_kind[source_kind] = by_source_kind.get(source_kind, 0) + 1
        if source["read_only"] is True:
            read_only_count += 1
    return {
        "total": len(sources),
        "by_status": by_status,
        "by_source_kind": by_source_kind,
        "read_only": read_only_count,
    }


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
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
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
        query_options=options,
    )
    event_projection = build_operational_event_projection(
        selected_event_store,
        service_id=service_id,
        severity=event_severity,
        event_type=event_type,
        trace_id=trace_id,
        query_options=options,
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
            **options.to_filter_dict(),
        },
        "jobs": job_projection,
        "events": event_projection,
        "summary": {
            "jobs": job_projection["summary"],
            "events": event_projection["summary"],
            "source_statuses": job_projection["source_statuses"],
        },
        "pagination": {
            "jobs": job_projection["pagination"],
            "events": event_projection["pagination"],
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
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
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
        service_jobs = _filter_records_by_operation_time(
            service_jobs,
            options,
            timestamp_field="updated_at",
        )
        source_statuses[selected_service_id] = {
            "status": "READY",
            "job_count": len(service_jobs),
        }
        projected_jobs.extend(
            _project_job_for_service(selected_service_id, job)
            for job in service_jobs
        )

    page = _apply_operation_query_options(
        projected_jobs,
        options,
        timestamp_field="updated_at",
        tie_breaker_fields=("created_at", "service_id", "job_id"),
    )
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
            **options.to_filter_dict(),
        },
        "jobs": page["items"],
        "summary": summarize_job_operations(page["items"]),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_job_operation_detail_projection(
    job: dict[str, Any],
    *,
    service_id: str,
    event_store: OperationalEventStore | None = None,
    event_limit: int = 50,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    lifecycle_timeline = _build_job_lifecycle_timeline(
        job,
        service_id=service_id,
        event_store=event_store,
        event_limit=event_limit,
    )
    projection = {
        "projection_schema_version": "ag_job_operation_detail_projection.v1",
        "checked_at": _utc_now(),
        "service_id": service_id,
        "job": _project_job_for_service(service_id, job),
        "lifecycle_timeline": lifecycle_timeline,
        "summary": {
            "service_id": service_id,
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "trace_id": job["trace_id"],
            "subject_ref": deepcopy(job.get("subject_ref")),
            "attempt_count": job["attempt_count"],
            "timeline_status": lifecycle_timeline["timeline_status"],
            "timeline_event_count": lifecycle_timeline["event_count"],
        },
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
            title="Invalid operations query",
            detail=exc.detail,
            type_uri="https://nex-platform.local/problems/operations-query-invalid",
        )


def _normalize_event_search_query_or_problem(
    request: Request,
    value: str | None,
) -> str | None | JSONResponse:
    try:
        return normalize_operation_event_search_query(value)
    except OperationsQueryError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Invalid operational event search query",
            detail=exc.detail,
            type_uri="https://nex-platform.local/problems/operational-event-query-invalid",
        )


def normalize_operation_event_search_query(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > MAX_OPERATION_EVENT_QUERY_LENGTH:
        raise OperationsQueryError(
            error_code="ag.operation_event_query_invalid",
            detail=(
                "operational event search query must be "
                f"{MAX_OPERATION_EVENT_QUERY_LENGTH} characters or fewer."
            ),
        )
    return normalized


def _operation_source_statuses(
    runtime: AgOperationsSourceRuntime,
    *,
    service_id: str | None,
) -> list[dict[str, Any]]:
    selected_service_ids = (
        [service_id]
        if service_id is not None
        else list(runtime.selected_service_ids)
    )
    return [
        _operation_source_status(runtime, selected_service_id)
        for selected_service_id in selected_service_ids
    ]


def _operation_source_status(
    runtime: AgOperationsSourceRuntime,
    service_id: str,
) -> dict[str, Any]:
    source = runtime.registry.get(service_id) if runtime.registry is not None else None
    if source is None and runtime.registry is None and runtime.mode == "memory":
        return {
            "service_id": service_id,
            "readiness_status": "DEFAULT_MEMORY",
            "configured": False,
            "source_kind": "memory-default",
            "capabilities": {
                "jobs": True,
                "events": True,
            },
            "read_only": False,
            "job_queue": "InMemoryJobQueue",
            "operational_event_store": "InMemoryOperationalEventStore",
            "database_env": None,
            "redacted_database_url": None,
        }
    if source is None:
        return {
            "service_id": service_id,
            "readiness_status": "NOT_CONFIGURED",
            "configured": False,
            "source_kind": "none",
            "capabilities": {
                "jobs": False,
                "events": False,
            },
            "read_only": None,
            "job_queue": None,
            "operational_event_store": None,
            "database_env": None,
            "redacted_database_url": None,
        }
    source_summary = source.to_summary()
    return {
        "service_id": service_id,
        "readiness_status": "READY",
        "configured": True,
        "source_kind": source.source_kind,
        "capabilities": source_summary["capabilities"],
        "read_only": _operation_source_is_read_only(source),
        "job_queue": source_summary["job_queue"],
        "operational_event_store": source_summary["operational_event_store"],
        "database_env": source_summary.get("database_env"),
        "redacted_database_url": source_summary.get("redacted_database_url"),
    }


def _operation_source_is_read_only(source: OperationsSource) -> bool:
    job_read_only = (
        source.job_queue is None
        or isinstance(source.job_queue, ReadOnlyJobQueue)
    )
    event_read_only = (
        source.operational_event_store is None
        or isinstance(source.operational_event_store, ReadOnlyOperationalEventStore)
    )
    return job_read_only and event_read_only


def _operations_source_read_only_job_error() -> JobQueueError:
    return JobQueueError(
        error_code="ag.operations_source.read_only",
        detail="AG operations source registry is read-only.",
        status_code=405,
    )


def _apply_operation_query_options(
    records: list[dict[str, Any]],
    options: OperationQueryOptions,
    *,
    timestamp_field: str,
    tie_breaker_fields: tuple[str, ...],
) -> dict[str, Any]:
    filtered = _filter_records_by_operation_time(
        records,
        options,
        timestamp_field=timestamp_field,
    )
    reverse = options.sort == "desc"
    filtered.sort(
        key=lambda record: (
            _operation_record_timestamp(record, timestamp_field=timestamp_field),
            *[str(record.get(field, "")) for field in tie_breaker_fields],
        ),
        reverse=reverse,
    )
    offset = options.offset
    items = filtered[offset : offset + options.limit]
    return {
        "items": items,
        "pagination": options.pagination(total=len(filtered), returned=len(items)),
    }


def _filter_records_by_operation_time(
    records: list[dict[str, Any]],
    options: OperationQueryOptions,
    *,
    timestamp_field: str,
) -> list[dict[str, Any]]:
    since_dt = (
        _parse_operation_timestamp(options.since)
        if options.since is not None
        else None
    )
    until_dt = (
        _parse_operation_timestamp(options.until)
        if options.until is not None
        else None
    )
    filtered: list[dict[str, Any]] = []
    for record in records:
        timestamp = _operation_record_timestamp(record, timestamp_field=timestamp_field)
        if since_dt is not None and timestamp < since_dt:
            continue
        if until_dt is not None and timestamp > until_dt:
            continue
        filtered.append(record)
    return filtered


def _operation_record_timestamp(
    record: dict[str, Any],
    *,
    timestamp_field: str,
) -> datetime:
    value = record.get(timestamp_field)
    if value is None and timestamp_field == "updated_at":
        value = record.get("created_at")
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return _parse_operation_timestamp(str(value), field_name=timestamp_field)


def _parse_operation_timestamp(
    value: str,
    *,
    field_name: str = "timestamp",
) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsQueryError(
            error_code="ag.operation_timestamp_invalid",
            detail=f"{field_name} must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _operational_event_matches_query(event: dict[str, Any], query: str) -> bool:
    lowered_query = query.lower()
    searchable_parts = [
        event.get("event_id"),
        event.get("service_id"),
        event.get("event_type"),
        event.get("severity"),
        event.get("message"),
        event.get("trace_id"),
        event.get("request_id"),
    ]
    subject_ref = event.get("subject_ref")
    if isinstance(subject_ref, Mapping):
        searchable_parts.extend(subject_ref.values())
    details = event.get("details")
    if isinstance(details, Mapping):
        searchable_parts.append(
            json.dumps(details, ensure_ascii=False, sort_keys=True)
        )
    return any(
        lowered_query in str(part).lower()
        for part in searchable_parts
        if part is not None
    )


def _build_job_lifecycle_timeline(
    job: dict[str, Any],
    *,
    service_id: str,
    event_store: OperationalEventStore | None,
    event_limit: int,
) -> dict[str, Any]:
    normalized_event_limit = normalize_operational_event_limit(event_limit)
    if event_store is None:
        return {
            "timeline_status": "NOT_CONFIGURED",
            "event_count": 0,
            "events": [],
            "source_error": None,
        }
    try:
        events = event_store.list_events(
            service_id=service_id,
            trace_id=str(job["trace_id"]),
            limit=normalized_event_limit,
        )
    except OperationalEventError as exc:
        return {
            "timeline_status": "UNAVAILABLE",
            "event_count": 0,
            "events": [],
            "source_error": {
                "error_code": exc.error_code,
                "detail": exc.detail,
                "status_code": exc.status_code,
            },
        }
    lifecycle_events = [
        event
        for event in events
        if _operational_event_matches_job(job, event)
    ]
    lifecycle_events.sort(
        key=lambda event: (
            _operation_record_timestamp(event, timestamp_field="created_at"),
            str(event.get("event_id", "")),
        )
    )
    lifecycle_events = lifecycle_events[:normalized_event_limit]
    return {
        "timeline_status": "READY",
        "event_count": len(lifecycle_events),
        "events": lifecycle_events,
        "source_error": None,
    }


def _operational_event_matches_job(
    job: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    details = event.get("details")
    if isinstance(details, Mapping) and details.get("job_id") == job.get("job_id"):
        return True
    return _subject_refs_match(event.get("subject_ref"), job.get("subject_ref"))


def _subject_refs_match(left: object, right: object) -> bool:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    return left.get("type") == right.get("type") and left.get("id") == right.get("id")


def _project_job_for_service(service_id: str, job: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(job)
    projected["service_id"] = service_id
    return projected


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
