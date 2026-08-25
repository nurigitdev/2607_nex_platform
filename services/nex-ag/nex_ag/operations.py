from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    AG_JOB_CONTROL_EVENT_FAILED,
    AG_JOB_CONTROL_EVENT_SUCCEEDED,
    DEFAULT_WORKER_STALE_AFTER_SECONDS,
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_OPERATIONAL_EVENT_TAXONOMY,
    DEFAULT_SERVICE_LOG_LIMIT,
    DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    InMemoryWorkerHeartbeatStore,
    JOB_STATUSES,
    JobQueue,
    JobQueueError,
    OPERATIONAL_EVENT_SEVERITIES,
    OperationalEventStore,
    OperationalEventError,
    OperationalEventEmitResult,
    OperationalEventEmitter,
    OperationalEventTypeSpec,
    MAX_SERVICE_LOG_LIMIT,
    DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
    REDACTED_LOG_VALUE,
    SERVICE_SPECS,
    SERVICE_LOG_SEVERITIES,
    SERVICE_LOG_RETENTION_EXECUTION_MODES,
    SERVICE_LOG_RETENTION_EXECUTION_STATUSES,
    SENSITIVE_LOG_ATTRIBUTE_KEY_PARTS,
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    SqlAlchemyServiceLogStore,
    SqlAlchemyWorkerHeartbeatStore,
    ServiceLogError,
    ServiceLogStore,
    WORKER_HEARTBEAT_STATUSES,
    WorkerHeartbeatError,
    WorkerHeartbeatStore,
    build_engine,
    build_session_factory,
    database_pool_settings,
    list_operational_event_taxonomy,
    normalize_job_limit,
    normalize_operational_event_limit,
    normalize_service_log_limit,
    normalize_service_log_retention_history_limit,
    problem_response,
    redact_database_url,
    required_database_url,
    request_id_from_headers,
    service_database_env_prefix,
    normalize_worker_stale_after_seconds,
    summarize_operational_event_taxonomy,
    summarize_jobs,
    summarize_operational_events,
    summarize_service_log_retention_history,
    summarize_service_logs,
    summarize_worker_heartbeats,
    trace_id_from_headers,
    validate_authorization_header,
    worker_heartbeat_is_stale,
)
from nex_ag.job_control import (
    AgJobControlClient,
    AgJobControlError,
    build_default_ag_job_control_client,
)
from nex_ag.service_log_retention import (
    AgServiceLogRetentionClient,
    AgServiceLogRetentionError,
    build_default_ag_service_log_retention_client,
)
from nex_ag.retrieval_score_calibration import (
    build_retrieval_score_calibration_projection,
    summarize_retrieval_score_calibration_samples,
)
from nex_ag.retrieval_threshold_decisions import (
    project_retrieval_threshold_decision,
    summarize_retrieval_threshold_calibration_closure,
    summarize_retrieval_threshold_decisions,
)
from nex_runtime.retrieval_policies import list_retrieval_policy_records

DEFAULT_OPERATIONAL_EVENT_STORE = InMemoryOperationalEventStore()
DEFAULT_JOB_QUEUE_STORES = {
    service_id: InMemoryJobQueue() for service_id in sorted(SERVICE_SPECS)
}
DEFAULT_SERVICE_LOG_STORES = {
    service_id: InMemoryServiceLogStore() for service_id in sorted(SERVICE_SPECS)
}
DEFAULT_WORKER_HEARTBEAT_STORES = {
    service_id: InMemoryWorkerHeartbeatStore() for service_id in sorted(SERVICE_SPECS)
}

AG_OPERATIONS_SOURCE_MODE_ENV = "NEX_AG_OPERATIONS_SOURCE_MODE"
AG_OPERATIONS_SOURCE_PROFILE_ENV = "NEX_AG_OPERATIONS_SOURCE_PROFILE"
AG_OPERATIONS_SOURCE_SERVICES_ENV = "NEX_AG_OPERATIONS_SOURCE_SERVICES"
AG_OPERATIONS_SOURCE_MODES = ("memory", "postgres")
AG_OPERATIONS_SOURCE_PROFILES = ("dev", "test")
AG_OPERATION_SORT_ORDERS = ("desc", "asc")
AG_JOB_CONTROL_DISPATCH_SCHEMA_VERSION = "ag_job_control_dispatch.v1"
AG_SERVICE_LOG_QUERY_POLICY_PROJECTION_SCHEMA_VERSION = (
    "ag_service_log_query_policy_projection.v1"
)
AG_SERVICE_LOG_RETENTION_DRY_RUN_PROJECTION_SCHEMA_VERSION = (
    "ag_service_log_retention_dry_run_projection.v1"
)
AG_SERVICE_LOG_RETENTION_DISPATCH_SCHEMA_VERSION = (
    "ag_service_log_retention_dispatch.v1"
)
AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION = (
    "ag_service_log_retention_history_projection.v1"
)
AG_GENERATION_QUALITY_ISSUE_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_generation_quality_issue_detail_projection.v1"
)
AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED = "ag.service_log_retention.succeeded"
AG_SERVICE_LOG_RETENTION_EVENT_FAILED = "ag.service_log_retention.failed"
SERVICE_LOG_QUERY_POLICY_SCHEMA_VERSION = "service_log_query_policy.v1"
SERVICE_LOG_QUERY_POLICY_ID = "service-log-query-retention-v1"
SERVICE_LOG_QUERY_SUPPORTED_FILTERS = (
    "service_id",
    "severity",
    "logger_name",
    "trace_id",
    "request_id",
    "job_id",
    "subject_type",
    "subject_id",
    "q",
    "since",
    "until",
    "sort",
    "cursor",
    "limit",
)
DEFAULT_SERVICE_LOG_RETENTION_DAYS = 30
RETRIEVAL_THRESHOLD_SOURCE_SERVICE_ID = "nex-cx"


class RetrievalPackageTraceStore(Protocol):
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
        limit: int = 500,
    ) -> list[dict[str, Any]]: ...


class CxProcessingRunDashboardStore(Protocol):
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
        limit: int = 500,
    ) -> list[dict[str, Any]]: ...


class GenerationRemediationTaskDashboardStore(Protocol):
    source_kind: str
    database_env: str | None
    redacted_database_url: str | None

    def list_recent(self, *, limit: int = 500) -> list[dict[str, Any]]: ...


MIN_SERVICE_LOG_RETENTION_DAYS = 7
MAX_SERVICE_LOG_RETENTION_DAYS = 365
MAX_OPERATION_EVENT_QUERY_LENGTH = 128
MAX_DASHBOARD_RECENT_LIMIT = 20
GENERATION_QUALITY_STATUSES = ("PASS", "WARN", "FAIL", "NOT_REQUIRED", "UNKNOWN")
GENERATION_QUALITY_ATTENTION_STATUSES = {"WARN", "FAIL", "UNKNOWN"}
GENERATION_REMEDIATION_TERMINAL_STATUSES = {"COMPLETED", "CANCELLED"}
GENERATION_REMEDIATION_ACTIVE_STATUSES = {
    "PROPOSED",
    "ASSIGNED",
    "IN_PROGRESS",
    "WAITING_ON_CX",
}
OPERATIONS_ISSUE_CANDIDATE_RULES = (
    {
        "rule_id": "operations_source_unavailable.v1",
        "severity": "ERROR",
        "title": "Operations source unavailable",
        "description": "A configured operations source could not be read.",
        "enabled": True,
        "signal_type": "source_status",
    },
    {
        "rule_id": "operations_source_not_configured.v1",
        "severity": "WARNING",
        "title": "Operations source not configured",
        "description": "A selected service is missing an operations source.",
        "enabled": True,
        "signal_type": "source_status",
    },
    {
        "rule_id": "failed_jobs_present.v1",
        "severity": "ERROR",
        "title": "Failed jobs observed",
        "description": "One or more failed jobs were observed in the selected window.",
        "enabled": True,
        "signal_type": "job_status",
    },
    {
        "rule_id": "dead_letter_replay_available.v1",
        "severity": "WARNING",
        "title": "Dead-letter replay available",
        "description": "One or more failed dead-letter jobs can be replayed.",
        "enabled": True,
        "signal_type": "job_control",
    },
    {
        "rule_id": "error_events_present.v1",
        "severity": "ERROR",
        "title": "Error events observed",
        "description": "One or more ERROR operational events were observed.",
        "enabled": True,
        "signal_type": "event_severity",
    },
    {
        "rule_id": "critical_events_present.v1",
        "severity": "CRITICAL",
        "title": "Critical events observed",
        "description": "One or more CRITICAL operational events were observed.",
        "enabled": True,
        "signal_type": "event_severity",
    },
    {
        "rule_id": "error_service_logs_present.v1",
        "severity": "ERROR",
        "title": "Error service logs observed",
        "description": "One or more ERROR structured service logs were observed.",
        "enabled": True,
        "signal_type": "service_log_severity",
    },
    {
        "rule_id": "critical_service_logs_present.v1",
        "severity": "CRITICAL",
        "title": "Critical service logs observed",
        "description": "One or more CRITICAL structured service logs were observed.",
        "enabled": True,
        "signal_type": "service_log_severity",
    },
    {
        "rule_id": "active_jobs_review.v1",
        "severity": "INFO",
        "title": "Active jobs need review",
        "description": "One or more QUEUED or RUNNING jobs are active in the selected window.",
        "enabled": True,
        "signal_type": "job_status",
    },
    {
        "rule_id": "stale_worker_heartbeat.v1",
        "severity": "WARNING",
        "title": "Stale worker heartbeat observed",
        "description": "One or more worker heartbeats exceeded the configured stale threshold.",
        "enabled": True,
        "signal_type": "worker_heartbeat",
    },
    {
        "rule_id": "active_job_without_fresh_worker.v1",
        "severity": "WARNING",
        "title": "Active job missing fresh worker",
        "description": "One or more RUNNING jobs have no fresh BUSY worker heartbeat.",
        "enabled": True,
        "signal_type": "job_worker_reconciliation",
    },
    {
        "rule_id": "retrieval_threshold_decision_checkpoint_missing.v1",
        "severity": "WARNING",
        "title": "Retrieval threshold checkpoint missing",
        "description": "A retrieval policy is missing its threshold decision checkpoint.",
        "enabled": True,
        "signal_type": "retrieval_threshold_decision",
    },
    {
        "rule_id": "retrieval_threshold_live_samples_insufficient.v1",
        "severity": "INFO",
        "title": "Retrieval threshold samples insufficient",
        "description": "A retrieval threshold decision needs more live score samples.",
        "enabled": True,
        "signal_type": "retrieval_threshold_decision",
    },
    {
        "rule_id": "retrieval_threshold_operator_review_required.v1",
        "severity": "WARNING",
        "title": "Retrieval threshold operator review required",
        "description": "A retrieval threshold decision has samples that need operator review.",
        "enabled": True,
        "signal_type": "retrieval_threshold_decision",
    },
    {
        "rule_id": "retrieval_threshold_policy_review_ready.v1",
        "severity": "INFO",
        "title": "Retrieval threshold policy review ready",
        "description": "A retrieval threshold decision has enough samples for policy review.",
        "enabled": True,
        "signal_type": "retrieval_threshold_decision",
    },
    {
        "rule_id": "generation_quality_attention_required.v1",
        "severity": "WARNING",
        "title": "Generation quality attention required",
        "description": "One or more grounded generation quality projections need review.",
        "enabled": True,
        "signal_type": "generation_quality",
    },
    {
        "rule_id": "generation_remediation_attention_required.v1",
        "severity": "WARNING",
        "title": "Generation remediation attention required",
        "description": "One or more generation remediation tasks need operator review.",
        "enabled": True,
        "signal_type": "generation_remediation",
    },
)
RETRIEVAL_THRESHOLD_ISSUE_RULES_BY_READINESS = {
    "NO_DECISION_CHECKPOINT": {
        "rule_id": "retrieval_threshold_decision_checkpoint_missing.v1",
        "severity": "WARNING",
        "title": "Retrieval threshold checkpoint missing",
    },
    "INSUFFICIENT_SAMPLES": {
        "rule_id": "retrieval_threshold_live_samples_insufficient.v1",
        "severity": "INFO",
        "title": "Retrieval threshold samples insufficient",
    },
    "NEEDS_OPERATOR_REVIEW": {
        "rule_id": "retrieval_threshold_operator_review_required.v1",
        "severity": "WARNING",
        "title": "Retrieval threshold operator review required",
    },
    "READY_FOR_REVIEW": {
        "rule_id": "retrieval_threshold_policy_review_ready.v1",
        "severity": "INFO",
        "title": "Retrieval threshold policy review ready",
    },
}
RETRIEVAL_THRESHOLD_ISSUE_READINESS_ORDER = (
    "NO_DECISION_CHECKPOINT",
    "INSUFFICIENT_SAMPLES",
    "NEEDS_OPERATOR_REVIEW",
    "READY_FOR_REVIEW",
)

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

    def start_job(
        self, job_id: str, *, updated_at: str | None = None
    ) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def complete_job(
        self, job_id: str, *, updated_at: str | None = None
    ) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def fail_job(self, job_id: str, *, updated_at: str | None = None) -> dict[str, Any]:
        raise _operations_source_read_only_job_error()

    def cancel_job(
        self, job_id: str, *, updated_at: str | None = None
    ) -> dict[str, Any]:
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


class ReadOnlyServiceLogStore:
    def __init__(self, delegate: ServiceLogStore) -> None:
        self.delegate = delegate

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        raise ServiceLogError(
            error_code="ag.operations_source.read_only",
            detail="AG operations source registry is read-only.",
            status_code=405,
        )

    def get_log(self, log_id: str) -> dict[str, Any] | None:
        return self.delegate.get_log(log_id)

    def list_logs(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    ) -> list[dict[str, Any]]:
        return self.delegate.list_logs(
            service_id=service_id,
            severity=severity,
            logger_name=logger_name,
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            subject_type=subject_type,
            subject_id=subject_id,
            limit=limit,
        )


class ReadOnlyWorkerHeartbeatStore:
    def __init__(self, delegate: WorkerHeartbeatStore) -> None:
        self.delegate = delegate

    def upsert_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        raise WorkerHeartbeatError(
            error_code="ag.operations_source.read_only",
            detail="AG operations source registry is read-only.",
            status_code=405,
        )

    def get_heartbeat(self, service_id: str, worker_id: str) -> dict[str, Any] | None:
        return self.delegate.get_heartbeat(service_id, worker_id)

    def list_heartbeats(
        self,
        *,
        service_id: str | None = None,
        worker_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.delegate.list_heartbeats(
            service_id=service_id,
            worker_type=worker_type,
            status=status,
        )


@dataclass(frozen=True)
class OperationsSource:
    service_id: str
    job_queue: JobQueue | None = None
    operational_event_store: OperationalEventStore | None = None
    service_log_store: ServiceLogStore | None = None
    worker_heartbeat_store: WorkerHeartbeatStore | None = None
    source_kind: str = "memory"
    database_env: str | None = None
    redacted_database_url: str | None = None

    def __post_init__(self) -> None:
        if self.service_id not in SERVICE_SPECS:
            raise ValueError(
                f"unsupported operations source service: {self.service_id}"
            )
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
            "service_log_store": (
                self.service_log_store.__class__.__name__
                if self.service_log_store is not None
                else None
            ),
            "worker_heartbeat_store": (
                self.worker_heartbeat_store.__class__.__name__
                if self.worker_heartbeat_store is not None
                else None
            ),
            "capabilities": {
                "jobs": self.job_queue is not None,
                "events": self.operational_event_store is not None,
                "logs": self.service_log_store is not None,
                "workers": self.worker_heartbeat_store is not None,
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
                self.registry.to_summary() if self.registry is not None else None
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

    def service_log_stores(self) -> dict[str, ServiceLogStore]:
        return {
            service_id: source.service_log_store
            for service_id, source in self.sources.items()
            if source.service_log_store is not None
        }

    def worker_heartbeat_stores(self) -> dict[str, WorkerHeartbeatStore]:
        return {
            service_id: source.worker_heartbeat_store
            for service_id, source in self.sources.items()
            if source.worker_heartbeat_store is not None
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
        selected_service_ids = (
            [service_id] if service_id is not None else sorted(SERVICE_SPECS)
        )
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


class RegistryServiceLogStore:
    def __init__(self, registry: OperationsSourceRegistry) -> None:
        self.registry = registry

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        raise ServiceLogError(
            error_code="ag.operations_registry.read_only",
            detail="AG operations registry service log store is read-only.",
            status_code=405,
        )

    def get_log(self, log_id: str) -> dict[str, Any] | None:
        for store in self.registry.service_log_stores().values():
            entry = store.get_log(log_id)
            if entry is not None:
                return entry
        return None

    def list_logs(
        self,
        *,
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    ) -> list[dict[str, Any]]:
        normalized_limit = normalize_service_log_limit(limit)
        stores = self.registry.service_log_stores()
        selected_service_ids = (
            [service_id] if service_id is not None else sorted(SERVICE_SPECS)
        )
        logs: list[dict[str, Any]] = []
        for selected_service_id in selected_service_ids:
            store = stores.get(selected_service_id)
            if store is None:
                continue
            logs.extend(
                store.list_logs(
                    service_id=selected_service_id,
                    severity=severity,
                    logger_name=logger_name,
                    trace_id=trace_id,
                    request_id=request_id,
                    job_id=job_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    limit=normalized_limit,
                )
            )
        logs.sort(
            key=lambda entry: (
                str(entry.get("observed_at", "")),
                str(entry.get("log_id", "")),
            ),
            reverse=True,
        )
        return logs[:normalized_limit]


def build_operations_source_registry(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_stores: Mapping[str, OperationalEventStore] | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None = None,
    source_kind: str = "memory",
) -> OperationsSourceRegistry:
    queue_map = job_queues or {}
    event_store_map = event_stores or {}
    log_store_map = service_log_stores or {}
    worker_store_map = worker_heartbeat_stores or {}
    source_ids = sorted(
        set(queue_map)
        | set(event_store_map)
        | set(log_store_map)
        | set(worker_store_map)
    )
    registry = OperationsSourceRegistry()
    for service_id in source_ids:
        registry.register(
            OperationsSource(
                service_id=service_id,
                job_queue=queue_map.get(service_id),
                operational_event_store=event_store_map.get(service_id),
                service_log_store=log_store_map.get(service_id),
                worker_heartbeat_store=worker_store_map.get(service_id),
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
        service_id for service_id in selected if service_id not in SERVICE_SPECS
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

    worker_session_factory = session_factory_builder(worker_engine)
    api_session_factory = session_factory_builder(api_engine)
    return OperationsSource(
        service_id=service_id,
        job_queue=ReadOnlyJobQueue(SqlAlchemyJobQueue(worker_session_factory)),
        operational_event_store=ReadOnlyOperationalEventStore(
            SqlAlchemyOperationalEventStore(api_session_factory)
        ),
        service_log_store=ReadOnlyServiceLogStore(
            SqlAlchemyServiceLogStore(api_session_factory)
        ),
        worker_heartbeat_store=ReadOnlyWorkerHeartbeatStore(
            SqlAlchemyWorkerHeartbeatStore(worker_session_factory)
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
        if (
            severity is not None
            and severity.upper() not in OPERATIONAL_EVENT_SEVERITIES
        ):
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


def register_service_log_routes(
    app: FastAPI,
    *,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    retention_control_client: AgServiceLogRetentionClient | None = None,
    audit_event_store: OperationalEventStore | None = None,
) -> None:
    control_client = (
        retention_control_client or build_default_ag_service_log_retention_client()
    )
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or DEFAULT_OPERATIONAL_EVENT_STORE,
    )

    @app.get("/admin/v1/operations/logs", response_model=None)
    def list_service_logs(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        severity: str | None = None,
        logger_name: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
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
        filter_problem = _validate_service_log_filters(
            request,
            service_id=service_id,
            severity=severity,
            logger_name=logger_name,
            subject_type=subject_type,
            subject_id=subject_id,
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
        normalized_query = _normalize_log_search_query_or_problem(request, q)
        if isinstance(normalized_query, JSONResponse):
            return normalized_query

        return build_service_log_projection(
            service_log_stores=service_log_stores,
            registry=registry,
            service_id=service_id,
            severity=severity,
            logger_name=logger_name,
            trace_id=trace_id,
            request_id=request_id,
            job_id=job_id,
            subject_type=subject_type,
            subject_id=subject_id,
            q=normalized_query,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/logs/policy", response_model=None)
    def get_service_log_query_policy(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        return build_service_log_query_policy_projection(
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/logs/retention/dry-run", response_model=None)
    def get_service_log_retention_dry_run(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        retention_days: int = Query(default=DEFAULT_SERVICE_LOG_RETENTION_DAYS, ge=1),
        limit: int = Query(default=DEFAULT_SERVICE_LOG_LIMIT, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_service_log_filters(
            request,
            service_id=service_id,
            severity=None,
            logger_name=None,
            subject_type=None,
            subject_id=None,
        )
        if filter_problem is not None:
            return filter_problem
        return build_service_log_retention_dry_run_projection(
            service_log_stores=service_log_stores,
            registry=registry,
            service_id=service_id,
            retention_days=retention_days,
            limit=limit,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/logs/retention/history", response_model=None)
    def list_service_log_retention_history(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        mode: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_service_log_filters(
            request,
            service_id=service_id,
            severity=None,
            logger_name=None,
            subject_type=None,
            subject_id=None,
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
        try:
            return build_service_log_retention_history_projection(
                service_log_stores=service_log_stores,
                registry=registry,
                service_id=service_id,
                mode=mode,
                execution_status=execution_status,
                trace_id=trace_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                query_options=query_options,
                request_trace_id=trace_id_from_headers(request),
            )
        except ServiceLogError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Service log retention history query failed",
                detail=exc.detail,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "service-log-retention-history-query-failed"
                ),
            )

    @app.post(
        "/admin/v1/operations/logs/retention/{service_id}/purge", response_model=None
    )
    def dispatch_service_log_retention_purge(
        service_id: str,
        request: Request,
        payload: dict[str, Any] | None = None,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        filter_problem = _validate_service_log_filters(
            request,
            service_id=service_id,
            severity=None,
            logger_name=None,
            subject_type=None,
            subject_id=None,
        )
        if filter_problem is not None:
            return filter_problem

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            purge_request = _service_log_retention_dispatch_request(payload)
            if not purge_request["dry_run"] and not purge_request["delete_enabled"]:
                raise AgServiceLogRetentionError(
                    status_code=409,
                    error_code="ag.service_log_retention_delete_not_enabled",
                    detail=(
                        "delete_enabled must be true before AG dispatches an "
                        "execute-mode service log retention purge."
                    ),
                    retryable=False,
                )
            service_response = control_client.purge_logs(
                service_id,
                request_id=request_id,
                trace_id=trace_id,
                retention_cutoff=purge_request["retention_cutoff"],
                retention_days=purge_request["retention_days"],
                checked_at=purge_request["checked_at"],
                dry_run=purge_request["dry_run"],
                delete_enabled=purge_request["delete_enabled"],
                max_delete_count=purge_request["max_delete_count"],
                requested_by=purge_request["requested_by"],
                idempotency_key=purge_request["idempotency_key"],
            )
        except AgServiceLogRetentionError as exc:
            audit_result = emit_service_log_retention_dispatch_audit_event(
                audit_emitter,
                service_id=service_id,
                request_id=request_id,
                trace_id=trace_id,
                error=exc,
            )
            return _service_log_retention_dispatch_problem_response(
                request,
                exc,
                audit_result=audit_result,
            )
        audit_result = emit_service_log_retention_dispatch_audit_event(
            audit_emitter,
            service_id=service_id,
            request_id=request_id,
            trace_id=trace_id,
            service_response=service_response,
        )
        return build_service_log_retention_dispatch_projection(
            service_id=service_id,
            service_response=service_response,
            audit_result=audit_result,
            request_trace_id=trace_id,
        )

    @app.get("/admin/v1/operations/logs/{log_id}", response_model=None)
    def get_service_log_detail(
        log_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        stores = _service_log_stores_for_projection(
            service_log_stores=service_log_stores,
            registry=registry,
        )
        try:
            entry = _get_service_log_from_stores(stores, log_id)
        except ServiceLogError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Service log source unavailable",
                detail=exc.detail,
                type_uri="https://nex-platform.local/problems/service-log-source-unavailable",
            )
        if entry is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.service_log_not_found",
                title="Service log not found",
                detail=f"Service log was not found: {log_id}",
                type_uri="https://nex-platform.local/problems/service-log-not-found",
            )
        return build_service_log_detail_projection(
            entry,
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
    audit_event_store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
    job_control_client: AgJobControlClient | None = None,
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
    control_client = job_control_client or build_default_ag_job_control_client()
    audit_emitter = OperationalEventEmitter(
        service_id="nex-ag",
        store=audit_event_store or event_store or DEFAULT_OPERATIONAL_EVENT_STORE,
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

    @app.post(
        "/admin/v1/operations/jobs/{service_id}/{job_id}/cancel", response_model=None
    )
    def cancel_operational_job(
        service_id: str,
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = None,
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

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            service_response = control_client.cancel_job(
                service_id,
                job_id,
                request_id=request_id,
                trace_id=trace_id,
                observed_at=_job_control_payload_string(payload, "observed_at"),
            )
        except AgJobControlError as exc:
            audit_result = emit_job_control_audit_event(
                audit_emitter,
                service_id=service_id,
                job_id=job_id,
                action="cancel",
                request_id=request_id,
                trace_id=trace_id,
                error=exc,
            )
            return _job_control_dispatch_problem_response(
                request,
                exc,
                audit_result=audit_result,
            )
        audit_result = emit_job_control_audit_event(
            audit_emitter,
            service_id=service_id,
            job_id=job_id,
            action="cancel",
            request_id=request_id,
            trace_id=trace_id,
            service_response=service_response,
        )
        return build_job_control_dispatch_projection(
            service_id=service_id,
            job_id=job_id,
            action="cancel",
            service_response=service_response,
            audit_result=audit_result,
            request_trace_id=trace_id,
        )

    @app.post(
        "/admin/v1/operations/jobs/{service_id}/{job_id}/retry", response_model=None
    )
    def retry_operational_job(
        service_id: str,
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = None,
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

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            service_response = control_client.retry_job(
                service_id,
                job_id,
                request_id=request_id,
                trace_id=trace_id,
                error_code=_job_control_payload_string(payload, "error_code"),
                detail=_job_control_payload_string(payload, "detail"),
                observed_at=_job_control_payload_string(payload, "observed_at"),
            )
        except AgJobControlError as exc:
            audit_result = emit_job_control_audit_event(
                audit_emitter,
                service_id=service_id,
                job_id=job_id,
                action="retry",
                request_id=request_id,
                trace_id=trace_id,
                error=exc,
            )
            return _job_control_dispatch_problem_response(
                request,
                exc,
                audit_result=audit_result,
            )
        audit_result = emit_job_control_audit_event(
            audit_emitter,
            service_id=service_id,
            job_id=job_id,
            action="retry",
            request_id=request_id,
            trace_id=trace_id,
            service_response=service_response,
        )
        return build_job_control_dispatch_projection(
            service_id=service_id,
            job_id=job_id,
            action="retry",
            service_response=service_response,
            audit_result=audit_result,
            request_trace_id=trace_id,
        )

    @app.post(
        "/admin/v1/operations/jobs/{service_id}/{job_id}/replay", response_model=None
    )
    def replay_operational_job(
        service_id: str,
        job_id: str,
        request: Request,
        payload: dict[str, Any] | None = None,
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

        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            service_response = control_client.replay_job(
                service_id,
                job_id,
                request_id=request_id,
                trace_id=trace_id,
                replay_job_id=_job_control_required_payload_string(
                    payload,
                    "replay_job_id",
                ),
                idempotency_key=_job_control_required_payload_string(
                    payload,
                    "idempotency_key",
                ),
                requested_by=_job_control_required_payload_string(
                    payload,
                    "requested_by",
                ),
                reason=_job_control_required_payload_string(payload, "reason"),
                observed_at=_job_control_payload_string(payload, "observed_at"),
            )
        except AgJobControlError as exc:
            audit_result = emit_job_control_audit_event(
                audit_emitter,
                service_id=service_id,
                job_id=job_id,
                action="replay",
                request_id=request_id,
                trace_id=trace_id,
                error=exc,
            )
            return _job_control_dispatch_problem_response(
                request,
                exc,
                audit_result=audit_result,
            )
        audit_result = emit_job_control_audit_event(
            audit_emitter,
            service_id=service_id,
            job_id=job_id,
            action="replay",
            request_id=request_id,
            trace_id=trace_id,
            service_response=service_response,
        )
        return build_job_control_dispatch_projection(
            service_id=service_id,
            job_id=job_id,
            action="replay",
            service_response=service_response,
            audit_result=audit_result,
            request_trace_id=trace_id,
        )


def register_unified_operation_routes(
    app: FastAPI,
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    retrieval_package_stores: Mapping[str, RetrievalPackageTraceStore] | None = None,
    cx_processing_run_stores: Mapping[str, CxProcessingRunDashboardStore] | None = None,
    generation_remediation_task_stores: (
        Mapping[str, GenerationRemediationTaskDashboardStore] | None
    ) = None,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    runtime: AgOperationsSourceRuntime | None = None,
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

    @app.get("/admin/v1/operations/rollups", response_model=None)
    def get_operations_rollup_metrics(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
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
        query_options = _build_query_options_or_problem(
            request,
            limit=500,
            since=since,
            until=until,
            sort=None,
            cursor=None,
        )
        if isinstance(query_options, JSONResponse):
            return query_options

        return build_operations_rollup_metrics_projection(
            job_queues=job_queues,
            event_store=event_store,
            service_log_stores=service_log_stores,
            registry=registry,
            service_id=service_id,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/dashboard", response_model=None)
    def get_operations_dashboard_snapshot(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        recent_limit: int = Query(default=5, ge=1),
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
        query_options = _build_query_options_or_problem(
            request,
            limit=500,
            since=since,
            until=until,
            sort=None,
            cursor=None,
        )
        if isinstance(query_options, JSONResponse):
            return query_options

        selected_runtime = runtime or getattr(
            request.app.state,
            "nex_ag_operations_source_runtime",
            None,
        )
        return build_operations_dashboard_snapshot_projection(
            job_queues=job_queues,
            event_store=event_store,
            service_log_stores=service_log_stores,
            retrieval_package_stores=retrieval_package_stores,
            registry=registry,
            runtime=selected_runtime,
            cx_processing_run_stores=cx_processing_run_stores,
            generation_remediation_task_stores=generation_remediation_task_stores,
            service_id=service_id,
            recent_limit=recent_limit,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/issue-candidates", response_model=None)
    def get_operations_issue_candidates(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        recent_limit: int = Query(default=5, ge=1),
        stale_after_seconds: int = Query(
            default=DEFAULT_WORKER_STALE_AFTER_SECONDS, ge=1
        ),
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
        query_options = _build_query_options_or_problem(
            request,
            limit=500,
            since=since,
            until=until,
            sort=None,
            cursor=None,
        )
        if isinstance(query_options, JSONResponse):
            return query_options

        selected_runtime = runtime or getattr(
            request.app.state,
            "nex_ag_operations_source_runtime",
            None,
        )
        return build_operations_issue_candidate_projection(
            job_queues=job_queues,
            event_store=event_store,
            service_log_stores=service_log_stores,
            retrieval_package_stores=retrieval_package_stores,
            generation_remediation_task_stores=generation_remediation_task_stores,
            worker_heartbeat_stores=worker_heartbeat_stores,
            registry=registry,
            runtime=selected_runtime,
            service_id=service_id,
            recent_limit=recent_limit,
            stale_after_seconds=stale_after_seconds,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get("/admin/v1/operations/workers", response_model=None)
    def list_worker_runtime_projection(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        worker_type: str | None = None,
        status: str | None = None,
        stale_after_seconds: int = Query(
            default=DEFAULT_WORKER_STALE_AFTER_SECONDS, ge=1
        ),
        since: str | None = None,
        until: str | None = None,
        sort: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        filter_problem = _validate_worker_runtime_filters(
            request,
            service_id=service_id,
            status=status,
            worker_type=worker_type,
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

        return build_worker_runtime_projection(
            worker_heartbeat_stores=worker_heartbeat_stores,
            registry=registry,
            service_id=service_id,
            worker_type=worker_type,
            status=status,
            stale_after_seconds=stale_after_seconds,
            query_options=query_options,
            request_trace_id=trace_id_from_headers(request),
        )

    @app.get(
        "/admin/v1/operations/workers/{service_id}/{worker_id}", response_model=None
    )
    def get_worker_detail_projection(
        service_id: str,
        worker_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        stale_after_seconds: int = Query(
            default=DEFAULT_WORKER_STALE_AFTER_SECONDS, ge=1
        ),
        event_limit: int = Query(default=50, ge=1),
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        filter_problem = _validate_worker_runtime_filters(
            request,
            service_id=service_id,
            status=None,
            worker_type=None,
        )
        if filter_problem is not None:
            return filter_problem
        if not worker_id.strip():
            return problem_response(
                request,
                status_code=400,
                error_code="ag.worker_id_invalid",
                title="Invalid worker id",
                detail="worker_id must be a non-empty string.",
                type_uri="https://nex-platform.local/problems/worker-id-invalid",
            )

        try:
            return build_worker_detail_projection(
                worker_heartbeat_stores=worker_heartbeat_stores,
                job_queues=job_queues,
                event_store=event_store,
                registry=registry,
                service_id=service_id,
                worker_id=worker_id,
                stale_after_seconds=stale_after_seconds,
                event_limit=event_limit,
                request_trace_id=trace_id_from_headers(request),
            )
        except OperationsQueryError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="Worker detail query failed",
                detail=exc.detail,
                type_uri="https://nex-platform.local/problems/worker-detail-query-failed",
            )

    @app.get("/admin/v1/operations/traces/{trace_id}", response_model=None)
    def get_cross_service_trace_timeline(
        trace_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
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
            status=None,
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

        return build_cross_service_trace_timeline_projection(
            trace_id=trace_id,
            job_queues=job_queues,
            event_store=event_store,
            service_log_stores=service_log_stores,
            retrieval_package_stores=retrieval_package_stores,
            registry=registry,
            service_id=service_id,
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
            event for event in events if _operational_event_matches_query(event, q)
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


def build_service_log_projection(
    *,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    severity: str | None = None,
    logger_name: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
    stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    normalized_severity = severity.upper() if severity is not None else None
    normalized_logger_name = logger_name.strip() if logger_name is not None else None
    normalized_subject_type = subject_type.strip() if subject_type is not None else None
    normalized_subject_id = subject_id.strip() if subject_id is not None else None
    projected_logs: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}

    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "log_count": 0,
            }
            continue
        try:
            logs = store.list_logs(
                service_id=selected_service_id,
                severity=normalized_severity,
                logger_name=normalized_logger_name,
                trace_id=trace_id,
                request_id=request_id,
                job_id=job_id,
                subject_type=normalized_subject_type,
                subject_id=normalized_subject_id,
                limit=normalize_service_log_limit(500),
            )
        except ServiceLogError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "log_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        if q is not None:
            logs = [entry for entry in logs if _service_log_matches_query(entry, q)]
        logs = _filter_records_by_operation_time(
            logs,
            options,
            timestamp_field="observed_at",
        )
        source_statuses[selected_service_id] = {
            "status": "READY",
            "log_count": len(logs),
        }
        projected_logs.extend(deepcopy(entry) for entry in logs)

    page = _apply_operation_query_options(
        projected_logs,
        options,
        timestamp_field="observed_at",
        tie_breaker_fields=("service_id", "logger_name", "log_id"),
    )
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_service_log_projection.v1",
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "severity": normalized_severity,
            "logger_name": normalized_logger_name,
            "trace_id": trace_id,
            "request_id": request_id,
            "job_id": job_id,
            "subject_type": normalized_subject_type,
            "subject_id": normalized_subject_id,
            "q": q,
            **options.to_filter_dict(),
        },
        "logs": page["items"],
        "summary": summarize_service_logs(page["items"]),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_service_log_query_policy_projection(
    *,
    retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    policy = service_log_query_policy(retention_days=retention_days)
    projection = {
        "projection_schema_version": AG_SERVICE_LOG_QUERY_POLICY_PROJECTION_SCHEMA_VERSION,
        "projection_status": "READY",
        "checked_at": _utc_now(),
        "policy": policy,
        "summary": {
            "policy_id": policy["policy_id"],
            "status": policy["status"],
            "default_limit": policy["query"]["default_limit"],
            "max_limit": policy["query"]["max_limit"],
            "default_retention_days": policy["retention"]["default_retention_days"],
            "supported_filter_count": len(policy["query"]["supported_filters"]),
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_service_log_retention_dry_run_projection(
    *,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
    limit: int = DEFAULT_SERVICE_LOG_LIMIT,
    checked_at: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_retention_days = normalize_service_log_retention_days(retention_days)
    normalized_limit = normalize_service_log_limit(limit)
    normalized_checked_at = normalize_operation_timestamp(
        checked_at,
        field_name="checked_at",
    )
    observed_at = normalized_checked_at or _utc_now()
    checked_dt = _parse_operation_timestamp(observed_at, field_name="checked_at")
    cutoff_dt = checked_dt - timedelta(days=normalized_retention_days)
    retention_cutoff = cutoff_dt.isoformat().replace("+00:00", "Z")
    stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    source_statuses: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []

    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "log_count": 0,
                "candidate_count": 0,
            }
            continue
        try:
            logs = store.list_logs(
                service_id=selected_service_id,
                limit=normalize_service_log_limit(500),
            )
        except ServiceLogError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "log_count": 0,
                "candidate_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        service_candidates = [
            _service_log_retention_candidate(
                entry,
                checked_dt=checked_dt,
                retention_cutoff=retention_cutoff,
            )
            for entry in logs
            if _operation_record_timestamp(entry, timestamp_field="observed_at")
            < cutoff_dt
        ]
        source_statuses[selected_service_id] = {
            "status": "READY",
            "log_count": len(logs),
            "candidate_count": len(service_candidates),
        }
        candidates.extend(service_candidates)

    options = OperationQueryOptions(
        limit=normalized_limit,
        sort="asc",
        cursor=None,
    )
    page = _apply_operation_query_options(
        candidates,
        options,
        timestamp_field="observed_at",
        tie_breaker_fields=("service_id", "logger_name", "log_id"),
    )
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
        else "READY"
    )
    policy = service_log_query_policy(retention_days=normalized_retention_days)
    projection = {
        "projection_schema_version": (
            AG_SERVICE_LOG_RETENTION_DRY_RUN_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "checked_at": observed_at,
        "filters": {
            "service_id": service_id,
            "retention_days": normalized_retention_days,
            "limit": normalized_limit,
            "scan_limit": MAX_SERVICE_LOG_LIMIT,
        },
        "policy": policy,
        "retention_cutoff": retention_cutoff,
        "dry_run": {
            "delete_enabled": False,
            "purge_execution": policy["retention"]["purge_execution"],
            "storage_owner": policy["retention"]["storage_owner"],
        },
        "retention_candidates": page["items"],
        "summary": _summarize_service_log_retention_dry_run(
            candidates,
            source_statuses=source_statuses,
            selected_service_count=len(selected_service_ids),
            returned_candidate_count=len(page["items"]),
            retention_days=normalized_retention_days,
            retention_cutoff=retention_cutoff,
        ),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_service_log_retention_history_projection(
    *,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    mode: str | None = None,
    execution_status: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    limit: int = DEFAULT_SERVICE_LOG_RETENTION_HISTORY_LIMIT,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_mode = _normalize_service_log_retention_history_mode(mode)
    normalized_status = _normalize_service_log_retention_history_status(
        execution_status
    )
    options = query_options or build_operation_query_options(
        limit=normalize_service_log_retention_history_limit(limit),
    )
    stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    source_statuses: dict[str, dict[str, Any]] = {}
    history_entries: list[dict[str, Any]] = []

    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "history_count": 0,
            }
            continue
        try:
            service_history = store.list_retention_history(
                service_id=selected_service_id,
                mode=normalized_mode,
                execution_status=normalized_status,
                trace_id=trace_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                limit=normalize_service_log_retention_history_limit(500),
            )
        except ServiceLogError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "history_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        service_history = _filter_records_by_operation_time(
            service_history,
            options,
            timestamp_field="recorded_at",
        )
        source_statuses[selected_service_id] = {
            "status": "READY",
            "history_count": len(service_history),
        }
        history_entries.extend(deepcopy(entry) for entry in service_history)

    page = _apply_operation_query_options(
        history_entries,
        options,
        timestamp_field="recorded_at",
        tie_breaker_fields=("service_id", "execution_id"),
    )
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
            AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "mode": normalized_mode,
            "execution_status": normalized_status,
            "trace_id": trace_id,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            **options.to_filter_dict(),
        },
        "retention_history": page["items"],
        "summary": _summarize_service_log_retention_history_projection(
            page["items"],
            source_statuses=source_statuses,
            selected_service_count=len(selected_service_ids),
        ),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def service_log_query_policy(
    *,
    retention_days: int = DEFAULT_SERVICE_LOG_RETENTION_DAYS,
) -> dict[str, Any]:
    normalized_retention_days = normalize_service_log_retention_days(retention_days)
    return {
        "policy_schema_version": SERVICE_LOG_QUERY_POLICY_SCHEMA_VERSION,
        "policy_id": SERVICE_LOG_QUERY_POLICY_ID,
        "status": "ACTIVE",
        "owner_service": "nex-ag",
        "applies_to": sorted(SERVICE_SPECS),
        "query": {
            "default_limit": DEFAULT_SERVICE_LOG_LIMIT,
            "max_limit": MAX_SERVICE_LOG_LIMIT,
            "max_q_length": MAX_OPERATION_EVENT_QUERY_LENGTH,
            "default_sort": "desc",
            "timestamp_field": "observed_at",
            "supported_filters": list(SERVICE_LOG_QUERY_SUPPORTED_FILTERS),
            "cursor_mode": "offset-string",
        },
        "retention": {
            "default_retention_days": normalized_retention_days,
            "minimum_retention_days": MIN_SERVICE_LOG_RETENTION_DAYS,
            "maximum_retention_days": MAX_SERVICE_LOG_RETENTION_DAYS,
            "storage_owner": "service-local",
            "purge_execution": "service_local_control_api",
            "future_archive_target": "object_storage_or_cold_table",
        },
        "redaction": {
            "attribute_policy": "redact_or_omit_before_persistence",
            "redacted_value": REDACTED_LOG_VALUE,
            "sensitive_key_parts": list(SENSITIVE_LOG_ATTRIBUTE_KEY_PARTS),
        },
    }


def normalize_service_log_retention_days(value: int) -> int:
    if value < MIN_SERVICE_LOG_RETENTION_DAYS:
        return MIN_SERVICE_LOG_RETENTION_DAYS
    if value > MAX_SERVICE_LOG_RETENTION_DAYS:
        return MAX_SERVICE_LOG_RETENTION_DAYS
    return value


def build_service_log_detail_projection(
    entry: dict[str, Any],
    *,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projection = {
        "projection_schema_version": "ag_service_log_detail_projection.v1",
        "checked_at": _utc_now(),
        "log": deepcopy(entry),
        "summary": {
            "log_id": entry["log_id"],
            "service_id": entry["service_id"],
            "severity": entry["severity"],
            "logger_name": entry["logger_name"],
            "trace_id": entry.get("trace_id"),
            "request_id": entry.get("request_id"),
            "job_id": entry.get("job_id"),
            "subject_ref": deepcopy(entry.get("subject_ref")),
            "observed_at": entry["observed_at"],
            "redacted_attribute_keys": deepcopy(entry["redacted_attribute_keys"]),
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
        "DEGRADED" if job_projection["projection_status"] == "DEGRADED" else "READY"
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


def build_operations_issue_candidate_projection(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    retrieval_package_stores: Mapping[str, RetrievalPackageTraceStore] | None = None,
    generation_remediation_task_stores: (
        Mapping[str, GenerationRemediationTaskDashboardStore] | None
    ) = None,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    runtime: AgOperationsSourceRuntime | None = None,
    service_id: str | None = None,
    recent_limit: int = 5,
    stale_after_seconds: int = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    limit: int = 500,
    query_options: OperationQueryOptions | None = None,
    checked_at: str | None = None,
    request_trace_id: str | None = None,
    retrieval_policies: tuple[dict[str, Any], ...] | None = None,
    generation_audit_projections: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
    observed_at = checked_at or _utc_now()
    dashboard = build_operations_dashboard_snapshot_projection(
        job_queues=job_queues,
        event_store=event_store,
        service_log_stores=service_log_stores,
        retrieval_package_stores=retrieval_package_stores,
        generation_remediation_task_stores=generation_remediation_task_stores,
        registry=registry,
        runtime=runtime,
        service_id=service_id,
        recent_limit=recent_limit,
        query_options=options,
        retrieval_policies=retrieval_policies,
        generation_audit_projections=generation_audit_projections,
    )
    worker_projection = None
    if _worker_reconciliation_enabled(
        registry=registry,
        worker_heartbeat_stores=worker_heartbeat_stores,
    ):
        worker_projection = build_worker_runtime_projection(
            worker_heartbeat_stores=worker_heartbeat_stores,
            registry=registry,
            service_id=service_id,
            stale_after_seconds=stale_after_seconds,
            query_options=options,
            checked_at=observed_at,
        )
    candidates = build_operations_issue_candidates(
        dashboard,
        worker_runtime_projection=worker_projection,
    )
    projection_status = (
        "DEGRADED"
        if dashboard["projection_status"] == "DEGRADED"
        or (
            worker_projection is not None
            and worker_projection["projection_status"] == "DEGRADED"
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_operations_issue_candidate_projection.v1",
        "projection_status": projection_status,
        "checked_at": observed_at,
        "filters": dashboard["filters"],
        "rules": operations_issue_candidate_rules(),
        "issue_candidates": candidates,
        "summary": summarize_operations_issue_candidates(candidates),
        "job_source_statuses": dashboard["job_source_statuses"],
        "event_source_statuses": dashboard["event_source_statuses"],
    }
    if "log_source_statuses" in dashboard:
        projection["log_source_statuses"] = dashboard["log_source_statuses"]
    if worker_projection is not None:
        projection["filters"]["stale_after_seconds"] = worker_projection["filters"][
            "stale_after_seconds"
        ]
        projection["worker_source_statuses"] = worker_projection["source_statuses"]
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_worker_runtime_projection(
    *,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    worker_type: str | None = None,
    status: str | None = None,
    stale_after_seconds: int = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    limit: int = 50,
    query_options: OperationQueryOptions | None = None,
    checked_at: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
    normalized_status = status.upper() if status is not None else None
    normalized_worker_type = worker_type.strip() if worker_type is not None else None
    normalized_stale_after = normalize_worker_stale_after_seconds(stale_after_seconds)
    observed_at = checked_at or _utc_now()
    stores = (
        registry.worker_heartbeat_stores()
        if registry is not None
        else worker_heartbeat_stores or DEFAULT_WORKER_HEARTBEAT_STORES
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )

    projected_workers: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "worker_count": 0,
            }
            continue
        try:
            workers = store.list_heartbeats(
                service_id=selected_service_id,
                worker_type=normalized_worker_type,
                status=normalized_status,
            )
        except WorkerHeartbeatError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "worker_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        workers = _filter_records_by_operation_time(
            workers,
            options,
            timestamp_field="last_seen_at",
        )
        source_statuses[selected_service_id] = {
            "status": "READY",
            "worker_count": len(workers),
        }
        projected_workers.extend(
            _project_worker_for_service(
                selected_service_id,
                worker,
                stale_after_seconds=normalized_stale_after,
                checked_at=observed_at,
            )
            for worker in workers
        )

    page = _apply_operation_query_options(
        projected_workers,
        options,
        timestamp_field="last_seen_at",
        tie_breaker_fields=("service_id", "worker_type", "worker_id"),
    )
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_worker_runtime_projection.v1",
        "projection_status": projection_status,
        "checked_at": observed_at,
        "filters": {
            "service_id": service_id,
            "worker_type": normalized_worker_type,
            "status": normalized_status,
            "stale_after_seconds": normalized_stale_after,
            **options.to_filter_dict(),
        },
        "workers": page["items"],
        "summary": summarize_worker_heartbeats(
            page["items"],
            stale_after_seconds=normalized_stale_after,
            checked_at=observed_at,
        ),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_worker_detail_projection(
    *,
    service_id: str,
    worker_id: str,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None = None,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    registry: OperationsSourceRegistry | None = None,
    stale_after_seconds: int = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    event_limit: int = 50,
    checked_at: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    normalized_worker_id = worker_id.strip()
    if service_id not in SERVICE_SPECS:
        raise OperationsQueryError(
            error_code="ag.worker_service_invalid",
            detail=f"Unsupported worker service: {service_id}",
            status_code=400,
        )
    if not normalized_worker_id:
        raise OperationsQueryError(
            error_code="ag.worker_id_invalid",
            detail="worker_id must be a non-empty string.",
            status_code=400,
        )

    normalized_stale_after = normalize_worker_stale_after_seconds(stale_after_seconds)
    observed_at = checked_at or _utc_now()
    worker_stores = (
        registry.worker_heartbeat_stores()
        if registry is not None
        else (
            DEFAULT_WORKER_HEARTBEAT_STORES
            if worker_heartbeat_stores is None
            else worker_heartbeat_stores
        )
    )
    job_stores = (
        registry.job_queues()
        if registry is not None
        else (DEFAULT_JOB_QUEUE_STORES if job_queues is None else job_queues)
    )
    selected_event_store = event_store
    if registry is not None:
        selected_event_store = (
            RegistryOperationalEventStore(registry)
            if service_id in registry.event_stores()
            else None
        )

    worker_store = worker_stores.get(service_id)
    worker: dict[str, Any] | None = None
    worker_source_status: dict[str, Any]
    if worker_store is None:
        worker_source_status = {
            "status": "NOT_CONFIGURED",
            "worker_count": 0,
        }
    else:
        try:
            worker = worker_store.get_heartbeat(service_id, normalized_worker_id)
        except WorkerHeartbeatError as exc:
            worker_source_status = {
                "status": "UNAVAILABLE",
                "worker_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
        else:
            if worker is None:
                raise OperationsQueryError(
                    error_code="ag.worker_not_found",
                    detail=f"Worker was not found for {service_id}: {normalized_worker_id}",
                    status_code=404,
                )
            worker_source_status = {
                "status": "READY",
                "worker_count": 1,
            }

    projected_worker = (
        _project_worker_for_service(
            service_id,
            worker,
            stale_after_seconds=normalized_stale_after,
            checked_at=observed_at,
        )
        if worker is not None
        else None
    )
    active_job, job_source_status = _worker_active_job_for_service(
        worker,
        service_id=service_id,
        job_stores=job_stores,
    )
    lifecycle_timeline = _build_worker_lifecycle_timeline(
        worker,
        service_id=service_id,
        event_store=selected_event_store,
        event_limit=event_limit,
    )
    source_statuses = {
        "workers": worker_source_status,
        "jobs": job_source_status,
        "events": {
            "status": lifecycle_timeline["timeline_status"],
            "event_count": lifecycle_timeline["event_count"],
            **(
                {
                    "error_code": lifecycle_timeline["source_error"]["error_code"],
                    "detail": lifecycle_timeline["source_error"]["detail"],
                }
                if lifecycle_timeline["source_error"] is not None
                else {}
            ),
        },
    }
    projection_status = (
        "DEGRADED"
        if any(source["status"] != "READY" for source in source_statuses.values())
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_worker_detail_projection.v1",
        "projection_status": projection_status,
        "checked_at": observed_at,
        "service_id": service_id,
        "worker": projected_worker,
        "active_job": active_job,
        "worker_lifecycle_timeline": lifecycle_timeline,
        "summary": {
            "service_id": service_id,
            "worker_id": normalized_worker_id,
            "worker_found": projected_worker is not None,
            "worker_type": (
                projected_worker["worker_type"]
                if projected_worker is not None
                else None
            ),
            "status": (
                projected_worker["status"] if projected_worker is not None else None
            ),
            "stale": (
                projected_worker["stale"] if projected_worker is not None else None
            ),
            "active_job_id": (
                projected_worker["active_job_id"]
                if projected_worker is not None
                else None
            ),
            "active_job_status": (
                active_job["status"] if active_job is not None else None
            ),
            "timeline_status": lifecycle_timeline["timeline_status"],
            "timeline_event_count": lifecycle_timeline["event_count"],
            "source_statuses": {
                source_kind: source_status["status"]
                for source_kind, source_status in source_statuses.items()
            },
        },
        "source_statuses": source_statuses,
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_operations_dashboard_snapshot_projection(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    retrieval_package_stores: Mapping[str, RetrievalPackageTraceStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    runtime: AgOperationsSourceRuntime | None = None,
    cx_processing_run_stores: Mapping[str, CxProcessingRunDashboardStore] | None = None,
    generation_remediation_task_stores: (
        Mapping[str, GenerationRemediationTaskDashboardStore] | None
    ) = None,
    service_id: str | None = None,
    recent_limit: int = 5,
    limit: int = 500,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
    retrieval_policies: tuple[dict[str, Any], ...] | None = None,
    generation_audit_projections: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(limit=limit)
    normalized_recent_limit = normalize_dashboard_recent_limit(recent_limit)
    selected_runtime = _dashboard_source_runtime(
        runtime=runtime,
        registry=registry,
    )
    readiness_projection = build_operation_source_readiness_projection(
        runtime=selected_runtime,
        service_id=service_id,
    )
    rollup_projection = build_operations_rollup_metrics_projection(
        job_queues=job_queues,
        event_store=event_store,
        service_log_stores=service_log_stores,
        registry=registry,
        service_id=service_id,
        query_options=options,
    )
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
    selected_log_stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    failure_logs, log_source_statuses = _dashboard_failure_log_candidates(
        selected_log_stores,
        service_id=service_id,
        options=options,
        limit=normalized_recent_limit,
    )
    recent_failures = {
        "jobs": _dashboard_job_candidates(
            queue_stores,
            service_id=service_id,
            statuses={"FAILED"},
            options=options,
            limit=normalized_recent_limit,
        ),
        "events": _dashboard_failure_event_candidates(
            selected_event_store,
            service_id=service_id,
            options=options,
            limit=normalized_recent_limit,
        ),
        "logs": failure_logs,
    }
    replay_candidates = _dashboard_replay_candidates(recent_failures["jobs"])
    active_jobs = _dashboard_job_candidates(
        queue_stores,
        service_id=service_id,
        statuses={"QUEUED", "RUNNING"},
        options=options,
        limit=normalized_recent_limit,
    )
    cx_processing_runs = _dashboard_cx_processing_run_section(
        cx_processing_run_stores,
        service_id=service_id,
        options=options,
        limit=normalized_recent_limit,
    )
    retrieval_threshold_decisions = _dashboard_retrieval_threshold_decision_section(
        retrieval_package_stores,
        service_id=service_id,
        options=options,
        policies=retrieval_policies,
    )
    generation_quality = _dashboard_generation_quality_section(
        generation_audit_projections,
        limit=normalized_recent_limit,
    )
    generation_remediation = _dashboard_generation_remediation_section(
        generation_remediation_task_stores,
        service_id=service_id,
        options=options,
        limit=normalized_recent_limit,
    )
    degraded_sources = _dashboard_degraded_sources(
        operation_sources=readiness_projection["sources"],
        job_source_statuses=rollup_projection["job_source_statuses"],
        event_source_statuses=rollup_projection["event_source_statuses"],
        log_source_statuses=log_source_statuses,
        cx_processing_run_source_statuses=cx_processing_runs["source_statuses"],
        retrieval_threshold_decision_source_statuses=(
            retrieval_threshold_decisions["source_statuses"]
        ),
        generation_remediation_source_statuses=(
            generation_remediation["source_statuses"]
        ),
    )
    projection = {
        "projection_schema_version": "ag_operations_dashboard_snapshot_projection.v1",
        "projection_status": "DEGRADED" if degraded_sources else "READY",
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "since": options.since,
            "until": options.until,
            "recent_limit": normalized_recent_limit,
        },
        "operation_sources": readiness_projection["sources"],
        "source_readiness_summary": readiness_projection["summary"],
        "rollups": rollup_projection["rollups"],
        "rollup_summary": rollup_projection["summary"],
        "recent_failures": recent_failures,
        "replay_candidates": replay_candidates,
        "active_jobs": active_jobs,
        "cx_processing_runs": cx_processing_runs,
        "retrieval_threshold_decisions": retrieval_threshold_decisions,
        "generation_quality": generation_quality,
        "generation_remediation": generation_remediation,
        "degraded_sources": degraded_sources,
        "job_source_statuses": rollup_projection["job_source_statuses"],
        "event_source_statuses": rollup_projection["event_source_statuses"],
        "log_source_statuses": log_source_statuses,
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_operations_rollup_metrics_projection(
    *,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
    limit: int = 500,
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
    selected_log_stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    configured_event_service_ids = (
        set(registry.event_stores()) if registry is not None else None
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )

    rollups: list[dict[str, Any]] = []
    job_source_statuses: dict[str, dict[str, Any]] = {}
    event_source_statuses: dict[str, dict[str, Any]] = {}
    log_source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        jobs, job_source_status = _operations_rollup_jobs_for_service(
            queue_stores,
            service_id=selected_service_id,
            options=options,
        )
        events, event_source_status = _operations_rollup_events_for_service(
            selected_event_store,
            service_id=selected_service_id,
            options=options,
            configured_service_ids=configured_event_service_ids,
        )
        logs, log_source_status = _operations_rollup_logs_for_service(
            selected_log_stores,
            service_id=selected_service_id,
            options=options,
        )
        job_source_statuses[selected_service_id] = job_source_status
        event_source_statuses[selected_service_id] = event_source_status
        log_source_statuses[selected_service_id] = log_source_status
        rollups.append(
            {
                "service_id": selected_service_id,
                "jobs": jobs,
                "events": events,
                "logs": logs,
                "source_status": {
                    "jobs": job_source_status["status"],
                    "events": event_source_status["status"],
                    "logs": log_source_status["status"],
                },
            }
        )

    projection_status = (
        "DEGRADED"
        if any(
            source["status"] != "READY"
            for source in [
                *job_source_statuses.values(),
                *event_source_statuses.values(),
            ]
        )
        or any(
            source["status"] == "UNAVAILABLE" for source in log_source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_operations_rollup_metrics_projection.v1",
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "service_id": service_id,
            "since": options.since,
            "until": options.until,
        },
        "rollups": rollups,
        "summary": summarize_operations_rollup_metrics(rollups),
        "job_source_statuses": job_source_statuses,
        "event_source_statuses": event_source_statuses,
        "log_source_statuses": log_source_statuses,
    }
    if registry is not None:
        projection["source_registry"] = registry.to_summary()
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_cross_service_trace_timeline_projection(
    *,
    trace_id: str,
    job_queues: Mapping[str, JobQueue] | None = None,
    event_store: OperationalEventStore | None = None,
    service_log_stores: Mapping[str, ServiceLogStore] | None = None,
    retrieval_package_stores: Mapping[str, RetrievalPackageTraceStore] | None = None,
    registry: OperationsSourceRegistry | None = None,
    service_id: str | None = None,
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
    selected_log_stores = _service_log_stores_for_projection(
        service_log_stores=service_log_stores,
        registry=registry,
    )
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    job_items, job_source_statuses = _trace_job_timeline_items(
        queue_stores,
        selected_service_ids=selected_service_ids,
        trace_id=trace_id,
    )
    event_items, event_source_status = _trace_event_timeline_items(
        selected_event_store,
        trace_id=trace_id,
        service_id=service_id,
    )
    log_items, log_source_statuses = _trace_log_timeline_items(
        selected_log_stores,
        selected_service_ids=selected_service_ids,
        trace_id=trace_id,
    )
    retrieval_package_items, retrieval_package_source_statuses = (
        _trace_retrieval_package_timeline_items(
            retrieval_package_stores,
            selected_service_ids=selected_service_ids,
            trace_id=trace_id,
        )
    )
    page = _apply_operation_query_options(
        [*job_items, *event_items, *log_items, *retrieval_package_items],
        options,
        timestamp_field="operation_timestamp",
        tie_breaker_fields=("item_id",),
    )
    projection_status = (
        "DEGRADED"
        if event_source_status["status"] == "UNAVAILABLE"
        or any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in job_source_statuses.values()
        )
        or any(
            source["status"] == "UNAVAILABLE" for source in log_source_statuses.values()
        )
        or any(
            source["status"] == "UNAVAILABLE"
            for source in retrieval_package_source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": "ag_cross_service_trace_timeline_projection.v1",
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "trace_id": trace_id,
            "service_id": service_id,
            **options.to_filter_dict(),
        },
        "timeline": page["items"],
        "summary": summarize_trace_timeline_items(page["items"]),
        "job_source_statuses": job_source_statuses,
        "event_source_status": event_source_status,
        "log_source_statuses": log_source_statuses,
        "retrieval_package_source_statuses": retrieval_package_source_statuses,
        "pagination": page["pagination"],
    }
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
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
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
            _project_job_for_service(selected_service_id, job) for job in service_jobs
        )

    page = _apply_operation_query_options(
        projected_jobs,
        options,
        timestamp_field="updated_at",
        tie_breaker_fields=("created_at", "service_id", "job_id"),
    )
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
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


def build_job_control_dispatch_projection(
    *,
    service_id: str,
    job_id: str,
    action: str,
    service_response: dict[str, Any],
    audit_result: OperationalEventEmitResult | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    service_job = service_response.get("job")
    job_status = service_job.get("status") if isinstance(service_job, Mapping) else None
    controls = service_response.get("controls")
    projection = {
        "projection_schema_version": AG_JOB_CONTROL_DISPATCH_SCHEMA_VERSION,
        "dispatch_status": "SUCCEEDED",
        "checked_at": _utc_now(),
        "service_id": service_id,
        "job_id": job_id,
        "action": action,
        "service_response": deepcopy(service_response),
        "audit_event": (
            audit_result.to_summary()
            if audit_result is not None
            else {"ok": False, "error_code": "ag.job_control_audit_not_requested"}
        ),
        "summary": {
            "service_id": service_id,
            "job_id": job_id,
            "action": action,
            "job_status": job_status,
            "allowed_actions": (
                deepcopy(controls.get("allowed_actions"))
                if isinstance(controls, Mapping)
                else []
            ),
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def build_service_log_retention_dispatch_projection(
    *,
    service_id: str,
    service_response: dict[str, Any],
    audit_result: OperationalEventEmitResult | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projection = {
        "projection_schema_version": AG_SERVICE_LOG_RETENTION_DISPATCH_SCHEMA_VERSION,
        "dispatch_status": "SUCCEEDED",
        "checked_at": _utc_now(),
        "service_id": service_id,
        "service_response": deepcopy(service_response),
        "audit_event": (
            audit_result.to_summary()
            if audit_result is not None
            else {
                "ok": False,
                "error_code": "ag.service_log_retention_audit_not_requested",
            }
        ),
        "summary": {
            "service_id": service_id,
            "mode": service_response.get("mode"),
            "execution_status": service_response.get("execution_status"),
            "candidate_count": service_response.get("candidate_count"),
            "deleted_count": service_response.get("deleted_count"),
            "delete_enabled": service_response.get("delete_enabled"),
            "max_delete_count": service_response.get("max_delete_count"),
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def emit_service_log_retention_dispatch_audit_event(
    emitter: OperationalEventEmitter,
    *,
    service_id: str,
    request_id: str,
    trace_id: str,
    service_response: dict[str, Any] | None = None,
    error: AgServiceLogRetentionError | None = None,
) -> OperationalEventEmitResult:
    if error is not None:
        return emitter.safe_emit(
            event_type=AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
            severity="ERROR",
            message=f"AG failed to dispatch service log retention purge for {service_id}.",
            trace_id=trace_id,
            request_id=request_id,
            subject_ref={"type": "service_log_retention", "id": service_id},
            details={
                "target_service_id": service_id,
                "dispatch_status": "FAILED",
                "error_code": error.error_code,
                "status_code": error.status_code,
                "retryable": error.retryable,
            },
        )
    return emitter.safe_emit(
        event_type=AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
        severity="INFO",
        message=f"AG dispatched service log retention purge for {service_id}.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref={"type": "service_log_retention", "id": service_id},
        details={
            "target_service_id": service_id,
            "dispatch_status": "SUCCEEDED",
            "mode": (service_response or {}).get("mode"),
            "execution_status": (service_response or {}).get("execution_status"),
            "candidate_count": (service_response or {}).get("candidate_count"),
            "deleted_count": (service_response or {}).get("deleted_count"),
            "delete_enabled": (service_response or {}).get("delete_enabled"),
            "retention_execution_schema_version": (service_response or {}).get(
                "retention_execution_schema_version"
            ),
        },
    )


def emit_job_control_audit_event(
    emitter: OperationalEventEmitter,
    *,
    service_id: str,
    job_id: str,
    action: str,
    request_id: str,
    trace_id: str,
    service_response: dict[str, Any] | None = None,
    error: AgJobControlError | None = None,
) -> OperationalEventEmitResult:
    if error is not None:
        return emitter.safe_emit(
            event_type=AG_JOB_CONTROL_EVENT_FAILED,
            severity="ERROR",
            message=f"AG failed to dispatch {action} for {service_id} job {job_id}.",
            trace_id=trace_id,
            request_id=request_id,
            subject_ref={"type": "job", "id": f"{service_id}:{job_id}"},
            details={
                "target_service_id": service_id,
                "target_job_id": job_id,
                "action": action,
                "dispatch_status": "FAILED",
                "error_code": error.error_code,
                "status_code": error.status_code,
                "retryable": error.retryable,
            },
        )
    service_job = (service_response or {}).get("job")
    return emitter.safe_emit(
        event_type=AG_JOB_CONTROL_EVENT_SUCCEEDED,
        severity="INFO",
        message=f"AG dispatched {action} for {service_id} job {job_id}.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref={"type": "job", "id": f"{service_id}:{job_id}"},
        details={
            "target_service_id": service_id,
            "target_job_id": job_id,
            "action": action,
            "dispatch_status": "SUCCEEDED",
            "job_status": (
                service_job.get("status") if isinstance(service_job, Mapping) else None
            ),
            "service_job_control_schema_version": (service_response or {}).get(
                "job_control_schema_version"
            ),
        },
    )


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


def summarize_trace_timeline_items(
    timeline_items: list[dict[str, Any]],
) -> dict[str, Any]:
    by_item_type: dict[str, int] = {}
    by_service: dict[str, int] = {}
    for item in timeline_items:
        item_type = str(item["timeline_item_type"])
        service_id = str(item["service_id"])
        by_item_type[item_type] = by_item_type.get(item_type, 0) + 1
        by_service[service_id] = by_service.get(service_id, 0) + 1
    return {
        "total": len(timeline_items),
        "by_item_type": by_item_type,
        "by_service": by_service,
    }


def normalize_dashboard_recent_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_DASHBOARD_RECENT_LIMIT:
        return MAX_DASHBOARD_RECENT_LIMIT
    return limit


def operations_issue_candidate_rules() -> list[dict[str, Any]]:
    return [dict(rule) for rule in OPERATIONS_ISSUE_CANDIDATE_RULES]


def build_operations_issue_candidates(
    dashboard_snapshot: Mapping[str, Any],
    *,
    worker_runtime_projection: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(
        _issue_candidates_from_degraded_sources(dashboard_snapshot["degraded_sources"])
    )
    candidates.extend(_issue_candidates_from_rollups(dashboard_snapshot["rollups"]))
    candidates.extend(
        _issue_candidates_from_failure_logs(
            dashboard_snapshot.get("recent_failures", {}).get("logs", [])
        )
    )
    candidates.extend(
        _issue_candidates_from_replay_candidates(
            dashboard_snapshot.get("replay_candidates", [])
        )
    )
    candidates.extend(
        _issue_candidates_from_active_jobs(dashboard_snapshot["active_jobs"])
    )
    candidates.extend(
        _issue_candidates_from_retrieval_threshold_decisions(
            dashboard_snapshot.get("retrieval_threshold_decisions")
        )
    )
    candidates.extend(
        _issue_candidates_from_generation_quality(
            dashboard_snapshot.get("generation_quality")
        )
    )
    candidates.extend(
        _issue_candidates_from_generation_remediation(
            dashboard_snapshot.get("generation_remediation")
        )
    )
    if worker_runtime_projection is not None:
        candidates.extend(
            _issue_candidates_from_worker_source_statuses(
                worker_runtime_projection["source_statuses"]
            )
        )
        candidates.extend(
            _issue_candidates_from_stale_workers(worker_runtime_projection["workers"])
        )
        candidates.extend(
            _issue_candidates_from_active_jobs_without_fresh_workers(
                dashboard_snapshot["active_jobs"],
                worker_runtime_projection["workers"],
            )
        )
    return candidates


def summarize_operations_issue_candidates(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    by_severity = {severity: 0 for severity in OPERATIONAL_EVENT_SEVERITIES}
    by_service: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for candidate in candidates:
        severity = str(candidate["severity"])
        if severity in by_severity:
            by_severity[severity] += 1
        service_id = str(candidate["service_id"])
        rule_id = str(candidate["rule_id"])
        by_service[service_id] = by_service.get(service_id, 0) + 1
        by_rule[rule_id] = by_rule.get(rule_id, 0) + 1
    return {
        "total": len(candidates),
        "by_severity": by_severity,
        "by_service": by_service,
        "by_rule": by_rule,
    }


def summarize_operations_rollup_metrics(
    rollups: list[dict[str, Any]],
) -> dict[str, Any]:
    job_statuses = {status: 0 for status in JOB_STATUSES}
    event_severities = {severity: 0 for severity in OPERATIONAL_EVENT_SEVERITIES}
    log_severities = {severity: 0 for severity in SERVICE_LOG_SEVERITIES}
    jobs_by_service: dict[str, int] = {}
    events_by_service: dict[str, int] = {}
    logs_by_service: dict[str, int] = {}
    source_statuses = {
        "jobs": {},
        "events": {},
        "logs": {},
    }
    total_jobs = 0
    active_jobs = 0
    terminal_jobs = 0
    total_events = 0
    total_logs = 0
    redacted_attribute_count = 0
    for rollup in rollups:
        service_id = str(rollup["service_id"])
        jobs = rollup["jobs"]
        events = rollup["events"]
        logs = rollup["logs"]
        total_jobs += int(jobs["total"])
        active_jobs += int(jobs["active"])
        terminal_jobs += int(jobs["terminal"])
        total_events += int(events["total"])
        total_logs += int(logs["total"])
        redacted_attribute_count += int(logs["redacted_attribute_count"])
        jobs_by_service[service_id] = int(jobs["total"])
        events_by_service[service_id] = int(events["total"])
        logs_by_service[service_id] = int(logs["total"])
        for status, count in jobs["statuses"].items():
            if status in job_statuses:
                job_statuses[status] += int(count)
        for severity, count in events["by_severity"].items():
            if severity in event_severities:
                event_severities[severity] += int(count)
        for severity, count in logs["by_severity"].items():
            if severity in log_severities:
                log_severities[severity] += int(count)
        for source_kind in ("jobs", "events", "logs"):
            source_status = str(rollup["source_status"][source_kind])
            source_counts = source_statuses[source_kind]
            source_counts[source_status] = source_counts.get(source_status, 0) + 1
    return {
        "service_count": len(rollups),
        "jobs": {
            "total": total_jobs,
            "active": active_jobs,
            "terminal": terminal_jobs,
            "statuses": job_statuses,
            "by_service": jobs_by_service,
        },
        "events": {
            "total": total_events,
            "by_severity": event_severities,
            "by_service": events_by_service,
        },
        "logs": {
            "total": total_logs,
            "by_severity": log_severities,
            "by_service": logs_by_service,
            "redacted_attribute_count": redacted_attribute_count,
        },
        "source_statuses": source_statuses,
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


def _job_control_payload_string(payload: dict[str, Any] | None, key: str) -> str | None:
    if payload is None or key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise AgJobControlError(
            status_code=422,
            error_code="ag.job_control_payload_invalid",
            detail=f"{key} must be a non-empty string when supplied.",
            retryable=False,
        )
    return value


def _job_control_required_payload_string(
    payload: dict[str, Any] | None, key: str
) -> str:
    value = _job_control_payload_string(payload, key)
    if value is None:
        raise AgJobControlError(
            status_code=422,
            error_code="ag.job_control_payload_invalid",
            detail=f"{key} must be a non-empty string.",
            retryable=False,
        )
    return value


def _job_control_dispatch_problem_response(
    request: Request,
    exc: AgJobControlError,
    *,
    audit_result: OperationalEventEmitResult | None = None,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Job control dispatch failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/job-control-dispatch-failed",
        details={
            "audit_event": (
                audit_result.to_summary()
                if audit_result is not None
                else {"ok": False, "error_code": "ag.job_control_audit_not_requested"}
            )
        },
    )


def _service_log_retention_dispatch_request(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    source = payload or {}
    if not isinstance(source, dict):
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail="retention purge payload must be an object.",
            retryable=False,
        )
    dry_run = _service_log_retention_payload_bool(
        source,
        "dry_run",
        default=True,
    )
    delete_enabled = _service_log_retention_payload_bool(
        source,
        "delete_enabled",
        default=False,
    )
    if dry_run and delete_enabled:
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail="delete_enabled cannot be true for dry-run retention purge.",
            retryable=False,
        )
    return {
        "retention_cutoff": _service_log_retention_required_payload_string(
            source,
            "retention_cutoff",
        ),
        "retention_days": _service_log_retention_payload_int(
            source,
            "retention_days",
            default=DEFAULT_SERVICE_LOG_RETENTION_DAYS,
        ),
        "checked_at": _service_log_retention_payload_string(
            source,
            "checked_at",
        ),
        "dry_run": dry_run,
        "delete_enabled": delete_enabled,
        "max_delete_count": _service_log_retention_payload_int(
            source,
            "max_delete_count",
            default=DEFAULT_SERVICE_LOG_RETENTION_MAX_DELETE_COUNT,
        ),
        "requested_by": _service_log_retention_payload_object(
            source,
            "requested_by",
        ),
        "idempotency_key": _service_log_retention_payload_string(
            source,
            "idempotency_key",
        ),
    }


def _service_log_retention_required_payload_string(
    payload: dict[str, Any],
    key: str,
) -> str:
    value = _service_log_retention_payload_string(payload, key)
    if value is None:
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail=f"{key} must be a non-empty string.",
            retryable=False,
        )
    return value


def _service_log_retention_payload_string(
    payload: dict[str, Any],
    key: str,
) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail=f"{key} must be a non-empty string when supplied.",
            retryable=False,
        )
    return value


def _service_log_retention_payload_bool(
    payload: dict[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail=f"{key} must be a boolean.",
            retryable=False,
        )
    return value


def _service_log_retention_payload_int(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail=f"{key} must be an integer.",
            retryable=False,
        )
    return value


def _service_log_retention_payload_object(
    payload: dict[str, Any],
    key: str,
) -> dict[str, Any] | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, dict):
        raise AgServiceLogRetentionError(
            status_code=422,
            error_code="ag.service_log_retention_payload_invalid",
            detail=f"{key} must be an object.",
            retryable=False,
        )
    return deepcopy(value)


def _service_log_retention_dispatch_problem_response(
    request: Request,
    exc: AgServiceLogRetentionError,
    *,
    audit_result: OperationalEventEmitResult | None = None,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Service log retention dispatch failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "service-log-retention-dispatch-failed"
        ),
        details={
            "audit_event": (
                audit_result.to_summary()
                if audit_result is not None
                else {
                    "ok": False,
                    "error_code": "ag.service_log_retention_audit_not_requested",
                }
            )
        },
    )


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
    if (
        event_severity is not None
        and event_severity.upper() not in OPERATIONAL_EVENT_SEVERITIES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.operational_event_severity_invalid",
            title="Invalid operational event severity",
            detail=f"Unsupported operational event severity: {event_severity}",
            type_uri="https://nex-platform.local/problems/operational-event-severity-invalid",
        )
    return None


def _validate_worker_runtime_filters(
    request: Request,
    *,
    service_id: str | None,
    status: str | None,
    worker_type: str | None,
) -> JSONResponse | None:
    if service_id is not None and service_id not in SERVICE_SPECS:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.worker_service_invalid",
            title="Invalid worker service filter",
            detail=f"Unsupported worker service: {service_id}",
            type_uri="https://nex-platform.local/problems/worker-service-invalid",
        )
    if status is not None and status.upper() not in WORKER_HEARTBEAT_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.worker_status_invalid",
            title="Invalid worker status filter",
            detail=f"Unsupported worker status: {status}",
            type_uri="https://nex-platform.local/problems/worker-status-invalid",
        )
    if worker_type is not None and not worker_type.strip():
        return problem_response(
            request,
            status_code=400,
            error_code="ag.worker_type_invalid",
            title="Invalid worker type filter",
            detail="worker_type must be a non-empty string when provided.",
            type_uri="https://nex-platform.local/problems/worker-type-invalid",
        )
    return None


def _validate_service_log_filters(
    request: Request,
    *,
    service_id: str | None,
    severity: str | None,
    logger_name: str | None,
    subject_type: str | None,
    subject_id: str | None,
) -> JSONResponse | None:
    if service_id is not None and service_id not in SERVICE_SPECS:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.service_log_service_invalid",
            title="Invalid service log service filter",
            detail=f"Unsupported service log service: {service_id}",
            type_uri="https://nex-platform.local/problems/service-log-service-invalid",
        )
    if severity is not None and severity.upper() not in SERVICE_LOG_SEVERITIES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.service_log_severity_invalid",
            title="Invalid service log severity",
            detail=f"Unsupported service log severity: {severity}",
            type_uri="https://nex-platform.local/problems/service-log-severity-invalid",
        )
    for field_name, value in (
        ("logger_name", logger_name),
        ("subject_type", subject_type),
        ("subject_id", subject_id),
    ):
        if value is not None and not value.strip():
            return problem_response(
                request,
                status_code=400,
                error_code=f"ag.service_log_{field_name}_invalid",
                title="Invalid service log filter",
                detail=f"{field_name} must be a non-empty string when provided.",
                type_uri="https://nex-platform.local/problems/service-log-filter-invalid",
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


def _normalize_log_search_query_or_problem(
    request: Request,
    value: str | None,
) -> str | None | JSONResponse:
    try:
        return normalize_operation_log_search_query(value)
    except OperationsQueryError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Invalid service log search query",
            detail=exc.detail,
            type_uri="https://nex-platform.local/problems/service-log-query-invalid",
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


def normalize_operation_log_search_query(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if len(normalized) > MAX_OPERATION_EVENT_QUERY_LENGTH:
        raise OperationsQueryError(
            error_code="ag.service_log_query_invalid",
            detail=(
                "service log search query must be "
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
        [service_id] if service_id is not None else list(runtime.selected_service_ids)
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
                "logs": True,
                "workers": True,
            },
            "read_only": False,
            "job_queue": "InMemoryJobQueue",
            "operational_event_store": "InMemoryOperationalEventStore",
            "service_log_store": "InMemoryServiceLogStore",
            "worker_heartbeat_store": "InMemoryWorkerHeartbeatStore",
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
                "logs": False,
                "workers": False,
            },
            "read_only": None,
            "job_queue": None,
            "operational_event_store": None,
            "service_log_store": None,
            "worker_heartbeat_store": None,
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
        "service_log_store": source_summary["service_log_store"],
        "worker_heartbeat_store": source_summary["worker_heartbeat_store"],
        "database_env": source_summary.get("database_env"),
        "redacted_database_url": source_summary.get("redacted_database_url"),
    }


def _operation_source_is_read_only(source: OperationsSource) -> bool:
    job_read_only = source.job_queue is None or isinstance(
        source.job_queue, ReadOnlyJobQueue
    )
    event_read_only = source.operational_event_store is None or isinstance(
        source.operational_event_store, ReadOnlyOperationalEventStore
    )
    log_read_only = source.service_log_store is None or isinstance(
        source.service_log_store, ReadOnlyServiceLogStore
    )
    worker_read_only = source.worker_heartbeat_store is None or isinstance(
        source.worker_heartbeat_store, ReadOnlyWorkerHeartbeatStore
    )
    return job_read_only and event_read_only and log_read_only and worker_read_only


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
        _parse_operation_timestamp(options.since) if options.since is not None else None
    )
    until_dt = (
        _parse_operation_timestamp(options.until) if options.until is not None else None
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
        searchable_parts.append(json.dumps(details, ensure_ascii=False, sort_keys=True))
    return any(
        lowered_query in str(part).lower()
        for part in searchable_parts
        if part is not None
    )


def _service_log_stores_for_projection(
    *,
    service_log_stores: Mapping[str, ServiceLogStore] | None,
    registry: OperationsSourceRegistry | None,
) -> Mapping[str, ServiceLogStore]:
    if registry is not None:
        return registry.service_log_stores()
    return service_log_stores or DEFAULT_SERVICE_LOG_STORES


def _get_service_log_from_stores(
    stores: Mapping[str, ServiceLogStore],
    log_id: str,
) -> dict[str, Any] | None:
    for store in stores.values():
        entry = store.get_log(log_id)
        if entry is not None:
            return entry
    return None


def _service_log_matches_query(entry: dict[str, Any], query: str) -> bool:
    lowered_query = query.lower()
    searchable_parts = [
        entry.get("log_id"),
        entry.get("service_id"),
        entry.get("severity"),
        entry.get("logger_name"),
        entry.get("message"),
        entry.get("trace_id"),
        entry.get("request_id"),
        entry.get("job_id"),
    ]
    subject_ref = entry.get("subject_ref")
    if isinstance(subject_ref, Mapping):
        searchable_parts.extend(subject_ref.values())
    attributes = entry.get("attributes")
    if isinstance(attributes, Mapping):
        searchable_parts.append(
            json.dumps(attributes, ensure_ascii=False, sort_keys=True)
        )
    redacted_keys = entry.get("redacted_attribute_keys")
    if isinstance(redacted_keys, list):
        searchable_parts.extend(redacted_keys)
    return any(
        lowered_query in str(part).lower()
        for part in searchable_parts
        if part is not None
    )


def _service_log_retention_candidate(
    entry: dict[str, Any],
    *,
    checked_dt: datetime,
    retention_cutoff: str,
) -> dict[str, Any]:
    observed_dt = _operation_record_timestamp(entry, timestamp_field="observed_at")
    age_days = max(0, (checked_dt - observed_dt).days)
    return {
        "service_id": entry["service_id"],
        "log_id": entry["log_id"],
        "severity": entry["severity"],
        "logger_name": entry["logger_name"],
        "trace_id": entry.get("trace_id"),
        "request_id": entry.get("request_id"),
        "job_id": entry.get("job_id"),
        "subject_ref": deepcopy(entry.get("subject_ref")),
        "observed_at": entry["observed_at"],
        "age_days": age_days,
        "retention_cutoff": retention_cutoff,
        "redacted_attribute_keys": deepcopy(entry["redacted_attribute_keys"]),
    }


def _summarize_service_log_retention_dry_run(
    candidates: list[dict[str, Any]],
    *,
    source_statuses: Mapping[str, dict[str, Any]],
    selected_service_count: int,
    returned_candidate_count: int,
    retention_days: int,
    retention_cutoff: str,
) -> dict[str, Any]:
    candidate_summary = summarize_service_logs(candidates)
    source_status_counts: dict[str, int] = {}
    scanned_log_count = 0
    for source_status in source_statuses.values():
        status = str(source_status["status"])
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
        scanned_log_count += int(source_status.get("log_count", 0))
    return {
        "retention_days": retention_days,
        "retention_cutoff": retention_cutoff,
        "scan_limit": MAX_SERVICE_LOG_LIMIT,
        "selected_service_count": selected_service_count,
        "source_statuses": source_status_counts,
        "scanned_log_count": scanned_log_count,
        "total_candidate_count": candidate_summary["total"],
        "returned_candidate_count": returned_candidate_count,
        "by_service": candidate_summary["by_service"],
        "by_severity": candidate_summary["by_severity"],
        "redacted_attribute_count": candidate_summary["redacted_attribute_count"],
    }


def _summarize_service_log_retention_history_projection(
    entries: list[dict[str, Any]],
    *,
    source_statuses: Mapping[str, dict[str, Any]],
    selected_service_count: int,
) -> dict[str, Any]:
    history_summary = summarize_service_log_retention_history(entries)
    source_status_counts: dict[str, int] = {}
    scanned_history_count = 0
    for source_status in source_statuses.values():
        status = str(source_status["status"])
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
        scanned_history_count += int(source_status.get("history_count", 0))
    return {
        **history_summary,
        "selected_service_count": selected_service_count,
        "source_statuses": source_status_counts,
        "scanned_history_count": scanned_history_count,
        "returned_history_count": len(entries),
    }


def _normalize_service_log_retention_history_mode(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper()
    if normalized not in SERVICE_LOG_RETENTION_EXECUTION_MODES:
        raise ServiceLogError(
            error_code="ag.service_log_retention_history_mode_invalid",
            detail=(
                f"Unsupported service log retention history mode: {value}; "
                f"expected one of {', '.join(SERVICE_LOG_RETENTION_EXECUTION_MODES)}."
            ),
            status_code=422,
        )
    return normalized


def _normalize_service_log_retention_history_status(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper()
    if normalized not in SERVICE_LOG_RETENTION_EXECUTION_STATUSES:
        raise ServiceLogError(
            error_code="ag.service_log_retention_history_status_invalid",
            detail=(
                "Unsupported service log retention history execution_status: "
                f"{value}; expected one of "
                f"{', '.join(SERVICE_LOG_RETENTION_EXECUTION_STATUSES)}."
            ),
            status_code=422,
        )
    return normalized


def _trace_job_timeline_items(
    job_queues: Mapping[str, JobQueue],
    *,
    selected_service_ids: list[str],
    trace_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    timeline_items: list[dict[str, Any]] = []
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
            jobs = [job for job in queue.list_jobs() if job.get("trace_id") == trace_id]
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
            "job_count": len(jobs),
        }
        timeline_items.extend(
            _job_trace_timeline_item(selected_service_id, job) for job in jobs
        )
    return timeline_items, source_statuses


def _trace_log_timeline_items(
    log_stores: Mapping[str, ServiceLogStore],
    *,
    selected_service_ids: list[str],
    trace_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    timeline_items: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        store = log_stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "log_count": 0,
            }
            continue
        try:
            logs = store.list_logs(
                service_id=selected_service_id,
                trace_id=trace_id,
                limit=normalize_service_log_limit(500),
            )
        except ServiceLogError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "log_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        source_statuses[selected_service_id] = {
            "status": "READY",
            "log_count": len(logs),
        }
        timeline_items.extend(_log_trace_timeline_item(log) for log in logs)
    return timeline_items, source_statuses


def _trace_retrieval_package_timeline_items(
    retrieval_package_stores: Mapping[str, RetrievalPackageTraceStore] | None,
    *,
    selected_service_ids: list[str],
    trace_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if retrieval_package_stores is None:
        return [], {}
    timeline_items: list[dict[str, Any]] = []
    source_statuses: dict[str, dict[str, Any]] = {}
    for selected_service_id in selected_service_ids:
        if selected_service_id != "nex-cx":
            continue
        store = retrieval_package_stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "retrieval_package_count": 0,
            }
            continue
        try:
            packages = store.list_retrieval_packages(
                trace_id=trace_id,
                limit=500,
            )
        except Exception as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "retrieval_package_count": 0,
                "error_code": getattr(
                    exc,
                    "error_code",
                    "ag.retrieval_package_source_unavailable",
                ),
                "detail": getattr(
                    exc,
                    "detail",
                    "Retrieval package source could not be read.",
                ),
            }
            continue
        source_statuses[selected_service_id] = {
            "status": "READY",
            "retrieval_package_count": len(packages),
        }
        timeline_items.extend(
            _retrieval_package_trace_timeline_item(selected_service_id, package)
            for package in packages
        )
    return timeline_items, source_statuses


def _dashboard_source_runtime(
    *,
    runtime: AgOperationsSourceRuntime | None,
    registry: OperationsSourceRegistry | None,
) -> AgOperationsSourceRuntime:
    if runtime is not None:
        return runtime
    return AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=tuple(sorted(SERVICE_SPECS)),
        registry=registry,
    )


def _dashboard_job_candidates(
    job_queues: Mapping[str, JobQueue],
    *,
    service_id: str | None,
    statuses: set[str],
    options: OperationQueryOptions,
    limit: int,
) -> list[dict[str, Any]]:
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    jobs: list[dict[str, Any]] = []
    for selected_service_id in selected_service_ids:
        queue = job_queues.get(selected_service_id)
        if queue is None:
            continue
        try:
            service_jobs = [
                job for job in queue.list_jobs() if str(job.get("status")) in statuses
            ]
        except JobQueueError:
            continue
        jobs.extend(
            _project_job_for_service(selected_service_id, job) for job in service_jobs
        )
    dashboard_options = OperationQueryOptions(
        limit=limit,
        since=options.since,
        until=options.until,
        sort="desc",
        cursor=None,
    )
    return _apply_operation_query_options(
        jobs,
        dashboard_options,
        timestamp_field="updated_at",
        tie_breaker_fields=("created_at", "service_id", "job_id"),
    )["items"]


def _dashboard_failure_event_candidates(
    event_store: OperationalEventStore,
    *,
    service_id: str | None,
    options: OperationQueryOptions,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        events = event_store.list_events(
            service_id=service_id,
            limit=normalize_operational_event_limit(500),
        )
    except OperationalEventError:
        return []
    failure_events = [
        event for event in events if str(event.get("severity")) in {"ERROR", "CRITICAL"}
    ]
    dashboard_options = OperationQueryOptions(
        limit=limit,
        since=options.since,
        until=options.until,
        sort="desc",
        cursor=None,
    )
    return _apply_operation_query_options(
        failure_events,
        dashboard_options,
        timestamp_field="created_at",
        tie_breaker_fields=("event_id",),
    )["items"]


def _dashboard_failure_log_candidates(
    log_stores: Mapping[str, ServiceLogStore],
    *,
    service_id: str | None,
    options: OperationQueryOptions,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    selected_service_ids = (
        [service_id] if service_id is not None else sorted(SERVICE_SPECS)
    )
    source_statuses: dict[str, dict[str, Any]] = {}
    logs: list[dict[str, Any]] = []
    for selected_service_id in selected_service_ids:
        store = log_stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = {
                "status": "NOT_CONFIGURED",
                "log_count": 0,
            }
            continue
        try:
            service_logs = store.list_logs(
                service_id=selected_service_id,
                limit=normalize_service_log_limit(500),
            )
        except ServiceLogError as exc:
            source_statuses[selected_service_id] = {
                "status": "UNAVAILABLE",
                "log_count": 0,
                "error_code": exc.error_code,
                "detail": exc.detail,
            }
            continue
        failure_logs = [
            log
            for log in service_logs
            if str(log.get("severity", "")).upper() in {"ERROR", "CRITICAL"}
        ]
        source_statuses[selected_service_id] = {
            "status": "READY",
            "log_count": len(service_logs),
        }
        logs.extend(failure_logs)
    dashboard_options = OperationQueryOptions(
        limit=limit,
        since=options.since,
        until=options.until,
        sort="desc",
        cursor=None,
    )
    page = _apply_operation_query_options(
        logs,
        dashboard_options,
        timestamp_field="observed_at",
        tie_breaker_fields=("service_id", "logger_name", "log_id"),
    )
    return page["items"], source_statuses


def _dashboard_cx_processing_run_section(
    stores: Mapping[str, CxProcessingRunDashboardStore] | None,
    *,
    service_id: str | None,
    options: OperationQueryOptions,
    limit: int,
) -> dict[str, Any]:
    source_statuses: dict[str, dict[str, Any]] = {}
    if stores is None:
        return _empty_dashboard_cx_processing_run_section(source_statuses)

    selected_service_ids = (
        ["nex-cx"]
        if service_id is None
        else (["nex-cx"] if service_id == "nex-cx" else [])
    )
    processing_runs: list[dict[str, Any]] = []
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = (
                _dashboard_cx_processing_run_source_status(
                    service_id=selected_service_id,
                    store=None,
                    run_count=0,
                )
            )
            continue
        try:
            records = store.list_processing_runs(
                include_steps=False,
                limit=500,
            )
        except Exception as exc:
            source_statuses[selected_service_id] = (
                _dashboard_cx_processing_run_source_status(
                    service_id=selected_service_id,
                    store=store,
                    run_count=0,
                    error=exc,
                )
            )
            continue
        projected = [
            _dashboard_cx_processing_run_item(selected_service_id, record)
            for record in records
        ]
        visible = _filter_records_by_operation_time(
            projected,
            options,
            timestamp_field="updated_at",
        )
        source_statuses[selected_service_id] = (
            _dashboard_cx_processing_run_source_status(
                service_id=selected_service_id,
                store=store,
                run_count=len(visible),
            )
        )
        processing_runs.extend(visible)

    dashboard_options = OperationQueryOptions(
        limit=limit,
        since=options.since,
        until=options.until,
        sort="desc",
        cursor=None,
    )
    recent = _apply_operation_query_options(
        processing_runs,
        dashboard_options,
        timestamp_field="updated_at",
        tie_breaker_fields=("service_id", "pipeline_run_id"),
    )["items"]
    recent_failures = [run for run in recent if run["status"] == "FAILED"][:limit]
    active = [run for run in recent if run["status"] in {"QUEUED", "RUNNING"}][:limit]
    return {
        "summary": _summarize_dashboard_cx_processing_runs(processing_runs),
        "recent": recent,
        "recent_failures": recent_failures,
        "active": active,
        "source_statuses": source_statuses,
    }


def _empty_dashboard_cx_processing_run_section(
    source_statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": _summarize_dashboard_cx_processing_runs([]),
        "recent": [],
        "recent_failures": [],
        "active": [],
        "source_statuses": source_statuses,
    }


def _dashboard_cx_processing_run_item(
    service_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(record.get("status", "UNKNOWN"))
    return {
        "service_id": service_id,
        "operation_type": "cx_processing_run",
        "pipeline_run_id": str(record.get("pipeline_run_id", "")),
        "document_id": str(record.get("document_id", "")),
        "status": status,
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "job_id": record.get("job_id"),
        "job_type": record.get("job_type"),
        "job_status": record.get("job_status"),
        "job_retryable": record.get("job_retryable"),
        "step_total": _safe_int(record.get("step_total")),
        "step_succeeded": _safe_int(record.get("step_succeeded")),
        "step_skipped": _safe_int(record.get("step_skipped")),
        "step_failed": _safe_int(record.get("step_failed")),
        "queued_at": _dashboard_optional_timestamp(record.get("queued_at")),
        "started_at": _dashboard_optional_timestamp(record.get("started_at")),
        "completed_at": _dashboard_optional_timestamp(record.get("completed_at")),
        "updated_at": _dashboard_timestamp(
            record.get("updated_at")
            or record.get("completed_at")
            or record.get("started_at")
            or record.get("queued_at")
        ),
        "detail_path": (
            "/admin/v1/operations/cx-processing-runs/"
            f"{record.get('pipeline_run_id', '')}"
        ),
    }


def _dashboard_cx_processing_run_source_status(
    *,
    service_id: str,
    store: CxProcessingRunDashboardStore | None,
    run_count: int,
    error: Exception | None = None,
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
    source = {
        "status": "UNAVAILABLE" if error is not None else "READY",
        "service_id": service_id,
        "source_kind": store.source_kind,
        "processing_run_count": run_count,
        "database_env": store.database_env,
        "redacted_database_url": store.redacted_database_url,
    }
    if error is not None:
        source["error_code"] = getattr(
            error,
            "error_code",
            "ag.cx_processing_run_source_unavailable",
        )
        source["detail"] = getattr(
            error,
            "detail",
            "CX processing run source could not be read.",
        )
    return source


def _dashboard_retrieval_threshold_decision_section(
    stores: Mapping[str, RetrievalPackageTraceStore] | None,
    *,
    service_id: str | None,
    options: OperationQueryOptions,
    policies: tuple[dict[str, Any], ...] | None,
) -> dict[str, Any]:
    source_statuses: dict[str, dict[str, Any]] = {}
    selected_service_ids = _dashboard_retrieval_threshold_service_ids(service_id)
    if not selected_service_ids or stores is None:
        return _empty_dashboard_retrieval_threshold_decision_section(source_statuses)

    samples: list[dict[str, Any]] = []
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = (
                _dashboard_retrieval_threshold_source_status(
                    service_id=selected_service_id,
                    store=None,
                    package_count=0,
                )
            )
            continue
        try:
            records = store.list_retrieval_packages(limit=500)
        except Exception as exc:
            source_statuses[selected_service_id] = (
                _dashboard_retrieval_threshold_source_status(
                    service_id=selected_service_id,
                    store=store,
                    package_count=0,
                    error=exc,
                )
            )
            continue
        visible_records = _filter_records_by_operation_time(
            [dict(record) for record in records],
            options,
            timestamp_field="created_at",
        )
        source_statuses[selected_service_id] = (
            _dashboard_retrieval_threshold_source_status(
                service_id=selected_service_id,
                store=store,
                package_count=len(visible_records),
            )
        )
        samples.extend(
            _dashboard_retrieval_threshold_calibration_sample(
                selected_service_id,
                record,
            )
            for record in visible_records
        )

    policy_records = (
        list_retrieval_policy_records()
        if policies is None
        else (list_retrieval_policy_records(policies))
    )
    source_degraded = any(
        source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
        for source in source_statuses.values()
    )
    decisions = [
        project_retrieval_threshold_decision(
            policy,
            sample_summary=summarize_retrieval_score_calibration_samples(
                _dashboard_retrieval_threshold_samples_for_policy(
                    samples,
                    policy.get("policy_id"),
                )
            ),
            source_degraded=source_degraded,
            service_id=RETRIEVAL_THRESHOLD_SOURCE_SERVICE_ID,
        )
        for policy in policy_records
    ]
    return {
        "summary": summarize_retrieval_threshold_decisions(decisions),
        "closure": summarize_retrieval_threshold_calibration_closure(decisions),
        "threshold_decisions": decisions,
        "source_statuses": source_statuses,
    }


def _dashboard_retrieval_threshold_service_ids(
    service_id: str | None,
) -> list[str]:
    if service_id is None:
        return [RETRIEVAL_THRESHOLD_SOURCE_SERVICE_ID]
    if service_id == RETRIEVAL_THRESHOLD_SOURCE_SERVICE_ID:
        return [RETRIEVAL_THRESHOLD_SOURCE_SERVICE_ID]
    return []


def _empty_dashboard_retrieval_threshold_decision_section(
    source_statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": summarize_retrieval_threshold_decisions([]),
        "closure": summarize_retrieval_threshold_calibration_closure([]),
        "threshold_decisions": [],
        "source_statuses": source_statuses,
    }


def _dashboard_retrieval_threshold_calibration_sample(
    service_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    calibration = build_retrieval_score_calibration_projection(record)
    created_at = _dashboard_timestamp(record.get("created_at"))
    return {
        "service_id": service_id,
        "operation_type": "retrieval_score_calibration",
        "operation_timestamp": created_at,
        "retrieval_package_id": str(record.get("retrieval_package_id", "")),
        "package_hash": record.get("package_hash"),
        "status": str(record.get("status") or "UNKNOWN"),
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "retrieval_policy_id": str(record.get("retrieval_policy_id") or "UNKNOWN"),
        "retrieval_policy_version": record.get("retrieval_policy_version"),
        "ranker_mix": record.get("ranker_mix"),
        "rerank_state": record.get("rerank_state"),
        "evidence_count": _safe_int(record.get("evidence_count")),
        "warning_count": _safe_int(record.get("warning_count")),
        "no_answer_reason": record.get("no_answer_reason"),
        "best_score": calibration["best_score"],
        "score_calibration": calibration,
        "created_at": created_at,
        "updated_at": _dashboard_timestamp(record.get("updated_at")),
    }


def _dashboard_retrieval_threshold_samples_for_policy(
    samples: list[dict[str, Any]],
    policy_id: object,
) -> list[dict[str, Any]]:
    return [
        sample for sample in samples if sample.get("retrieval_policy_id") == policy_id
    ]


def _dashboard_retrieval_threshold_source_status(
    *,
    service_id: str,
    store: RetrievalPackageTraceStore | None,
    package_count: int,
    error: Exception | None = None,
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
    source = {
        "status": "UNAVAILABLE" if error is not None else "READY",
        "service_id": service_id,
        "source_kind": store.source_kind,
        "package_count": package_count,
        "database_env": store.database_env,
        "redacted_database_url": store.redacted_database_url,
    }
    if error is not None:
        source["error_code"] = getattr(
            error,
            "error_code",
            "ag.retrieval_threshold_decision_source_unavailable",
        )
        source["detail"] = getattr(
            error,
            "detail",
            "Retrieval threshold decision source could not be read.",
        )
    return source


def _dashboard_generation_remediation_section(
    stores: Mapping[str, GenerationRemediationTaskDashboardStore] | None,
    *,
    service_id: str | None,
    options: OperationQueryOptions,
    limit: int,
) -> dict[str, Any]:
    source_statuses: dict[str, dict[str, Any]] = {}
    selected_service_ids = _dashboard_generation_remediation_service_ids(service_id)
    if not selected_service_ids or stores is None:
        return _empty_dashboard_generation_remediation_section(source_statuses)

    tasks: list[dict[str, Any]] = []
    for selected_service_id in selected_service_ids:
        store = stores.get(selected_service_id)
        if store is None:
            source_statuses[selected_service_id] = (
                _dashboard_generation_remediation_source_status(
                    service_id=selected_service_id,
                    store=None,
                    task_count=0,
                )
            )
            continue
        try:
            records = store.list_recent(limit=500)
        except Exception as exc:
            source_statuses[selected_service_id] = (
                _dashboard_generation_remediation_source_status(
                    service_id=selected_service_id,
                    store=store,
                    task_count=0,
                    error=exc,
                )
            )
            continue
        projected = [
            _dashboard_generation_remediation_item(selected_service_id, record)
            for record in records
            if isinstance(record, Mapping)
        ]
        visible = _filter_records_by_operation_time(
            projected,
            options,
            timestamp_field="updated_at",
        )
        source_statuses[selected_service_id] = (
            _dashboard_generation_remediation_source_status(
                service_id=selected_service_id,
                store=store,
                task_count=len(visible),
            )
        )
        tasks.extend(visible)

    dashboard_options = OperationQueryOptions(
        limit=limit,
        since=options.since,
        until=options.until,
        sort="desc",
        cursor=None,
    )
    recent = _apply_operation_query_options(
        tasks,
        dashboard_options,
        timestamp_field="updated_at",
        tie_breaker_fields=("service_id", "remediation_action_id"),
    )["items"]
    attention = [
        task for task in recent if _generation_remediation_task_needs_attention(task)
    ]
    return {
        "projection_schema_version": "ag_generation_remediation_dashboard_section.v1",
        "summary": _summarize_dashboard_generation_remediation(tasks),
        "recent": recent,
        "attention": attention,
        "source_statuses": source_statuses,
    }


def _dashboard_generation_remediation_service_ids(service_id: str | None) -> list[str]:
    if service_id is None:
        return ["nex-ag"]
    if service_id == "nex-ag":
        return ["nex-ag"]
    return []


def _empty_dashboard_generation_remediation_section(
    source_statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "projection_schema_version": "ag_generation_remediation_dashboard_section.v1",
        "summary": _summarize_dashboard_generation_remediation([]),
        "recent": [],
        "attention": [],
        "source_statuses": source_statuses,
    }


def _dashboard_generation_remediation_item(
    service_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    owner = record.get("owner_ref")
    owner_ref = owner if isinstance(owner, Mapping) else {}
    evidence = record.get("evidence")
    evidence_summary = evidence if isinstance(evidence, Mapping) else {}
    result = record.get("result_ref")
    remediation_action_id = str(record.get("remediation_action_id") or "")
    cx_generation_id = str(record.get("cx_generation_id") or "UNKNOWN")
    return {
        "service_id": service_id,
        "operation_type": "generation_remediation_task",
        "remediation_action_id": remediation_action_id,
        "cx_generation_id": cx_generation_id,
        "trace_id": _nullable_string(record.get("trace_id")),
        "request_id": _nullable_string(record.get("request_id")),
        "action_type": str(record.get("action_type") or "unknown"),
        "action_status": str(record.get("action_status") or "UNKNOWN"),
        "priority": str(record.get("priority") or "NORMAL"),
        "owner_type": _nullable_string(owner_ref.get("owner_type")),
        "owner_id": _nullable_string(owner_ref.get("owner_id")),
        "tenant_id": _nullable_string(record.get("tenant_id")),
        "reason_codes": [
            str(reason)
            for reason in record.get("reason_codes", [])
            if isinstance(reason, str)
        ],
        "source_ref_count": _safe_int(len(record.get("source_refs", []))),
        "evidence_hash_count": _safe_int(
            len(evidence_summary.get("evidence_hashes", []))
        ),
        "evidence_preview_count": _safe_int(
            len(evidence_summary.get("evidence_previews", []))
        ),
        "result_available": isinstance(result, Mapping),
        "created_at": _dashboard_optional_timestamp(record.get("created_at")),
        "updated_at": _dashboard_timestamp(record.get("updated_at")),
        "detail_path": (
            f"/admin/v1/generation-audit/generations/{cx_generation_id}"
            f"/remediation-tasks/{remediation_action_id}"
        ),
    }


def _summarize_dashboard_generation_remediation(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    by_status = _dashboard_count_by(items, "action_status")
    by_action_type = _dashboard_count_by(items, "action_type")
    return {
        "total": len(items),
        "by_status": by_status,
        "by_action_type": by_action_type,
        "active_count": sum(
            1
            for item in items
            if item["action_status"] in GENERATION_REMEDIATION_ACTIVE_STATUSES
        ),
        "failed_count": sum(1 for item in items if item["action_status"] == "FAILED"),
        "completed_count": sum(
            1 for item in items if item["action_status"] == "COMPLETED"
        ),
        "urgent_count": sum(1 for item in items if item["priority"] == "URGENT"),
        "attention_count": sum(
            1 for item in items if _generation_remediation_task_needs_attention(item)
        ),
    }


def _dashboard_count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = str(item.get(key) or "UNKNOWN")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def _generation_remediation_task_needs_attention(item: Mapping[str, Any]) -> bool:
    status = str(item.get("action_status") or "UNKNOWN")
    return status not in GENERATION_REMEDIATION_TERMINAL_STATUSES


def _dashboard_generation_remediation_source_status(
    *,
    service_id: str,
    store: GenerationRemediationTaskDashboardStore | None,
    task_count: int,
    error: Exception | None = None,
) -> dict[str, Any]:
    if store is None:
        return {
            "status": "NOT_CONFIGURED",
            "service_id": service_id,
            "source_kind": "none",
            "task_count": 0,
            "database_env": None,
            "redacted_database_url": None,
        }
    source = {
        "status": "UNAVAILABLE" if error is not None else "READY",
        "service_id": service_id,
        "source_kind": getattr(store, "source_kind", "unknown"),
        "task_count": task_count,
        "database_env": getattr(store, "database_env", None),
        "redacted_database_url": getattr(store, "redacted_database_url", None),
    }
    if error is not None:
        source["error_code"] = getattr(
            error,
            "error_code",
            "ag.generation_remediation_source_unavailable",
        )
        source["detail"] = getattr(
            error,
            "detail",
            "Generation remediation task source could not be read.",
        )
    return source


def _dashboard_generation_quality_section(
    generation_audit_projections: list[Mapping[str, Any]] | None,
    *,
    limit: int,
) -> dict[str, Any]:
    items = [
        item
        for projection in generation_audit_projections or []
        if isinstance(projection, Mapping)
        and (item := _dashboard_generation_quality_item(projection)) is not None
    ]
    items.sort(key=lambda item: item["created_at"] or "", reverse=True)
    recent = items[:limit]
    attention = [
        item for item in recent if _generation_quality_item_needs_attention(item)
    ]
    return {
        "projection_schema_version": "ag_generation_quality_dashboard_section.v1",
        "summary": _summarize_dashboard_generation_quality(items),
        "recent": recent,
        "attention": attention,
    }


def _dashboard_generation_quality_item(
    generation_audit_projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    quality = generation_audit_projection.get("grounded_response_quality")
    if not isinstance(quality, Mapping):
        return None
    cx_generation_id = str(
        generation_audit_projection.get("cx_generation_id") or "UNKNOWN"
    )
    coverage_status = _generation_quality_status(quality.get("coverage_status"))
    boundary_status = _generation_quality_status(quality.get("boundary_status"))
    issue_codes = [
        str(code) for code in quality.get("issue_codes", []) if isinstance(code, str)
    ]
    lineage_mismatches = [
        str(field)
        for field in quality.get("lineage_mismatches", [])
        if isinstance(field, str)
    ]
    return {
        "cx_generation_id": cx_generation_id,
        "trace_id": generation_audit_projection.get("trace_id"),
        "request_id": generation_audit_projection.get("request_id"),
        "created_at": _dashboard_optional_timestamp(
            generation_audit_projection.get("created_at")
        ),
        "coverage_status": coverage_status,
        "boundary_status": boundary_status,
        "citation_status": _nullable_string(quality.get("citation_status")),
        "grounding_required": bool(quality.get("grounding_required")),
        "source_quality_issue_count": _safe_optional_int(
            quality.get("source_quality_issue_count")
        ),
        "projection_issue_count": _safe_int(quality.get("projection_issue_count")),
        "issue_codes": issue_codes,
        "lineage_mismatches": lineage_mismatches,
        "recommended_action": _nullable_string(quality.get("recommended_action")),
        "retrieval_package_id": _nullable_string(quality.get("retrieval_package_id")),
        "retrieval_package_hash": _nullable_string(
            quality.get("retrieval_package_hash")
        ),
        "structured_draft_id": _nullable_string(quality.get("structured_draft_id")),
        "evidence_ref_count": _safe_optional_int(quality.get("evidence_ref_count")),
        "artifact_handoff_quality_available": bool(
            quality.get("artifact_handoff_quality_available")
        ),
        "detail_path": f"/admin/v1/generation-audit/generations/{cx_generation_id}",
    }


def _summarize_dashboard_generation_quality(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    by_coverage_status = {status: 0 for status in GENERATION_QUALITY_STATUSES}
    by_boundary_status = {status: 0 for status in GENERATION_QUALITY_STATUSES}
    for item in items:
        by_coverage_status[str(item["coverage_status"])] += 1
        by_boundary_status[str(item["boundary_status"])] += 1
    return {
        "total": len(items),
        "by_coverage_status": by_coverage_status,
        "by_boundary_status": by_boundary_status,
        "attention_count": sum(
            1 for item in items if _generation_quality_item_needs_attention(item)
        ),
        "failed_count": sum(
            1
            for item in items
            if item["coverage_status"] == "FAIL" or item["boundary_status"] == "FAIL"
        ),
        "warning_count": sum(
            1
            for item in items
            if item["coverage_status"] == "WARN" or item["boundary_status"] == "WARN"
        ),
    }


def _generation_quality_status(value: object) -> str:
    if isinstance(value, str) and value in GENERATION_QUALITY_STATUSES:
        return value
    return "UNKNOWN"


def _generation_quality_item_needs_attention(item: Mapping[str, Any]) -> bool:
    return (
        item.get("coverage_status") in GENERATION_QUALITY_ATTENTION_STATUSES
        or item.get("boundary_status") in GENERATION_QUALITY_ATTENTION_STATUSES
    )


def build_generation_quality_issue_detail_projection(
    generation_audit_projection: Mapping[str, Any],
    *,
    checked_at: str | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    item = _dashboard_generation_quality_item(generation_audit_projection)
    projection = {
        "projection_schema_version": (
            AG_GENERATION_QUALITY_ISSUE_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "READY" if item is not None else "DEGRADED",
        "checked_at": checked_at or _utc_now(),
        "cx_generation_id": _generation_quality_detail_generation_id(
            generation_audit_projection,
            item,
        ),
        "trace_id": generation_audit_projection.get("trace_id"),
        "request_id": generation_audit_projection.get("request_id"),
        "source_projection": _generation_quality_detail_source_projection(
            generation_audit_projection
        ),
        "quality": item,
        "attention_required": (
            _generation_quality_item_needs_attention(item)
            if item is not None
            else True
        ),
        "severity": _generation_quality_detail_severity(item),
        "runbook": _generation_quality_detail_runbook(item),
        "debug_paths": _generation_quality_detail_debug_paths(item),
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
            "excluded_fields": [
                "raw_prompt",
                "messages",
                "source_text",
                "output_text",
                "raw_output",
                "provider_url",
                "provider_endpoint",
                "model_path",
                "storage_path",
            ],
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _generation_quality_detail_generation_id(
    generation_audit_projection: Mapping[str, Any],
    item: Mapping[str, Any] | None,
) -> str:
    if item is not None:
        return str(item["cx_generation_id"])
    return str(generation_audit_projection.get("cx_generation_id") or "UNKNOWN")


def _generation_quality_detail_source_projection(
    generation_audit_projection: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "projection_schema_version": generation_audit_projection.get(
            "projection_schema_version"
        ),
        "created_at": _dashboard_optional_timestamp(
            generation_audit_projection.get("created_at")
        ),
        "grounded_response_quality_available": isinstance(
            generation_audit_projection.get("grounded_response_quality"),
            Mapping,
        ),
    }


def _generation_quality_detail_severity(item: Mapping[str, Any] | None) -> str:
    if item is None:
        return "WARNING"
    if item["coverage_status"] == "FAIL" or item["boundary_status"] == "FAIL":
        return "ERROR"
    if (
        item["coverage_status"] in {"WARN", "UNKNOWN"}
        or item["boundary_status"] in {"WARN", "UNKNOWN"}
    ):
        return "WARNING"
    return "INFO"


def _generation_quality_detail_runbook(
    item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if item is None:
        return {
            "runbook_id": "ag.generation_quality.source_projection_invalid.v1",
            "recommended_operator_action": "restore_generation_quality_projection",
            "operator_steps": [
                "open_generation_audit_source",
                "verify_grounded_response_quality_projection",
                "rerun_generation_audit_projection",
            ],
        }
    if item["coverage_status"] == "FAIL" or item["boundary_status"] == "FAIL":
        return {
            "runbook_id": "ag.generation_quality.failure_triage.v1",
            "recommended_operator_action": "triage_grounded_generation_quality_failure",
            "operator_steps": [
                "open_generation_audit_detail",
                "compare_cx_and_ae_quality_lineage",
                "decide_repair_retry_or_user_escalation",
            ],
        }
    if item["coverage_status"] == "UNKNOWN" or item["boundary_status"] == "UNKNOWN":
        return {
            "runbook_id": "ag.generation_quality.metadata_gap_triage.v1",
            "recommended_operator_action": "restore_missing_quality_metadata",
            "operator_steps": [
                "open_generation_audit_detail",
                "verify_cx_grounded_response_quality_metadata",
                "verify_ae_artifact_handoff_quality_summary",
            ],
        }
    if item["coverage_status"] == "WARN" or item["boundary_status"] == "WARN":
        return {
            "runbook_id": "ag.generation_quality.warning_triage.v1",
            "recommended_operator_action": (
                item.get("recommended_action") or "review_generation_quality_warning"
            ),
            "operator_steps": [
                "open_generation_audit_detail",
                "review_issue_codes_and_lineage_mismatches",
                "complete_missing_quality_metadata",
            ],
        }
    return {
        "runbook_id": "ag.generation_quality.no_attention_required.v1",
        "recommended_operator_action": "observe",
        "operator_steps": ["keep_dashboard_monitoring"],
    }


def _generation_quality_detail_debug_paths(
    item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if item is None:
        return {
            "generation_audit_detail_path": None,
            "operations_dashboard_path": "/admin/v1/operations/dashboard",
            "retrieval_package_detail_path": None,
        }
    retrieval_package_id = item.get("retrieval_package_id")
    return {
        "generation_audit_detail_path": item.get("detail_path"),
        "operations_dashboard_path": "/admin/v1/operations/dashboard",
        "retrieval_package_detail_path": (
            f"/admin/v1/operations/retrieval-packages/{retrieval_package_id}"
            if retrieval_package_id
            else None
        ),
    }


def _summarize_dashboard_cx_processing_runs(
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
        "queued_count": by_status.get("QUEUED", 0),
        "active_count": by_status.get("QUEUED", 0) + by_status.get("RUNNING", 0),
        "retryable_failed_count": sum(
            1
            for run in processing_runs
            if run["status"] == "FAILED" and run.get("job_retryable") is True
        ),
        "step_failed_count": sum(
            _safe_int(run.get("step_failed")) for run in processing_runs
        ),
    }


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _safe_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        if parsed >= 0:
            return parsed
    return None


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _dashboard_optional_timestamp(value: object) -> str | None:
    if value is None:
        return None
    return _dashboard_timestamp(value)


def _dashboard_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if value is None:
        return "1970-01-01T00:00:00Z"
    return str(value)


def _dashboard_replay_candidates(
    failed_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _dashboard_replay_candidate(job)
        for job in failed_jobs
        if _job_dead_lettered(job)
    ]


def _dashboard_replay_candidate(job: dict[str, Any]) -> dict[str, Any]:
    service_id = str(job["service_id"])
    job_id = str(job["job_id"])
    return {
        "service_id": service_id,
        "job_id": job_id,
        "job_type": job["job_type"],
        "status": job["status"],
        "trace_id": job["trace_id"],
        "request_id": job["request_id"],
        "updated_at": job["updated_at"],
        "source_error_code": _job_error_code(job),
        "recommended_action": "replay",
        "allowed_actions": ["read", "replay"],
        "control_path": f"/admin/v1/operations/jobs/{service_id}/{job_id}/replay",
        "required_payload_fields": [
            "replay_job_id",
            "idempotency_key",
            "requested_by",
            "reason",
        ],
    }


def _dashboard_degraded_sources(
    *,
    operation_sources: list[dict[str, Any]],
    job_source_statuses: Mapping[str, dict[str, Any]],
    event_source_statuses: Mapping[str, dict[str, Any]],
    log_source_statuses: Mapping[str, dict[str, Any]] | None = None,
    cx_processing_run_source_statuses: Mapping[str, dict[str, Any]] | None = None,
    retrieval_threshold_decision_source_statuses: (
        Mapping[str, dict[str, Any]] | None
    ) = None,
    generation_remediation_source_statuses: Mapping[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    degraded: list[dict[str, Any]] = []
    for source in operation_sources:
        readiness_status = str(source["readiness_status"])
        if readiness_status not in {"READY", "DEFAULT_MEMORY"}:
            degraded.append(
                {
                    "source_type": "readiness",
                    "service_id": source["service_id"],
                    "status": readiness_status,
                    "detail": source["source_kind"],
                }
            )
    for source_type, statuses in (
        ("jobs", job_source_statuses),
        ("events", event_source_statuses),
        ("logs", log_source_statuses or {}),
        ("cx_processing_runs", cx_processing_run_source_statuses or {}),
        (
            "retrieval_threshold_decisions",
            retrieval_threshold_decision_source_statuses or {},
        ),
        ("generation_remediation", generation_remediation_source_statuses or {}),
    ):
        for service_id, source_status in statuses.items():
            status = str(source_status["status"])
            if status == "READY":
                continue
            if source_type == "logs" and status == "NOT_CONFIGURED":
                continue
            degraded_source = {
                "source_type": source_type,
                "service_id": service_id,
                "status": status,
                "detail": source_status.get("detail"),
            }
            if source_status.get("error_code") is not None:
                degraded_source["error_code"] = source_status["error_code"]
            degraded.append(degraded_source)
    return degraded


def _issue_candidates_from_degraded_sources(
    degraded_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in degraded_sources:
        status = str(source["status"])
        rule_id = (
            "operations_source_unavailable.v1"
            if status == "UNAVAILABLE"
            else "operations_source_not_configured.v1"
        )
        severity = "ERROR" if status == "UNAVAILABLE" else "WARNING"
        candidates.append(
            _operations_issue_candidate(
                rule_id=rule_id,
                service_id=str(source["service_id"]),
                severity=severity,
                title=(
                    "Operations source unavailable"
                    if status == "UNAVAILABLE"
                    else "Operations source not configured"
                ),
                detail=(
                    f"{source['source_type']} source for {source['service_id']} "
                    f"is {status}."
                ),
                signal={
                    "source_type": source["source_type"],
                    "status": status,
                    "detail": source.get("detail"),
                    "error_code": source.get("error_code"),
                },
            )
        )
    return candidates


def _issue_candidates_from_rollups(
    rollups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for rollup in rollups:
        service_id = str(rollup["service_id"])
        failed_count = int(rollup["jobs"]["statuses"].get("FAILED", 0))
        error_count = int(rollup["events"]["by_severity"].get("ERROR", 0))
        critical_count = int(rollup["events"]["by_severity"].get("CRITICAL", 0))
        if failed_count > 0:
            candidates.append(
                _operations_issue_candidate(
                    rule_id="failed_jobs_present.v1",
                    service_id=service_id,
                    severity="ERROR",
                    title="Failed jobs observed",
                    detail=f"{failed_count} failed job(s) observed for {service_id}.",
                    signal={"count": failed_count, "threshold": 1},
                )
            )
        if error_count > 0:
            candidates.append(
                _operations_issue_candidate(
                    rule_id="error_events_present.v1",
                    service_id=service_id,
                    severity="ERROR",
                    title="Error events observed",
                    detail=f"{error_count} ERROR event(s) observed for {service_id}.",
                    signal={"count": error_count, "threshold": 1},
                )
            )
        if critical_count > 0:
            candidates.append(
                _operations_issue_candidate(
                    rule_id="critical_events_present.v1",
                    service_id=service_id,
                    severity="CRITICAL",
                    title="Critical events observed",
                    detail=(
                        f"{critical_count} CRITICAL event(s) observed "
                        f"for {service_id}."
                    ),
                    signal={"count": critical_count, "threshold": 1},
                )
            )
    return candidates


def _issue_candidates_from_replay_candidates(
    replay_candidates: object,
) -> list[dict[str, Any]]:
    if not isinstance(replay_candidates, list):
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in replay_candidates:
        if not isinstance(candidate, Mapping):
            continue
        service_id = str(candidate.get("service_id", ""))
        if service_id not in SERVICE_SPECS:
            continue
        grouped.setdefault(service_id, []).append(dict(candidate))

    issue_candidates: list[dict[str, Any]] = []
    for service_id, candidates in sorted(grouped.items()):
        job_ids = sorted(str(candidate["job_id"]) for candidate in candidates)
        issue_candidates.append(
            _operations_issue_candidate(
                rule_id="dead_letter_replay_available.v1",
                service_id=service_id,
                severity="WARNING",
                title="Dead-letter replay available",
                detail=(
                    f"{len(candidates)} dead-letter job(s) can be replayed "
                    f"for {service_id}."
                ),
                signal={
                    "status": "FAILED_DEAD_LETTER",
                    "count": len(candidates),
                    "threshold": 1,
                    "job_ids": job_ids,
                    "recommended_action": "replay",
                    "control_paths": [
                        str(candidate["control_path"])
                        for candidate in sorted(
                            candidates,
                            key=lambda item: str(item["job_id"]),
                        )
                    ],
                    "required_payload_fields": [
                        "replay_job_id",
                        "idempotency_key",
                        "requested_by",
                        "reason",
                    ],
                },
            )
        )
    return issue_candidates


def _issue_candidates_from_failure_logs(
    failure_logs: object,
) -> list[dict[str, Any]]:
    if not isinstance(failure_logs, list):
        return []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for log in failure_logs:
        if not isinstance(log, Mapping):
            continue
        service_id = str(log.get("service_id", ""))
        severity = str(log.get("severity", "")).upper()
        log_id = str(log.get("log_id", ""))
        logger_name = str(log.get("logger_name", ""))
        if (
            service_id not in SERVICE_SPECS
            or severity not in {"ERROR", "CRITICAL"}
            or not log_id
            or not logger_name
        ):
            continue
        grouped.setdefault((service_id, severity), []).append(
            {**dict(log), "log_id": log_id, "logger_name": logger_name}
        )

    candidates: list[dict[str, Any]] = []
    for (service_id, severity), logs in sorted(grouped.items()):
        rule_id = (
            "critical_service_logs_present.v1"
            if severity == "CRITICAL"
            else "error_service_logs_present.v1"
        )
        candidates.append(
            _operations_issue_candidate(
                rule_id=rule_id,
                service_id=service_id,
                severity=severity,
                title=(
                    "Critical service logs observed"
                    if severity == "CRITICAL"
                    else "Error service logs observed"
                ),
                detail=(
                    f"{len(logs)} {severity} structured service log(s) "
                    f"observed for {service_id}."
                ),
                signal={
                    "status": f"{severity}_SERVICE_LOGS",
                    "count": len(logs),
                    "threshold": 1,
                    "log_ids": sorted(str(log["log_id"]) for log in logs),
                    "logger_names": sorted({str(log["logger_name"]) for log in logs}),
                },
            )
        )
    return candidates


def _issue_candidates_from_active_jobs(
    active_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_counts: dict[str, int] = {}
    for job in active_jobs:
        service_id = str(job["service_id"])
        active_counts[service_id] = active_counts.get(service_id, 0) + 1
    return [
        _operations_issue_candidate(
            rule_id="active_jobs_review.v1",
            service_id=service_id,
            severity="INFO",
            title="Active jobs need review",
            detail=f"{count} active job(s) observed for {service_id}.",
            signal={"count": count, "threshold": 1},
        )
        for service_id, count in sorted(active_counts.items())
        if count > 0
    ]


def _issue_candidates_from_retrieval_threshold_decisions(
    section: object,
) -> list[dict[str, Any]]:
    if not isinstance(section, Mapping):
        return []
    decisions = section.get("threshold_decisions")
    if not isinstance(decisions, list):
        return []

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        service_id = str(decision.get("service_id", ""))
        readiness = str(decision.get("sample_readiness", ""))
        policy_id = str(decision.get("policy_id", ""))
        if (
            service_id not in SERVICE_SPECS
            or readiness not in RETRIEVAL_THRESHOLD_ISSUE_RULES_BY_READINESS
            or not policy_id
        ):
            continue
        grouped.setdefault((service_id, readiness), []).append(dict(decision))

    candidates: list[dict[str, Any]] = []
    for service_id in sorted({key[0] for key in grouped}):
        for readiness in RETRIEVAL_THRESHOLD_ISSUE_READINESS_ORDER:
            grouped_decisions = grouped.get((service_id, readiness))
            if not grouped_decisions:
                continue
            candidates.append(
                _retrieval_threshold_issue_candidate(
                    service_id=service_id,
                    readiness=readiness,
                    grouped_decisions=grouped_decisions,
                )
            )
    return candidates


def _retrieval_threshold_issue_candidate(
    *,
    service_id: str,
    readiness: str,
    grouped_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    rule = RETRIEVAL_THRESHOLD_ISSUE_RULES_BY_READINESS[readiness]
    policy_ids = sorted({str(decision["policy_id"]) for decision in grouped_decisions})
    recommended_actions = sorted(
        {
            str(decision.get("recommended_operator_action"))
            for decision in grouped_decisions
            if decision.get("recommended_operator_action")
        }
    )
    decision_statuses = sorted(
        {
            str(decision.get("decision_status", "UNKNOWN"))
            for decision in grouped_decisions
        }
    )
    operator_reviews = [
        review
        for decision in grouped_decisions
        if isinstance((review := decision.get("operator_review")), Mapping)
    ]
    return _operations_issue_candidate(
        rule_id=str(rule["rule_id"]),
        service_id=service_id,
        severity=str(rule["severity"]),
        title=str(rule["title"]),
        detail=(
            f"{len(grouped_decisions)} retrieval threshold decision(s) "
            f"are {readiness} for {service_id}."
        ),
        signal={
            "status": readiness,
            "count": len(grouped_decisions),
            "threshold": 1,
            "policy_ids": policy_ids,
            "decision_statuses": decision_statuses,
            "recommended_actions": recommended_actions,
            "observed_sample_count": sum(
                _safe_int(decision.get("observed_sample_count"))
                for decision in grouped_decisions
            ),
            "minimum_live_samples_before_change": max(
                _safe_int(decision.get("minimum_live_samples_before_change"))
                for decision in grouped_decisions
            ),
            "runbook_ids": sorted(
                {
                    str(review.get("runbook_id"))
                    for review in operator_reviews
                    if review.get("runbook_id")
                }
            ),
            "threshold_decision_paths": sorted(
                {
                    str(review.get("threshold_decision_path"))
                    for review in operator_reviews
                    if review.get("threshold_decision_path")
                }
            ),
            "calibration_samples_paths": sorted(
                {
                    str(review.get("calibration_samples_path"))
                    for review in operator_reviews
                    if review.get("calibration_samples_path")
                }
            ),
            "policy_detail_paths": sorted(
                {
                    str(review.get("policy_detail_path"))
                    for review in operator_reviews
                    if review.get("policy_detail_path")
                }
            ),
        },
    )


def _issue_candidates_from_generation_quality(
    section: object,
) -> list[dict[str, Any]]:
    if not isinstance(section, Mapping):
        return []
    attention = section.get("attention")
    if not isinstance(attention, list):
        return []
    items = [
        dict(item)
        for item in attention
        if isinstance(item, Mapping) and _generation_quality_item_needs_attention(item)
    ]
    if not items:
        return []
    return [_generation_quality_issue_candidate(items)]


def _generation_quality_issue_candidate(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    has_failure = any(
        item["coverage_status"] == "FAIL" or item["boundary_status"] == "FAIL"
        for item in items
    )
    coverage_statuses = sorted({str(item["coverage_status"]) for item in items})
    boundary_statuses = sorted({str(item["boundary_status"]) for item in items})
    issue_codes = sorted(
        {
            str(code)
            for item in items
            for code in item.get("issue_codes", [])
            if isinstance(code, str)
        }
    )
    return _operations_issue_candidate(
        rule_id="generation_quality_attention_required.v1",
        service_id="nex-ag",
        severity="ERROR" if has_failure else "WARNING",
        title="Generation quality attention required",
        detail=f"{len(items)} generation quality projection(s) need review.",
        signal={
            "source_type": "generation_quality",
            "status": "FAIL" if has_failure else "WARN",
            "count": len(items),
            "threshold": 1,
            "coverage_statuses": coverage_statuses,
            "boundary_statuses": boundary_statuses,
            "issue_codes": issue_codes,
            "cx_generation_ids": sorted(
                {
                    str(item["cx_generation_id"])
                    for item in items
                    if item.get("cx_generation_id")
                }
            ),
            "detail_paths": sorted(
                {str(item["detail_path"]) for item in items if item.get("detail_path")}
            ),
        },
    )


def _issue_candidates_from_generation_remediation(
    section: object,
) -> list[dict[str, Any]]:
    if not isinstance(section, Mapping):
        return []
    attention = section.get("attention")
    if not isinstance(attention, list):
        return []
    items = [
        dict(item)
        for item in attention
        if isinstance(item, Mapping)
        and str(item.get("service_id") or "") in SERVICE_SPECS
        and _generation_remediation_task_needs_attention(item)
    ]
    if not items:
        return []
    return [_generation_remediation_issue_candidate(items)]


def _generation_remediation_issue_candidate(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_count = sum(
        1 for item in items if str(item.get("action_status") or "UNKNOWN") == "FAILED"
    )
    urgent_count = sum(
        1 for item in items if str(item.get("priority") or "NORMAL") == "URGENT"
    )
    waiting_on_cx_count = sum(
        1
        for item in items
        if str(item.get("action_status") or "UNKNOWN") == "WAITING_ON_CX"
    )
    status = "FAILED" if failed_count > 0 else "ACTIVE"
    return _operations_issue_candidate(
        rule_id="generation_remediation_attention_required.v1",
        service_id="nex-ag",
        severity="ERROR" if failed_count > 0 else "WARNING",
        title="Generation remediation attention required",
        detail=f"{len(items)} generation remediation task(s) need operator review.",
        signal={
            "source_type": "generation_remediation",
            "status": status,
            "count": len(items),
            "threshold": 1,
            "failed_count": failed_count,
            "urgent_count": urgent_count,
            "waiting_on_cx_count": waiting_on_cx_count,
            "action_statuses": sorted(
                {str(item.get("action_status") or "UNKNOWN") for item in items}
            ),
            "action_types": sorted(
                {str(item.get("action_type") or "unknown") for item in items}
            ),
            "priorities": sorted(
                {str(item.get("priority") or "NORMAL") for item in items}
            ),
            "remediation_action_ids": sorted(
                {
                    str(item["remediation_action_id"])
                    for item in items
                    if item.get("remediation_action_id")
                }
            ),
            "cx_generation_ids": sorted(
                {
                    str(item["cx_generation_id"])
                    for item in items
                    if item.get("cx_generation_id")
                }
            ),
            "task_detail_paths": sorted(
                {str(item["detail_path"]) for item in items if item.get("detail_path")}
            ),
            "runbook_ids": _generation_remediation_issue_runbook_ids(items),
            "recommended_operator_actions": (
                _generation_remediation_issue_operator_actions(items)
            ),
        },
    )


def _generation_remediation_issue_runbook_ids(
    items: list[dict[str, Any]],
) -> list[str]:
    runbook_ids: set[str] = set()
    for item in items:
        action_status = str(item.get("action_status") or "")
        priority = str(item.get("priority") or "")
        action_type = str(item.get("action_type") or "")
        if action_status == "FAILED":
            runbook_ids.add("ag.generation_remediation.failed_task_triage.v1")
        elif action_status == "WAITING_ON_CX":
            runbook_ids.add("ag.generation_remediation.cx_dependency_followup.v1")
        elif priority == "URGENT":
            runbook_ids.add("ag.generation_remediation.urgent_task_review.v1")
        else:
            runbook_ids.add("ag.generation_remediation.active_task_review.v1")
        if action_type == "prompt_policy_review":
            runbook_ids.add("ag.generation_remediation.prompt_policy_review.v1")
    return sorted(runbook_ids)


def _generation_remediation_issue_operator_actions(
    items: list[dict[str, Any]],
) -> list[str]:
    actions: set[str] = set()
    for item in items:
        action_status = str(item.get("action_status") or "")
        priority = str(item.get("priority") or "")
        action_type = str(item.get("action_type") or "")
        if action_status == "FAILED":
            actions.add("triage_failed_remediation_task")
        elif action_status == "WAITING_ON_CX":
            actions.add("follow_up_with_cx_owner")
        elif priority == "URGENT":
            actions.add("review_urgent_remediation_task")
        else:
            actions.add("review_active_remediation_task")
        if action_type == "prompt_policy_review":
            actions.add("prepare_prompt_policy_review")
    return sorted(actions)


def _job_dead_lettered(job: Mapping[str, Any]) -> bool:
    error = job.get("error")
    return isinstance(error, Mapping) and error.get("dead_lettered") is True


def _job_error_code(job: Mapping[str, Any]) -> str | None:
    error = job.get("error")
    if not isinstance(error, Mapping):
        return None
    error_code = error.get("error_code")
    return str(error_code) if error_code else None


def _issue_candidates_from_worker_source_statuses(
    source_statuses: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for service_id, source_status in sorted(source_statuses.items()):
        status = str(source_status["status"])
        if status == "READY":
            continue
        rule_id = (
            "operations_source_unavailable.v1"
            if status == "UNAVAILABLE"
            else "operations_source_not_configured.v1"
        )
        severity = "ERROR" if status == "UNAVAILABLE" else "WARNING"
        candidates.append(
            _operations_issue_candidate(
                rule_id=rule_id,
                service_id=service_id,
                severity=severity,
                title=(
                    "Operations source unavailable"
                    if status == "UNAVAILABLE"
                    else "Operations source not configured"
                ),
                detail=f"workers source for {service_id} is {status}.",
                signal={
                    "source_type": "workers",
                    "status": status,
                    "detail": source_status.get("detail"),
                    "error_code": source_status.get("error_code"),
                },
            )
        )
    return candidates


def _issue_candidates_from_stale_workers(
    workers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stale_workers_by_service: dict[str, list[str]] = {}
    stale_after_by_service: dict[str, int] = {}
    for worker in workers:
        if worker.get("stale") is not True:
            continue
        service_id = str(worker["service_id"])
        stale_workers_by_service.setdefault(service_id, []).append(
            str(worker["worker_id"])
        )
        stale_after_by_service[service_id] = int(worker["stale_after_seconds"])
    return [
        _operations_issue_candidate(
            rule_id="stale_worker_heartbeat.v1",
            service_id=service_id,
            severity="WARNING",
            title="Stale worker heartbeat observed",
            detail=f"{len(worker_ids)} stale worker heartbeat(s) observed for {service_id}.",
            signal={
                "count": len(worker_ids),
                "threshold": stale_after_by_service[service_id],
                "worker_ids": sorted(worker_ids),
            },
        )
        for service_id, worker_ids in sorted(stale_workers_by_service.items())
        if worker_ids
    ]


def _issue_candidates_from_active_jobs_without_fresh_workers(
    active_jobs: list[dict[str, Any]],
    workers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh_busy_jobs = {
        (str(worker["service_id"]), str(worker["active_job_id"]))
        for worker in workers
        if worker.get("stale") is False
        and worker.get("status") == "BUSY"
        and worker.get("active_job_id") is not None
    }
    missing_by_service: dict[str, list[str]] = {}
    for job in active_jobs:
        if job.get("status") != "RUNNING":
            continue
        service_id = str(job["service_id"])
        job_id = str(job["job_id"])
        if (service_id, job_id) in fresh_busy_jobs:
            continue
        missing_by_service.setdefault(service_id, []).append(job_id)
    return [
        _operations_issue_candidate(
            rule_id="active_job_without_fresh_worker.v1",
            service_id=service_id,
            severity="WARNING",
            title="Active job missing fresh worker",
            detail=f"{len(job_ids)} RUNNING job(s) lack a fresh BUSY worker heartbeat for {service_id}.",
            signal={
                "count": len(job_ids),
                "threshold": 1,
                "job_ids": sorted(job_ids),
            },
        )
        for service_id, job_ids in sorted(missing_by_service.items())
        if job_ids
    ]


def _operations_issue_candidate(
    *,
    rule_id: str,
    service_id: str,
    severity: str,
    title: str,
    detail: str,
    signal: dict[str, Any],
) -> dict[str, Any]:
    signal_key = signal.get("source_type") or signal.get("status") or "signal"
    return {
        "candidate_id": f"{service_id}:{signal_key}:{rule_id}",
        "rule_id": rule_id,
        "service_id": service_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "signal": signal,
    }


def _worker_reconciliation_enabled(
    *,
    registry: OperationsSourceRegistry | None,
    worker_heartbeat_stores: Mapping[str, WorkerHeartbeatStore] | None,
) -> bool:
    if registry is not None:
        return bool(registry.worker_heartbeat_stores())
    return worker_heartbeat_stores is not None


def _operations_rollup_jobs_for_service(
    job_queues: Mapping[str, JobQueue],
    *,
    service_id: str,
    options: OperationQueryOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    queue = job_queues.get(service_id)
    if queue is None:
        return _empty_job_rollup(), {
            "status": "NOT_CONFIGURED",
            "job_count": 0,
        }
    try:
        jobs = queue.list_jobs()
    except JobQueueError as exc:
        return _empty_job_rollup(), {
            "status": "UNAVAILABLE",
            "job_count": 0,
            "error_code": exc.error_code,
            "detail": exc.detail,
        }
    jobs = _filter_records_by_operation_time(
        jobs,
        options,
        timestamp_field="updated_at",
    )
    projected_jobs = [_project_job_for_service(service_id, job) for job in jobs]
    return _rollup_jobs(projected_jobs), {
        "status": "READY",
        "job_count": len(projected_jobs),
    }


def _operations_rollup_events_for_service(
    event_store: OperationalEventStore,
    *,
    service_id: str,
    options: OperationQueryOptions,
    configured_service_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if configured_service_ids is not None and service_id not in configured_service_ids:
        return _empty_event_rollup(), {
            "status": "NOT_CONFIGURED",
            "event_count": 0,
        }
    try:
        events = event_store.list_events(
            service_id=service_id,
            limit=normalize_operational_event_limit(500),
        )
    except OperationalEventError as exc:
        return _empty_event_rollup(), {
            "status": "UNAVAILABLE",
            "event_count": 0,
            "error_code": exc.error_code,
            "detail": exc.detail,
        }
    events = _filter_records_by_operation_time(
        events,
        options,
        timestamp_field="created_at",
    )
    return _rollup_events(events), {
        "status": "READY",
        "event_count": len(events),
    }


def _operations_rollup_logs_for_service(
    log_stores: Mapping[str, ServiceLogStore],
    *,
    service_id: str,
    options: OperationQueryOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    store = log_stores.get(service_id)
    if store is None:
        return _empty_log_rollup(), {
            "status": "NOT_CONFIGURED",
            "log_count": 0,
        }
    try:
        logs = store.list_logs(
            service_id=service_id,
            limit=normalize_service_log_limit(500),
        )
    except ServiceLogError as exc:
        return _empty_log_rollup(), {
            "status": "UNAVAILABLE",
            "log_count": 0,
            "error_code": exc.error_code,
            "detail": exc.detail,
        }
    logs = _filter_records_by_operation_time(
        logs,
        options,
        timestamp_field="observed_at",
    )
    return _rollup_logs(logs), {
        "status": "READY",
        "log_count": len(logs),
    }


def _trace_event_timeline_items(
    event_store: OperationalEventStore,
    *,
    trace_id: str,
    service_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        events = event_store.list_events(
            service_id=service_id,
            trace_id=trace_id,
            limit=normalize_operational_event_limit(500),
        )
    except OperationalEventError as exc:
        return [], {
            "status": "UNAVAILABLE",
            "event_count": 0,
            "error_code": exc.error_code,
            "detail": exc.detail,
        }
    return [_event_trace_timeline_item(event) for event in events], {
        "status": "READY",
        "event_count": len(events),
    }


def _job_trace_timeline_item(service_id: str, job: dict[str, Any]) -> dict[str, Any]:
    projected_job = _project_job_for_service(service_id, job)
    return {
        "timeline_item_type": "job",
        "item_id": f"job:{service_id}:{job['job_id']}",
        "service_id": service_id,
        "trace_id": job["trace_id"],
        "operation_timestamp": _job_operation_timestamp(job),
        "job": projected_job,
    }


def _event_trace_timeline_item(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "timeline_item_type": "event",
        "item_id": f"event:{event['event_id']}",
        "service_id": event["service_id"],
        "trace_id": event.get("trace_id"),
        "operation_timestamp": event["created_at"],
        "event": deepcopy(event),
    }


def _log_trace_timeline_item(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "timeline_item_type": "log",
        "item_id": f"log:{entry['service_id']}:{entry['log_id']}",
        "service_id": entry["service_id"],
        "trace_id": entry.get("trace_id"),
        "operation_timestamp": entry["observed_at"],
        "log": deepcopy(entry),
    }


def _retrieval_package_trace_timeline_item(
    service_id: str,
    package: dict[str, Any],
) -> dict[str, Any]:
    retrieval_package_id = str(package["retrieval_package_id"])
    score_summary = _mapping_or_empty(package.get("score_summary"))
    source_summary = _mapping_or_empty(package.get("source_summary"))
    return {
        "timeline_item_type": "retrieval_package",
        "item_id": f"retrieval_package:{service_id}:{retrieval_package_id}",
        "service_id": service_id,
        "trace_id": package.get("trace_id"),
        "request_id": package.get("request_id"),
        "operation_timestamp": package["created_at"],
        "retrieval_package": {
            "service_id": service_id,
            "operation_type": "retrieval_package",
            "operation_timestamp": package["created_at"],
            "retrieval_package_id": retrieval_package_id,
            "package_hash": package.get("package_hash"),
            "status": package.get("status"),
            "trace_id": package.get("trace_id"),
            "request_id": package.get("request_id"),
            "query_text_sha256": package.get("query_text_sha256"),
            "query_text_preview": package.get("query_text_preview"),
            "query_embedding_provided": package.get("query_embedding_provided"),
            "query_embedding_sha256": package.get("query_embedding_sha256"),
            "query_embedding_dimension": int(
                package.get("query_embedding_dimension", 0)
            ),
            "purpose": package.get("purpose"),
            "retrieval_policy_id": package.get("retrieval_policy_id"),
            "retrieval_policy_version": package.get("retrieval_policy_version"),
            "retrieval_policy_hash": package.get("retrieval_policy_hash"),
            "retrieval_policy_source": package.get("retrieval_policy_source"),
            "ranker_mix": package.get("ranker_mix"),
            "rerank_state": package.get("rerank_state"),
            "permission_snapshot_hash": package.get("permission_snapshot_hash"),
            "evidence_count": int(package.get("evidence_count", 0)),
            "warning_count": int(package.get("warning_count", 0)),
            "no_answer_reason": package.get("no_answer_reason"),
            "best_score": _operation_number_or_none(score_summary.get("best_score")),
            "source_count": _operation_integer_or_none(
                source_summary.get("source_count")
            ),
            "document_count": _operation_integer_or_none(
                source_summary.get("document_count")
            ),
            "chunk_count": _operation_integer_or_none(
                source_summary.get("chunk_count")
            ),
            "created_at": package["created_at"],
            "updated_at": package.get("updated_at"),
        },
    }


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _operation_number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _operation_integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _job_operation_timestamp(job: dict[str, Any]) -> str:
    return str(job.get("updated_at") or job["created_at"])


def _rollup_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_job_operations(jobs)
    return {
        "total": summary["total"],
        "active": summary["active"],
        "terminal": summary["terminal"],
        "statuses": summary["statuses"],
        "by_job_type": summary["by_job_type"],
    }


def _rollup_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_operational_events(events)
    by_event_type: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type", "unknown"))
        by_event_type[event_type] = by_event_type.get(event_type, 0) + 1
    return {
        "total": summary["total"],
        "by_severity": summary["by_severity"],
        "by_event_type": by_event_type,
    }


def _rollup_logs(logs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_service_logs(logs)
    by_logger_name: dict[str, int] = {}
    for entry in logs:
        logger_name = str(entry.get("logger_name", "unknown"))
        by_logger_name[logger_name] = by_logger_name.get(logger_name, 0) + 1
    return {
        "total": summary["total"],
        "by_severity": summary["by_severity"],
        "by_logger_name": by_logger_name,
        "redacted_attribute_count": summary["redacted_attribute_count"],
    }


def _empty_job_rollup() -> dict[str, Any]:
    return _rollup_jobs([])


def _empty_event_rollup() -> dict[str, Any]:
    return _rollup_events([])


def _empty_log_rollup() -> dict[str, Any]:
    return _rollup_logs([])


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
        event for event in events if _operational_event_matches_job(job, event)
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


def _worker_active_job_for_service(
    worker: dict[str, Any] | None,
    *,
    service_id: str,
    job_stores: Mapping[str, JobQueue],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    active_job_id = worker.get("active_job_id") if worker is not None else None
    if active_job_id is None:
        return None, {
            "status": "READY",
            "job_count": 0,
        }
    queue = job_stores.get(service_id)
    if queue is None:
        return None, {
            "status": "NOT_CONFIGURED",
            "job_count": 0,
        }
    try:
        job = queue.get_job(str(active_job_id))
    except JobQueueError as exc:
        return None, {
            "status": "UNAVAILABLE",
            "job_count": 0,
            "error_code": exc.error_code,
            "detail": exc.detail,
        }
    if job is None:
        return None, {
            "status": "READY",
            "job_count": 0,
        }
    return _project_job_for_service(service_id, job), {
        "status": "READY",
        "job_count": 1,
    }


def _build_worker_lifecycle_timeline(
    worker: dict[str, Any] | None,
    *,
    service_id: str,
    event_store: OperationalEventStore | None,
    event_limit: int,
) -> dict[str, Any]:
    normalized_event_limit = normalize_operational_event_limit(event_limit)
    if worker is None:
        return {
            "timeline_status": "READY",
            "event_count": 0,
            "events": [],
            "source_error": None,
        }
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
            trace_id=worker.get("trace_id"),
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
        event for event in events if _operational_event_matches_worker(worker, event)
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


def _operational_event_matches_worker(
    worker: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    worker_id = worker.get("worker_id")
    subject_ref = event.get("subject_ref")
    if (
        isinstance(subject_ref, Mapping)
        and subject_ref.get("type") == "worker"
        and subject_ref.get("id") == worker_id
    ):
        return True
    details = event.get("details")
    if isinstance(details, Mapping) and details.get("worker_id") == worker_id:
        return True
    return False


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


def _project_worker_for_service(
    service_id: str,
    worker: dict[str, Any],
    *,
    stale_after_seconds: int,
    checked_at: str,
) -> dict[str, Any]:
    projected = deepcopy(worker)
    projected["service_id"] = service_id
    projected["stale"] = worker_heartbeat_is_stale(
        projected,
        stale_after_seconds=stale_after_seconds,
        checked_at=checked_at,
    )
    projected["stale_after_seconds"] = stale_after_seconds
    return projected


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
