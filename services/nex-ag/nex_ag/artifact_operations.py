from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    ACTIVE_JOB_STATUSES,
    DEFAULT_SERVICE_SCOPE,
    JOB_STATUSES,
    SERVICE_SPECS,
    TERMINAL_JOB_STATUSES,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)

AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_collection_projection.v1"
)
AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_lifecycle_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_history_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_batch_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_scheduled_job_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_scheduled_dispatch.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_automation_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_attention.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_runtime_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_ISSUE_CANDIDATE_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_runtime_issue_candidate.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_lifecycle_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_run_collection_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_run_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_supervisor_collection_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_supervisor_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_supervised_process_collection_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_supervised_process_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_operator_control_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_operator_control_execution_collection_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_operator_control_execution_detail_projection.v1"
)
AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION = (
    "ag_artifact_operation_retention_daemon_operator_control_execution_worker_projection.v1"
)
AE_ARTIFACT_SOURCE_SERVICE_ID = "nex-ae-api"
AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE = (
    "ae.artifact_retention.scheduler_daemon"
)
NEX_AG_AE_ARTIFACT_BASE_URL_ENV = "NEX_AG_AE_ARTIFACT_BASE_URL"
NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV = "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN"
NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV = "NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS"
DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS = 10.0
SAFE_ARTIFACT_FILE_ROUTE_PREFIX = "/api/v1/artifact-files/"
SAFE_ARTIFACT_ROUTE_PREFIX = "/api/v1/artifacts/"
SAFE_STORAGE_REF_PREFIX = "ae://artifacts/"
DEFAULT_ARTIFACT_COLLECTION_LIMIT = 20
MAX_ARTIFACT_COLLECTION_LIMIT = 100
SUPPORTED_ARTIFACT_STATUSES = {
    "DRAFT",
    "RENDERING",
    "READY",
    "FAILED",
    "ARCHIVED",
    "DELETED",
}
SUPPORTED_ARTIFACT_LIFECYCLE_ACTIONS = ("ARCHIVE", "RESTORE", "MARK_DELETED")
SUPPORTED_ARTIFACT_RETENTION_MODES = ("DRY_RUN", "EXECUTE")
SUPPORTED_ARTIFACT_RETENTION_STATUSES = (
    "PLANNED",
    "SUCCEEDED",
    "BLOCKED",
    "FAILED",
)
SUPPORTED_ARTIFACT_RETENTION_BATCH_STATUSES = ("READY", "NOOP")
SUPPORTED_ARTIFACT_RETENTION_SCHEDULED_TRIGGERS = (
    "scheduler_tick",
    "operator_dispatch",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_ACTIONS = (
    "status_probe",
    "manual_tick_once",
    "start_daemon",
    "stop_daemon",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_LIFECYCLE_STATUSES = (
    "STARTING",
    "RUNNING",
    "STOPPING",
    "STOPPED",
    "DISABLED",
    "ERROR",
    "UNKNOWN",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_RESULT_STATUSES = (
    "SUCCEEDED",
    "FAILED",
    "STOPPED",
    "SKIPPED",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_ACTIONS = (
    "status_probe",
    "start_daemon",
    "stop_daemon",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_ACTIONS = (
    "status_probe",
    "start_daemon",
    "stop_daemon",
    "restart_daemon",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_STATUSES = (
    "READY",
    "BLOCKED",
    "NOOP",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_STATUSES = (
    "ADMITTED",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "NOOP",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_STATUSES = (
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_IDEMPOTENCY_STATUSES = (
    "NEW",
    "REPLAYED",
    "CONFLICT",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_RESULT_STATUSES = (
    "READY",
    "BLOCKED",
    "NOOP",
    "FAILED",
)
SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISED_PROCESS_STATUSES = (
    "MISSING",
    "START_REQUESTED",
    "RUNNING",
    "STOP_REQUESTED",
    "STOPPED",
    "EXITED",
    "STALE",
    "FAILED",
    "BLOCKED",
)
AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE = "ae.artifact_retention.scheduled_execution"
ARCHIVABLE_ARTIFACT_STATUSES = {"DRAFT", "READY", "FAILED"}
DELETABLE_ARTIFACT_STATUSES = {"DRAFT", "READY", "FAILED", "ARCHIVED"}
RESTORABLE_ARTIFACT_STATUSES = {"ARCHIVED", "DELETED"}
DEFAULT_ARTIFACT_RESTORE_STATUS = "READY"


class AeArtifactOperationsClient(Protocol):
    source_kind: str
    base_url: str | None

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def list_artifact_retention_executions(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        mode: str | None,
        execution_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_batch_plan(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int,
        max_delete_count: int,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def list_artifact_retention_scheduled_jobs(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def dispatch_artifact_retention_scheduled_job(
        self,
        *,
        batch_plan: Mapping[str, Any],
        trigger_type: str,
        requested_at: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_config(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_runtime(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def list_artifact_retention_scheduler_daemon_runs(
        self,
        *,
        scheduler_id: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_run_detail(
        self,
        daemon_run_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def list_artifact_retention_scheduler_daemon_supervisor_results(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_supervisor_detail(
        self,
        daemon_supervisor_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def list_artifact_retention_scheduler_daemon_process_snapshots(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        process_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_process_snapshot_detail(
        self,
        daemon_supervised_process_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def get_artifact_retention_scheduler_daemon_operator_control_policy(
        self,
        *,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def preview_artifact_retention_scheduler_daemon_operator_control(
        self,
        *,
        action: str,
        operator_subject: Mapping[str, Any],
        idempotency_key: str,
        reason: str,
        requested_at: str | None,
        checked_at: str | None,
        profile: str,
        enabled: bool,
        explicit_opt_in: bool,
        max_cycles: int,
        run_worker: bool,
        approval: Mapping[str, Any] | None,
        current_process: Mapping[str, Any] | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def dispatch_artifact_retention_scheduler_daemon_control(
        self,
        *,
        action: str,
        tenant_id: str | None,
        workspace_id: str | None,
        owner_user_id: str | None,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int | None,
        max_delete_count: int | None,
        requested_at: str | None,
        requested_by: Mapping[str, Any] | None,
        reason: str | None,
        tick_at: str | None,
        run_worker: bool,
        worker_id: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def list_artifact_retention_scheduler_daemon_operator_control_executions(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        execution_status: str | None,
        idempotency_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        self,
        operator_control_execution_state_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        self,
        *,
        operator_control_execution_state_id: str | None,
        operator_control_execution_state: Mapping[str, Any] | None,
        checked_at: str | None,
        worker_observed_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]: ...

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None: ...

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AeArtifactOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503


@dataclass
class InMemoryAeArtifactOperationsClient:
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_collections: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_retention_history_collections: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    artifact_retention_batch_plans: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    artifact_retention_scheduled_job_collections: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    artifact_retention_scheduled_jobs: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    artifact_retention_scheduled_dispatch_results: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    artifact_retention_scheduler_daemon_config: dict[str, Any] | None = None
    artifact_retention_scheduler_daemon_runtime: dict[str, Any] | None = None
    artifact_retention_scheduler_daemon_run_collections: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_run_details: dict[str, dict[str, Any]] = (
        field(default_factory=dict)
    )
    artifact_retention_scheduler_daemon_supervisor_collections: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_supervisor_details: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_process_snapshot_collections: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_process_snapshot_details: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_operator_control_policy: dict[
        str, Any
    ] | None = None
    artifact_retention_scheduler_daemon_operator_control_previews: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_dispatch_results: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_operator_control_execution_collections: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_operator_control_execution_details: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    artifact_retention_scheduler_daemon_operator_control_execution_worker_results: dict[
        str, dict[str, Any]
    ] = field(default_factory=dict)
    handoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    chat_artifact_refs: dict[str, list[dict[str, Any]] | dict[str, Any]] = field(
        default_factory=dict
    )
    source_kind: str = "memory"
    base_url: str | None = None

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_collection_cache_key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if collection_key in self.artifact_collections:
            return deepcopy(self.artifact_collections[collection_key])

        normalized_status = _normalized_status(status)
        records = [
            artifact
            for artifact in self.artifacts.values()
            if _artifact_matches_collection_filter(
                artifact,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                status=normalized_status,
            )
        ]
        records.sort(
            key=lambda artifact: str(artifact.get("updated_at") or ""),
            reverse=True,
        )
        items = [_artifact_to_collection_item(artifact) for artifact in records[:limit]]
        return {
            "artifact_collection_schema_version": "ae_artifact_collection.v1",
            "filter": {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "status": normalized_status,
                "limit": limit,
            },
            "count": len(items),
            "limit": limit,
            "next_cursor": None,
            "items": items,
        }

    def list_artifact_retention_executions(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        mode: str | None,
        execution_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_retention_history_cache_key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode=mode,
            execution_status=execution_status,
            limit=limit,
        )
        if collection_key in self.artifact_retention_history_collections:
            return deepcopy(self.artifact_retention_history_collections[collection_key])
        return {
            "artifact_retention_execution_history_collection_schema_version": (
                "ae_artifact_retention_execution_history_collection.v1"
            ),
            "filter": {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "mode": _normalized_retention_mode(mode),
                "execution_status": _normalized_retention_status(execution_status),
                "limit": limit,
            },
            "count": 0,
            "limit": limit,
            "next_cursor": None,
            "items": [],
            "summary": summarize_artifact_retention_history_operations([]),
            "metadata": {"metadata_only": True, "system_of_record": "nex-ae-api"},
        }

    def get_artifact_retention_batch_plan(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int,
        max_delete_count: int,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        plan_key = _artifact_retention_batch_plan_cache_key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            as_of=as_of,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
            checked_at=checked_at,
        )
        if plan_key in self.artifact_retention_batch_plans:
            return deepcopy(self.artifact_retention_batch_plans[plan_key])
        return _empty_artifact_retention_batch_plan_payload(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            as_of=as_of,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
            checked_at=checked_at,
        )

    def list_artifact_retention_scheduled_jobs(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_retention_scheduled_job_cache_key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if collection_key in self.artifact_retention_scheduled_job_collections:
            return deepcopy(
                self.artifact_retention_scheduled_job_collections[collection_key]
            )

        normalized_status = _normalized_job_status(status)
        records = [
            job
            for job in self.artifact_retention_scheduled_jobs.values()
            if _retention_scheduled_job_matches_filter(
                job,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                status=normalized_status,
            )
        ]
        records.sort(key=lambda job: str(job.get("updated_at") or ""), reverse=True)
        items = [deepcopy(job) for job in records[:limit]]
        collection = _empty_artifact_retention_scheduled_job_collection_payload(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=normalized_status,
            limit=limit,
        )
        collection["count"] = len(items)
        collection["items"] = items
        return collection

    def dispatch_artifact_retention_scheduled_job(
        self,
        *,
        batch_plan: Mapping[str, Any],
        trigger_type: str,
        requested_at: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        projected_plan = _project_retention_batch_plan(batch_plan)
        result_key = _artifact_retention_scheduled_dispatch_cache_key(
            plan_id=_text_or_none(projected_plan.get("plan_id")),
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
        )
        if result_key in self.artifact_retention_scheduled_dispatch_results:
            return deepcopy(
                self.artifact_retention_scheduled_dispatch_results[result_key]
            )
        return _memory_artifact_retention_scheduled_dispatch_result(
            projected_plan,
            trigger_type=trigger_type,
            requested_at=requested_at,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_artifact_retention_scheduler_daemon_config(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if self.artifact_retention_scheduler_daemon_config is not None:
            return deepcopy(self.artifact_retention_scheduler_daemon_config)
        return _empty_artifact_retention_scheduler_daemon_config_payload()

    def get_artifact_retention_scheduler_daemon_runtime(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if self.artifact_retention_scheduler_daemon_runtime is not None:
            return deepcopy(self.artifact_retention_scheduler_daemon_runtime)
        return _empty_artifact_retention_scheduler_daemon_runtime_payload(
            daemon_config=self.get_artifact_retention_scheduler_daemon_config(
                request_id=request_id,
                trace_id=trace_id,
            )
        )

    def list_artifact_retention_scheduler_daemon_runs(
        self,
        *,
        scheduler_id: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_retention_scheduler_daemon_run_cache_key(
            scheduler_id=scheduler_id,
            result_status=result_status,
            limit=limit,
        )
        if collection_key in self.artifact_retention_scheduler_daemon_run_collections:
            return deepcopy(
                self.artifact_retention_scheduler_daemon_run_collections[
                    collection_key
                ]
            )
        return _empty_artifact_retention_scheduler_daemon_run_collection_payload(
            scheduler_id=scheduler_id,
            result_status=result_status,
            limit=limit,
        )

    def get_artifact_retention_scheduler_daemon_run_detail(
        self,
        daemon_run_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(
            self.artifact_retention_scheduler_daemon_run_details.get(
                daemon_run_record_id
            )
        )

    def list_artifact_retention_scheduler_daemon_supervisor_results(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = _artifact_retention_scheduler_daemon_supervisor_cache_key(
            scheduler_id=scheduler_id,
            action=action,
            result_status=result_status,
            limit=limit,
        )
        if (
            collection_key
            in self.artifact_retention_scheduler_daemon_supervisor_collections
        ):
            return deepcopy(
                self.artifact_retention_scheduler_daemon_supervisor_collections[
                    collection_key
                ]
            )
        return _empty_artifact_retention_scheduler_daemon_supervisor_collection_payload(
            scheduler_id=scheduler_id,
            action=action,
            result_status=result_status,
            limit=limit,
        )

    def get_artifact_retention_scheduler_daemon_supervisor_detail(
        self,
        daemon_supervisor_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(
            self.artifact_retention_scheduler_daemon_supervisor_details.get(
                daemon_supervisor_record_id
            )
        )

    def list_artifact_retention_scheduler_daemon_process_snapshots(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        process_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = (
            _artifact_retention_scheduler_daemon_process_snapshot_cache_key(
                scheduler_id=scheduler_id,
                action=action,
                process_status=process_status,
                limit=limit,
            )
        )
        if (
            collection_key
            in self.artifact_retention_scheduler_daemon_process_snapshot_collections
        ):
            return deepcopy(
                self.artifact_retention_scheduler_daemon_process_snapshot_collections[
                    collection_key
                ]
            )
        return _empty_artifact_retention_scheduler_daemon_process_snapshot_collection_payload(
            scheduler_id=scheduler_id,
            action=action,
            process_status=process_status,
            limit=limit,
        )

    def get_artifact_retention_scheduler_daemon_process_snapshot_detail(
        self,
        daemon_supervised_process_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(
            self.artifact_retention_scheduler_daemon_process_snapshot_details.get(
                daemon_supervised_process_record_id
            )
        )

    def get_artifact_retention_scheduler_daemon_operator_control_policy(
        self,
        *,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if self.artifact_retention_scheduler_daemon_operator_control_policy is not None:
            return deepcopy(
                self.artifact_retention_scheduler_daemon_operator_control_policy
            )
        return _empty_artifact_retention_scheduler_daemon_operator_control_policy_payload(
            checked_at=checked_at,
        )

    def preview_artifact_retention_scheduler_daemon_operator_control(
        self,
        *,
        action: str,
        operator_subject: Mapping[str, Any],
        idempotency_key: str,
        reason: str,
        requested_at: str | None,
        checked_at: str | None,
        profile: str,
        enabled: bool,
        explicit_opt_in: bool,
        max_cycles: int,
        run_worker: bool,
        approval: Mapping[str, Any] | None,
        current_process: Mapping[str, Any] | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        preview_key = _artifact_retention_scheduler_daemon_operator_control_preview_cache_key(
            action=action,
            idempotency_key=idempotency_key,
            checked_at=checked_at,
        )
        if preview_key in self.artifact_retention_scheduler_daemon_operator_control_previews:
            return deepcopy(
                self.artifact_retention_scheduler_daemon_operator_control_previews[
                    preview_key
                ]
            )
        return _memory_artifact_retention_scheduler_daemon_operator_control_preview_payload(
            action=action,
            operator_subject=operator_subject,
            idempotency_key=idempotency_key,
            reason=reason,
            requested_at=requested_at,
            checked_at=checked_at,
            profile=profile,
            enabled=enabled,
            explicit_opt_in=explicit_opt_in,
            max_cycles=max_cycles,
            run_worker=run_worker,
            approval=approval,
            current_process=current_process,
        )

    def dispatch_artifact_retention_scheduler_daemon_control(
        self,
        *,
        action: str,
        tenant_id: str | None,
        workspace_id: str | None,
        owner_user_id: str | None,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int | None,
        max_delete_count: int | None,
        requested_at: str | None,
        requested_by: Mapping[str, Any] | None,
        reason: str | None,
        tick_at: str | None,
        run_worker: bool,
        worker_id: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        dispatch_key = _artifact_retention_scheduler_daemon_dispatch_cache_key(
            action=action,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            idempotency_key=idempotency_key,
        )
        if dispatch_key in self.artifact_retention_scheduler_daemon_dispatch_results:
            return deepcopy(
                self.artifact_retention_scheduler_daemon_dispatch_results[dispatch_key]
            )
        return _empty_artifact_retention_scheduler_daemon_dispatch_payload(
            daemon_config=self.get_artifact_retention_scheduler_daemon_config(
                request_id=request_id,
                trace_id=trace_id,
            ),
            action=action,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            requested_at=requested_at,
            requested_by=requested_by,
            reason=reason,
        )

    def list_artifact_retention_scheduler_daemon_operator_control_executions(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        execution_status: str | None,
        idempotency_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        collection_key = (
            _artifact_retention_scheduler_daemon_operator_control_execution_cache_key(
                scheduler_id=scheduler_id,
                action=action,
                execution_status=execution_status,
                idempotency_status=idempotency_status,
                limit=limit,
            )
        )
        if (
            collection_key
            in self.artifact_retention_scheduler_daemon_operator_control_execution_collections
        ):
            return deepcopy(
                self.artifact_retention_scheduler_daemon_operator_control_execution_collections[
                    collection_key
                ]
            )
        return _empty_artifact_retention_scheduler_daemon_operator_control_execution_collection_payload(
            scheduler_id=scheduler_id,
            action=action,
            execution_status=execution_status,
            idempotency_status=idempotency_status,
            limit=limit,
        )

    def get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        self,
        operator_control_execution_state_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(
            self.artifact_retention_scheduler_daemon_operator_control_execution_details.get(
                operator_control_execution_state_id
            )
        )

    def run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        self,
        *,
        operator_control_execution_state_id: str | None,
        operator_control_execution_state: Mapping[str, Any] | None,
        checked_at: str | None,
        worker_observed_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        state = _mapping_or_empty(operator_control_execution_state)
        state_id = _text_or_none(
            operator_control_execution_state_id
            or state.get("operator_control_execution_state_id")
        )
        result_key = (
            _artifact_retention_scheduler_daemon_operator_control_execution_worker_cache_key(
                operator_control_execution_state_id=state_id,
                checked_at=checked_at,
                worker_observed_at=worker_observed_at,
            )
        )
        if (
            result_key
            in self.artifact_retention_scheduler_daemon_operator_control_execution_worker_results
        ):
            return deepcopy(
                self.artifact_retention_scheduler_daemon_operator_control_execution_worker_results[
                    result_key
                ]
            )
        return _empty_artifact_retention_scheduler_daemon_operator_control_execution_worker_payload(
            operator_control_execution_state_id=state_id,
            operator_control_execution_state=state,
            checked_at=checked_at,
            worker_observed_at=worker_observed_at,
        )

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(self.artifacts.get(artifact_id))

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return _deepcopy_or_none(self.handoffs.get(artifact_handoff_id))

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        raw_value = self.chat_artifact_refs.get(interaction_id, [])
        if isinstance(raw_value, Mapping):
            raw_value = _list_value(raw_value.get("artifact_refs"))
        return deepcopy(list(raw_value))


@dataclass(frozen=True)
class HttpAeArtifactOperationsClient:
    base_url: str
    service_token: str | None = None
    timeout_seconds: float = DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    source_kind: str = "http"

    def get_artifact(
        self,
        artifact_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/artifacts/{artifact_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_artifacts(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifacts",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"status": status} if status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def list_artifact_retention_executions(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        mode: str | None,
        execution_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/executions",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"mode": mode} if mode else {}),
                **({"execution_status": execution_status} if execution_status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_batch_plan(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int,
        max_delete_count: int,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/batch-plan",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "scan_limit": str(scan_limit),
                "max_delete_count": str(max_delete_count),
                **(
                    {"retention_days": str(retention_days)}
                    if retention_days is not None
                    else {}
                ),
                **({"as_of": as_of} if as_of else {}),
                **({"checked_at": checked_at} if checked_at else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def list_artifact_retention_scheduled_jobs(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        owner_user_id: str,
        status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduled-jobs",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"status": status} if status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def dispatch_artifact_retention_scheduled_job(
        self,
        *,
        batch_plan: Mapping[str, Any],
        trigger_type: str,
        requested_at: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._post_json(
            "/api/v1/artifact-retention/scheduled-jobs/admission",
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            json_body={
                "batch_plan": dict(batch_plan),
                "trigger_type": trigger_type,
                **({"requested_at": requested_at} if requested_at else {}),
                **({"idempotency_key": idempotency_key} if idempotency_key else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_config(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduler-daemon-config",
            request_id=request_id,
            trace_id=trace_id,
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_runtime(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduler-daemon-runtime",
            request_id=request_id,
            trace_id=trace_id,
        )
        return payload if isinstance(payload, dict) else {}

    def list_artifact_retention_scheduler_daemon_runs(
        self,
        *,
        scheduler_id: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduler-daemon-runs",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"result_status": result_status} if result_status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_run_detail(
        self,
        daemon_run_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/artifact-retention/scheduler-daemon-runs/{daemon_run_record_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_artifact_retention_scheduler_daemon_supervisor_results(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        result_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduler-daemon-supervisor-results",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"action": action} if action else {}),
                **({"result_status": result_status} if result_status else {}),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_supervisor_detail(
        self,
        daemon_supervisor_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            (
                "/api/v1/artifact-retention/scheduler-daemon-supervisor-results/"
                f"{daemon_supervisor_record_id}"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_artifact_retention_scheduler_daemon_process_snapshots(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        process_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/api/v1/artifact-retention/scheduler-daemon-process-snapshots",
            request_id=request_id,
            trace_id=trace_id,
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"action": action} if action else {}),
                **(
                    {"process_status": process_status}
                    if process_status
                    else {}
                ),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_process_snapshot_detail(
        self,
        daemon_supervised_process_record_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            (
                "/api/v1/artifact-retention/scheduler-daemon-process-snapshots/"
                f"{daemon_supervised_process_record_id}"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )

    def get_artifact_retention_scheduler_daemon_operator_control_policy(
        self,
        *,
        checked_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-policy"
            ),
            request_id=request_id,
            trace_id=trace_id,
            params=({"checked_at": checked_at} if checked_at else {}),
        )
        return payload if isinstance(payload, dict) else {}

    def preview_artifact_retention_scheduler_daemon_operator_control(
        self,
        *,
        action: str,
        operator_subject: Mapping[str, Any],
        idempotency_key: str,
        reason: str,
        requested_at: str | None,
        checked_at: str | None,
        profile: str,
        enabled: bool,
        explicit_opt_in: bool,
        max_cycles: int,
        run_worker: bool,
        approval: Mapping[str, Any] | None,
        current_process: Mapping[str, Any] | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        json_body: dict[str, Any] = {
            "action": action,
            "operator_subject": dict(operator_subject),
            "idempotency_key": idempotency_key,
            "reason": reason,
            "profile": profile,
            "enabled": enabled,
            "explicit_opt_in": explicit_opt_in,
            "max_cycles": max_cycles,
            "run_worker": run_worker,
            **({"requested_at": requested_at} if requested_at else {}),
            **({"checked_at": checked_at} if checked_at else {}),
            **({"approval": dict(approval)} if approval else {}),
            **({"current_process": dict(current_process)} if current_process else {}),
        }
        payload = self._post_json(
            (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            json_body=json_body,
        )
        return payload if isinstance(payload, dict) else {}

    def dispatch_artifact_retention_scheduler_daemon_control(
        self,
        *,
        action: str,
        tenant_id: str | None,
        workspace_id: str | None,
        owner_user_id: str | None,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int | None,
        max_delete_count: int | None,
        requested_at: str | None,
        requested_by: Mapping[str, Any] | None,
        reason: str | None,
        tick_at: str | None,
        run_worker: bool,
        worker_id: str | None,
        idempotency_key: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        json_body: dict[str, Any] = {
            "action": action,
            "run_worker": run_worker,
            "trace_id": trace_id,
            **({"tenant_id": tenant_id} if tenant_id else {}),
            **({"workspace_id": workspace_id} if workspace_id else {}),
            **({"owner_user_id": owner_user_id} if owner_user_id else {}),
            **(
                {"retention_days": retention_days}
                if retention_days is not None
                else {}
            ),
            **({"as_of": as_of} if as_of else {}),
            **({"scan_limit": scan_limit} if scan_limit is not None else {}),
            **(
                {"max_delete_count": max_delete_count}
                if max_delete_count is not None
                else {}
            ),
            **({"requested_at": requested_at} if requested_at else {}),
            **({"requested_by": dict(requested_by)} if requested_by else {}),
            **({"reason": reason} if reason else {}),
            **({"tick_at": tick_at} if tick_at else {}),
            **({"worker_id": worker_id} if worker_id else {}),
            **({"idempotency_key": idempotency_key} if idempotency_key else {}),
        }
        payload = self._post_json(
            "/api/v1/artifact-retention/scheduler-daemon-controls",
            request_id=request_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            json_body=json_body,
        )
        return payload if isinstance(payload, dict) else {}

    def list_artifact_retention_scheduler_daemon_operator_control_executions(
        self,
        *,
        scheduler_id: str | None,
        action: str | None,
        execution_status: str | None,
        idempotency_status: str | None,
        limit: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        payload = self._get_json(
            (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-executions"
            ),
            request_id=request_id,
            trace_id=trace_id,
            params={
                "limit": str(limit),
                **({"scheduler_id": scheduler_id} if scheduler_id else {}),
                **({"action": action} if action else {}),
                **(
                    {"execution_status": execution_status}
                    if execution_status
                    else {}
                ),
                **(
                    {"idempotency_status": idempotency_status}
                    if idempotency_status
                    else {}
                ),
            },
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
        self,
        operator_control_execution_state_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-executions/"
                f"{operator_control_execution_state_id}"
            ),
            request_id=request_id,
            trace_id=trace_id,
        )

    def run_artifact_retention_scheduler_daemon_operator_control_execution_worker(
        self,
        *,
        operator_control_execution_state_id: str | None,
        operator_control_execution_state: Mapping[str, Any] | None,
        checked_at: str | None,
        worker_observed_at: str | None,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        state = _mapping_or_empty(operator_control_execution_state)
        json_body: dict[str, Any] = {
            **(
                {"operator_control_execution_state_id": operator_control_execution_state_id}
                if operator_control_execution_state_id
                else {}
            ),
            **(
                {"operator_control_execution_state": state}
                if state
                else {}
            ),
            **({"checked_at": checked_at} if checked_at else {}),
            **({"worker_observed_at": worker_observed_at} if worker_observed_at else {}),
        }
        payload = self._post_json(
            (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
            request_id=request_id,
            trace_id=trace_id,
            json_body=json_body,
        )
        return payload if isinstance(payload, dict) else {}

    def get_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        return self._get_json(
            f"/api/v1/artifact-handoffs/{artifact_handoff_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def list_chat_artifact_refs(
        self,
        interaction_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        payload = self._get_json(
            f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
            request_id=request_id,
            trace_id=trace_id,
        )
        if payload is None:
            return []
        return _list_value(payload.get("artifact_refs"))

    def _get_json(
        self,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}{path}",
                headers=self._headers(request_id=request_id, trace_id=trace_id),
                params=dict(params or {}),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_unreachable",
                detail="AE artifact source could not be reached.",
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise AeArtifactOperationsError(
                error_code=body.get(
                    "error_code",
                    "ag.ae_artifact_source_request_failed",
                ),
                detail=body.get("detail", "AE artifact source request failed."),
                status_code=response.status_code,
            )
        return response.json()

    def _post_json(
        self,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        json_body: Mapping[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        headers = self._headers(request_id=request_id, trace_id=trace_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}{path}",
                headers=headers,
                json=dict(json_body),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_unreachable",
                detail="AE artifact source could not be reached.",
            ) from exc
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise AeArtifactOperationsError(
                error_code=body.get(
                    "error_code",
                    "ag.ae_artifact_source_request_failed",
                ),
                detail=body.get("detail", "AE artifact source request failed."),
                status_code=response.status_code,
            )
        return response.json()

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        token = (
            self.service_token
            or issue_mock_service_token(
                service_id="nex-ag",
                audience=AE_ARTIFACT_SOURCE_SERVICE_ID,
            ).access_token
        )
        return {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
            "X-Service-ID": "nex-ag",
        }


def build_default_ae_artifact_operations_client(
    environ: Mapping[str, str] | None = None,
) -> HttpAeArtifactOperationsClient:
    env = environ if environ is not None else os.environ
    service_spec = SERVICE_SPECS[AE_ARTIFACT_SOURCE_SERVICE_ID]
    base_url = env.get(
        NEX_AG_AE_ARTIFACT_BASE_URL_ENV,
        f"http://127.0.0.1:{service_spec.default_port}",
    )
    return HttpAeArtifactOperationsClient(
        base_url=base_url.rstrip("/"),
        service_token=env.get(NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV),
        timeout_seconds=_timeout_seconds(
            env.get(NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV)
        ),
    )


def register_artifact_operation_routes(
    app: FastAPI,
    *,
    client: AeArtifactOperationsClient | None = None,
) -> None:
    configured_client = client

    @app.get("/admin/v1/operations/artifacts", response_model=None)
    def list_artifact_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_collection_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifacts(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                status=filter_result["status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/executions",
        response_model=None,
    )
    def list_artifact_retention_history_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        mode: str | None = None,
        execution_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_history_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode=mode,
            execution_status=execution_status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifact_retention_executions(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                mode=filter_result["mode"],
                execution_status=filter_result["execution_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_history_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/batch-plan",
        response_model=None,
    )
    def get_artifact_retention_batch_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        retention_days: str | None = None,
        as_of: str | None = None,
        scan_limit: str | None = None,
        max_delete_count: str | None = None,
        checked_at: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_batch_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            plan = selected_client.get_artifact_retention_batch_plan(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                retention_days=filter_result["retention_days"],
                as_of=as_of,
                scan_limit=filter_result["scan_limit"],
                max_delete_count=filter_result["max_delete_count"],
                checked_at=checked_at,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_batch_projection(
            plan=plan,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/scheduled-jobs",
        response_model=None,
    )
    def list_artifact_retention_scheduled_job_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_scheduled_job_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            status=status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifact_retention_scheduled_jobs(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                status=filter_result["status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_scheduled_job_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.post(
        "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
        response_model=None,
    )
    def dispatch_artifact_retention_scheduled_job_operations(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        dispatch_request = _validate_artifact_retention_scheduled_dispatch_request(
            request,
            payload=payload,
        )
        if isinstance(dispatch_request, JSONResponse):
            return dispatch_request

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            plan = selected_client.get_artifact_retention_batch_plan(
                tenant_id=dispatch_request["tenant_id"],
                workspace_id=dispatch_request["workspace_id"],
                owner_user_id=dispatch_request["owner_user_id"],
                retention_days=dispatch_request["retention_days"],
                as_of=dispatch_request["as_of"],
                scan_limit=dispatch_request["scan_limit"],
                max_delete_count=dispatch_request["max_delete_count"],
                checked_at=dispatch_request["checked_at"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        projected_plan = _project_retention_batch_plan(plan)
        if not summarize_artifact_retention_batch_operations(projected_plan)[
            "dispatch_available"
        ]:
            return problem_response(
                request,
                status_code=409,
                error_code="ag.ae_artifact_retention_scheduled_dispatch_blocked",
                title="Artifact retention scheduled dispatch is blocked",
                detail=(
                    "Artifact retention scheduled dispatch requires a READY "
                    "DRY_RUN batch plan with selected candidates."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-scheduled-dispatch-blocked"
                ),
            )

        try:
            dispatch_response = (
                selected_client.dispatch_artifact_retention_scheduled_job(
                    batch_plan=projected_plan,
                    trigger_type=dispatch_request["trigger_type"],
                    requested_at=dispatch_request["requested_at"],
                    idempotency_key=dispatch_request["idempotency_key"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_scheduled_dispatch_projection(
            dispatch_request=dispatch_request,
            batch_plan=projected_plan,
            dispatch_response=dispatch_response,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/automation",
        response_model=None,
    )
    def get_artifact_retention_automation_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        owner_user_id: str | None = None,
        retention_days: str | None = None,
        as_of: str | None = None,
        scan_limit: str | None = None,
        max_delete_count: str | None = None,
        checked_at: str | None = None,
        scheduled_status: str | None = None,
        history_mode: str | None = None,
        history_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_automation_query(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            retention_days=retention_days,
            scan_limit=scan_limit,
            max_delete_count=max_delete_count,
            scheduled_status=scheduled_status,
            history_mode=history_mode,
            history_status=history_status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            plan = selected_client.get_artifact_retention_batch_plan(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                retention_days=filter_result["retention_days"],
                as_of=as_of,
                scan_limit=filter_result["scan_limit"],
                max_delete_count=filter_result["max_delete_count"],
                checked_at=checked_at,
                request_id=request_id,
                trace_id=trace_id,
            )
            scheduled_jobs = selected_client.list_artifact_retention_scheduled_jobs(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                status=filter_result["scheduled_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
            history = selected_client.list_artifact_retention_executions(
                tenant_id=filter_result["tenant_id"],
                workspace_id=filter_result["workspace_id"],
                owner_user_id=filter_result["owner_user_id"],
                mode=filter_result["history_mode"],
                execution_status=filter_result["history_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
            daemon_config = (
                selected_client.get_artifact_retention_scheduler_daemon_config(
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        daemon_process_errors: list[AeArtifactOperationsError] = []
        scheduler_id = _text_or_none(daemon_config.get("scheduler_id"))
        try:
            daemon_process_snapshots = (
                selected_client.list_artifact_retention_scheduler_daemon_process_snapshots(
                    scheduler_id=scheduler_id,
                    action=None,
                    process_status=None,
                    limit=filter_result["limit"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            daemon_process_errors.append(exc)
            daemon_process_snapshots = (
                _empty_artifact_retention_scheduler_daemon_process_snapshot_collection_payload(
                    scheduler_id=scheduler_id,
                    action=None,
                    process_status=None,
                    limit=filter_result["limit"],
                )
            )

        operator_control_errors: list[AeArtifactOperationsError] = []
        try:
            operator_control_policy = (
                selected_client.get_artifact_retention_scheduler_daemon_operator_control_policy(
                    checked_at=checked_at,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            operator_control_errors.append(exc)
            operator_control_policy = {}

        operator_control_facade: dict[str, Any] = {}
        if operator_control_policy:
            try:
                operator_control_facade = (
                    selected_client.preview_artifact_retention_scheduler_daemon_operator_control(
                        action="status_probe",
                        operator_subject={
                            "actor_type": "service",
                            "actor_id": "nex-ag",
                            "service_id": "nex-ag",
                        },
                        idempotency_key=(
                            "ag-artifact-retention-automation-operator-control:"
                            f"{request_id}"
                        ),
                        reason="ag_artifact_retention_automation_status_probe",
                        requested_at=checked_at,
                        checked_at=checked_at,
                        profile="test",
                        enabled=False,
                        explicit_opt_in=False,
                        max_cycles=1,
                        run_worker=False,
                        approval=None,
                        current_process=(
                            _artifact_retention_automation_operator_control_current_process(
                                daemon_process_snapshots
                            )
                        ),
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                )
            except AeArtifactOperationsError as exc:
                operator_control_errors.append(exc)

        return build_artifact_operation_retention_automation_projection(
            plan=plan,
            scheduled_jobs=scheduled_jobs,
            history=history,
            daemon_config=daemon_config,
            daemon_process_snapshots=daemon_process_snapshots,
            operator_control_policy=operator_control_policy,
            operator_control_facade=operator_control_facade,
            source_client=selected_client,
            daemon_process_errors=daemon_process_errors,
            operator_control_errors=operator_control_errors,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            daemon_config = (
                selected_client.get_artifact_retention_scheduler_daemon_config(
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        runtime_errors: list[AeArtifactOperationsError] = []
        try:
            daemon_runtime = (
                selected_client.get_artifact_retention_scheduler_daemon_runtime(
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            daemon_runtime = {}
            runtime_errors.append(
                AeArtifactOperationsError(
                    error_code="ag.ae_artifact_retention_daemon_runtime_warning",
                    detail=exc.detail,
                    status_code=exc.status_code,
                )
            )

        return build_artifact_operation_retention_daemon_projection(
            daemon_config=daemon_config,
            daemon_runtime=daemon_runtime,
            source_client=selected_client,
            source_errors=runtime_errors,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/scheduler-daemon-runs",
        response_model=None,
    )
    def list_artifact_retention_scheduler_daemon_run_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        scheduler_id: str | None = None,
        result_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_daemon_run_query(
            request,
            scheduler_id=scheduler_id,
            result_status=result_status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = (
                selected_client.list_artifact_retention_scheduler_daemon_runs(
                    scheduler_id=filter_result["scheduler_id"],
                    result_status=filter_result["result_status"],
                    limit=filter_result["limit"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_run_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-runs/{daemon_run_record_id}",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_run_operation_detail(
        daemon_run_record_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            detail = selected_client.get_artifact_retention_scheduler_daemon_run_detail(
                daemon_run_record_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if detail is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.ae_artifact_retention_daemon_run_not_found",
                title="AE artifact retention daemon run not found",
                detail=(
                    "AE artifact retention scheduler daemon run "
                    f"{daemon_run_record_id} was not found."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-daemon-run-not-found"
                ),
            )

        return build_artifact_operation_retention_daemon_run_detail_projection(
            detail=detail,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-supervisor-results",
        response_model=None,
    )
    def list_artifact_retention_scheduler_daemon_supervisor_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        scheduler_id: str | None = None,
        action: str | None = None,
        result_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_daemon_supervisor_query(
            request,
            scheduler_id=scheduler_id,
            action=action,
            result_status=result_status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifact_retention_scheduler_daemon_supervisor_results(
                scheduler_id=filter_result["scheduler_id"],
                action=filter_result["action"],
                result_status=filter_result["result_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_supervisor_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-supervisor-results/{daemon_supervisor_record_id}",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_supervisor_operation_detail(
        daemon_supervisor_record_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            detail = (
                selected_client.get_artifact_retention_scheduler_daemon_supervisor_detail(
                    daemon_supervisor_record_id,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if detail is None:
            return problem_response(
                request,
                status_code=404,
                error_code=(
                    "ag.ae_artifact_retention_daemon_supervisor_not_found"
                ),
                title="AE artifact retention daemon supervisor result not found",
                detail=(
                    "AE artifact retention scheduler daemon supervisor result "
                    f"{daemon_supervisor_record_id} was not found."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-daemon-supervisor-not-found"
                ),
            )

        return build_artifact_operation_retention_daemon_supervisor_detail_projection(
            detail=detail,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-process-snapshots",
        response_model=None,
    )
    def list_artifact_retention_scheduler_daemon_process_snapshot_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        scheduler_id: str | None = None,
        action: str | None = None,
        process_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = (
            _validate_artifact_retention_daemon_supervised_process_query(
                request,
                scheduler_id=scheduler_id,
                action=action,
                process_status=process_status,
                limit=limit,
            )
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifact_retention_scheduler_daemon_process_snapshots(
                scheduler_id=filter_result["scheduler_id"],
                action=filter_result["action"],
                process_status=filter_result["process_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_supervised_process_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-process-snapshots/{daemon_supervised_process_record_id}",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_process_snapshot_operation_detail(
        daemon_supervised_process_record_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            detail = selected_client.get_artifact_retention_scheduler_daemon_process_snapshot_detail(
                daemon_supervised_process_record_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if detail is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.ae_artifact_retention_daemon_process_not_found",
                title="AE artifact retention daemon process snapshot not found",
                detail=(
                    "AE artifact retention scheduler daemon process snapshot "
                    f"{daemon_supervised_process_record_id} was not found."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-daemon-process-not-found"
                ),
            )

        return build_artifact_operation_retention_daemon_supervised_process_detail_projection(
            detail=detail,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-policy",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_operator_control_policy_operation(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        checked_at: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            policy = selected_client.get_artifact_retention_scheduler_daemon_operator_control_policy(
                checked_at=checked_at,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_operator_control_projection(
            policy=policy,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.post(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-preview",
        response_model=None,
    )
    def preview_artifact_retention_scheduler_daemon_operator_control_operation(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key_header: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        preview_request = _validate_artifact_retention_daemon_operator_control_preview_request(
            request,
            payload=payload,
            idempotency_key_header=idempotency_key_header,
        )
        if isinstance(preview_request, JSONResponse):
            return preview_request

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            facade = selected_client.preview_artifact_retention_scheduler_daemon_operator_control(
                action=preview_request["action"],
                operator_subject=preview_request["operator_subject"],
                idempotency_key=preview_request["idempotency_key"],
                reason=preview_request["reason"],
                requested_at=preview_request["requested_at"],
                checked_at=preview_request["checked_at"],
                profile=preview_request["profile"],
                enabled=preview_request["enabled"],
                explicit_opt_in=preview_request["explicit_opt_in"],
                max_cycles=preview_request["max_cycles"],
                run_worker=preview_request["run_worker"],
                approval=preview_request["approval"],
                current_process=preview_request["current_process"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_operator_control_projection(
            policy=facade.get("operator_control_policy")
            if isinstance(facade, Mapping)
            else {},
            facade=facade,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-executions",
        response_model=None,
    )
    def list_artifact_retention_scheduler_daemon_operator_control_execution_operations(
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        scheduler_id: str | None = None,
        action: str | None = None,
        execution_status: str | None = None,
        idempotency_status: str | None = None,
        limit: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        filter_result = _validate_artifact_retention_daemon_operator_control_execution_query(
            request,
            scheduler_id=scheduler_id,
            action=action,
            execution_status=execution_status,
            idempotency_status=idempotency_status,
            limit=limit,
        )
        if isinstance(filter_result, JSONResponse):
            return filter_result

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            collection = selected_client.list_artifact_retention_scheduler_daemon_operator_control_executions(
                scheduler_id=filter_result["scheduler_id"],
                action=filter_result["action"],
                execution_status=filter_result["execution_status"],
                idempotency_status=filter_result["idempotency_status"],
                limit=filter_result["limit"],
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_daemon_operator_control_execution_collection_projection(
            collection=collection,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifact-retention/"
        "scheduler-daemon-operator-control-executions/"
        "{operator_control_execution_state_id}",
        response_model=None,
    )
    def get_artifact_retention_scheduler_daemon_operator_control_execution_operation_detail(
        operator_control_execution_state_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            detail = selected_client.get_artifact_retention_scheduler_daemon_operator_control_execution_detail(
                operator_control_execution_state_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if detail is None:
            return problem_response(
                request,
                status_code=404,
                error_code=(
                    "ag.ae_artifact_retention_daemon_operator_control_execution_not_found"
                ),
                title="AE artifact retention daemon operator-control execution not found",
                detail=(
                    "AE artifact retention scheduler daemon operator-control "
                    "execution state "
                    f"{operator_control_execution_state_id} was not found."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-daemon-operator-control-execution-not-found"
                ),
            )

        return build_artifact_operation_retention_daemon_operator_control_execution_detail_projection(
            detail=detail,
            source_client=selected_client,
            request_trace_id=trace_id,
        )

    @app.post(
        "/admin/v1/operations/artifact-retention/scheduler-daemon/manual-tick-once",
        response_model=None,
    )
    def dispatch_artifact_retention_scheduler_daemon_manual_tick_once(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key_header: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem
        dispatch_request = _validate_artifact_retention_daemon_manual_tick_request(
            request,
            payload=payload,
            idempotency_key_header=idempotency_key_header,
        )
        if isinstance(dispatch_request, JSONResponse):
            return dispatch_request

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            daemon_config = (
                selected_client.get_artifact_retention_scheduler_daemon_config(
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        projected_config = _project_retention_scheduler_daemon_config(daemon_config)
        manual_action = _daemon_action_item(projected_config, "manual_tick_once")
        if _text_or_none(manual_action.get("decision_status")) != "READY":
            return problem_response(
                request,
                status_code=409,
                error_code="ag.ae_artifact_retention_daemon_manual_tick_blocked",
                title="Artifact retention daemon manual tick is blocked",
                detail=(
                    "Artifact retention daemon manual tick requires AE to "
                    "report a READY manual_tick_once action."
                ),
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "ae-artifact-retention-daemon-manual-tick-blocked"
                ),
            )

        try:
            dispatch_response = (
                selected_client.dispatch_artifact_retention_scheduler_daemon_control(
                    action="manual_tick_once",
                    tenant_id=dispatch_request["tenant_id"],
                    workspace_id=dispatch_request["workspace_id"],
                    owner_user_id=dispatch_request["owner_user_id"],
                    retention_days=dispatch_request["retention_days"],
                    as_of=dispatch_request["as_of"],
                    scan_limit=dispatch_request["scan_limit"],
                    max_delete_count=dispatch_request["max_delete_count"],
                    requested_at=dispatch_request["requested_at"],
                    requested_by=dispatch_request["requested_by"],
                    reason=dispatch_request["reason"],
                    tick_at=dispatch_request["tick_at"],
                    run_worker=dispatch_request["run_worker"],
                    worker_id=dispatch_request["worker_id"],
                    idempotency_key=dispatch_request["idempotency_key"],
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        runtime_errors: list[AeArtifactOperationsError] = []
        try:
            daemon_runtime = (
                selected_client.get_artifact_retention_scheduler_daemon_runtime(
                    request_id=request_id,
                    trace_id=trace_id,
                )
            )
        except AeArtifactOperationsError as exc:
            daemon_runtime = {}
            runtime_errors.append(
                AeArtifactOperationsError(
                    error_code="ag.ae_artifact_retention_daemon_runtime_warning",
                    detail=exc.detail,
                    status_code=exc.status_code,
                )
            )

        return build_artifact_operation_retention_daemon_projection(
            daemon_config=projected_config,
            daemon_runtime=daemon_runtime,
            dispatch_response=dispatch_response,
            source_client=selected_client,
            source_errors=runtime_errors,
            request_trace_id=trace_id,
        )

    @app.get("/admin/v1/operations/artifacts/{artifact_id}", response_model=None)
    def get_artifact_operation_detail(
        artifact_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
        interaction_id: str | None = None,
        include_handoff: bool = True,
        include_chat_links: bool = True,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            artifact = selected_client.get_artifact(
                artifact_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if artifact is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.ae_artifact_not_found",
                title="AE artifact not found",
                detail=f"AE artifact {artifact_id} was not found.",
                type_uri="https://nex-platform.local/problems/ae-artifact-not-found",
            )

        source_errors: list[AeArtifactOperationsError] = []
        handoff = None
        handoff_id = _handoff_id_from_artifact(artifact)
        if include_handoff and handoff_id is not None:
            try:
                handoff = selected_client.get_artifact_handoff(
                    handoff_id,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except AeArtifactOperationsError as exc:
                source_errors.append(exc)

        chat_artifact_refs: list[dict[str, Any]] = []
        if include_chat_links and interaction_id:
            try:
                chat_artifact_refs = selected_client.list_chat_artifact_refs(
                    interaction_id,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except AeArtifactOperationsError as exc:
                source_errors.append(exc)

        return build_artifact_operation_detail_projection(
            artifact=artifact,
            handoff=handoff,
            chat_artifact_refs=chat_artifact_refs,
            source_client=selected_client,
            source_errors=source_errors,
            request_trace_id=trace_id,
        )

    @app.get(
        "/admin/v1/operations/artifacts/{artifact_id}/lifecycle",
        response_model=None,
    )
    def get_artifact_operation_lifecycle(
        artifact_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        service_id: str | None = None,
    ):
        auth_problem = _authorize_ag_request(request, authorization)
        if auth_problem is not None:
            return auth_problem
        service_problem = _validate_artifact_service_filter(request, service_id)
        if service_problem is not None:
            return service_problem

        selected_client = (
            configured_client or build_default_ae_artifact_operations_client()
        )
        request_id = request_id_from_headers(request)
        trace_id = trace_id_from_headers(request)
        try:
            artifact = selected_client.get_artifact(
                artifact_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)
        if artifact is None:
            return problem_response(
                request,
                status_code=404,
                error_code="ag.ae_artifact_not_found",
                title="AE artifact not found",
                detail=f"AE artifact {artifact_id} was not found.",
                type_uri="https://nex-platform.local/problems/ae-artifact-not-found",
            )

        return build_artifact_operation_lifecycle_projection(
            artifact=artifact,
            source_client=selected_client,
            request_trace_id=trace_id,
        )


def build_artifact_operation_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_artifact_collection_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_collection",
        "filter": _project_collection_filter(collection.get("filter")),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "next_cursor": _text_or_none(collection.get("next_cursor")),
        "items": items,
        "summary": summarize_artifact_operation_collection(items),
        "source_status": _artifact_collection_source_status(
            source_client=source_client,
            item_count=len(items),
            errors=errors,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_batch_projection(
    *,
    plan: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_plan = _project_retention_batch_plan(plan)
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_BATCH_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_batch_plan",
        "plan": projected_plan,
        "summary": summarize_artifact_retention_batch_operations(projected_plan),
        "source_status": _artifact_retention_batch_source_status(
            source_client=source_client,
            plan_loaded=bool(projected_plan.get("plan_id")),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_batch_plan_route": "/api/v1/artifact-retention/batch-plan",
            "ae_purge_route": "/api/v1/artifact-retention/purge",
            "scheduled_command_required_before_worker": True,
            "mock_worker_available": True,
            "physical_delete_confirmation_required": True,
            "ag_direct_database_write_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_scheduled_job_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_scheduled_job_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduled_jobs",
        "filter": _project_retention_scheduled_job_filter(collection.get("filter")),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "next_cursor": _text_or_none(collection.get("next_cursor")),
        "items": items,
        "summary": summarize_artifact_retention_scheduled_job_operations(items),
        "source_status": _artifact_retention_scheduled_job_source_status(
            source_client=source_client,
            item_count=len(items),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_scheduled_jobs_route": ("/api/v1/artifact-retention/scheduled-jobs"),
            "ae_batch_plan_route": "/api/v1/artifact-retention/batch-plan",
            "ae_retention_history_route": "/api/v1/artifact-retention/executions",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_enabled": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_scheduled_dispatch_projection(
    *,
    dispatch_request: Mapping[str, Any],
    batch_plan: Mapping[str, Any],
    dispatch_response: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_plan = _project_retention_batch_plan(batch_plan)
    projected_response = _project_retention_scheduled_dispatch_response(
        dispatch_response
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduled_dispatch",
        "dispatch_request": _project_retention_scheduled_dispatch_request(
            dispatch_request
        ),
        "batch_plan": projected_plan,
        "dispatch_response": projected_response,
        "summary": summarize_artifact_retention_scheduled_dispatch(
            batch_plan=projected_plan,
            dispatch_response=projected_response,
        ),
        "source_status": _artifact_retention_scheduled_dispatch_source_status(
            source_client=source_client,
            dispatch_response_loaded=bool(projected_response),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_scheduled_job_admission_route": (
                "/api/v1/artifact-retention/scheduled-jobs/admission"
            ),
            "confirm_dispatch_required": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_enabled": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_automation_projection(
    *,
    plan: Mapping[str, Any],
    scheduled_jobs: Mapping[str, Any],
    history: Mapping[str, Any],
    daemon_config: Mapping[str, Any] | None = None,
    daemon_process_snapshots: Mapping[str, Any] | None = None,
    operator_control_policy: Mapping[str, Any] | None = None,
    operator_control_facade: Mapping[str, Any] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    daemon_process_errors: list[AeArtifactOperationsError] | None = None,
    operator_control_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_plan = _project_retention_batch_plan(plan)
    projected_daemon_config = _project_retention_scheduler_daemon_config(
        daemon_config or {}
    )
    daemon_summary = _optional_retention_daemon_summary(projected_daemon_config)
    daemon_attention = classify_artifact_retention_daemon_attention(
        daemon_config=projected_daemon_config,
    )
    scheduled_items = [
        _project_retention_scheduled_job_item(item)
        for item in _list_value(scheduled_jobs.get("items"))
        if isinstance(item, Mapping)
    ]
    history_items = [
        _project_retention_history_item(item)
        for item in _list_value(history.get("items"))
        if isinstance(item, Mapping)
    ]
    projected_operator_control_policy = (
        _project_retention_scheduler_daemon_operator_control_policy(
            operator_control_policy or {}
        )
    )
    projected_operator_control_facade = (
        _project_retention_scheduler_daemon_operator_control_facade(
            operator_control_facade or {}
        )
    )
    operator_control_summary = (
        summarize_artifact_retention_daemon_operator_control_projection(
            policy=projected_operator_control_policy,
            facade=projected_operator_control_facade,
        )
    )
    process_collection = daemon_process_snapshots or {}
    process_items = [
        _project_retention_scheduler_daemon_supervised_process_item(item)
        for item in _list_value(process_collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    process_errors = daemon_process_errors or []
    control_errors = operator_control_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": (
            "DEGRADED" if errors or process_errors or control_errors else "READY"
        ),
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_automation",
        "batch_plan": {
            "plan": projected_plan,
            "summary": summarize_artifact_retention_batch_operations(projected_plan),
        },
        "scheduled_jobs": {
            "filter": _project_retention_scheduled_job_filter(
                scheduled_jobs.get("filter")
            ),
            "count": _int_or_zero(scheduled_jobs.get("count")),
            "limit": _int_or_zero(scheduled_jobs.get("limit")),
            "next_cursor": _text_or_none(scheduled_jobs.get("next_cursor")),
            "items": scheduled_items,
            "summary": summarize_artifact_retention_scheduled_job_operations(
                scheduled_items
            ),
        },
        "history": {
            "filter": _project_retention_history_filter(history.get("filter")),
            "count": _int_or_zero(history.get("count")),
            "limit": _int_or_zero(history.get("limit")),
            "next_cursor": _text_or_none(history.get("next_cursor")),
            "items": history_items,
            "summary": summarize_artifact_retention_history_operations(history_items),
        },
        "scheduler_daemon": {
            "daemon_config": projected_daemon_config,
            "summary": daemon_summary,
            "attention": daemon_attention,
        },
        "scheduler_daemon_processes": {
            "filter": _project_retention_scheduler_daemon_supervised_process_filter(
                process_collection.get("filter")
            ),
            "count": _int_or_zero(process_collection.get("count")),
            "limit": _int_or_zero(process_collection.get("limit")),
            "items": process_items,
            "summary": (
                summarize_artifact_retention_daemon_supervised_process_operations(
                    process_items
                )
            ),
        },
        "operator_control": {
            "projection_schema_version": (
                AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
            ),
            "policy": projected_operator_control_policy,
            "facade": projected_operator_control_facade or None,
            "summary": operator_control_summary,
            "preview_only": True,
        },
        "summary": summarize_artifact_retention_automation_operations(
            batch_plan=projected_plan,
            scheduled_jobs=scheduled_items,
            history=history_items,
            daemon_config=projected_daemon_config,
            daemon_process_snapshots=process_items,
            operator_control_summary=operator_control_summary,
        ),
        "source_status": _artifact_retention_automation_source_status(
            source_client=source_client,
            batch_plan_loaded=bool(projected_plan.get("plan_id")),
            scheduled_job_count=len(scheduled_items),
            history_count=len(history_items),
            daemon_config_loaded=bool(projected_daemon_config.get("scheduler_id")),
            daemon_process_snapshot_count=len(process_items),
            daemon_process_snapshots_loaded=(
                process_collection.get("items") is not None
            ),
            operator_control_policy_loaded=bool(
                projected_operator_control_policy.get("operator_control_policy_id")
            ),
            operator_control_facade_loaded=bool(
                projected_operator_control_facade.get("operator_control_facade_id")
            ),
            errors=errors,
            daemon_process_errors=process_errors,
            operator_control_errors=control_errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_scheduler_config_route": "/api/v1/artifact-retention/scheduler-config",
            "ae_daemon_config_route": (
                "/api/v1/artifact-retention/scheduler-daemon-config"
            ),
            "ag_daemon_operations_route": (
                "/admin/v1/operations/artifact-retention/scheduler-daemon"
            ),
            "ae_daemon_process_snapshots_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-process-snapshots"
            ),
            "ag_daemon_process_snapshots_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-process-snapshots"
            ),
            "ae_batch_plan_route": "/api/v1/artifact-retention/batch-plan",
            "ae_scheduled_jobs_route": ("/api/v1/artifact-retention/scheduled-jobs"),
            "ae_scheduled_job_admission_route": (
                "/api/v1/artifact-retention/scheduled-jobs/admission"
            ),
            "ae_retention_history_route": "/api/v1/artifact-retention/executions",
            "ae_purge_route": "/api/v1/artifact-retention/purge",
            "ae_operator_control_policy_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-policy"
            ),
            "ae_operator_control_preview_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            "ag_operator_control_policy_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-policy"
            ),
            "ag_operator_control_preview_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
            "operator_control_preview_only": True,
            "physical_delete_operator_approval_required": True,
            "physical_delete_automation_enabled": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_projection(
    *,
    daemon_config: Mapping[str, Any],
    daemon_runtime: Mapping[str, Any] | None = None,
    dispatch_response: Mapping[str, Any] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_config = _project_retention_scheduler_daemon_config(daemon_config)
    projected_runtime = _normalize_retention_scheduler_daemon_runtime_observation(
        daemon_runtime
    )
    projected_dispatch = _project_retention_scheduler_daemon_dispatch_response(
        dispatch_response
    )
    daemon_attention = classify_artifact_retention_daemon_attention(
        daemon_config=projected_config,
        daemon_runtime=projected_runtime,
        dispatch_response=projected_dispatch,
    )
    lifecycle_projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=projected_config,
        daemon_runtime=projected_runtime,
        dispatch_response=projected_dispatch,
    )
    issue_candidates = build_artifact_retention_daemon_runtime_issue_candidates(
        daemon_runtime=projected_runtime,
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon",
        "daemon_config": projected_config,
        "daemon_runtime": projected_runtime or None,
        "dispatch_response": projected_dispatch or None,
        "lifecycle_projection": lifecycle_projection,
        "issue_candidates": issue_candidates,
        "summary": summarize_artifact_retention_daemon_operations(
            daemon_config=projected_config,
            daemon_runtime=projected_runtime,
            dispatch_response=projected_dispatch,
        ),
        "attention": daemon_attention,
        "source_status": _artifact_retention_daemon_source_status(
            source_client=source_client,
            config_loaded=bool(projected_config.get("scheduler_id")),
            runtime_observation_loaded=bool(projected_runtime),
            dispatch_response_loaded=bool(projected_dispatch),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_config_route": (
                "/api/v1/artifact-retention/scheduler-daemon-config"
            ),
            "ae_daemon_controls_route": (
                "/api/v1/artifact-retention/scheduler-daemon-controls"
            ),
            "ae_daemon_runtime_route": (
                "/api/v1/artifact-retention/scheduler-daemon-runtime"
            ),
            "ae_daemon_runs_route": (
                "/api/v1/artifact-retention/scheduler-daemon-runs"
            ),
            "ae_daemon_lifecycle_projection": "metadata_only",
            "manual_tick_once_only": True,
            "manual_tick_once_requires_ae_api": True,
            "confirm_dispatch_required": True,
            "start_daemon_allowed": False,
            "continuous_loop_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_run_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_scheduler_daemon_run_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon_runs",
        "filter": _project_retention_scheduler_daemon_run_filter(
            collection.get("filter")
        ),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "items": items,
        "summary": summarize_artifact_retention_daemon_run_operations(items),
        "source_status": _artifact_retention_daemon_run_source_status(
            source_client=source_client,
            item_count=len(items),
            detail_loaded=False,
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_runs_route": (
                "/api/v1/artifact-retention/scheduler-daemon-runs"
            ),
            "ag_daemon_runs_route": (
                "/admin/v1/operations/artifact-retention/scheduler-daemon-runs"
            ),
            "read_model": "ae_artifact_retention_scheduler_daemon_runs",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_run_detail_projection(
    *,
    detail: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    run_record = _project_retention_scheduler_daemon_run_record(
        detail.get("run_record")
    )
    lifecycle_events = [
        _project_retention_scheduler_daemon_lifecycle_event(event)
        for event in _list_value(detail.get("lifecycle_events"))
        if isinstance(event, Mapping)
    ]
    daemon_run_record_id = _text_or_none(detail.get("daemon_run_record_id"))
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUN_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon_run",
        "daemon_run_record_id": daemon_run_record_id,
        "run_record": run_record,
        "lifecycle_event_count": _int_or_zero(detail.get("lifecycle_event_count")),
        "lifecycle_events": lifecycle_events,
        "summary": summarize_artifact_retention_daemon_run_detail(
            run_record=run_record,
            lifecycle_events=lifecycle_events,
        ),
        "source_status": _artifact_retention_daemon_run_source_status(
            source_client=source_client,
            item_count=len(lifecycle_events),
            detail_loaded=bool(run_record.get("daemon_run_record_id")),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_run_detail_route": (
                "/api/v1/artifact-retention/scheduler-daemon-runs/"
                f"{daemon_run_record_id or ''}"
            ),
            "ag_daemon_run_detail_route": (
                "/admin/v1/operations/artifact-retention/scheduler-daemon-runs/"
                f"{daemon_run_record_id or ''}"
            ),
            "read_model": "ae_artifact_retention_scheduler_daemon_run_detail",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_supervisor_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_scheduler_daemon_supervisor_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon_supervisor_results",
        "filter": _project_retention_scheduler_daemon_supervisor_filter(
            collection.get("filter")
        ),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "items": items,
        "summary": summarize_artifact_retention_daemon_supervisor_operations(items),
        "source_status": _artifact_retention_daemon_supervisor_source_status(
            source_client=source_client,
            item_count=len(items),
            detail_loaded=False,
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_supervisor_results_route": (
                "/api/v1/artifact-retention/scheduler-daemon-supervisor-results"
            ),
            "ag_daemon_supervisor_results_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-supervisor-results"
            ),
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_results"
            ),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_supervisor_detail_projection(
    *,
    detail: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    supervisor_record = _project_retention_scheduler_daemon_supervisor_record(
        detail.get("supervisor_record")
    )
    supervisor_events = [
        _project_retention_scheduler_daemon_supervisor_event(event)
        for event in _list_value(detail.get("supervisor_events"))
        if isinstance(event, Mapping)
    ]
    daemon_supervisor_record_id = _text_or_none(
        detail.get("daemon_supervisor_record_id")
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISOR_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon_supervisor_result",
        "daemon_supervisor_record_id": daemon_supervisor_record_id,
        "supervisor_record": supervisor_record,
        "supervisor_event_count": _int_or_zero(
            detail.get("supervisor_event_count")
        ),
        "supervisor_events": supervisor_events,
        "summary": summarize_artifact_retention_daemon_supervisor_detail(
            supervisor_record=supervisor_record,
            supervisor_events=supervisor_events,
        ),
        "source_status": _artifact_retention_daemon_supervisor_source_status(
            source_client=source_client,
            item_count=len(supervisor_events),
            detail_loaded=bool(
                supervisor_record.get("daemon_supervisor_record_id")
            ),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_supervisor_detail_route": (
                "/api/v1/artifact-retention/scheduler-daemon-supervisor-results/"
                f"{daemon_supervisor_record_id or ''}"
            ),
            "ag_daemon_supervisor_detail_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-supervisor-results/"
                f"{daemon_supervisor_record_id or ''}"
            ),
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_detail"
            ),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_supervised_process_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_scheduler_daemon_supervised_process_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": (
            "ae_artifact_retention_scheduler_daemon_process_snapshots"
        ),
        "filter": _project_retention_scheduler_daemon_supervised_process_filter(
            collection.get("filter")
        ),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "items": items,
        "summary": (
            summarize_artifact_retention_daemon_supervised_process_operations(
                items
            )
        ),
        "source_status": _artifact_retention_daemon_supervised_process_source_status(
            source_client=source_client,
            item_count=len(items),
            detail_loaded=False,
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_process_snapshots_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-process-snapshots"
            ),
            "ag_daemon_process_snapshots_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-process-snapshots"
            ),
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_snapshots"
            ),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_supervised_process_detail_projection(
    *,
    detail: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    supervised_process_record = (
        _project_retention_scheduler_daemon_supervised_process_record(
            detail.get("supervised_process_record")
        )
    )
    supervised_process_events = [
        _project_retention_scheduler_daemon_supervised_process_event(event)
        for event in _list_value(detail.get("supervised_process_events"))
        if isinstance(event, Mapping)
    ]
    daemon_supervised_process_record_id = _text_or_none(
        detail.get("daemon_supervised_process_record_id")
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_SUPERVISED_PROCESS_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": (
            "ae_artifact_retention_scheduler_daemon_process_snapshot"
        ),
        "daemon_supervised_process_record_id": (
            daemon_supervised_process_record_id
        ),
        "supervised_process_record": supervised_process_record,
        "supervised_process_event_count": _int_or_zero(
            detail.get("supervised_process_event_count")
        ),
        "supervised_process_events": supervised_process_events,
        "summary": summarize_artifact_retention_daemon_supervised_process_detail(
            supervised_process_record=supervised_process_record,
            supervised_process_events=supervised_process_events,
        ),
        "source_status": _artifact_retention_daemon_supervised_process_source_status(
            source_client=source_client,
            item_count=len(supervised_process_events),
            detail_loaded=bool(
                supervised_process_record.get(
                    "daemon_supervised_process_record_id"
                )
            ),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_daemon_process_detail_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-process-snapshots/"
                f"{daemon_supervised_process_record_id or ''}"
            ),
            "ag_daemon_process_detail_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-process-snapshots/"
                f"{daemon_supervised_process_record_id or ''}"
            ),
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_detail"
            ),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_operator_control_projection(
    *,
    policy: Mapping[str, Any],
    facade: Mapping[str, Any] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_policy = _project_retention_scheduler_daemon_operator_control_policy(
        policy
    )
    projected_facade = _project_retention_scheduler_daemon_operator_control_facade(
        facade
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_scheduler_daemon_operator_control",
        "policy": projected_policy,
        "facade": projected_facade or None,
        "summary": summarize_artifact_retention_daemon_operator_control_projection(
            policy=projected_policy,
            facade=projected_facade,
        ),
        "source_status": _artifact_retention_daemon_operator_control_source_status(
            source_client=source_client,
            policy_loaded=bool(projected_policy.get("operator_control_policy_id")),
            facade_loaded=bool(projected_facade.get("operator_control_facade_id")),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_operator_control_policy_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-policy"
            ),
            "ae_operator_control_preview_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            "ag_operator_control_policy_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-policy"
            ),
            "ag_operator_control_preview_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-preview"
            ),
            "preview_only": True,
            "ag_direct_process_control_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "supervisor_dispatch_performed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_operator_control_execution_collection_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_scheduler_daemon_operator_control_execution_state_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_COLLECTION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": (
            "ae_artifact_retention_scheduler_daemon_operator_control_executions"
        ),
        "filter": _project_retention_scheduler_daemon_operator_control_execution_filter(
            collection.get("filter")
        ),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "items": items,
        "summary": (
            summarize_artifact_retention_daemon_operator_control_execution_operations(
                items
            )
        ),
        "source_status": _artifact_retention_daemon_operator_control_execution_source_status(
            source_client=source_client,
            item_count=len(items),
            detail_loaded=False,
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_operator_control_execution_collection_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-executions"
            ),
            "ag_operator_control_execution_collection_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-executions"
            ),
            "read_model": "ae_daemon_operator_control_execution_states",
            "ag_direct_process_control_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "supervisor_dispatch_performed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_operator_control_execution_detail_projection(
    *,
    detail: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    execution_state = (
        _project_retention_scheduler_daemon_operator_control_execution_state_record(
            detail.get("execution_state")
        )
    )
    transitions = [
        _project_retention_scheduler_daemon_operator_control_execution_transition(
            transition
        )
        for transition in _list_value(detail.get("transitions"))
        if isinstance(transition, Mapping)
    ]
    operator_control_execution_state_id = _text_or_none(
        detail.get("operator_control_execution_state_id")
        or execution_state.get("operator_control_execution_state_id")
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution"
        ),
        "operator_control_execution_state_id": operator_control_execution_state_id,
        "execution_state": execution_state,
        "transition_count": _int_or_zero(detail.get("transition_count")),
        "transitions": transitions,
        "summary": (
            summarize_artifact_retention_daemon_operator_control_execution_detail(
                execution_state=execution_state,
                transitions=transitions,
            )
        ),
        "source_status": _artifact_retention_daemon_operator_control_execution_source_status(
            source_client=source_client,
            item_count=len(transitions),
            detail_loaded=bool(
                execution_state.get("operator_control_execution_state_id")
            ),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_operator_control_execution_detail_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-executions/"
                f"{operator_control_execution_state_id or ''}"
            ),
            "ag_operator_control_execution_detail_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-executions/"
                f"{operator_control_execution_state_id or ''}"
            ),
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_operator_control_execution_detail"
            ),
            "ag_direct_process_control_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "supervisor_dispatch_performed": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_daemon_operator_control_execution_worker_projection(
    *,
    worker_result: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_worker_result = (
        _project_retention_scheduler_daemon_operator_control_execution_worker_result(
            worker_result
        )
    )
    operator_control_execution_state_id = _text_or_none(
        projected_worker_result.get("operator_control_execution_state_id")
    )
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker"
        ),
        "operator_control_execution_state_id": operator_control_execution_state_id,
        "operator_control_execution_worker_result_id": _text_or_none(
            projected_worker_result.get(
                "operator_control_execution_worker_result_id"
            )
        ),
        "worker_result": projected_worker_result,
        "summary": (
            summarize_artifact_retention_daemon_operator_control_execution_worker_result(
                projected_worker_result
            )
        ),
        "source_status": (
            _artifact_retention_daemon_operator_control_execution_worker_source_status(
                source_client=source_client,
                worker_result_loaded=bool(
                    projected_worker_result.get(
                        "operator_control_execution_worker_result_id"
                    )
                ),
                errors=errors,
            )
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_operator_control_execution_worker_route": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
            "ag_operator_control_execution_worker_route": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
            "read_model": "ae_operator_control_execution_worker_result",
            "ag_direct_process_control_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "physical_delete_automation_enabled": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_retention_history_projection(
    *,
    collection: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    items = [
        _project_retention_history_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_retention_history",
        "filter": _project_retention_history_filter(collection.get("filter")),
        "count": _int_or_zero(collection.get("count")),
        "limit": _int_or_zero(collection.get("limit")),
        "next_cursor": _text_or_none(collection.get("next_cursor")),
        "items": items,
        "summary": summarize_artifact_retention_history_operations(items),
        "source_status": _artifact_retention_history_source_status(
            source_client=source_client,
            item_count=len(items),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "raw_execution_payload_available_in_ae": True,
            "physical_delete_confirmation_required": True,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_lifecycle_projection(
    *,
    artifact: Mapping[str, Any],
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_artifact = _project_lifecycle_artifact(artifact)
    actions = _project_lifecycle_actions(projected_artifact)
    errors = source_errors or []
    issues = _artifact_lifecycle_issues(projected_artifact, actions)
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_LIFECYCLE_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors or issues else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact_lifecycle",
        "artifact": projected_artifact,
        "lifecycle": {
            "supported_actions": list(SUPPORTED_ARTIFACT_LIFECYCLE_ACTIONS),
            "default_restore_status": DEFAULT_ARTIFACT_RESTORE_STATUS,
            "metadata_only": True,
            "storage_mutation_allowed": False,
            "physical_delete_allowed": False,
            "actions": actions,
        },
        "summary": summarize_artifact_operation_lifecycle(
            projected_artifact,
            actions,
        ),
        "source_status": _artifact_lifecycle_source_status(
            source_client=source_client,
            artifact_loaded=True,
            errors=errors,
        ),
        "issues": issues,
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def build_artifact_operation_detail_projection(
    *,
    artifact: Mapping[str, Any],
    handoff: Mapping[str, Any] | None = None,
    chat_artifact_refs: list[dict[str, Any]] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_artifact = _project_artifact(artifact)
    projected_handoff = _project_handoff(handoff) if handoff is not None else None
    projected_chat_refs = [
        _project_chat_artifact_ref(ref) for ref in (chat_artifact_refs or [])
    ]
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
        "checked_at": _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "operation_type": "ae_artifact",
        "artifact": projected_artifact,
        "handoff": projected_handoff,
        "chat_artifact_refs": projected_chat_refs,
        "summary": summarize_artifact_operation_detail(
            projected_artifact,
            projected_handoff,
            projected_chat_refs,
        ),
        "source_status": _artifact_source_status(
            source_client=source_client,
            artifact_loaded=True,
            handoff_loaded=projected_handoff is not None,
            chat_artifact_ref_count=len(projected_chat_refs),
            errors=errors,
        ),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    assert_artifact_operation_projection_redacted(projection)
    return projection


def summarize_artifact_operation_lifecycle(
    artifact: Mapping[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    enabled_actions = [
        str(action["action"]) for action in actions if action.get("enabled") is True
    ]
    blocked_actions = [
        str(action["action"]) for action in actions if action.get("enabled") is not True
    ]
    status = _normalized_status(artifact.get("artifact_status"))
    return {
        "artifact_status": status,
        "enabled_action_count": len(enabled_actions),
        "blocked_action_count": len(blocked_actions),
        "enabled_actions": enabled_actions,
        "blocked_actions": blocked_actions,
        "archive_available": "ARCHIVE" in enabled_actions,
        "restore_available": "RESTORE" in enabled_actions,
        "mark_deleted_available": "MARK_DELETED" in enabled_actions,
        "is_hidden_from_active_library": status in {"ARCHIVED", "DELETED"},
        "is_logically_deleted": status == "DELETED",
        "metadata_only": True,
    }


def summarize_artifact_operation_detail(
    artifact: Mapping[str, Any],
    handoff: Mapping[str, Any] | None,
    chat_artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    render_jobs = _list_value(artifact.get("render_jobs"))
    latest_render_job = render_jobs[0] if render_jobs else None
    return {
        "artifact_status": artifact.get("artifact_status"),
        "artifact_type": artifact.get("artifact_type"),
        "version_count": len(_list_value(artifact.get("versions"))),
        "render_job_count": len(render_jobs),
        "file_count": len(_list_value(artifact.get("files"))),
        "link_count": len(_list_value(artifact.get("links"))),
        "source_ref_count": len(_list_value(artifact.get("source_refs"))),
        "chat_artifact_ref_count": len(chat_artifact_refs),
        "handoff_loaded": handoff is not None,
        "latest_render_status": (
            latest_render_job.get("render_status")
            if isinstance(latest_render_job, Mapping)
            else None
        ),
    }


def summarize_artifact_operation_collection(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    downloadable_count = 0
    previewable_count = 0
    latest_updated_at: str | None = None
    for item in items:
        status = item.get("artifact_status")
        if isinstance(status, str) and status:
            status_counts[status] = status_counts.get(status, 0) + 1
        if item.get("downloadable_formats"):
            downloadable_count += 1
        if item.get("previewable_formats"):
            previewable_count += 1
        updated_at = item.get("updated_at")
        if isinstance(updated_at, str) and (
            latest_updated_at is None or updated_at > latest_updated_at
        ):
            latest_updated_at = updated_at
    return {
        "item_count": len(items),
        "ready_count": status_counts.get("READY", 0),
        "draft_count": status_counts.get("DRAFT", 0),
        "failed_count": status_counts.get("FAILED", 0),
        "downloadable_count": downloadable_count,
        "previewable_count": previewable_count,
        "status_counts": status_counts,
        "latest_updated_at": latest_updated_at,
    }


def summarize_artifact_retention_batch_operations(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    estimated_deleted_counts = plan.get("estimated_deleted_counts")
    if not isinstance(estimated_deleted_counts, Mapping):
        estimated_deleted_counts = {}
    plan_status = _normalized_retention_batch_status(plan.get("plan_status"))
    scheduler_status = _text_or_none(plan.get("scheduler_status"))
    selected_count = _int_or_zero(plan.get("selected_count"))
    return {
        "plan_status": plan_status,
        "scheduler_status": scheduler_status,
        "candidate_count": _int_or_zero(plan.get("candidate_count")),
        "selected_count": selected_count,
        "unselected_count": _int_or_zero(plan.get("unselected_count")),
        "estimated_deleted_artifacts": _int_or_zero(
            estimated_deleted_counts.get("artifacts")
        ),
        "estimated_deleted_storage_files": _int_or_zero(
            estimated_deleted_counts.get("storage_files")
        ),
        "operator_attention_required": plan_status == "READY",
        "dispatch_available": (
            plan_status == "READY"
            and plan.get("mode") == "DRY_RUN"
            and selected_count > 0
        ),
        "latest_checked_at": _text_or_none(plan.get("checked_at")),
    }


def summarize_artifact_retention_scheduled_job_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    latest_updated_at: str | None = None
    selected_artifact_count = 0
    estimated_deleted_artifacts = 0
    estimated_deleted_storage_files = 0
    retryable_failed_count = 0
    dry_run_job_count = 0
    for item in items:
        status = _normalized_job_status(item.get("status"))
        if status is not None:
            status_counts[status] = status_counts.get(status, 0) + 1
        if status == "FAILED" and item.get("retryable") is True:
            retryable_failed_count += 1

        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if payload.get("execution_mode") == "DRY_RUN":
            dry_run_job_count += 1
        selected_artifact_count += _int_or_zero(payload.get("selected_count"))
        deleted_counts = payload.get("estimated_deleted_counts")
        if not isinstance(deleted_counts, Mapping):
            deleted_counts = {}
        estimated_deleted_artifacts += _int_or_zero(deleted_counts.get("artifacts"))
        estimated_deleted_storage_files += _int_or_zero(
            deleted_counts.get("storage_files")
        )

        updated_at = _text_or_none(item.get("updated_at"))
        if updated_at is not None and (
            latest_updated_at is None or updated_at > latest_updated_at
        ):
            latest_updated_at = updated_at

    active_count = sum(status_counts.get(status, 0) for status in ACTIVE_JOB_STATUSES)
    failed_count = status_counts.get("FAILED", 0)
    return {
        "job_count": len(items),
        "active_count": active_count,
        "queued_count": status_counts.get("QUEUED", 0),
        "running_count": status_counts.get("RUNNING", 0),
        "terminal_count": sum(
            status_counts.get(status, 0) for status in TERMINAL_JOB_STATUSES
        ),
        "failed_count": failed_count,
        "retryable_failed_count": retryable_failed_count,
        "dry_run_job_count": dry_run_job_count,
        "selected_artifact_count": selected_artifact_count,
        "estimated_deleted_artifacts": estimated_deleted_artifacts,
        "estimated_deleted_storage_files": estimated_deleted_storage_files,
        "operator_attention_required": active_count > 0 or failed_count > 0,
        "latest_updated_at": latest_updated_at,
    }


def summarize_artifact_retention_scheduled_dispatch(
    *,
    batch_plan: Mapping[str, Any],
    dispatch_response: Mapping[str, Any],
) -> dict[str, Any]:
    plan_summary = summarize_artifact_retention_batch_operations(batch_plan)
    job = dispatch_response.get("enqueued_job")
    if not isinstance(job, Mapping):
        job = {}
    return {
        "dispatch_available": plan_summary["dispatch_available"],
        "enqueue_status": _text_or_none(dispatch_response.get("enqueue_status")),
        "job_enqueued": dispatch_response.get("job_enqueued") is True,
        "duplicate_returned": dispatch_response.get("duplicate_returned") is True,
        "job_id": _text_or_none(dispatch_response.get("job_id")),
        "job_status": _normalized_job_status(job.get("status")),
        "command_id": _text_or_none(dispatch_response.get("command_id")),
        "source_plan_id": _text_or_none(batch_plan.get("plan_id")),
        "trigger_type": _text_or_none(dispatch_response.get("trigger_type")),
        "selected_count": plan_summary["selected_count"],
        "estimated_deleted_artifacts": plan_summary["estimated_deleted_artifacts"],
        "estimated_deleted_storage_files": (
            plan_summary["estimated_deleted_storage_files"]
        ),
        "dry_run_required": True,
        "physical_delete_automation_enabled": False,
    }


def build_artifact_retention_daemon_lifecycle_projection(
    *,
    daemon_config: Mapping[str, Any],
    daemon_runtime: Mapping[str, Any] | None = None,
    dispatch_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    projected_config = _project_retention_scheduler_daemon_config(daemon_config)
    projected_runtime = _normalize_retention_scheduler_daemon_runtime_observation(
        daemon_runtime
    )
    projected_dispatch = _project_retention_scheduler_daemon_dispatch_response(
        dispatch_response
    )
    runtime_state = _mapping_or_empty(projected_runtime.get("runtime_state"))
    heartbeat = _mapping_or_empty(projected_runtime.get("heartbeat"))
    bounded_loop_result = _mapping_or_empty(
        projected_runtime.get("bounded_loop_result")
    )
    shutdown_transition = _mapping_or_empty(
        projected_runtime.get("shutdown_transition")
    )
    retry_circuit_guard = _mapping_or_empty(
        projected_runtime.get("retry_circuit_guard")
    )
    lifecycle_status, lifecycle_source = _daemon_lifecycle_status_and_source(
        daemon_config=projected_config,
        runtime_state=runtime_state,
        heartbeat=heartbeat,
    )
    lifecycle_reason = _daemon_lifecycle_reason(
        lifecycle_status=lifecycle_status,
        lifecycle_source=lifecycle_source,
        daemon_config=projected_config,
        runtime_state=runtime_state,
        heartbeat=heartbeat,
    )
    lifecycle_attention = _daemon_lifecycle_attention(
        lifecycle_status=lifecycle_status,
        lifecycle_reason=lifecycle_reason,
        bounded_loop_result=bounded_loop_result,
        shutdown_transition=shutdown_transition,
        retry_circuit_guard=retry_circuit_guard,
    )
    runtime_last_cycle = _mapping_or_empty(runtime_state.get("last_cycle"))
    control_plan = _mapping_or_empty(projected_dispatch.get("control_plan"))
    projection = {
        "lifecycle_projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_LIFECYCLE_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": (
            "READY" if projected_config.get("scheduler_id") else "NO_DAEMON_CONFIG"
        ),
        "checked_at": _latest_timestamp_text(
            _text_or_none(projected_runtime.get("checked_at")),
            _text_or_none(projected_config.get("checked_at")),
        )
        or _utc_now(),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": _text_or_none(projected_config.get("scheduler_id")),
        "lifecycle": {
            "status": lifecycle_status,
            "reason": lifecycle_reason,
            "source": lifecycle_source,
            "stop_requested": runtime_state.get("stop_requested") is True,
            "shutdown_requested_at": _text_or_none(
                runtime_state.get("shutdown_requested_at")
            ),
            "runtime_state_observed": bool(runtime_state),
            "heartbeat_observed": bool(heartbeat),
            "heartbeat_status": _text_or_none(heartbeat.get("status")),
            "heartbeat_worker_id": _text_or_none(heartbeat.get("worker_id")),
            "last_cycle_status": _text_or_none(runtime_last_cycle.get("result_status")),
            "next_tick_at": _text_or_none(runtime_state.get("next_tick_at")),
            "cycle_count": _int_or_zero(runtime_state.get("cycle_count")),
            "consecutive_failure_count": _int_or_zero(
                runtime_state.get("consecutive_failure_count")
            ),
        },
        "bounded_loop": {
            "result_status": _text_or_none(bounded_loop_result.get("result_status")),
            "stop_reason": _text_or_none(bounded_loop_result.get("stop_reason")),
            "cycle_count": _int_or_zero(bounded_loop_result.get("cycle_count")),
            "consecutive_failure_count": _int_or_zero(
                bounded_loop_result.get("consecutive_failure_count")
            ),
        },
        "shutdown_transition": {
            "decision_status": _text_or_none(
                shutdown_transition.get("decision_status")
            ),
            "decision_reason": _text_or_none(
                shutdown_transition.get("decision_reason")
            ),
            "requested_at": _text_or_none(shutdown_transition.get("requested_at")),
        },
        "retry_circuit_guard": {
            "decision_status": _text_or_none(
                retry_circuit_guard.get("decision_status")
            ),
            "decision_reason": _text_or_none(
                retry_circuit_guard.get("decision_reason")
            ),
            "retry_allowed": retry_circuit_guard.get("retry_allowed") is True,
            "next_retry_at": _text_or_none(retry_circuit_guard.get("next_retry_at")),
            "failure_threshold": _int_or_zero(
                retry_circuit_guard.get("failure_threshold")
            ),
        },
        "last_control_action": _text_or_none(control_plan.get("action")),
        "attention": lifecycle_attention,
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "review_runtime_state_in_ae": bool(runtime_state),
            "review_heartbeat_when_runtime_state_missing": not bool(runtime_state),
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
        "guardrails": {
            "metadata_only": True,
            "safe_for_ag_projection": True,
            "daemon_process_owner_ae": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_daemon_process_control_allowed": False,
        },
        "metadata": {
            "metadata_only": True,
            "runtime_state_observed": bool(runtime_state),
            "heartbeat_observed": bool(heartbeat),
            "bounded_loop_observed": bool(bounded_loop_result),
            "shutdown_transition_observed": bool(shutdown_transition),
            "retry_circuit_guard_observed": bool(retry_circuit_guard),
        },
    }
    assert_artifact_operation_projection_redacted(projection)
    return projection


def summarize_artifact_retention_daemon_lifecycle_projection(
    *,
    daemon_config: Mapping[str, Any],
    daemon_runtime: Mapping[str, Any] | None = None,
    dispatch_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    projection = build_artifact_retention_daemon_lifecycle_projection(
        daemon_config=daemon_config,
        daemon_runtime=daemon_runtime,
        dispatch_response=dispatch_response,
    )
    lifecycle = _mapping_or_empty(projection.get("lifecycle"))
    bounded_loop = _mapping_or_empty(projection.get("bounded_loop"))
    shutdown_transition = _mapping_or_empty(projection.get("shutdown_transition"))
    retry_circuit_guard = _mapping_or_empty(projection.get("retry_circuit_guard"))
    attention = _mapping_or_empty(projection.get("attention"))
    return {
        "lifecycle_status": _text_or_none(lifecycle.get("status")),
        "lifecycle_reason": _text_or_none(lifecycle.get("reason")),
        "lifecycle_source": _text_or_none(lifecycle.get("source")),
        "stop_requested": lifecycle.get("stop_requested") is True,
        "shutdown_requested_at": _text_or_none(
            lifecycle.get("shutdown_requested_at")
        ),
        "runtime_state_observed": lifecycle.get("runtime_state_observed") is True,
        "heartbeat_observed": lifecycle.get("heartbeat_observed") is True,
        "heartbeat_status": _text_or_none(lifecycle.get("heartbeat_status")),
        "last_cycle_status": _text_or_none(lifecycle.get("last_cycle_status")),
        "consecutive_failure_count": _int_or_zero(
            lifecycle.get("consecutive_failure_count")
        ),
        "bounded_loop_result_status": _text_or_none(
            bounded_loop.get("result_status")
        ),
        "bounded_loop_stop_reason": _text_or_none(bounded_loop.get("stop_reason")),
        "shutdown_transition_status": _text_or_none(
            shutdown_transition.get("decision_status")
        ),
        "shutdown_transition_reason": _text_or_none(
            shutdown_transition.get("decision_reason")
        ),
        "retry_circuit_status": _text_or_none(
            retry_circuit_guard.get("decision_status")
        ),
        "retry_circuit_reason": _text_or_none(
            retry_circuit_guard.get("decision_reason")
        ),
        "retry_allowed": retry_circuit_guard.get("retry_allowed") is True,
        "attention_status": _text_or_none(attention.get("attention_status")),
        "attention_level": _text_or_none(attention.get("attention_level")),
        "operator_attention_required": (
            attention.get("operator_attention_required") is True
        ),
        "operator_action": _text_or_none(attention.get("operator_action")),
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_operations(
    *,
    daemon_config: Mapping[str, Any],
    daemon_runtime: Mapping[str, Any] | None = None,
    dispatch_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = _mapping_or_empty(daemon_config.get("runtime"))
    runtime_observation = _mapping_or_empty(daemon_runtime)
    runtime_heartbeat = _mapping_or_empty(runtime_observation.get("heartbeat"))
    heartbeat_store = _mapping_or_empty(
        runtime_observation.get("heartbeat_store")
    )
    runtime_metadata = _mapping_or_empty(runtime_observation.get("metadata"))
    lease_repository = _mapping_or_empty(daemon_config.get("lease_repository"))
    manual_action = _daemon_action_item(daemon_config, "manual_tick_once")
    start_action = _daemon_action_item(daemon_config, "start_daemon")
    dispatch = _mapping_or_empty(dispatch_response)
    dispatch_metadata = _mapping_or_empty(dispatch.get("metadata"))
    control_plan = _mapping_or_empty(dispatch.get("control_plan"))
    runtime_issue_candidates = build_artifact_retention_daemon_runtime_issue_candidates(
        daemon_runtime=runtime_observation,
    )
    manual_status = _text_or_none(manual_action.get("decision_status"))
    start_status = _text_or_none(start_action.get("decision_status"))
    attention = classify_artifact_retention_daemon_attention(
        daemon_config=daemon_config,
        daemon_runtime=runtime_observation,
        dispatch_response=dispatch_response,
    )
    lifecycle_summary = summarize_artifact_retention_daemon_lifecycle_projection(
        daemon_config=daemon_config,
        daemon_runtime=runtime_observation,
        dispatch_response=dispatch_response,
    )
    return {
        "scheduler_id": _text_or_none(daemon_config.get("scheduler_id")),
        "scheduler_daemon_enabled": runtime.get("scheduler_daemon_enabled") is True,
        "scheduler_daemon_started": runtime.get("scheduler_daemon_started") is True,
        "continuous_loop_started": runtime.get("continuous_loop_started") is True,
        "manual_tick_once_decision_status": manual_status,
        "manual_tick_once_block_reason": _text_or_none(
            manual_action.get("block_reason")
        ),
        "manual_tick_once_available": manual_status == "READY",
        "start_daemon_decision_status": start_status,
        "start_daemon_block_reason": _text_or_none(start_action.get("block_reason")),
        "start_daemon_available": start_status == "READY",
        "lease_repository_available": lease_repository.get("available") is True,
        "lease_repository_backend": _text_or_none(lease_repository.get("backend")),
        "job_queue_available": runtime.get("job_queue_available") is True,
        "job_queue_backend": _text_or_none(runtime.get("job_queue_backend")),
        "default_execution_mode": _text_or_none(runtime.get("default_execution_mode")),
        "last_dispatch_status": _text_or_none(dispatch.get("dispatch_status")),
        "last_dispatch_action": _text_or_none(control_plan.get("action")),
        "last_dispatch_job_enqueued": dispatch_metadata.get("job_enqueued") is True,
        "last_dispatch_tick_once_dispatched": (
            dispatch_metadata.get("tick_once_dispatched") is True
        ),
        "runtime_observation_available": bool(runtime_observation),
        "runtime_heartbeat_store_available": (
            heartbeat_store.get("available") is True
        ),
        "runtime_heartbeat_observed": (
            runtime_metadata.get("heartbeat_observed") is True
        ),
        "runtime_heartbeat_status": _text_or_none(runtime_heartbeat.get("status")),
        "runtime_heartbeat_worker_id": _text_or_none(
            runtime_heartbeat.get("worker_id")
        ),
        "runtime_heartbeat_active_job_id": _text_or_none(
            runtime_heartbeat.get("active_job_id")
        ),
        "runtime_heartbeat_last_seen_at": _text_or_none(
            runtime_heartbeat.get("last_seen_at")
        ),
        "lifecycle_status": lifecycle_summary["lifecycle_status"],
        "lifecycle_reason": lifecycle_summary["lifecycle_reason"],
        "lifecycle_source": lifecycle_summary["lifecycle_source"],
        "lifecycle_attention_status": lifecycle_summary["attention_status"],
        "lifecycle_attention_level": lifecycle_summary["attention_level"],
        "lifecycle_operator_attention_required": lifecycle_summary[
            "operator_attention_required"
        ],
        "bounded_loop_result_status": lifecycle_summary[
            "bounded_loop_result_status"
        ],
        "shutdown_transition_status": lifecycle_summary[
            "shutdown_transition_status"
        ],
        "retry_circuit_status": lifecycle_summary["retry_circuit_status"],
        "retry_allowed": lifecycle_summary["retry_allowed"],
        "runtime_issue_candidate_count": len(runtime_issue_candidates),
        "attention_status": attention["attention_status"],
        "attention_level": attention["attention_level"],
        "attention_reason_codes": attention["reason_codes"],
        "attention_operator_actions": attention["operator_actions"],
        "batch_window_enforced": attention["batch_window_enforced"],
        "operator_attention_required": attention["operator_attention_required"],
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_run_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    result_counts: dict[str, int] = {}
    latest_completed_at: str | None = None
    job_enqueued_count = 0
    worker_executed_count = 0
    worker_requested_count = 0
    for item in items:
        result_status = _normalized_daemon_result_status(item.get("result_status"))
        if result_status is not None:
            result_counts[result_status] = result_counts.get(result_status, 0) + 1
        if item.get("job_enqueued") is True:
            job_enqueued_count += 1
        if item.get("worker_executed") is True:
            worker_executed_count += 1
        if item.get("worker_requested") is True:
            worker_requested_count += 1
        completed_at = _text_or_none(item.get("completed_at"))
        if completed_at is not None and (
            latest_completed_at is None or completed_at > latest_completed_at
        ):
            latest_completed_at = completed_at
    failed_count = result_counts.get("FAILED", 0)
    return {
        "run_count": len(items),
        "result_counts": result_counts,
        "succeeded_count": result_counts.get("SUCCEEDED", 0),
        "failed_count": failed_count,
        "stopped_count": result_counts.get("STOPPED", 0),
        "skipped_count": result_counts.get("SKIPPED", 0),
        "job_enqueued_count": job_enqueued_count,
        "worker_requested_count": worker_requested_count,
        "worker_executed_count": worker_executed_count,
        "operator_attention_required": failed_count > 0,
        "latest_completed_at": latest_completed_at,
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_run_detail(
    *,
    run_record: Mapping[str, Any],
    lifecycle_events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_types = [
        str(event["event_type"])
        for event in lifecycle_events
        if _text_or_none(event.get("event_type"))
    ]
    result_status = _normalized_daemon_result_status(
        run_record.get("result_status")
    )
    return {
        "daemon_run_record_id": _text_or_none(
            run_record.get("daemon_run_record_id")
        ),
        "scheduler_id": _text_or_none(run_record.get("scheduler_id")),
        "run_status": _normalized_daemon_run_status(run_record.get("run_status")),
        "result_status": result_status,
        "stop_reason": _text_or_none(run_record.get("stop_reason")),
        "cycle_count": _int_or_zero(run_record.get("cycle_count")),
        "max_cycles": _int_or_zero(run_record.get("max_cycles")),
        "worker_requested": run_record.get("worker_requested") is True,
        "job_enqueued": run_record.get("job_enqueued") is True,
        "worker_executed": run_record.get("worker_executed") is True,
        "lifecycle_event_count": len(lifecycle_events),
        "lifecycle_event_types": event_types,
        "started_at": _text_or_none(run_record.get("started_at")),
        "completed_at": _text_or_none(run_record.get("completed_at")),
        "operator_attention_required": result_status == "FAILED",
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_supervisor_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    latest_observed_at: str | None = None
    blocked_count = 0
    failed_count = 0
    adapter_invoked_count = 0
    for item in items:
        action = _normalized_daemon_supervisor_action(item.get("action"))
        result_status = _normalized_daemon_supervisor_result_status(
            item.get("result_status")
        )
        if action is not None:
            action_counts[action] = action_counts.get(action, 0) + 1
        if result_status is not None:
            result_counts[result_status] = result_counts.get(result_status, 0) + 1
        if result_status == "BLOCKED":
            blocked_count += 1
        if result_status == "FAILED":
            failed_count += 1
        if item.get("supervisor_adapter_invoked") is True:
            adapter_invoked_count += 1
        observed_at = _text_or_none(item.get("observed_at"))
        if observed_at is not None and (
            latest_observed_at is None or observed_at > latest_observed_at
        ):
            latest_observed_at = observed_at
    return {
        "supervisor_record_count": len(items),
        "action_counts": action_counts,
        "result_counts": result_counts,
        "ready_count": result_counts.get("READY", 0),
        "blocked_count": blocked_count,
        "noop_count": result_counts.get("NOOP", 0),
        "failed_count": failed_count,
        "adapter_invoked_count": adapter_invoked_count,
        "operator_attention_required": failed_count > 0,
        "latest_observed_at": latest_observed_at,
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_supervisor_detail(
    *,
    supervisor_record: Mapping[str, Any],
    supervisor_events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_types = [
        str(event["event_type"])
        for event in supervisor_events
        if _text_or_none(event.get("event_type"))
    ]
    result_status = _normalized_daemon_supervisor_result_status(
        supervisor_record.get("result_status")
    )
    return {
        "daemon_supervisor_record_id": _text_or_none(
            supervisor_record.get("daemon_supervisor_record_id")
        ),
        "scheduler_id": _text_or_none(supervisor_record.get("scheduler_id")),
        "action": _normalized_daemon_supervisor_action(
            supervisor_record.get("action")
        ),
        "result_status": result_status,
        "decision_reason": _text_or_none(supervisor_record.get("decision_reason")),
        "runtime_ready": supervisor_record.get("runtime_ready") is True,
        "supervisor_adapter_available": (
            supervisor_record.get("supervisor_adapter_available") is True
        ),
        "supervisor_adapter_invoked": (
            supervisor_record.get("supervisor_adapter_invoked") is True
        ),
        "process_started": supervisor_record.get("process_started") is True,
        "process_stopped": supervisor_record.get("process_stopped") is True,
        "supervisor_event_count": len(supervisor_events),
        "supervisor_event_types": event_types,
        "observed_at": _text_or_none(supervisor_record.get("observed_at")),
        "operator_attention_required": result_status == "FAILED",
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_supervised_process_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    process_status_counts: dict[str, int] = {}
    latest_observed_at: str | None = None
    running_count = 0
    failed_count = 0
    stale_count = 0
    blocked_count = 0
    adapter_required_count = 0
    for item in items:
        action = _normalized_daemon_supervisor_action(item.get("action"))
        process_status = _normalized_daemon_supervised_process_status(
            item.get("process_status")
        )
        if action is not None:
            action_counts[action] = action_counts.get(action, 0) + 1
        if process_status is not None:
            process_status_counts[process_status] = (
                process_status_counts.get(process_status, 0) + 1
            )
        if process_status == "RUNNING":
            running_count += 1
        if process_status == "FAILED":
            failed_count += 1
        if process_status == "STALE":
            stale_count += 1
        if process_status == "BLOCKED":
            blocked_count += 1
        if item.get("subprocess_adapter_required") is True:
            adapter_required_count += 1
        observed_at = _text_or_none(item.get("observed_at"))
        if observed_at is not None and (
            latest_observed_at is None or observed_at > latest_observed_at
        ):
            latest_observed_at = observed_at
    return {
        "supervised_process_record_count": len(items),
        "action_counts": action_counts,
        "process_status_counts": process_status_counts,
        "running_count": running_count,
        "failed_count": failed_count,
        "stale_count": stale_count,
        "blocked_count": blocked_count,
        "adapter_required_count": adapter_required_count,
        "operator_attention_required": (
            failed_count > 0 or stale_count > 0 or blocked_count > 0
        ),
        "latest_observed_at": latest_observed_at,
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_supervised_process_detail(
    *,
    supervised_process_record: Mapping[str, Any],
    supervised_process_events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_types = [
        str(event["event_type"])
        for event in supervised_process_events
        if _text_or_none(event.get("event_type"))
    ]
    process_status = _normalized_daemon_supervised_process_status(
        supervised_process_record.get("process_status")
    )
    return {
        "daemon_supervised_process_record_id": _text_or_none(
            supervised_process_record.get("daemon_supervised_process_record_id")
        ),
        "scheduler_id": _text_or_none(
            supervised_process_record.get("scheduler_id")
        ),
        "action": _normalized_daemon_supervisor_action(
            supervised_process_record.get("action")
        ),
        "process_status": process_status,
        "daemon_supervised_process_id": _text_or_none(
            supervised_process_record.get("daemon_supervised_process_id")
        ),
        "process_id": _int_or_zero(supervised_process_record.get("process_id")),
        "host_id": _text_or_none(supervised_process_record.get("host_id")),
        "process_running": supervised_process_record.get("process_running") is True,
        "process_started_observed": (
            supervised_process_record.get("process_started_observed") is True
        ),
        "process_stopped_observed": (
            supervised_process_record.get("process_stopped_observed") is True
        ),
        "subprocess_adapter_required": (
            supervised_process_record.get("subprocess_adapter_required") is True
        ),
        "supervised_process_event_count": len(supervised_process_events),
        "supervised_process_event_types": event_types,
        "observed_at": _text_or_none(
            supervised_process_record.get("observed_at")
        ),
        "operator_attention_required": process_status
        in {"FAILED", "STALE", "BLOCKED"},
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_operator_control_projection(
    *,
    policy: Mapping[str, Any],
    facade: Mapping[str, Any],
) -> dict[str, Any]:
    supported_actions = [
        item
        for item in _list_value(policy.get("supported_actions"))
        if isinstance(item, Mapping)
    ]
    mutating_actions = [
        item for item in supported_actions if item.get("mutates_process") is True
    ]
    command_preview = _mapping_or_empty(
        facade.get("operator_control_command_preview")
    )
    command_metadata = _mapping_or_empty(command_preview.get("metadata"))
    facade_status = _normalized_operator_control_admission_status(
        facade.get("facade_status")
    )
    supervisor_actions = _text_list(command_metadata.get("supervisor_actions"))
    return {
        "policy_loaded": bool(policy.get("operator_control_policy_id")),
        "facade_loaded": bool(facade.get("operator_control_facade_id")),
        "scheduler_id": _text_or_none(
            facade.get("scheduler_id") or policy.get("scheduler_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            facade.get("action")
        ),
        "facade_status": facade_status,
        "ready_for_dispatch": command_metadata.get("ready_for_dispatch") is True,
        "command_preview_count": _int_or_zero(
            command_metadata.get("command_preview_count")
        ),
        "supervisor_actions": supervisor_actions,
        "supported_action_count": len(supported_actions),
        "mutating_action_count": len(mutating_actions),
        "restart_supported": any(
            _normalized_daemon_operator_control_action(item.get("action"))
            == "restart_daemon"
            for item in supported_actions
        ),
        "preview_only": True,
        "operator_attention_required": facade_status == "BLOCKED",
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_operator_control_execution_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    execution_status_counts: dict[str, int] = {}
    idempotency_status_counts: dict[str, int] = {}
    latest_observed_at: str | None = None
    admitted_count = 0
    executing_count = 0
    succeeded_count = 0
    failed_count = 0
    blocked_count = 0
    noop_count = 0
    replayed_count = 0
    conflict_count = 0
    for item in items:
        action = _normalized_daemon_operator_control_action(item.get("action"))
        execution_status = _normalized_operator_control_execution_status(
            item.get("execution_status")
        )
        idempotency_status = _normalized_operator_control_idempotency_status(
            item.get("idempotency_status")
        )
        if action is not None:
            action_counts[action] = action_counts.get(action, 0) + 1
        if execution_status is not None:
            execution_status_counts[execution_status] = (
                execution_status_counts.get(execution_status, 0) + 1
            )
        if idempotency_status is not None:
            idempotency_status_counts[idempotency_status] = (
                idempotency_status_counts.get(idempotency_status, 0) + 1
            )
        if execution_status == "ADMITTED":
            admitted_count += 1
        if execution_status == "EXECUTING":
            executing_count += 1
        if execution_status == "SUCCEEDED":
            succeeded_count += 1
        if execution_status == "FAILED":
            failed_count += 1
        if execution_status == "BLOCKED":
            blocked_count += 1
        if execution_status == "NOOP":
            noop_count += 1
        if idempotency_status == "REPLAYED":
            replayed_count += 1
        if idempotency_status == "CONFLICT":
            conflict_count += 1
        observed_at = _text_or_none(item.get("observed_at"))
        if observed_at is not None and (
            latest_observed_at is None or observed_at > latest_observed_at
        ):
            latest_observed_at = observed_at
    return {
        "operator_control_execution_state_count": len(items),
        "action_counts": action_counts,
        "execution_status_counts": execution_status_counts,
        "idempotency_status_counts": idempotency_status_counts,
        "admitted_count": admitted_count,
        "executing_count": executing_count,
        "succeeded_count": succeeded_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
        "noop_count": noop_count,
        "replayed_count": replayed_count,
        "conflict_count": conflict_count,
        "operator_attention_required": (
            failed_count > 0 or blocked_count > 0 or conflict_count > 0
        ),
        "latest_observed_at": latest_observed_at,
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_operator_control_execution_detail(
    *,
    execution_state: Mapping[str, Any],
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    execution_status = _normalized_operator_control_execution_status(
        execution_state.get("execution_status")
    )
    idempotency_status = _normalized_operator_control_idempotency_status(
        execution_state.get("idempotency_status")
    )
    latest_transitioned_at: str | None = None
    transition_statuses = []
    for transition in transitions:
        from_status = _normalized_operator_control_execution_status(
            transition.get("from_status")
        )
        to_status = _normalized_operator_control_execution_status(
            transition.get("to_status")
        )
        if from_status is not None and to_status is not None:
            transition_statuses.append(f"{from_status}->{to_status}")
        transitioned_at = _text_or_none(transition.get("transitioned_at"))
        if transitioned_at is not None and (
            latest_transitioned_at is None
            or transitioned_at > latest_transitioned_at
        ):
            latest_transitioned_at = transitioned_at
    terminal = execution_status in {"SUCCEEDED", "FAILED", "BLOCKED", "NOOP"}
    return {
        "operator_control_execution_state_id": _text_or_none(
            execution_state.get("operator_control_execution_state_id")
        ),
        "scheduler_id": _text_or_none(execution_state.get("scheduler_id")),
        "action": _normalized_daemon_operator_control_action(
            execution_state.get("action")
        ),
        "execution_mode": _text_or_none(execution_state.get("execution_mode")),
        "execution_status": execution_status,
        "idempotency_status": idempotency_status,
        "decision_reason": _text_or_none(execution_state.get("decision_reason")),
        "transition_count": len(transitions),
        "transition_statuses": transition_statuses,
        "latest_transitioned_at": latest_transitioned_at,
        "terminal_state": terminal,
        "operator_attention_required": (
            execution_status in {"FAILED", "BLOCKED"}
            or idempotency_status == "CONFLICT"
        ),
        "metadata_only": True,
    }


def summarize_artifact_retention_daemon_operator_control_execution_worker_result(
    worker_result: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _mapping_or_empty(worker_result.get("metadata"))
    guardrails = _mapping_or_empty(worker_result.get("guardrails"))
    worker_status = _normalized_operator_control_execution_worker_status(
        worker_result.get("worker_status")
    )
    supervisor_result_statuses = _normalized_daemon_supervisor_result_statuses(
        worker_result.get("supervisor_result_statuses")
    )
    transition_terminal_status = _normalized_operator_control_execution_status(
        worker_result.get("transition_terminal_status")
    )
    failed_supervisor_count = sum(
        1 for status in supervisor_result_statuses if status == "FAILED"
    )
    return {
        "operator_control_execution_worker_result_id": _text_or_none(
            worker_result.get("operator_control_execution_worker_result_id")
        ),
        "operator_control_execution_state_id": _text_or_none(
            worker_result.get("operator_control_execution_state_id")
        ),
        "scheduler_id": _text_or_none(worker_result.get("scheduler_id")),
        "action": _normalized_daemon_operator_control_action(
            worker_result.get("action")
        ),
        "execution_mode": _text_or_none(worker_result.get("execution_mode")),
        "worker_mode": _text_or_none(worker_result.get("worker_mode")),
        "worker_status": worker_status,
        "decision_reason": _text_or_none(worker_result.get("decision_reason")),
        "transition_terminal_status": transition_terminal_status,
        "transition_count": _int_or_zero(worker_result.get("transition_count")),
        "status_path": _normalized_operator_control_execution_statuses(
            worker_result.get("status_path")
        ),
        "supervisor_result_count": _int_or_zero(
            worker_result.get("supervisor_result_count")
        ),
        "supervisor_result_statuses": supervisor_result_statuses,
        "failed_supervisor_count": failed_supervisor_count,
        "worker_execution_performed": (
            metadata.get("worker_execution_performed") is True
            or guardrails.get("worker_execution_performed") is True
        ),
        "supervisor_adapter_invoked": (
            metadata.get("supervisor_adapter_invoked") is True
            or guardrails.get("supervisor_adapter_invoked") is True
        ),
        "subprocess_started": (
            metadata.get("subprocess_started") is True
            or guardrails.get("subprocess_started") is True
        ),
        "subprocess_stopped": (
            metadata.get("subprocess_stopped") is True
            or guardrails.get("subprocess_stopped") is True
        ),
        "database_write_performed": (
            metadata.get("database_write_performed") is True
            or guardrails.get("database_write_performed") is True
        ),
        "transition_persistence_performed": (
            metadata.get("transition_persistence_performed") is True
            or guardrails.get("transition_persistence_performed") is True
        ),
        "operator_attention_required": (
            worker_status in {"FAILED", "BLOCKED"} or failed_supervisor_count > 0
        ),
        "metadata_only": True,
    }


def classify_artifact_retention_daemon_attention(
    *,
    daemon_config: Mapping[str, Any],
    daemon_runtime: Mapping[str, Any] | None = None,
    dispatch_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    projected_config = _project_retention_scheduler_daemon_config(daemon_config)
    projected_runtime = _project_retention_scheduler_daemon_runtime_observation(
        daemon_runtime
    )
    projected_dispatch = (
        _project_retention_scheduler_daemon_dispatch_response(dispatch_response)
        if isinstance(dispatch_response, Mapping) and bool(dispatch_response)
        else {}
    )
    scheduler_id = _text_or_none(projected_config.get("scheduler_id"))
    if scheduler_id is None:
        return {
            "attention_schema_version": (
                AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION
            ),
            "attention_status": "NO_DAEMON_CONFIG",
            "attention_level": "INFO",
            "reason_codes": ["daemon_config_missing"],
            "operator_actions": ["load_ae_scheduler_daemon_config"],
            "operator_attention_required": False,
            "manual_tick_once_safe": False,
            "start_daemon_blocked_by_policy": False,
            "continuous_loop_blocked_by_policy": False,
            "batch_window_enforced": False,
            "metadata_only": True,
        }

    runtime = _mapping_or_empty(projected_config.get("runtime"))
    lease_repository = _mapping_or_empty(projected_config.get("lease_repository"))
    manual_action = _daemon_action_item(projected_config, "manual_tick_once")
    start_action = _daemon_action_item(projected_config, "start_daemon")
    manual_status = _text_or_none(manual_action.get("decision_status"))
    manual_block_reason = _text_or_none(manual_action.get("block_reason"))
    start_block_reason = _text_or_none(start_action.get("block_reason"))
    dispatch_status = _text_or_none(projected_dispatch.get("dispatch_status"))
    dispatch = bool(projected_dispatch)
    lease_available = lease_repository.get("available") is True
    job_queue_available = runtime.get("job_queue_available") is True
    batch_window_enforced = runtime.get("scheduler_tick_batch_window_enforced") is True
    manual_tick_once_safe = manual_status == "READY" and lease_available and job_queue_available
    start_daemon_blocked_by_policy = start_block_reason == "daemon_disabled_by_policy"
    continuous_loop_blocked_by_policy = (
        runtime.get("continuous_loop_enabled") is not True
        and runtime.get("continuous_loop_started") is not True
    )
    runtime_signals = _retention_daemon_runtime_issue_signals(projected_runtime)
    runtime_signal = runtime_signals[0] if runtime_signals else None

    attention_status = "READY"
    attention_level = "OK"
    operator_attention_required = False
    reason_codes: list[str] = ["manual_tick_once_ready"]
    operator_actions: list[str] = ["manual_tick_once_available"]

    if dispatch:
        attention_status = "DISPATCH_ATTENTION"
        attention_level = "WARN" if dispatch_status in {"BLOCKED", "FAILED"} else "INFO"
        operator_attention_required = True
        reason_codes = ["last_dispatch_observed"]
        if dispatch_status == "BLOCKED":
            reason_codes.append("last_dispatch_blocked")
        elif dispatch_status == "FAILED":
            reason_codes.append("last_dispatch_failed")
        elif dispatch_status == "DISPATCHED":
            reason_codes.append("last_dispatch_dispatched")
        else:
            reason_codes.append("last_dispatch_status_unknown")
        operator_actions = ["review_last_daemon_dispatch"]
    elif runtime_signal is not None:
        attention_status = "HEARTBEAT_ATTENTION"
        attention_level = "WARN"
        operator_attention_required = True
        reason_codes = [runtime_signal["reason_code"]]
        operator_actions = list(runtime_signal["operator_actions"])
    elif not lease_available:
        attention_status = "LEASE_ATTENTION"
        attention_level = "WARN"
        operator_attention_required = True
        reason_codes = [
            _text_or_none(lease_repository.get("failure_code"))
            or "lease_repository_unavailable"
        ]
        operator_actions = ["configure_ae_scheduler_lease_repository"]
    elif not job_queue_available:
        attention_status = "QUEUE_ATTENTION"
        attention_level = "WARN"
        operator_attention_required = True
        reason_codes = [manual_block_reason or "job_queue_unavailable"]
        operator_actions = ["configure_ae_job_queue"]
    elif manual_status != "READY":
        normalized_reason = manual_block_reason or "manual_tick_once_not_ready"
        reason_codes = [normalized_reason]
        operator_attention_required = True
        attention_level = "WARN"
        if "batch" in normalized_reason or "window" in normalized_reason:
            attention_status = "BATCH_WINDOW_ATTENTION"
            operator_actions = ["retry_inside_retention_batch_window"]
        else:
            attention_status = "CONTROL_POLICY_BLOCKED"
            operator_actions = ["review_ae_daemon_control_policy"]

    if start_daemon_blocked_by_policy and "start_daemon_disabled_by_policy" not in reason_codes:
        reason_codes.append("start_daemon_disabled_by_policy")
    if continuous_loop_blocked_by_policy and "continuous_loop_disabled_by_policy" not in reason_codes:
        reason_codes.append("continuous_loop_disabled_by_policy")

    return {
        "attention_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_ATTENTION_SCHEMA_VERSION
        ),
        "attention_status": attention_status,
        "attention_level": attention_level,
        "reason_codes": reason_codes,
        "operator_actions": operator_actions,
        "operator_attention_required": operator_attention_required,
        "manual_tick_once_safe": manual_tick_once_safe,
        "start_daemon_blocked_by_policy": start_daemon_blocked_by_policy,
        "continuous_loop_blocked_by_policy": continuous_loop_blocked_by_policy,
        "batch_window_enforced": batch_window_enforced,
        "metadata_only": True,
    }


def build_artifact_retention_daemon_runtime_issue_candidates(
    *,
    daemon_runtime: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    runtime = _normalize_retention_scheduler_daemon_runtime_observation(
        daemon_runtime
    )
    candidates: list[dict[str, Any]] = []
    for signal in _retention_daemon_runtime_issue_signals(runtime):
        candidates.append(
            {
                "candidate_schema_version": (
                    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_ISSUE_CANDIDATE_SCHEMA_VERSION
                ),
                "candidate_id": (
                    f"{signal['service_id']}:{signal['signal_key']}:"
                    f"{signal['rule_id']}"
                ),
                "rule_id": signal["rule_id"],
                "service_id": signal["service_id"],
                "scheduler_id": signal["scheduler_id"],
                "severity": signal["severity"],
                "title": signal["title"],
                "detail": signal["detail"],
                "signal": signal["signal"],
                "recommended_operator_actions": list(signal["operator_actions"]),
                "metadata_only": True,
            }
        )
    return candidates


def _retention_daemon_runtime_issue_signals(
    daemon_runtime: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not daemon_runtime:
        return []

    store = _mapping_or_empty(daemon_runtime.get("heartbeat_store"))
    heartbeat = _mapping_or_empty(daemon_runtime.get("heartbeat"))
    metadata = _mapping_or_empty(daemon_runtime.get("metadata"))
    service_id = (
        _text_or_none(daemon_runtime.get("service_id"))
        or AE_ARTIFACT_SOURCE_SERVICE_ID
    )
    scheduler_id = _text_or_none(daemon_runtime.get("scheduler_id"))
    checked_at = _text_or_none(daemon_runtime.get("checked_at"))
    worker_type = (
        _text_or_none(daemon_runtime.get("worker_type"))
        or AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE
    )
    signals: list[dict[str, Any]] = []

    if store and store.get("available") is not True:
        raw_failure_code = (
            _text_or_none(store.get("failure_code"))
            or "heartbeat_store_unavailable"
        )
        failure_code = (
            "heartbeat_store_unavailable"
            if raw_failure_code == "unavailable"
            else raw_failure_code
        )
        signals.append(
            _retention_daemon_runtime_issue_signal(
                rule_id="ae_scheduler_daemon_heartbeat_store_unavailable.v1",
                service_id=service_id,
                scheduler_id=scheduler_id,
                signal_key="heartbeat_store",
                severity="WARNING",
                title="AE scheduler daemon heartbeat store unavailable",
                detail=(
                    "AE scheduler daemon runtime observation cannot use a "
                    "healthy heartbeat store."
                ),
                signal={
                    "worker_type": worker_type,
                    "checked_at": checked_at,
                    "backend": _text_or_none(store.get("backend")),
                    "failure_code": failure_code,
                },
                reason_code=failure_code,
                operator_actions=[
                    "inspect_ae_scheduler_daemon_runtime_route",
                    "configure_ae_scheduler_daemon_heartbeat_store",
                ],
            )
        )

    if metadata.get("heartbeat_observed") is True:
        heartbeat_status = _text_or_none(heartbeat.get("status"))
        if heartbeat_status == "ERROR":
            signals.append(
                _retention_daemon_runtime_issue_signal(
                    rule_id="ae_scheduler_daemon_heartbeat_error.v1",
                    service_id=service_id,
                    scheduler_id=scheduler_id,
                    signal_key="heartbeat_error",
                    severity="ERROR",
                    title="AE scheduler daemon heartbeat error observed",
                    detail=(
                        "AE scheduler daemon reported an ERROR heartbeat in "
                        "runtime observation."
                    ),
                    signal={
                        "worker_type": worker_type,
                        "worker_id": _text_or_none(heartbeat.get("worker_id")),
                        "active_job_id": _text_or_none(
                            heartbeat.get("active_job_id")
                        ),
                        "last_seen_at": _text_or_none(
                            heartbeat.get("last_seen_at")
                        ),
                        "phase": _text_or_none(
                            _mapping_or_empty(heartbeat.get("metadata")).get(
                                "phase"
                            )
                        ),
                    },
                    reason_code="daemon_heartbeat_error",
                    operator_actions=[
                        "review_ae_scheduler_daemon_error_heartbeat",
                        "inspect_ae_artifact_retention_history",
                    ],
                )
            )
        elif heartbeat_status is None:
            signals.append(
                _retention_daemon_runtime_issue_signal(
                    rule_id="ae_scheduler_daemon_heartbeat_status_unknown.v1",
                    service_id=service_id,
                    scheduler_id=scheduler_id,
                    signal_key="heartbeat_status_unknown",
                    severity="WARNING",
                    title="AE scheduler daemon heartbeat status unknown",
                    detail=(
                        "AE scheduler daemon heartbeat was observed, but AG "
                        "could not classify its status."
                    ),
                    signal={
                        "worker_type": worker_type,
                        "worker_id": _text_or_none(heartbeat.get("worker_id")),
                        "last_seen_at": _text_or_none(
                            heartbeat.get("last_seen_at")
                        ),
                    },
                    reason_code="daemon_heartbeat_status_unknown",
                    operator_actions=[
                        "inspect_ae_scheduler_daemon_runtime_route",
                        "verify_ae_worker_heartbeat_status_mapping",
                    ],
                )
            )
    return signals


def _retention_daemon_runtime_issue_signal(
    *,
    rule_id: str,
    service_id: str,
    scheduler_id: str | None,
    signal_key: str,
    severity: str,
    title: str,
    detail: str,
    signal: dict[str, Any],
    reason_code: str,
    operator_actions: list[str],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "service_id": service_id,
        "scheduler_id": scheduler_id,
        "signal_key": signal_key,
        "severity": severity,
        "title": title,
        "detail": detail,
        "signal": signal,
        "reason_code": reason_code,
        "operator_actions": operator_actions,
    }


def summarize_artifact_retention_automation_operations(
    *,
    batch_plan: Mapping[str, Any],
    scheduled_jobs: list[dict[str, Any]],
    history: list[dict[str, Any]],
    daemon_config: Mapping[str, Any] | None = None,
    daemon_process_snapshots: list[dict[str, Any]] | None = None,
    operator_control_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    batch_summary = summarize_artifact_retention_batch_operations(batch_plan)
    job_summary = summarize_artifact_retention_scheduled_job_operations(scheduled_jobs)
    history_summary = summarize_artifact_retention_history_operations(history)
    daemon_summary = _optional_retention_daemon_summary(
        daemon_config=_project_retention_scheduler_daemon_config(daemon_config or {}),
    )
    process_summary = summarize_artifact_retention_daemon_supervised_process_operations(
        list(daemon_process_snapshots or [])
    )
    control_summary = _mapping_or_empty(operator_control_summary)
    control_attention_required = (
        control_summary.get("operator_attention_required") is True
    )
    approval_blocked_count = sum(
        1
        for item in history
        if item.get("blocked_reason") == "operator_approval_required"
    )
    delete_guard_blocked_count = sum(
        1 for item in history if item.get("blocked_reason") == "delete_not_enabled"
    )
    safety_status = "READY"
    if job_summary["failed_count"] or history_summary["failed_count"]:
        safety_status = "FAILED_ATTENTION"
    elif (
        job_summary["active_count"]
        or history_summary["blocked_count"]
        or batch_summary["dispatch_available"]
        or daemon_summary["operator_attention_required"]
        or process_summary["operator_attention_required"]
        or control_attention_required
    ):
        safety_status = "OPERATOR_ATTENTION"
    elif not scheduled_jobs and not history and not batch_summary["dispatch_available"]:
        safety_status = "IDLE"
    return {
        "safety_status": safety_status,
        "dispatch_available": batch_summary["dispatch_available"],
        "batch_plan_status": batch_summary["plan_status"],
        "scheduler_status": batch_summary["scheduler_status"],
        "scheduled_job_count": job_summary["job_count"],
        "active_job_count": job_summary["active_count"],
        "queued_job_count": job_summary["queued_count"],
        "running_job_count": job_summary["running_count"],
        "failed_job_count": job_summary["failed_count"],
        "retryable_failed_job_count": job_summary["retryable_failed_count"],
        "history_count": history_summary["item_count"],
        "history_blocked_count": history_summary["blocked_count"],
        "history_failed_count": history_summary["failed_count"],
        "history_execute_count": history_summary["execute_count"],
        "history_dry_run_count": history_summary["dry_run_count"],
        "daemon_scheduler_id": daemon_summary["scheduler_id"],
        "daemon_manual_tick_once_available": daemon_summary[
            "manual_tick_once_available"
        ],
        "daemon_start_daemon_available": daemon_summary["start_daemon_available"],
        "daemon_scheduler_daemon_started": daemon_summary[
            "scheduler_daemon_started"
        ],
        "daemon_continuous_loop_started": daemon_summary["continuous_loop_started"],
        "daemon_lease_repository_available": daemon_summary[
            "lease_repository_available"
        ],
        "daemon_job_queue_available": daemon_summary["job_queue_available"],
        "daemon_operator_attention_required": daemon_summary[
            "operator_attention_required"
        ],
        "daemon_attention_status": daemon_summary["attention_status"],
        "daemon_attention_level": daemon_summary["attention_level"],
        "daemon_attention_reason_codes": daemon_summary["attention_reason_codes"],
        "daemon_attention_operator_actions": daemon_summary[
            "attention_operator_actions"
        ],
        "daemon_process_record_count": process_summary[
            "supervised_process_record_count"
        ],
        "daemon_process_running_count": process_summary["running_count"],
        "daemon_process_failed_count": process_summary["failed_count"],
        "daemon_process_stale_count": process_summary["stale_count"],
        "daemon_process_blocked_count": process_summary["blocked_count"],
        "daemon_process_adapter_required_count": process_summary[
            "adapter_required_count"
        ],
        "daemon_process_operator_attention_required": process_summary[
            "operator_attention_required"
        ],
        "daemon_process_status_counts": process_summary["process_status_counts"],
        "daemon_process_latest_observed_at": process_summary["latest_observed_at"],
        "operator_control_policy_loaded": (
            control_summary.get("policy_loaded") is True
        ),
        "operator_control_facade_loaded": (
            control_summary.get("facade_loaded") is True
        ),
        "operator_control_action": _normalized_daemon_operator_control_action(
            control_summary.get("action")
        ),
        "operator_control_facade_status": (
            _normalized_operator_control_admission_status(
                control_summary.get("facade_status")
            )
        ),
        "operator_control_ready_for_dispatch": (
            control_summary.get("ready_for_dispatch") is True
        ),
        "operator_control_command_preview_count": _int_or_zero(
            control_summary.get("command_preview_count")
        ),
        "operator_control_restart_supported": (
            control_summary.get("restart_supported") is True
        ),
        "operator_control_operator_attention_required": (
            control_attention_required
        ),
        "operator_control_preview_only": True,
        "approval_blocked_count": approval_blocked_count,
        "delete_guard_blocked_count": delete_guard_blocked_count,
        "selected_artifact_count": batch_summary["selected_count"],
        "estimated_deleted_artifacts": batch_summary["estimated_deleted_artifacts"],
        "estimated_deleted_storage_files": (
            batch_summary["estimated_deleted_storage_files"]
        ),
        "total_deleted_artifacts": history_summary["total_deleted_artifacts"],
        "total_deleted_storage_files": (history_summary["total_deleted_storage_files"]),
        "operator_attention_required": (
            batch_summary["operator_attention_required"]
            or job_summary["operator_attention_required"]
            or history_summary["operator_attention_count"] > 0
            or daemon_summary["operator_attention_required"]
            or process_summary["operator_attention_required"]
            or control_attention_required
        ),
        "automated_execute_enabled": False,
        "physical_delete_automation_enabled": False,
        "physical_delete_operator_approval_required": True,
        "latest_activity_at": _latest_timestamp_text(
            batch_summary["latest_checked_at"],
            job_summary["latest_updated_at"],
            history_summary["latest_checked_at"],
            process_summary["latest_observed_at"],
        ),
    }


def _optional_retention_daemon_summary(
    daemon_config: Mapping[str, Any],
) -> dict[str, Any]:
    if not daemon_config.get("scheduler_id"):
        return {
            "scheduler_id": None,
            "scheduler_daemon_enabled": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "manual_tick_once_available": False,
            "start_daemon_available": False,
            "lease_repository_available": False,
            "lease_repository_backend": None,
            "job_queue_available": False,
            "job_queue_backend": None,
            "default_execution_mode": None,
            "attention_status": "NO_DAEMON_CONFIG",
            "attention_level": "INFO",
            "attention_reason_codes": ["daemon_config_missing"],
            "attention_operator_actions": ["load_ae_scheduler_daemon_config"],
            "batch_window_enforced": False,
            "operator_attention_required": False,
            "metadata_only": True,
        }
    return summarize_artifact_retention_daemon_operations(
        daemon_config=daemon_config,
    )


def summarize_artifact_retention_history_operations(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    mode_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    latest_checked_at: str | None = None
    total_deleted_artifacts = 0
    total_deleted_storage_files = 0
    for item in items:
        mode = _normalized_retention_mode(item.get("mode"))
        if mode is not None:
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        status = _normalized_retention_status(item.get("execution_status"))
        if status is not None:
            status_counts[status] = status_counts.get(status, 0) + 1
        checked_at = _text_or_none(item.get("checked_at"))
        if checked_at is not None and (
            latest_checked_at is None or checked_at > latest_checked_at
        ):
            latest_checked_at = checked_at
        deleted_counts = item.get("deleted_counts")
        if isinstance(deleted_counts, Mapping):
            total_deleted_artifacts += _int_or_zero(deleted_counts.get("artifacts"))
            total_deleted_storage_files += _int_or_zero(
                deleted_counts.get("storage_files")
            )
    blocked_count = status_counts.get("BLOCKED", 0)
    failed_count = status_counts.get("FAILED", 0)
    return {
        "item_count": len(items),
        "mode_counts": mode_counts,
        "status_counts": status_counts,
        "dry_run_count": mode_counts.get("DRY_RUN", 0),
        "execute_count": mode_counts.get("EXECUTE", 0),
        "succeeded_count": status_counts.get("SUCCEEDED", 0),
        "blocked_count": blocked_count,
        "failed_count": failed_count,
        "operator_attention_count": blocked_count + failed_count,
        "total_deleted_artifacts": total_deleted_artifacts,
        "total_deleted_storage_files": total_deleted_storage_files,
        "latest_checked_at": latest_checked_at,
    }


def assert_artifact_operation_projection_redacted(
    projection: Mapping[str, Any],
) -> None:
    serialized = str(projection)
    forbidden_fragments = (
        "/data/nex-platform",
        "content_base64",
        "database_url",
        "PRIVATE_MARKDOWN",
        "SECRET_SOURCE_TEXT",
        "SECRET_SYSTEM_PROMPT",
        "hidden prompt",
        "nuri1004",
        "raw source",
        "rendered_markdown",
        "comment_text",
        "raw_comment",
        "'execution':",
        '"execution":',
    )
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError("AG artifact operation projection contains private data.")


def _project_artifact(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_schema_version": _text_or_none(record.get("artifact_schema_version")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "display_title": _text_or_none(
            record.get("display_title") or record.get("artifact_title")
        ),
        "current_version_id": _text_or_none(record.get("current_version_id")),
        "artifact_handoff_id": _handoff_id_from_artifact(record),
        "artifact_request_id": _text_or_none(record.get("artifact_request_id")),
        "trace_id": _text_or_none(record.get("trace_id")),
        "request_id": _text_or_none(record.get("request_id")),
        "owner_scope": _owner_scope(record.get("owner_actor_ref")),
        "workspace_ref": _select_mapping(
            record.get("workspace_ref"),
            ("workspace_id", "document_group_id", "chat_document_id"),
        ),
        "target_formats": _text_list(record.get("target_formats")),
        "source_refs": [
            _project_source_ref(ref) for ref in _list_value(record.get("source_refs"))
        ],
        "versions": [
            _project_version(version) for version in _list_value(record.get("versions"))
        ],
        "render_jobs": [
            _project_render_job(render_job)
            for render_job in _list_value(record.get("render_jobs"))
        ],
        "files": [_project_file(file) for file in _list_value(record.get("files"))],
        "links": [_project_link(link) for link in _list_value(record.get("links"))],
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_artifact_collection_item(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_collection_item_schema_version": _text_or_none(
            record.get("artifact_collection_item_schema_version")
        ),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "display_title": _text_or_none(record.get("display_title")),
        "language": _text_or_none(record.get("language")),
        "artifact_intent": _text_or_none(record.get("artifact_intent")),
        "target_formats": _text_list(record.get("target_formats")),
        "available_formats": _text_list(record.get("available_formats")),
        "downloadable_formats": _text_list(record.get("downloadable_formats")),
        "previewable_formats": _text_list(record.get("previewable_formats")),
        "current_version_id": _text_or_none(record.get("current_version_id")),
        "current_version_no": _int_or_zero(record.get("current_version_no")),
        "version_count": _int_or_zero(record.get("version_count")),
        "file_count": _int_or_zero(record.get("file_count")),
        "link_count": _int_or_zero(record.get("link_count")),
        "render_job_count": _int_or_zero(record.get("render_job_count")),
        "latest_render_job": _select_mapping(
            record.get("latest_render_job"),
            (
                "render_job_id",
                "artifact_version_id",
                "render_status",
                "renderer_policy_id",
                "target_formats",
                "started_at",
                "completed_at",
                "created_at",
            ),
        ),
        "source_summary": _select_mapping(
            record.get("source_summary"),
            (
                "cx_generation_id",
                "structured_draft_id",
                "structured_draft_content_hash",
                "generation_response_hash",
                "retrieval_package_id",
                "retrieval_package_hash",
            ),
        ),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "routes": _safe_artifact_route_mapping(record.get("routes")),
        "tenant_id": _text_or_none(record.get("tenant_id")),
        "workspace_id": _text_or_none(record.get("workspace_id")),
        "owner_user_id": _text_or_none(record.get("owner_user_id")),
        "chat_document_id": _text_or_none(record.get("chat_document_id")),
        "interaction_id": _text_or_none(record.get("interaction_id")),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_lifecycle_artifact(record: Mapping[str, Any]) -> dict[str, Any]:
    artifact_id = _text_or_none(record.get("artifact_id"))
    routes = {}
    if artifact_id:
        routes = {
            "detail": f"/api/v1/artifacts/{artifact_id}",
            "lifecycle_action": f"/api/v1/artifacts/{artifact_id}/lifecycle-actions",
        }
    return {
        "artifact_id": artifact_id,
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _normalized_status(record.get("artifact_status")),
        "display_title": _text_or_none(
            record.get("display_title") or record.get("artifact_title")
        ),
        "current_version_id": _text_or_none(record.get("current_version_id")),
        "owner_scope": _owner_scope(record.get("owner_actor_ref")),
        "workspace_ref": _select_mapping(
            record.get("workspace_ref"),
            ("workspace_id", "document_group_id", "chat_document_id"),
        ),
        "file_count": len(_list_value(record.get("files"))),
        "link_count": len(_list_value(record.get("links"))),
        "routes": _safe_artifact_route_mapping(routes),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_collection_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "status": _normalized_status(raw_value.get("status")),
        "limit": _int_or_zero(raw_value.get("limit")),
    }


def _project_retention_history_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "mode": _normalized_retention_mode(raw_value.get("mode")),
        "execution_status": _normalized_retention_status(
            raw_value.get("execution_status")
        ),
        "limit": _int_or_zero(raw_value.get("limit")),
    }


def _project_retention_batch_plan(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "artifact_retention_batch_plan_schema_version": _text_or_none(
            raw_value.get("artifact_retention_batch_plan_schema_version")
        ),
        "plan_id": _text_or_none(raw_value.get("plan_id")),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "schedule": _project_retention_batch_schedule(raw_value.get("schedule")),
        "candidate_filter": _project_retention_batch_filter(
            raw_value.get("candidate_filter")
        ),
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "mode": _normalized_retention_mode(raw_value.get("mode")),
        "plan_status": _normalized_retention_batch_status(raw_value.get("plan_status")),
        "scheduler_status": _text_or_none(raw_value.get("scheduler_status")),
        "execution_advice": _text_or_none(raw_value.get("execution_advice")),
        "as_of": _text_or_none(raw_value.get("as_of")),
        "cutoff_at": _text_or_none(raw_value.get("cutoff_at")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "scan_limit": _int_or_zero(raw_value.get("scan_limit")),
        "max_delete_count": _int_or_zero(raw_value.get("max_delete_count")),
        "candidate_count": _int_or_zero(raw_value.get("candidate_count")),
        "selected_count": _int_or_zero(raw_value.get("selected_count")),
        "unselected_count": _int_or_zero(raw_value.get("unselected_count")),
        "estimated_deleted_counts": _safe_deleted_counts(
            raw_value.get("estimated_deleted_counts")
        ),
        "selected_candidates": [
            _project_retention_batch_candidate(candidate)
            for candidate in _list_value(raw_value.get("selected_candidates"))
            if isinstance(candidate, Mapping)
        ],
        "requested_by": _select_mapping(
            raw_value.get("requested_by"),
            ("actor_type", "actor_id", "service_id"),
        ),
        "idempotency_key": _text_or_none(raw_value.get("idempotency_key")),
        "metadata": _select_mapping(
            raw_value.get("metadata"),
            (
                "metadata_only",
                "dry_run",
                "physical_delete_executed",
                "storage_mutation_executed",
                "database_row_delete_executed",
                "history_write_executed",
                "source_collection_count",
            ),
        ),
    }


def _project_retention_batch_schedule(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "schedule_id": _text_or_none(raw_value.get("schedule_id")),
        "policy_id": _text_or_none(raw_value.get("policy_id")),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "enabled": raw_value.get("enabled") is True,
        "planning_enabled": raw_value.get("planning_enabled") is not False,
        "default_mode": _normalized_retention_mode(raw_value.get("default_mode")),
        "allowed_modes": [
            mode
            for mode in (
                _normalized_retention_mode(value)
                for value in _list_value(raw_value.get("allowed_modes"))
            )
            if mode is not None
        ],
        "retention_days_presets": [
            _int_or_zero(value)
            for value in _list_value(raw_value.get("retention_days_presets"))
            if _int_or_zero(value) > 0
        ],
        "default_retention_days_after_logical_purge": _int_or_zero(
            raw_value.get("default_retention_days_after_logical_purge")
        ),
        "max_scan_limit": _int_or_zero(raw_value.get("max_scan_limit")),
        "max_delete_count": _int_or_zero(raw_value.get("max_delete_count")),
        "timezone": _text_or_none(raw_value.get("timezone")),
        "batch_window": _select_mapping(
            raw_value.get("batch_window"),
            ("start_local_time", "end_local_time"),
        ),
        "scheduler": _select_mapping(raw_value.get("scheduler"), ("daemon_enabled",)),
        "execution_guards": _select_mapping(
            raw_value.get("execution_guards"),
            (
                "delete_enabled",
                "storage_mutation_enabled",
                "database_row_delete_enabled",
            ),
        ),
        "ownership": _select_mapping(
            raw_value.get("ownership"),
            ("system_of_record", "dispatch_owner"),
        ),
    }


def _project_retention_batch_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "status": _normalized_status(raw_value.get("status")),
        "retention_days": _int_or_zero(raw_value.get("retention_days")),
        "as_of": _text_or_none(raw_value.get("as_of")),
        "cutoff_at": _text_or_none(raw_value.get("cutoff_at")),
        "limit": _int_or_zero(raw_value.get("limit")),
        "dry_run": raw_value.get("dry_run") is not False,
    }


def _project_retention_batch_candidate(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_retention_batch_candidate_schema_version": _text_or_none(
            record.get("artifact_retention_batch_candidate_schema_version")
        ),
        "selection_order": _int_or_zero(record.get("selection_order")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "display_title": _text_or_none(record.get("display_title")),
        "artifact_status": _normalized_status(record.get("artifact_status")),
        "logical_purged_at": _text_or_none(record.get("logical_purged_at")),
        "purge_eligible_at": _text_or_none(record.get("purge_eligible_at")),
        "age_days_after_logical_purge": _int_or_zero(
            record.get("age_days_after_logical_purge")
        ),
        "version_count": _int_or_zero(record.get("version_count")),
        "file_count": _int_or_zero(record.get("file_count")),
        "link_count": _int_or_zero(record.get("link_count")),
        "render_job_count": _int_or_zero(record.get("render_job_count")),
        "planned_action": _text_or_none(record.get("planned_action")),
        "execution_mode": _normalized_retention_mode(record.get("execution_mode")),
        "dry_run": record.get("dry_run") is not False,
    }


def _project_retention_scheduled_job_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "status": _normalized_job_status(raw_value.get("status")),
        "limit": _int_or_zero(raw_value.get("limit")),
    }


def _project_retention_scheduled_job_item(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = _project_retention_scheduled_job_payload(record.get("payload"))
    return {
        "artifact_retention_scheduled_job_schema_version": _text_or_none(
            record.get("artifact_retention_scheduled_job_schema_version")
        ),
        "job_schema_version": _text_or_none(record.get("job_schema_version")),
        "job_id": _text_or_none(record.get("job_id")),
        "job_type": _text_or_none(record.get("job_type")),
        "status": _normalized_job_status(record.get("status")),
        "trace_id": _text_or_none(record.get("trace_id")),
        "request_id": _text_or_none(record.get("request_id")),
        "subject_ref": _select_mapping(record.get("subject_ref"), ("type", "id")),
        "idempotency_key": _text_or_none(record.get("idempotency_key")),
        "attempt_count": _int_or_zero(record.get("attempt_count")),
        "max_attempts": _int_or_zero(record.get("max_attempts")),
        "retryable": record.get("retryable") is True,
        "links": _safe_retention_scheduled_job_links(record.get("links")),
        "payload": payload,
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_retention_scheduled_job_payload(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "payload_schema_version": _text_or_none(
            raw_value.get("payload_schema_version")
        ),
        "command_id": _text_or_none(raw_value.get("command_id")),
        "source_plan_id": _text_or_none(raw_value.get("source_plan_id")),
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "trigger_type": _text_or_none(raw_value.get("trigger_type")),
        "scheduler_status": _text_or_none(raw_value.get("scheduler_status")),
        "command_status": _text_or_none(raw_value.get("command_status")),
        "execution_mode": _normalized_retention_mode(raw_value.get("execution_mode")),
        "retention_days_after_logical_purge": _int_or_zero(
            raw_value.get("retention_days_after_logical_purge")
        ),
        "scan_limit": _int_or_zero(raw_value.get("scan_limit")),
        "max_delete_count": _int_or_zero(raw_value.get("max_delete_count")),
        "candidate_count": _int_or_zero(raw_value.get("candidate_count")),
        "selected_count": _int_or_zero(raw_value.get("selected_count")),
        "estimated_deleted_counts": _safe_deleted_counts(
            raw_value.get("estimated_deleted_counts")
        ),
        "command_summary": _select_mapping(
            raw_value.get("command_summary"),
            (
                "command_status",
                "trigger_type",
                "scheduler_status",
                "execution_mode",
                "candidate_count",
                "selected_count",
                "estimated_deleted_artifacts",
                "estimated_deleted_storage_files",
                "command_created_at",
                "next_action",
            ),
        ),
        "requested_by": _select_mapping(
            raw_value.get("requested_by"),
            ("actor_type", "actor_id", "service_id"),
        ),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "redaction_summary": _select_mapping(
            raw_value.get("redaction_summary"),
            (
                "metadata_only",
                "scheduled_command_embedded",
                "batch_plan_embedded",
                "artifact_payload_included",
                "prompt_content_included",
                "generation_output_included",
                "storage_locator_included",
            ),
        ),
    }


def _project_retention_scheduled_dispatch_request(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "retention_days": _int_or_zero(raw_value.get("retention_days")),
        "as_of": _text_or_none(raw_value.get("as_of")),
        "scan_limit": _int_or_zero(raw_value.get("scan_limit")),
        "max_delete_count": _int_or_zero(raw_value.get("max_delete_count")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "trigger_type": _normalized_scheduled_trigger(raw_value.get("trigger_type")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "idempotency_key": _text_or_none(raw_value.get("idempotency_key")),
        "confirm_dispatch": raw_value.get("confirm_dispatch") is True,
    }


def _project_retention_scheduled_dispatch_response(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    enqueued_job = raw_value.get("enqueued_job")
    return {
        "artifact_retention_scheduled_job_enqueue_result_schema_version": (
            _text_or_none(
                raw_value.get(
                    "artifact_retention_scheduled_job_enqueue_result_schema_version"
                )
            )
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "source_plan_id": _text_or_none(raw_value.get("source_plan_id")),
        "command_id": _text_or_none(raw_value.get("command_id")),
        "job_id": _text_or_none(raw_value.get("job_id")),
        "job_type": _text_or_none(raw_value.get("job_type")),
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "workspace_id": _text_or_none(raw_value.get("workspace_id")),
        "owner_user_id": _text_or_none(raw_value.get("owner_user_id")),
        "trigger_type": _text_or_none(raw_value.get("trigger_type")),
        "trace_id": _text_or_none(raw_value.get("trace_id")),
        "request_id": _text_or_none(raw_value.get("request_id")),
        "idempotency_key": _text_or_none(raw_value.get("idempotency_key")),
        "enqueue_status": _text_or_none(raw_value.get("enqueue_status")),
        "job_enqueued": raw_value.get("job_enqueued") is True,
        "duplicate_returned": raw_value.get("duplicate_returned") is True,
        "queue_admission": _select_mapping(
            raw_value.get("queue_admission"),
            (
                "queue_service_id",
                "queue_backend",
                "target_job_type",
                "job_enqueued",
                "worker_execution_performed",
                "scheduler_daemon_started",
                "physical_delete_automation_enabled",
            ),
        ),
        "command_summary": _select_mapping(
            raw_value.get("command_summary"),
            (
                "command_status",
                "trigger_type",
                "scheduler_status",
                "execution_mode",
                "candidate_count",
                "selected_count",
                "estimated_deleted_artifacts",
                "estimated_deleted_storage_files",
                "command_created_at",
                "next_action",
            ),
        ),
        "job_summary": _select_mapping(
            raw_value.get("job_summary"),
            (
                "job_id",
                "job_type",
                "status",
                "command_id",
                "source_plan_id",
                "trigger_type",
                "execution_mode",
                "candidate_count",
                "selected_count",
                "history_write_expected",
                "physical_delete_automation_enabled",
            ),
        ),
        "enqueued_job": (
            _project_retention_scheduled_job_item(enqueued_job)
            if isinstance(enqueued_job, Mapping)
            else {}
        ),
    }


def _project_retention_scheduler_daemon_config(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_config_schema_version": _text_or_none(
            raw_value.get("daemon_config_schema_version")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "source_scheduler_config_schema_version": _text_or_none(
            raw_value.get("source_scheduler_config_schema_version")
        ),
        "runtime": _project_retention_scheduler_daemon_runtime(
            raw_value.get("runtime")
        ),
        "lease_repository": _project_retention_scheduler_daemon_lease_repository(
            raw_value.get("lease_repository")
        ),
        "supported_actions": [
            _project_retention_scheduler_daemon_action(item)
            for item in _list_value(raw_value.get("supported_actions"))
            if isinstance(item, Mapping)
        ],
        "guardrails": _project_retention_scheduler_daemon_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_runtime_observation(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "runtime_projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_PROJECTION_SCHEMA_VERSION
        ),
        "source_runtime_observation_schema_version": _text_or_none(
            raw_value.get("runtime_observation_schema_version")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "worker_type": _text_or_none(raw_value.get("worker_type")),
        "heartbeat_store": _project_retention_scheduler_daemon_heartbeat_store(
            raw_value.get("heartbeat_store")
        ),
        "heartbeat": _project_retention_scheduler_daemon_heartbeat(
            raw_value.get("heartbeat")
        ),
        "heartbeat_count": _int_or_zero(raw_value.get("heartbeat_count")),
        "daemon_config_checked_at": _text_or_none(
            raw_value.get("daemon_config_checked_at")
        ),
        "runtime_state": _project_retention_scheduler_daemon_runtime_state(
            raw_value.get("runtime_state")
        ),
        "bounded_loop_result": _project_retention_scheduler_daemon_bounded_loop_result(
            raw_value.get("bounded_loop_result")
        ),
        "shutdown_transition": _project_retention_scheduler_daemon_shutdown_transition(
            raw_value.get("shutdown_transition")
        ),
        "retry_circuit_guard": _project_retention_scheduler_daemon_retry_circuit_guard(
            raw_value.get("retry_circuit_guard")
        ),
        "guardrails": _project_retention_scheduler_daemon_runtime_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_runtime_metadata(
            raw_value.get("metadata")
        ),
    }


def _normalize_retention_scheduler_daemon_runtime_observation(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    if (
        raw_value.get("runtime_projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_RUNTIME_PROJECTION_SCHEMA_VERSION
    ):
        return dict(raw_value)
    return _project_retention_scheduler_daemon_runtime_observation(raw_value)


def _project_retention_scheduler_daemon_heartbeat_store(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "available": raw_value.get("available") is True,
        "backend": _text_or_none(raw_value.get("backend")),
        "failure_code": _text_or_none(raw_value.get("failure_code")),
    }


def _project_retention_scheduler_daemon_heartbeat(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "heartbeat_schema_version": _text_or_none(
            raw_value.get("heartbeat_schema_version")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "worker_id": _text_or_none(raw_value.get("worker_id")),
        "worker_type": _text_or_none(raw_value.get("worker_type")),
        "status": _normalized_daemon_heartbeat_status(raw_value.get("status")),
        "active_job_id": _text_or_none(raw_value.get("active_job_id")),
        "trace_id": _text_or_none(raw_value.get("trace_id")),
        "started_at": _text_or_none(raw_value.get("started_at")),
        "last_seen_at": _text_or_none(raw_value.get("last_seen_at")),
        "metadata": _project_retention_scheduler_daemon_heartbeat_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_heartbeat_metadata(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_loop_plan_id": _text_or_none(raw_value.get("daemon_loop_plan_id")),
        "phase": _text_or_none(raw_value.get("phase")),
        "loop_decision_status": _text_or_none(
            raw_value.get("loop_decision_status")
        ),
        "loop_decision_reason": _text_or_none(raw_value.get("loop_decision_reason")),
        "tick_once_result_status": _text_or_none(
            raw_value.get("tick_once_result_status")
        ),
        "tick_once_skip_reason": _text_or_none(raw_value.get("tick_once_skip_reason")),
        "one_cycle_only": raw_value.get("one_cycle_only") is True,
        "scheduler_daemon_started": raw_value.get("scheduler_daemon_started") is True,
        "continuous_loop_started": raw_value.get("continuous_loop_started") is True,
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _project_retention_scheduler_daemon_runtime_guardrails(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "metadata_only",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "scheduler_daemon_started",
            "continuous_loop_started",
            "physical_delete_automation_enabled",
            "heartbeat_observation_read_only",
        ),
    )


def _project_retention_scheduler_daemon_runtime_metadata(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "metadata_only": raw_value.get("metadata_only") is True,
        "heartbeat_observed": raw_value.get("heartbeat_observed") is True,
        "heartbeat_store_available": (
            raw_value.get("heartbeat_store_available") is True
        ),
        "persistence_endpoint_included": (
            raw_value.get("persistence_endpoint_included") is True
            or raw_value.get("database_url_included") is True
        ),
        "storage_locator_included": (
            raw_value.get("storage_locator_included") is True
            or raw_value.get("storage_path_included") is True
            or raw_value.get("storage_ref_included") is True
        ),
        "artifact_payload_included": (
            raw_value.get("artifact_payload_included") is True
            or raw_value.get("raw_artifact_payload_included") is True
        ),
        "execution_payload_included": (
            raw_value.get("execution_payload_included") is True
            or raw_value.get("raw_execution_payload_included") is True
        ),
        "scheduler_daemon_started": raw_value.get("scheduler_daemon_started") is True,
        "continuous_loop_started": raw_value.get("continuous_loop_started") is True,
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _project_retention_scheduler_daemon_runtime_state(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_runtime_state_schema_version": _text_or_none(
            raw_value.get("daemon_runtime_state_schema_version")
        ),
        "daemon_runtime_state_id": _text_or_none(
            raw_value.get("daemon_runtime_state_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(raw_value.get("daemon_instance_id")),
        "observed_at": _text_or_none(raw_value.get("observed_at")),
        "lifecycle_status": _normalized_daemon_lifecycle_status(
            raw_value.get("lifecycle_status")
        ),
        "lifecycle_reason": _text_or_none(raw_value.get("lifecycle_reason")),
        "stop_requested": raw_value.get("stop_requested") is True,
        "shutdown_requested_at": _text_or_none(raw_value.get("shutdown_requested_at")),
        "last_cycle": _project_retention_scheduler_daemon_runtime_state_last_cycle(
            raw_value.get("last_cycle")
        ),
        "next_tick_at": _text_or_none(raw_value.get("next_tick_at")),
        "cycle_count": _int_or_zero(raw_value.get("cycle_count")),
        "consecutive_failure_count": _int_or_zero(
            raw_value.get("consecutive_failure_count")
        ),
        "heartbeat_worker_id": _text_or_none(raw_value.get("heartbeat_worker_id")),
        "guardrails": _project_retention_scheduler_daemon_lifecycle_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_lifecycle_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_runtime_state_last_cycle(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "run_at",
            "result_status",
            "skip_reason",
            "error_code",
            "duration_ms",
            "planned_delete_count",
            "deleted_count",
        ),
    )


def _project_retention_scheduler_daemon_bounded_loop_result(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_bounded_loop_result_schema_version": _text_or_none(
            raw_value.get("daemon_bounded_loop_result_schema_version")
        ),
        "daemon_bounded_loop_result_id": _text_or_none(
            raw_value.get("daemon_bounded_loop_result_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(raw_value.get("daemon_instance_id")),
        "result_status": _text_or_none(raw_value.get("result_status")),
        "stop_reason": _text_or_none(raw_value.get("stop_reason")),
        "started_at": _text_or_none(raw_value.get("started_at")),
        "finished_at": _text_or_none(raw_value.get("finished_at")),
        "max_cycles": _int_or_zero(raw_value.get("max_cycles")),
        "cycle_count": _int_or_zero(raw_value.get("cycle_count")),
        "consecutive_failure_count": _int_or_zero(
            raw_value.get("consecutive_failure_count")
        ),
        "final_state": _project_retention_scheduler_daemon_runtime_state(
            raw_value.get("final_state")
        ),
        "guardrails": _project_retention_scheduler_daemon_lifecycle_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_lifecycle_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_shutdown_transition(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_shutdown_transition_schema_version": _text_or_none(
            raw_value.get("daemon_shutdown_transition_schema_version")
        ),
        "daemon_shutdown_transition_id": _text_or_none(
            raw_value.get("daemon_shutdown_transition_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(raw_value.get("daemon_instance_id")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "decision_status": _text_or_none(raw_value.get("decision_status")),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "previous_state": _project_retention_scheduler_daemon_runtime_state(
            raw_value.get("previous_state")
        ),
        "next_state": _project_retention_scheduler_daemon_runtime_state(
            raw_value.get("next_state")
        ),
        "execution_plan": _select_mapping(
            raw_value.get("execution_plan"),
            (
                "requires_runtime_state",
                "sends_stop_signal",
                "runs_tick_once",
                "dispatches_job_queue",
                "bounded_loop_should_stop_before_next_cycle",
                "writes_history",
                "physical_delete_enabled",
            ),
        ),
        "guardrails": _project_retention_scheduler_daemon_lifecycle_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_lifecycle_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_retry_circuit_guard(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_retry_circuit_guard_schema_version": _text_or_none(
            raw_value.get("daemon_retry_circuit_guard_schema_version")
        ),
        "daemon_retry_circuit_guard_id": _text_or_none(
            raw_value.get("daemon_retry_circuit_guard_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(raw_value.get("daemon_instance_id")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "decision_status": _text_or_none(raw_value.get("decision_status")),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "retry_allowed": raw_value.get("retry_allowed") is True,
        "next_retry_at": _text_or_none(raw_value.get("next_retry_at")),
        "failure_threshold": _int_or_zero(raw_value.get("failure_threshold")),
        "backoff_seconds": _int_or_zero(raw_value.get("backoff_seconds")),
        "execution_plan": _select_mapping(
            raw_value.get("execution_plan"),
            (
                "requires_runtime_state",
                "retry_allowed",
                "runs_tick_once",
                "dispatches_job_queue",
                "writes_history",
                "physical_delete_enabled",
            ),
        ),
        "guardrails": _project_retention_scheduler_daemon_lifecycle_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_lifecycle_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_lifecycle_guardrails(
    raw_value: Any,
) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "metadata_only",
            "state_snapshot_only",
            "daemon_process_owner_ae",
            "daemon_as_jobqueue_job_allowed",
            "retention_work_uses_job_queue",
            "job_enqueue_performed",
            "worker_execution_performed",
            "runtime_state_persisted_by_builder",
            "bounded_loop_is_finite",
            "bounded_loop_stop_requested",
            "retry_decision_only",
            "runtime_state_mutated",
            "database_write_performed",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "continuous_loop_started",
            "physical_delete_automation_enabled",
        ),
    )


def _project_retention_scheduler_daemon_lifecycle_metadata(
    raw_value: Any,
) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "metadata_only",
            "safe_for_ag_projection",
            "state_snapshot_only",
            "lifecycle_running",
            "lifecycle_stopped",
            "lifecycle_error",
            "stop_requested",
            "shutdown_requested",
            "last_cycle_present",
            "last_cycle_failed",
            "next_tick_scheduled",
            "consecutive_failures_present",
            "bounded_loop_started",
            "stopped_by_max_cycles",
            "stopped_by_request",
            "tick_once_ran",
            "job_enqueued",
            "worker_executed",
            "retry_ready",
            "backing_off",
            "circuit_open",
            "runtime_state_mutated",
            "database_write_performed",
            "continuous_loop_started",
            "physical_delete_automation_enabled",
        ),
    )


def _project_retention_scheduler_daemon_runtime(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "scheduler_daemon_enabled",
            "scheduler_daemon_started",
            "daemon_auto_start_allowed",
            "continuous_loop_enabled",
            "continuous_loop_started",
            "manual_tick_once_enabled",
            "manual_tick_once_requires_lease",
            "scheduler_tick_admission_enabled",
            "operator_dispatch_admission_enabled",
            "default_execution_mode",
            "job_queue_available",
            "job_queue_backend",
            "scheduler_tick_interval_seconds",
            "scheduler_tick_jitter_seconds",
            "scheduler_tick_lock_ttl_seconds",
            "scheduler_tick_stale_after_seconds",
            "scheduler_tick_max_jobs_per_tick",
            "scheduler_tick_batch_window_enforced",
            "scheduler_tick_timezone",
            "scheduler_tick_window_start",
            "scheduler_tick_window_end",
        ),
    )


def _project_retention_scheduler_daemon_lease_repository(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "required",
            "available",
            "backend",
            "lease_record_schema_version",
            "failure_code",
        ),
    )


def _project_retention_scheduler_daemon_action(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "action": _normalized_daemon_action(raw_value.get("action")),
        "decision_status": _text_or_none(raw_value.get("decision_status")),
        "requires_lease": raw_value.get("requires_lease") is True,
        "runs_tick_once": raw_value.get("runs_tick_once") is True,
        "starts_daemon": raw_value.get("starts_daemon") is True,
        "starts_continuous_loop": raw_value.get("starts_continuous_loop") is True,
        "block_reason": _text_or_none(raw_value.get("block_reason")),
    }


def _project_retention_scheduler_daemon_guardrails(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "metadata_only",
            "manual_tick_once_only",
            "lease_required_before_tick",
            "daemon_auto_start_allowed",
            "scheduler_daemon_started",
            "continuous_loop_started",
            "continuous_loop_allowed_before_lease",
            "physical_delete_automation_enabled",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "daemon_control_plan_required",
            "tick_once_requires_ready_control_plan",
            "start_stop_guardrail_required_for_start_stop",
            "start_stop_runtime_mutation_allowed",
            "stop_signal_allowed",
            "start_stop_control_guardrail_required",
            "start_control_enabled",
            "stop_control_enabled",
            "start_daemon_allowed",
            "stop_runtime_mutation_allowed",
            "runtime_state_mutation_allowed",
            "future_supervisor_required_before_start",
        ),
    )


def _project_retention_scheduler_daemon_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "metadata_only": raw_value.get("metadata_only") is True,
        "persistence_endpoint_included": (
            raw_value.get("persistence_endpoint_included") is True
            or raw_value.get("database_url_included") is True
        ),
        "storage_locator_included": (
            raw_value.get("storage_locator_included") is True
            or raw_value.get("storage_path_included") is True
            or raw_value.get("storage_ref_included") is True
        ),
        "artifact_payload_included": (
            raw_value.get("artifact_payload_included") is True
            or raw_value.get("raw_artifact_payload_included") is True
        ),
        "execution_payload_included": (
            raw_value.get("execution_payload_included") is True
            or raw_value.get("raw_execution_payload_included") is True
        ),
        "control_plan_ready": raw_value.get("control_plan_ready") is True,
        "tick_once_dispatched": raw_value.get("tick_once_dispatched") is True,
        "start_stop_guardrail_evaluated": (
            raw_value.get("start_stop_guardrail_evaluated") is True
        ),
        "lease_acquired_before_tick": (
            raw_value.get("lease_acquired_before_tick") is True
        ),
        "lease_released": raw_value.get("lease_released") is True,
        "job_enqueued": raw_value.get("job_enqueued") is True,
        "worker_executed": raw_value.get("worker_executed") is True,
        "runtime_state_mutated": raw_value.get("runtime_state_mutated") is True,
        "stop_signal_sent": raw_value.get("stop_signal_sent") is True,
        "scheduler_daemon_started": raw_value.get("scheduler_daemon_started") is True,
        "continuous_loop_started": raw_value.get("continuous_loop_started") is True,
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _project_retention_scheduler_daemon_dispatch_response(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_dispatch_result_schema_version": _text_or_none(
            raw_value.get("daemon_dispatch_result_schema_version")
        ),
        "daemon_dispatch_result_id": _text_or_none(
            raw_value.get("daemon_dispatch_result_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "dispatch_status": _text_or_none(raw_value.get("dispatch_status")),
        "control_plan": _project_retention_scheduler_daemon_control_plan(
            raw_value.get("control_plan")
        ),
        "tick_once_result": _project_retention_scheduler_tick_once_summary(
            raw_value.get("tick_once_result")
        ),
        "start_stop_guardrail": _project_retention_scheduler_start_stop_guardrail(
            raw_value.get("start_stop_guardrail")
        ),
        "guardrails": _project_retention_scheduler_daemon_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_run_filter(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "result_status": _normalized_daemon_result_status(
            raw_value.get("result_status")
        ),
    }


def _project_retention_scheduler_daemon_run_item(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    daemon_run_record_id = _text_or_none(record.get("daemon_run_record_id"))
    return {
        "daemon_run_record_id": daemon_run_record_id,
        "source_run_record_schema_version": _text_or_none(
            record.get("daemon_run_record_schema_version")
        ),
        "service_id": _text_or_none(record.get("service_id")),
        "scheduler_id": _text_or_none(record.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(record.get("daemon_instance_id")),
        "process_id": _int_or_zero(record.get("process_id")),
        "host_id": _text_or_none(record.get("host_id")),
        "run_status": _normalized_daemon_run_status(record.get("run_status")),
        "result_status": _normalized_daemon_result_status(
            record.get("result_status")
        ),
        "stop_reason": _text_or_none(record.get("stop_reason")),
        "max_cycles": _int_or_zero(record.get("max_cycles")),
        "cycle_count": _int_or_zero(record.get("cycle_count")),
        "worker_requested": record.get("worker_requested") is True,
        "job_enqueued": record.get("job_enqueued") is True,
        "worker_executed": record.get("worker_executed") is True,
        "started_at": _text_or_none(record.get("started_at")),
        "completed_at": _text_or_none(record.get("completed_at")),
        "checked_at": _text_or_none(record.get("checked_at")),
        "created_at": _text_or_none(record.get("created_at")),
        "summary": _safe_daemon_run_summary(record.get("summary")),
        "metadata": _safe_daemon_run_metadata(record.get("metadata")),
        "routes": {
            "ae_detail": (
                "/api/v1/artifact-retention/scheduler-daemon-runs/"
                f"{daemon_run_record_id}"
            )
            if daemon_run_record_id
            else None,
            "ag_detail": (
                "/admin/v1/operations/artifact-retention/"
                f"scheduler-daemon-runs/{daemon_run_record_id}"
            )
            if daemon_run_record_id
            else None,
        },
    }


def _project_retention_scheduler_daemon_run_record(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    item = _project_retention_scheduler_daemon_run_item(raw_value)
    return {
        **item,
        "daemon_cli_execution_result_id": _text_or_none(
            raw_value.get("daemon_cli_execution_result_id")
        ),
        "daemon_cli_execute_command_id": _text_or_none(
            raw_value.get("daemon_cli_execute_command_id")
        ),
        "daemon_process_lock_id": _text_or_none(
            raw_value.get("daemon_process_lock_id")
        ),
        "started_daemon_run_id": _text_or_none(
            raw_value.get("started_daemon_run_id")
        ),
        "completed_daemon_run_id": _text_or_none(
            raw_value.get("completed_daemon_run_id")
        ),
        "execution_result_hash": _text_or_none(raw_value.get("execution_result_hash")),
    }


def _project_retention_scheduler_daemon_lifecycle_event(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_lifecycle_event_schema_version": _text_or_none(
            raw_value.get("daemon_lifecycle_event_schema_version")
        ),
        "daemon_lifecycle_event_id": _text_or_none(
            raw_value.get("daemon_lifecycle_event_id")
        ),
        "daemon_run_record_id": _text_or_none(
            raw_value.get("daemon_run_record_id")
        ),
        "daemon_cli_execution_result_id": _text_or_none(
            raw_value.get("daemon_cli_execution_result_id")
        ),
        "daemon_run_metadata_id": _text_or_none(
            raw_value.get("daemon_run_metadata_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "daemon_instance_id": _text_or_none(raw_value.get("daemon_instance_id")),
        "event_type": _text_or_none(raw_value.get("event_type")),
        "run_status": _normalized_daemon_run_status(raw_value.get("run_status")),
        "result_status": _normalized_daemon_result_status(
            raw_value.get("result_status")
        ),
        "stop_reason": _text_or_none(raw_value.get("stop_reason")),
        "cycle_count": _int_or_zero(raw_value.get("cycle_count")),
        "occurred_at": _text_or_none(raw_value.get("occurred_at")),
        "process_id": _int_or_zero(raw_value.get("process_id")),
        "host_id": _text_or_none(raw_value.get("host_id")),
        "summary": _safe_daemon_lifecycle_event_summary(raw_value.get("summary")),
        "metadata": _safe_daemon_run_metadata(raw_value.get("metadata")),
        "created_at": _text_or_none(raw_value.get("created_at")),
    }


def _project_retention_scheduler_daemon_supervisor_filter(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "result_status": _normalized_daemon_supervisor_result_status(
            raw_value.get("result_status")
        ),
    }


def _project_retention_scheduler_daemon_supervisor_item(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    daemon_supervisor_record_id = _text_or_none(
        record.get("daemon_supervisor_record_id")
    )
    return {
        "daemon_supervisor_record_id": daemon_supervisor_record_id,
        "source_daemon_supervisor_record_schema_version": _text_or_none(
            record.get("daemon_supervisor_record_schema_version")
        ),
        "service_id": _text_or_none(record.get("service_id")),
        "scheduler_id": _text_or_none(record.get("scheduler_id")),
        "daemon_supervisor_command_id": _text_or_none(
            record.get("daemon_supervisor_command_id")
        ),
        "daemon_supervisor_result_id": _text_or_none(
            record.get("daemon_supervisor_result_id")
        ),
        "action": _normalized_daemon_supervisor_action(record.get("action")),
        "result_status": _normalized_daemon_supervisor_result_status(
            record.get("result_status")
        ),
        "decision_reason": _text_or_none(record.get("decision_reason")),
        "runtime_ready": record.get("runtime_ready") is True,
        "supervisor_adapter_available": (
            record.get("supervisor_adapter_available") is True
        ),
        "supervisor_adapter_invoked": (
            record.get("supervisor_adapter_invoked") is True
        ),
        "adapter_name": _text_or_none(record.get("adapter_name")),
        "process_started": record.get("process_started") is True,
        "process_stopped": record.get("process_stopped") is True,
        "message": _text_or_none(record.get("message")),
        "observed_at": _text_or_none(record.get("observed_at")),
        "checked_at": _text_or_none(record.get("checked_at")),
        "created_at": _text_or_none(record.get("created_at")),
        "summary": _safe_daemon_supervisor_summary(record.get("summary")),
        "metadata": _safe_daemon_supervisor_metadata(record.get("metadata")),
        "routes": {
            "ae_detail": (
                "/api/v1/artifact-retention/"
                f"scheduler-daemon-supervisor-results/{daemon_supervisor_record_id}"
            )
            if daemon_supervisor_record_id
            else None,
            "ag_detail": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-supervisor-results/"
                f"{daemon_supervisor_record_id}"
            )
            if daemon_supervisor_record_id
            else None,
        },
    }


def _project_retention_scheduler_daemon_supervisor_record(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    item = _project_retention_scheduler_daemon_supervisor_item(raw_value)
    return {
        **item,
        "supervisor_result_hash": _text_or_none(
            raw_value.get("supervisor_result_hash")
        ),
    }


def _project_retention_scheduler_daemon_supervisor_event(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_daemon_supervisor_event_schema_version": _text_or_none(
            raw_value.get("daemon_supervisor_event_schema_version")
        ),
        "daemon_supervisor_event_id": _text_or_none(
            raw_value.get("daemon_supervisor_event_id")
        ),
        "daemon_supervisor_record_id": _text_or_none(
            raw_value.get("daemon_supervisor_record_id")
        ),
        "daemon_supervisor_command_id": _text_or_none(
            raw_value.get("daemon_supervisor_command_id")
        ),
        "daemon_supervisor_result_id": _text_or_none(
            raw_value.get("daemon_supervisor_result_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "result_status": _normalized_daemon_supervisor_result_status(
            raw_value.get("result_status")
        ),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "event_type": _text_or_none(raw_value.get("event_type")),
        "occurred_at": _text_or_none(raw_value.get("occurred_at")),
        "summary": _safe_daemon_supervisor_event_summary(raw_value.get("summary")),
        "metadata": _safe_daemon_supervisor_metadata(raw_value.get("metadata")),
        "created_at": _text_or_none(raw_value.get("created_at")),
    }


def _project_retention_scheduler_daemon_supervised_process_filter(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "process_status": _normalized_daemon_supervised_process_status(
            raw_value.get("process_status")
        ),
    }


def _project_retention_scheduler_daemon_supervised_process_item(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    daemon_supervised_process_record_id = _text_or_none(
        record.get("daemon_supervised_process_record_id")
    )
    return {
        "daemon_supervised_process_record_id": (
            daemon_supervised_process_record_id
        ),
        "source_daemon_supervised_process_record_schema_version": (
            _text_or_none(
                record.get("daemon_supervised_process_record_schema_version")
            )
        ),
        "service_id": _text_or_none(record.get("service_id")),
        "scheduler_id": _text_or_none(record.get("scheduler_id")),
        "daemon_supervisor_command_id": _text_or_none(
            record.get("daemon_supervisor_command_id")
        ),
        "daemon_supervised_process_id": _text_or_none(
            record.get("daemon_supervised_process_id")
        ),
        "action": _normalized_daemon_supervisor_action(record.get("action")),
        "process_status": _normalized_daemon_supervised_process_status(
            record.get("process_status")
        ),
        "process_mode": _text_or_none(record.get("process_mode")),
        "process_id": _int_or_zero(record.get("process_id")),
        "host_id": _text_or_none(record.get("host_id")),
        "observed_at": _text_or_none(record.get("observed_at")),
        "started_at": _text_or_none(record.get("started_at")),
        "completed_at": _text_or_none(record.get("completed_at")),
        "exit_code": _int_or_zero(record.get("exit_code")),
        "termination_signal": _text_or_none(record.get("termination_signal")),
        "process_running": record.get("process_running") is True,
        "process_started_observed": (
            record.get("process_started_observed") is True
        ),
        "process_stopped_observed": (
            record.get("process_stopped_observed") is True
        ),
        "subprocess_adapter_required": (
            record.get("subprocess_adapter_required") is True
        ),
        "message": _text_or_none(record.get("message")),
        "summary": _safe_daemon_supervised_process_summary(
            record.get("summary")
        ),
        "metadata": _safe_daemon_supervised_process_metadata(
            record.get("metadata")
        ),
        "supervised_process_snapshot_hash": _text_or_none(
            record.get("supervised_process_snapshot_hash")
        ),
        "created_at": _text_or_none(record.get("created_at")),
        "routes": {
            "ae_detail": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-process-snapshots/"
                f"{daemon_supervised_process_record_id}"
            )
            if daemon_supervised_process_record_id
            else None,
            "ag_detail": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-process-snapshots/"
                f"{daemon_supervised_process_record_id}"
            )
            if daemon_supervised_process_record_id
            else None,
        },
    }


def _artifact_retention_automation_operator_control_current_process(
    collection: Any,
) -> dict[str, Any] | None:
    if not isinstance(collection, Mapping):
        return None
    projected_items = [
        _project_retention_scheduler_daemon_supervised_process_item(item)
        for item in _list_value(collection.get("items"))
        if isinstance(item, Mapping)
    ]
    if not projected_items:
        return None
    selected = _select_operator_control_process_projection(projected_items)
    return {
        "process_source": "scheduler_daemon_process_snapshots",
        "process_status": _normalized_daemon_supervised_process_status(
            selected.get("process_status")
        ),
        "process_running": selected.get("process_running") is True,
        "daemon_supervised_process_id": _text_or_none(
            selected.get("daemon_supervised_process_id")
            or selected.get("daemon_supervised_process_record_id")
        ),
        "daemon_supervisor_command_id": _text_or_none(
            selected.get("daemon_supervisor_command_id")
        ),
        "process_id": _int_or_zero(selected.get("process_id")),
        "host_id": _text_or_none(selected.get("host_id")),
        "observed_at": _text_or_none(selected.get("observed_at")),
    }


def _select_operator_control_process_projection(
    projected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    status_priority = (
        "RUNNING",
        "START_REQUESTED",
        "STOP_REQUESTED",
        "STALE",
        "FAILED",
        "BLOCKED",
        "STOPPED",
        "EXITED",
        "MISSING",
    )
    for status in status_priority:
        for item in projected_items:
            if item.get("process_status") == status:
                return item
    return projected_items[0]


def _project_retention_scheduler_daemon_supervised_process_record(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _project_retention_scheduler_daemon_supervised_process_item(raw_value)


def _project_retention_scheduler_daemon_supervised_process_event(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_daemon_supervised_process_event_schema_version": (
            _text_or_none(
                raw_value.get(
                    "daemon_supervised_process_event_schema_version"
                )
            )
        ),
        "daemon_supervised_process_event_id": _text_or_none(
            raw_value.get("daemon_supervised_process_event_id")
        ),
        "daemon_supervised_process_record_id": _text_or_none(
            raw_value.get("daemon_supervised_process_record_id")
        ),
        "daemon_supervised_process_id": _text_or_none(
            raw_value.get("daemon_supervised_process_id")
        ),
        "daemon_supervisor_command_id": _text_or_none(
            raw_value.get("daemon_supervisor_command_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "process_status": _normalized_daemon_supervised_process_status(
            raw_value.get("process_status")
        ),
        "event_type": _text_or_none(raw_value.get("event_type")),
        "occurred_at": _text_or_none(raw_value.get("occurred_at")),
        "summary": _safe_daemon_supervised_process_event_summary(
            raw_value.get("summary")
        ),
        "metadata": _safe_daemon_supervised_process_metadata(
            raw_value.get("metadata")
        ),
        "created_at": _text_or_none(raw_value.get("created_at")),
    }


def _project_retention_scheduler_daemon_control_plan(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_control_plan_schema_version": _text_or_none(
            raw_value.get("daemon_control_plan_schema_version")
        ),
        "daemon_control_plan_id": _text_or_none(
            raw_value.get("daemon_control_plan_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_action(raw_value.get("action")),
        "decision_status": _text_or_none(raw_value.get("decision_status")),
        "block_reason": _text_or_none(raw_value.get("block_reason")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "requested_by": _select_mapping(
            raw_value.get("requested_by"),
            ("actor_type", "actor_id", "tenant_id", "workspace_id", "request_id"),
        ),
        "reason": _text_or_none(raw_value.get("reason")),
        "execution_plan": _select_mapping(
            raw_value.get("execution_plan"),
            (
                "requires_lease",
                "runs_tick_once",
                "dispatches_job_queue",
                "starts_daemon",
                "starts_continuous_loop",
                "writes_history",
                "physical_delete_enabled",
            ),
        ),
        "guardrails": _project_retention_scheduler_daemon_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_start_stop_guardrail(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "daemon_start_stop_guardrail_schema_version": _text_or_none(
            raw_value.get("daemon_start_stop_guardrail_schema_version")
        ),
        "daemon_start_stop_guardrail_id": _text_or_none(
            raw_value.get("daemon_start_stop_guardrail_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_action(raw_value.get("action")),
        "guardrail_status": _text_or_none(raw_value.get("guardrail_status")),
        "guardrail_reason": _text_or_none(raw_value.get("guardrail_reason")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "action_allowed": raw_value.get("action_allowed") is True,
        "runtime_state_transition": _text_or_none(
            raw_value.get("runtime_state_transition")
        ),
        "execution_plan": _select_mapping(
            raw_value.get("execution_plan"),
            (
                "requires_control_plan",
                "requires_lease",
                "runs_tick_once",
                "dispatches_job_queue",
                "starts_daemon",
                "stops_daemon",
                "sends_stop_signal",
                "starts_continuous_loop",
                "runtime_state_mutated",
                "writes_history",
                "physical_delete_enabled",
                "mirrors_control_action",
            ),
        ),
        "guardrails": _project_retention_scheduler_daemon_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_tick_once_summary(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "tick_once_result_schema_version": _text_or_none(
            raw_value.get("tick_once_result_schema_version")
        ),
        "tick_once_result_id": _text_or_none(raw_value.get("tick_once_result_id")),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "lease_owner_id": _text_or_none(raw_value.get("lease_owner_id")),
        "run_at": _text_or_none(raw_value.get("run_at")),
        "result_status": _text_or_none(raw_value.get("result_status")),
        "skip_reason": _text_or_none(raw_value.get("skip_reason")),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
    }


def _project_retention_scheduler_daemon_operator_control_policy(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "source_operator_control_policy_schema_version": _text_or_none(
            raw_value.get("operator_control_policy_schema_version")
        ),
        "operator_control_policy_id": _text_or_none(
            raw_value.get("operator_control_policy_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "supported_actions": [
            _project_retention_scheduler_daemon_operator_control_supported_action(
                item
            )
            for item in _list_value(raw_value.get("supported_actions"))
            if isinstance(item, Mapping)
        ],
        "required_fields": _select_mapping(
            raw_value.get("required_fields"),
            (
                "operator_subject",
                "idempotency_key",
                "reason",
                "approval_required_for_start",
                "approval_required_for_restart",
                "profile",
                "max_cycles",
            ),
        ),
        "profile_policy": _select_mapping(
            raw_value.get("profile_policy"),
            (
                "default_profile",
                "allowed_profiles",
                "production_profiles_allowed",
                "production_continuous_start_enabled",
            ),
        ),
        "restart_policy": _select_mapping(
            raw_value.get("restart_policy"),
            (
                "restart_daemon_supported",
                "restart_semantics",
                "requires_distinct_stop_evidence",
                "requires_distinct_start_evidence",
            ),
        ),
        "guardrails": _safe_operator_control_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _safe_operator_control_metadata(raw_value.get("metadata")),
    }


def _project_retention_scheduler_daemon_operator_control_supported_action(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "action": _normalized_daemon_operator_control_action(raw_value.get("action")),
        "mutates_process": raw_value.get("mutates_process") is True,
        "requires_approval": raw_value.get("requires_approval") is True,
        "requires_running_process": raw_value.get("requires_running_process") is True,
        "starts_process": raw_value.get("starts_process") is True,
        "stops_process": raw_value.get("stops_process") is True,
    }


def _project_retention_scheduler_daemon_operator_control_facade(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "source_operator_control_facade_schema_version": _text_or_none(
            raw_value.get("operator_control_facade_schema_version")
        ),
        "operator_control_facade_id": _text_or_none(
            raw_value.get("operator_control_facade_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "operator_control_policy_id": _text_or_none(
            raw_value.get("operator_control_policy_id")
        ),
        "operator_control_request_id": _text_or_none(
            raw_value.get("operator_control_request_id")
        ),
        "operator_control_admission_id": _text_or_none(
            raw_value.get("operator_control_admission_id")
        ),
        "operator_control_command_preview_id": _text_or_none(
            raw_value.get("operator_control_command_preview_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "facade_status": _normalized_operator_control_admission_status(
            raw_value.get("facade_status")
        ),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "operator_control_request": (
            _project_retention_scheduler_daemon_operator_control_request(
                raw_value.get("operator_control_request")
            )
        ),
        "operator_control_admission": (
            _project_retention_scheduler_daemon_operator_control_admission(
                raw_value.get("operator_control_admission")
            )
        ),
        "operator_control_command_preview": (
            _project_retention_scheduler_daemon_operator_control_command_preview(
                raw_value.get("operator_control_command_preview")
            )
        ),
        "guardrails": _safe_operator_control_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _safe_operator_control_metadata(raw_value.get("metadata")),
    }


def _project_retention_scheduler_daemon_operator_control_request(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "source_operator_control_request_schema_version": _text_or_none(
            raw_value.get("operator_control_request_schema_version")
        ),
        "operator_control_request_id": _text_or_none(
            raw_value.get("operator_control_request_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "operator_subject": _operator_control_safe_subject(
            raw_value.get("operator_subject")
        ),
        "idempotency_key_present": _present_text(raw_value.get("idempotency_key")),
        "reason_present": _present_text(raw_value.get("reason")),
        "requested_at": _text_or_none(raw_value.get("requested_at")),
        "profile": _text_or_none(raw_value.get("profile")),
        "enabled": raw_value.get("enabled") is True,
        "explicit_opt_in": raw_value.get("explicit_opt_in") is True,
        "max_cycles": _int_or_zero(raw_value.get("max_cycles")),
        "run_worker": raw_value.get("run_worker") is True,
        "approval": _select_mapping(
            raw_value.get("approval"),
            ("approved", "approved_by", "approved_at", "approval_reason"),
        ),
        "execution_intent": _select_mapping(
            raw_value.get("execution_intent"),
            (
                "action",
                "mutates_process",
                "reads_status",
                "requests_start",
                "requests_stop",
                "restart_decomposes_to_stop_then_start",
                "requires_running_process",
                "requires_bounded_subprocess_adapter",
                "starts_continuous_loop",
                "enqueues_job_queue",
                "runs_worker",
                "physical_delete_enabled",
            ),
        ),
        "guardrails": _safe_operator_control_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _safe_operator_control_metadata(raw_value.get("metadata")),
    }


def _project_retention_scheduler_daemon_operator_control_admission(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "source_operator_control_admission_schema_version": _text_or_none(
            raw_value.get("operator_control_admission_schema_version")
        ),
        "operator_control_admission_id": _text_or_none(
            raw_value.get("operator_control_admission_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "operator_control_request_id": _text_or_none(
            raw_value.get("operator_control_request_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "admission_status": _normalized_operator_control_admission_status(
            raw_value.get("admission_status")
        ),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "current_process": _project_retention_scheduler_daemon_operator_current_process(
            raw_value.get("current_process")
        ),
        "next_supervisor_actions": [
            _project_retention_scheduler_daemon_operator_next_supervisor_action(
                item
            )
            for item in _list_value(raw_value.get("next_supervisor_actions"))
            if isinstance(item, Mapping)
        ],
        "execution_intent": _select_mapping(
            raw_value.get("execution_intent"),
            (
                "action",
                "mutates_process",
                "reads_status",
                "requests_start",
                "requests_stop",
                "restart_decomposes_to_stop_then_start",
                "requires_running_process",
                "requires_bounded_subprocess_adapter",
                "starts_continuous_loop",
                "enqueues_job_queue",
                "runs_worker",
                "physical_delete_enabled",
            ),
        ),
        "guardrails": _safe_operator_control_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _safe_operator_control_metadata(raw_value.get("metadata")),
    }


def _project_retention_scheduler_daemon_operator_control_command_preview(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "source_operator_control_command_preview_schema_version": _text_or_none(
            raw_value.get("operator_control_command_preview_schema_version")
        ),
        "operator_control_command_preview_id": _text_or_none(
            raw_value.get("operator_control_command_preview_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "operator_control_admission_id": _text_or_none(
            raw_value.get("operator_control_admission_id")
        ),
        "operator_control_request_id": _text_or_none(
            raw_value.get("operator_control_request_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "preview_status": _normalized_operator_control_admission_status(
            raw_value.get("preview_status")
        ),
        "checked_at": _text_or_none(raw_value.get("checked_at")),
        "supervisor_command_previews": [
            _project_retention_scheduler_daemon_operator_supervisor_command_preview(
                item
            )
            for item in _list_value(raw_value.get("supervisor_command_previews"))
            if isinstance(item, Mapping)
        ],
        "guardrails": _safe_operator_control_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _safe_operator_control_metadata(raw_value.get("metadata")),
    }


def _project_retention_scheduler_daemon_operator_current_process(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "process_source": _text_or_none(raw_value.get("process_source")),
        "process_status": _normalized_daemon_supervised_process_status(
            raw_value.get("process_status")
        ),
        "process_running": raw_value.get("process_running") is True,
        "daemon_supervised_process_id": _text_or_none(
            raw_value.get("daemon_supervised_process_id")
        ),
        "daemon_supervisor_command_id": _text_or_none(
            raw_value.get("daemon_supervisor_command_id")
        ),
        "process_id": _int_or_zero(raw_value.get("process_id")),
        "host_id": _text_or_none(raw_value.get("host_id")),
        "observed_at": _text_or_none(raw_value.get("observed_at")),
    }


def _project_retention_scheduler_daemon_operator_next_supervisor_action(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "sequence": _int_or_zero(raw_value.get("sequence")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "mutates_process": raw_value.get("mutates_process") is True,
        "requires_distinct_evidence": (
            raw_value.get("requires_distinct_evidence") is True
        ),
        "requires_follow_up_admission": (
            raw_value.get("requires_follow_up_admission") is True
        ),
    }


def _project_retention_scheduler_daemon_operator_supervisor_command_preview(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    supervisor_command = _mapping_or_empty(raw_value.get("supervisor_command"))
    command_body = _mapping_or_empty(supervisor_command.get("command"))
    return {
        "sequence": _int_or_zero(raw_value.get("sequence")),
        "action": _normalized_daemon_supervisor_action(raw_value.get("action")),
        "requires_distinct_evidence": (
            raw_value.get("requires_distinct_evidence") is True
        ),
        "requires_follow_up_admission": (
            raw_value.get("requires_follow_up_admission") is True
        ),
        "supervisor_command_id": _text_or_none(
            supervisor_command.get("daemon_supervisor_command_id")
            or supervisor_command.get("supervisor_command_id")
        ),
        "supervisor_command_schema_version": _text_or_none(
            supervisor_command.get("daemon_supervisor_command_schema_version")
            or supervisor_command.get("supervisor_command_schema_version")
        ),
        "command_action": _normalized_daemon_supervisor_action(
            command_body.get("action") or supervisor_command.get("action")
        ),
        "command_enabled": command_body.get("enabled") is True,
        "command_explicit_opt_in": command_body.get("explicit_opt_in") is True,
        "command_max_cycles": _int_or_zero(command_body.get("max_cycles")),
        "command_run_worker": command_body.get("run_worker") is True,
    }


def _project_retention_scheduler_daemon_operator_control_execution_filter(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "execution_status": _normalized_operator_control_execution_status(
            raw_value.get("execution_status")
        ),
        "idempotency_status": _normalized_operator_control_idempotency_status(
            raw_value.get("idempotency_status")
        ),
    }


def _project_retention_scheduler_daemon_operator_control_execution_state_item(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    operator_control_execution_state_id = _text_or_none(
        record.get("operator_control_execution_state_id")
    )
    request_hash = _text_or_none(
        record.get("operator_control_execution_request_hash")
        or _mapping_or_empty(record.get("metadata")).get(
            "operator_control_execution_request_hash"
        )
    )
    return {
        "operator_control_execution_state_id": operator_control_execution_state_id,
        "source_operator_control_execution_state_schema_version": (
            _text_or_none(
                record.get("operator_control_execution_state_schema_version")
                or record.get("source_operator_control_execution_state_schema_version")
            )
        ),
        "service_id": _text_or_none(record.get("service_id")),
        "scheduler_id": _text_or_none(record.get("scheduler_id")),
        "operator_control_execution_request_id": _text_or_none(
            record.get("operator_control_execution_request_id")
        ),
        "operator_control_facade_id": _text_or_none(
            record.get("operator_control_facade_id")
        ),
        "operator_control_request_id": _text_or_none(
            record.get("operator_control_request_id")
        ),
        "operator_control_admission_id": _text_or_none(
            record.get("operator_control_admission_id")
        ),
        "operator_control_command_preview_id": _text_or_none(
            record.get("operator_control_command_preview_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            record.get("action")
        ),
        "execution_mode": _text_or_none(record.get("execution_mode")),
        "execution_status": _normalized_operator_control_execution_status(
            record.get("execution_status")
        ),
        "idempotency_status": _normalized_operator_control_idempotency_status(
            record.get("idempotency_status")
        ),
        "decision_reason": _text_or_none(record.get("decision_reason")),
        "observed_at": _text_or_none(record.get("observed_at")),
        "prior_execution_state_id": _text_or_none(
            record.get("prior_execution_state_id")
        ),
        "operator_control_execution_request_hash": request_hash,
        "allowed_next_statuses": _normalized_operator_control_execution_statuses(
            record.get("allowed_next_statuses")
        ),
        "summary": _safe_operator_control_execution_summary(
            record.get("summary")
        ),
        "metadata": _safe_operator_control_execution_metadata(
            record.get("metadata")
        ),
        "guardrails": _safe_operator_control_execution_guardrails(
            record.get("guardrails")
        ),
        "routes": {
            "ae_detail": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-executions/"
                f"{operator_control_execution_state_id}"
            )
            if operator_control_execution_state_id
            else None,
            "ag_detail": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-executions/"
                f"{operator_control_execution_state_id}"
            )
            if operator_control_execution_state_id
            else None,
        },
    }


def _project_retention_scheduler_daemon_operator_control_execution_state_record(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _project_retention_scheduler_daemon_operator_control_execution_state_item(
        raw_value
    )


def _project_retention_scheduler_daemon_operator_control_execution_transition(
    raw_value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_operator_control_execution_state_transition_schema_version": (
            _text_or_none(
                raw_value.get(
                    "operator_control_execution_state_transition_schema_version"
                )
                or raw_value.get(
                    "source_operator_control_execution_state_transition_schema_version"
                )
            )
        ),
        "operator_control_execution_state_transition_id": _text_or_none(
            raw_value.get("operator_control_execution_state_transition_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "operator_control_execution_state_id": _text_or_none(
            raw_value.get("operator_control_execution_state_id")
        ),
        "operator_control_execution_request_id": _text_or_none(
            raw_value.get("operator_control_execution_request_id")
        ),
        "from_status": _normalized_operator_control_execution_status(
            raw_value.get("from_status")
        ),
        "to_status": _normalized_operator_control_execution_status(
            raw_value.get("to_status")
        ),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "transitioned_at": _text_or_none(raw_value.get("transitioned_at")),
        "summary": _safe_operator_control_execution_summary(
            raw_value.get("summary")
        ),
        "metadata": _safe_operator_control_execution_metadata(
            raw_value.get("metadata")
        ),
        "guardrails": _safe_operator_control_execution_guardrails(
            raw_value.get("guardrails")
        ),
    }


def _project_retention_scheduler_daemon_operator_control_execution_worker_result(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    command = _mapping_or_empty(
        raw_value.get("operator_control_execution_worker_command")
    )
    worker_plan = _mapping_or_empty(
        command.get("operator_control_execution_worker_plan")
    )
    transition_plan = _mapping_or_empty(
        raw_value.get("operator_control_execution_worker_transition_plan")
    )
    raw_metadata = _mapping_or_empty(raw_value.get("metadata"))
    raw_guardrails = _mapping_or_empty(raw_value.get("guardrails"))
    supervisor_results = [
        result
        for result in _list_value(raw_value.get("supervisor_results"))
        if isinstance(result, Mapping)
    ]
    supervisor_result_statuses = _normalized_daemon_supervisor_result_statuses(
        raw_metadata.get("supervisor_result_statuses")
        or [result.get("result_status") for result in supervisor_results]
    )
    supervisor_actions = _normalized_daemon_supervisor_actions(
        raw_metadata.get("supervisor_actions")
        or [result.get("action") for result in supervisor_results]
    )
    supervisor_result_ids = _text_list(
        raw_metadata.get("supervisor_result_ids")
        or [result.get("daemon_supervisor_result_id") for result in supervisor_results]
    )
    status_path = _normalized_operator_control_execution_statuses(
        raw_metadata.get("status_path")
        or _mapping_or_empty(transition_plan.get("metadata")).get("status_path")
    )
    transition_count = _int_or_zero(
        raw_metadata.get("transition_count")
        or transition_plan.get("transition_count")
        or max(len(status_path) - 1, 0)
    )
    supervisor_result_count = _int_or_zero(
        raw_value.get("supervisor_result_count") or len(supervisor_results)
    )
    return {
        "source_operator_control_execution_worker_result_schema_version": (
            _text_or_none(
                raw_value.get("operator_control_execution_worker_result_schema_version")
                or raw_value.get(
                    "source_operator_control_execution_worker_result_schema_version"
                )
            )
        ),
        "operator_control_execution_worker_result_id": _text_or_none(
            raw_value.get("operator_control_execution_worker_result_id")
        ),
        "service_id": _text_or_none(raw_value.get("service_id")),
        "scheduler_id": _text_or_none(raw_value.get("scheduler_id")),
        "operator_control_execution_worker_command_id": _text_or_none(
            raw_value.get("operator_control_execution_worker_command_id")
        ),
        "operator_control_execution_worker_plan_id": _text_or_none(
            raw_value.get("operator_control_execution_worker_plan_id")
        ),
        "operator_control_execution_worker_transition_plan_id": _text_or_none(
            raw_value.get("operator_control_execution_worker_transition_plan_id")
        ),
        "operator_control_execution_state_id": _text_or_none(
            raw_value.get("operator_control_execution_state_id")
        ),
        "operator_control_execution_request_id": _text_or_none(
            raw_value.get("operator_control_execution_request_id")
        ),
        "action": _normalized_daemon_operator_control_action(
            raw_value.get("action")
        ),
        "execution_mode": _text_or_none(raw_value.get("execution_mode")),
        "worker_mode": _text_or_none(raw_value.get("worker_mode")),
        "worker_status": _normalized_operator_control_execution_worker_status(
            raw_value.get("worker_status")
        ),
        "decision_reason": _text_or_none(raw_value.get("decision_reason")),
        "observed_at": _text_or_none(raw_value.get("observed_at")),
        "worker_plan_status": _text_or_none(worker_plan.get("plan_status")),
        "worker_command_status": _text_or_none(command.get("command_status")),
        "transition_plan_status": _text_or_none(
            transition_plan.get("transition_plan_status")
            or raw_metadata.get("transition_plan_status")
        ),
        "transition_terminal_status": _normalized_operator_control_execution_status(
            transition_plan.get("terminal_status")
            or raw_metadata.get("transition_terminal_status")
        ),
        "transition_count": transition_count,
        "status_path": status_path,
        "supervisor_result_count": supervisor_result_count,
        "supervisor_result_statuses": supervisor_result_statuses,
        "supervisor_actions": supervisor_actions,
        "supervisor_result_ids": supervisor_result_ids,
        "metadata": _safe_operator_control_execution_worker_metadata(raw_metadata),
        "guardrails": _safe_operator_control_execution_worker_guardrails(
            raw_guardrails
        ),
        "routes": {
            "ae_worker": (
                "/api/v1/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
            "ag_worker": (
                "/admin/v1/operations/artifact-retention/"
                "scheduler-daemon-operator-control-execution-workers"
            ),
        },
    }


def _operator_control_safe_subject(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "actor_type",
            "actor_id",
            "tenant_id",
            "workspace_id",
            "service_id",
            "request_id",
        ),
    )


def _safe_operator_control_guardrails(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "metadata_only",
            "operator_subject_required",
            "idempotency_key_required",
            "operator_reason_required",
            "approval_required_for_start_restart",
            "approval_required",
            "test_profile_required",
            "explicit_opt_in_required_for_start_restart",
            "explicit_opt_in_required",
            "bounded_max_cycles_required",
            "status_probe_before_mutation_required",
            "restart_is_stop_then_start",
            "restart_decomposes_to_stop_then_start",
            "restart_requires_follow_up_admission",
            "production_continuous_start_enabled",
            "admission_only",
            "operator_request_validated",
            "current_process_metadata_only",
            "ready_allows_supervisor_dispatch",
            "supervisor_adapter_required",
            "preview_only",
            "policy_evaluated",
            "request_validated",
            "admission_evaluated",
            "command_preview_evaluated",
            "process_control_allowed",
            "contract_starts_process",
            "contract_stops_process",
            "supervisor_dispatch_performed",
            "supervisor_adapter_invoked",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "ag_direct_process_control_allowed",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "physical_delete_automation_enabled",
        ),
    )


def _safe_operator_control_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "safe_for_ag_projection",
            "metadata_only",
            "policy_contract_only",
            "admission_contract_only",
            "command_preview_contract_only",
            "route_facade",
            "preview_only",
            "scheduler_id",
            "action",
            "admission_status",
            "decision_reason",
            "approval_required",
            "approval_granted",
            "mutating_action",
            "ready_for_dispatch",
            "blocked",
            "noop",
            "command_preview_count",
            "supervisor_actions",
            "next_supervisor_action_count",
            "start_preview_count",
            "stop_preview_count",
            "status_probe_preview_count",
            "restart_preview",
            "supervisor_adapter_invoked",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "secrets_redacted",
        ),
    )


def _safe_operator_control_execution_summary(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "scheduler_id",
            "operator_control_execution_state_id",
            "operator_control_execution_request_id",
            "operator_control_execution_state_transition_id",
            "action",
            "execution_mode",
            "execution_status",
            "idempotency_status",
            "decision_reason",
            "allowed_next_statuses",
            "from_status",
            "to_status",
            "transitioned_at",
            "safe_for_ag_projection",
            "metadata_only",
        ),
    )


def _safe_operator_control_execution_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "safe_for_ag_projection",
            "metadata_only",
            "execution_state_machine_only",
            "execution_state_transition_only",
            "read_model",
            "item_count",
            "limit",
            "has_more",
            "newest_observed_at",
            "observed_at",
            "transitioned_at",
            "source_facade_status",
            "execution_mode",
            "execution_status",
            "idempotency_status",
            "idempotency_replayed",
            "idempotency_conflict",
            "prior_execution_state_id",
            "allowed_next_statuses",
            "supervisor_command_count",
            "supervisor_actions",
            "transition_count",
            "transition_statuses",
            "operator_control_execution_request_hash",
            "operator_control_execution_state_hash",
            "from_status",
            "to_status",
            "source_idempotency_status",
            "to_terminal",
            "supervisor_dispatch_performed",
            "supervisor_adapter_invoked",
            "supervisor_result_persisted",
            "supervisor_event_persisted",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "secrets_redacted",
        ),
    )


def _safe_operator_control_execution_guardrails(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return _select_mapping(
        raw_value,
        (
            "read_only",
            "ae_owned_persistence",
            "ae_owned_execution_state",
            "metadata_only",
            "state_machine_only",
            "state_transition_only",
            "operator_control_execution_request_validated",
            "source_state_validated",
            "idempotency_key_required",
            "idempotency_key_scoped_to_request",
            "idempotency_replay_blocks_duplicate_dispatch",
            "idempotency_conflict_blocks_dispatch",
            "admitted_allows_execution_transition",
            "executing_allows_terminal_transition",
            "terminal_state",
            "transition_allowed",
            "admitted_to_executing",
            "admitted_to_blocked",
            "executing_to_succeeded",
            "executing_to_failed",
            "supervisor_dispatch_performed",
            "supervisor_adapter_invoked",
            "supervisor_result_persisted",
            "supervisor_event_persisted",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "test_profile_required",
            "bounded_max_cycles_required",
            "restart_decomposes_to_stop_then_start",
            "storage_path_included",
            "raw_artifact_payload_included",
            "raw_execution_payload_included",
            "raw_daemon_runtime_payload_included",
            "raw_supervised_process_snapshot_included",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "ag_direct_process_control_allowed",
            "physical_delete_automation_enabled",
            "secrets_redacted",
        ),
    )


def _safe_operator_control_execution_worker_metadata(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    safe = _select_mapping(
        raw_value,
        (
            "safe_for_ag_projection",
            "metadata_only",
            "worker_result_only",
            "operator_control_execution_worker_command_hash",
            "operator_control_execution_worker_transition_plan_hash",
            "observed_at",
            "worker_status",
            "decision_reason",
            "transition_plan_status",
            "transition_terminal_status",
            "status_path",
            "supervisor_result_count",
            "supervisor_result_statuses",
            "supervisor_actions",
            "supervisor_result_ids",
            "supervisor_dispatch_performed",
            "supervisor_adapter_invoked",
            "supervisor_result_persisted",
            "supervisor_event_persisted",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "transition_persistence_performed",
            "physical_delete_automation_enabled",
            "secrets_redacted",
        ),
    )
    safe["persistence_endpoint_included"] = (
        raw_value.get("persistence_endpoint_included") is True
        or raw_value.get("database_url_included") is True
    )
    safe["storage_locator_included"] = (
        raw_value.get("storage_locator_included") is True
        or raw_value.get("storage_path_included") is True
    )
    safe["artifact_payload_included"] = (
        raw_value.get("artifact_payload_included") is True
        or raw_value.get("raw_artifact_payload_included") is True
    )
    safe["execution_payload_included"] = (
        raw_value.get("execution_payload_included") is True
        or raw_value.get("raw_execution_payload_included") is True
    )
    safe["daemon_runtime_payload_included"] = (
        raw_value.get("daemon_runtime_payload_included") is True
        or raw_value.get("raw_daemon_runtime_payload_included") is True
    )
    safe["supervised_process_snapshot_payload_included"] = (
        raw_value.get("supervised_process_snapshot_payload_included") is True
        or raw_value.get("raw_supervised_process_snapshot_included") is True
    )
    return safe


def _safe_operator_control_execution_worker_guardrails(
    raw_value: Any,
) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    safe = _select_mapping(
        raw_value,
        (
            "worker_result_only",
            "source_worker_command_validated",
            "source_transition_plan_validated",
            "requires_ready_worker_command",
            "source_worker_command_ready",
            "ready_transition_plan_required",
            "source_transition_plan_ready",
            "transition_terminal_matches_worker_status",
            "fake_dry_run_worker_only",
            "uses_existing_supervisor_runner",
            "uses_fake_supervisor_adapter_first",
            "supervisor_dispatch_performed",
            "supervisor_adapter_invoked",
            "supervisor_result_persisted",
            "supervisor_event_persisted",
            "subprocess_started",
            "subprocess_stopped",
            "database_write_performed",
            "job_queue_enqueue_performed",
            "worker_execution_performed",
            "transition_persistence_performed",
            "worker_succeeded",
            "worker_failed",
            "worker_blocked",
            "test_profile_required",
            "bounded_max_cycles_required",
            "ag_direct_database_write_allowed",
            "ag_direct_job_enqueue_allowed",
            "ag_direct_process_control_allowed",
            "physical_delete_automation_enabled",
            "secrets_redacted",
        ),
    )
    safe["persistence_endpoint_included"] = (
        raw_value.get("persistence_endpoint_included") is True
        or raw_value.get("database_url_included") is True
    )
    safe["storage_locator_included"] = (
        raw_value.get("storage_locator_included") is True
        or raw_value.get("storage_path_included") is True
    )
    safe["artifact_payload_included"] = (
        raw_value.get("artifact_payload_included") is True
        or raw_value.get("raw_artifact_payload_included") is True
    )
    safe["execution_payload_included"] = (
        raw_value.get("execution_payload_included") is True
        or raw_value.get("raw_execution_payload_included") is True
    )
    safe["daemon_runtime_payload_included"] = (
        raw_value.get("daemon_runtime_payload_included") is True
        or raw_value.get("raw_daemon_runtime_payload_included") is True
    )
    safe["supervised_process_snapshot_payload_included"] = (
        raw_value.get("supervised_process_snapshot_payload_included") is True
        or raw_value.get("raw_supervised_process_snapshot_included") is True
    )
    return safe


def _project_retention_history_item(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_retention_execution_history_item_schema_version": _text_or_none(
            record.get("artifact_retention_execution_history_item_schema_version")
        ),
        "retention_execution_id": _text_or_none(record.get("retention_execution_id")),
        "policy_id": _text_or_none(record.get("policy_id")),
        "service_id": _text_or_none(record.get("service_id")),
        "mode": _normalized_retention_mode(record.get("mode")),
        "execution_status": _normalized_retention_status(
            record.get("execution_status")
        ),
        "tenant_id": _text_or_none(record.get("tenant_id")),
        "workspace_id": _text_or_none(record.get("workspace_id")),
        "owner_user_id": _text_or_none(record.get("owner_user_id")),
        "retention_days_after_logical_purge": _int_or_zero(
            record.get("retention_days_after_logical_purge")
        ),
        "as_of": _text_or_none(record.get("as_of")),
        "cutoff_at": _text_or_none(record.get("cutoff_at")),
        "checked_at": _text_or_none(record.get("checked_at")),
        "scan_limit": _int_or_zero(record.get("scan_limit")),
        "max_delete_count": _int_or_zero(record.get("max_delete_count")),
        "candidate_count": _int_or_zero(record.get("candidate_count")),
        "selected_count": _int_or_zero(record.get("selected_count")),
        "delete_enabled": record.get("delete_enabled") is True,
        "storage_mutation_enabled": record.get("storage_mutation_enabled") is True,
        "database_row_delete_enabled": (
            record.get("database_row_delete_enabled") is True
        ),
        "deleted_counts": _safe_deleted_counts(record.get("deleted_counts")),
        "requested_by": _select_mapping(
            record.get("requested_by"),
            ("actor_type", "actor_id", "service_id"),
        ),
        "idempotency_key": _text_or_none(record.get("idempotency_key")),
        "trace_id": _text_or_none(record.get("trace_id")),
        "request_id": _text_or_none(record.get("request_id")),
        "blocked_reason": _text_or_none(record.get("blocked_reason")),
        "error": _select_mapping(record.get("error"), ("error_code", "detail")),
        "audit": _select_mapping(
            record.get("audit"),
            ("audit_event_type", "audit_event_id", "emitted"),
        ),
        "metadata": _select_mapping(
            record.get("metadata"),
            (
                "metadata_only",
                "candidate_scan_metadata_only",
                "logical_purge_required_before_physical_delete",
                "scheduled_batch_timezone",
                "scheduled_batch_window",
            ),
        ),
        "execution_payload_hash": _text_or_none(record.get("execution_payload_hash")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_handoff(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_handoff_id": _text_or_none(record.get("artifact_handoff_id")),
        "handoff_schema_version": _text_or_none(record.get("handoff_schema_version")),
        "handoff_status": _text_or_none(record.get("handoff_status")),
        "artifact_request_id": _text_or_none(record.get("artifact_request_id")),
        "artifact_intent": _text_or_none(record.get("artifact_intent")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_title": _text_or_none(record.get("artifact_title")),
        "cx_generation_id": _text_or_none(record.get("cx_generation_id")),
        "structured_draft_id": _text_or_none(record.get("structured_draft_id")),
        "structured_draft_content_hash": _text_or_none(
            record.get("structured_draft_content_hash")
        ),
        "generation_response_hash": _text_or_none(
            record.get("generation_response_hash")
        ),
        "target_formats": _text_list(record.get("target_formats")),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "workspace_ref": _select_mapping(
            record.get("workspace_ref"),
            ("workspace_id", "document_group_id", "chat_document_id"),
        ),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_chat_artifact_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chat_artifact_ref_id": _text_or_none(record.get("chat_artifact_ref_id")),
        "chat_interaction_id": _text_or_none(record.get("chat_interaction_id")),
        "chat_document_id": _text_or_none(record.get("chat_document_id")),
        "tenant_id": _text_or_none(record.get("tenant_id")),
        "user_id": _text_or_none(record.get("user_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "display_title": _text_or_none(record.get("display_title")),
        "artifact_type": _text_or_none(record.get("artifact_type")),
        "artifact_status": _text_or_none(record.get("artifact_status")),
        "primary_format": _text_or_none(record.get("primary_format")),
        "available_formats": _text_list(record.get("available_formats")),
        "preview_route": _safe_route(record.get("preview_route")),
        "download_routes": _safe_route_mapping(record.get("download_routes")),
        "source_generation_id": _text_or_none(record.get("source_generation_id")),
        "source_content_hash": _text_or_none(record.get("source_content_hash")),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
        "actions": _safe_action_mapping(record.get("actions")),
        "created_at": _text_or_none(record.get("created_at")),
        "updated_at": _text_or_none(record.get("updated_at")),
    }


def _project_source_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cx_generation_id": _text_or_none(record.get("cx_generation_id")),
        "structured_draft_id": _text_or_none(record.get("structured_draft_id")),
        "structured_draft_content_hash": _text_or_none(
            record.get("structured_draft_content_hash")
        ),
        "generation_response_hash": _text_or_none(
            record.get("generation_response_hash")
        ),
        "quality_summary": _safe_quality_summary(record.get("quality_summary")),
    }


def _project_version(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "version_no": _int_or_zero(record.get("version_no")),
        "version_reason": _text_or_none(record.get("version_reason")),
        "source_content_hash": _text_or_none(record.get("source_content_hash")),
        "artifact_content_hash": _text_or_none(record.get("artifact_content_hash")),
        "rendered_formats": _text_list(record.get("rendered_formats")),
        "validation_snapshot": _safe_quality_summary(record.get("validation_snapshot")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_render_job(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "render_job_id": _text_or_none(record.get("render_job_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "render_status": _text_or_none(record.get("render_status")),
        "renderer_policy_id": _text_or_none(record.get("renderer_policy_id")),
        "target_formats": _text_list(record.get("target_formats")),
        "failure_summary": _safe_quality_summary(record.get("failure_summary")),
        "started_at": _text_or_none(record.get("started_at")),
        "completed_at": _text_or_none(record.get("completed_at")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_file(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_file_id": _text_or_none(record.get("artifact_file_id")),
        "artifact_version_id": _text_or_none(record.get("artifact_version_id")),
        "artifact_id": _text_or_none(record.get("artifact_id")),
        "format": _text_or_none(record.get("format")),
        "mime_type": _text_or_none(record.get("mime_type")),
        "file_name": _text_or_none(record.get("file_name")),
        "file_hash": _text_or_none(record.get("file_hash")),
        "file_size_bytes": _int_or_zero(record.get("file_size_bytes")),
        "storage_ref": _safe_storage_ref(record.get("storage_ref")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _project_link(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_link_id": _text_or_none(record.get("artifact_link_id")),
        "artifact_file_id": _text_or_none(record.get("artifact_file_id")),
        "link_type": _text_or_none(record.get("link_type")),
        "link_route": _safe_route(record.get("link_route")),
        "expires_at": _text_or_none(record.get("expires_at")),
        "created_at": _text_or_none(record.get("created_at")),
    }


def _artifact_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    artifact_loaded: bool,
    handoff_loaded: bool,
    chat_artifact_ref_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    source = {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "artifact_loaded": artifact_loaded,
        "handoff_loaded": handoff_loaded,
        "chat_artifact_ref_count": chat_artifact_ref_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }
    return source


def _artifact_collection_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "collection_loaded": not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_lifecycle_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    artifact_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "artifact_loaded": artifact_loaded,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_history_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "history_loaded": not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_batch_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    plan_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "plan_loaded": plan_loaded and not errors,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_scheduled_job_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "jobs_loaded": not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_scheduled_dispatch_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    dispatch_response_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "dispatch_response_loaded": dispatch_response_loaded and not errors,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    config_loaded: bool,
    dispatch_response_loaded: bool,
    runtime_observation_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "daemon_config_loaded": config_loaded and not errors,
        "daemon_runtime_loaded": runtime_observation_loaded and not errors,
        "dispatch_response_loaded": dispatch_response_loaded and not errors,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_run_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    detail_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "run_collection_loaded": not errors,
        "run_detail_loaded": detail_loaded and not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_supervisor_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    detail_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "supervisor_collection_loaded": not errors,
        "supervisor_detail_loaded": detail_loaded and not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_supervised_process_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    detail_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "process_snapshot_collection_loaded": not errors,
        "process_snapshot_detail_loaded": detail_loaded and not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_operator_control_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    policy_loaded: bool,
    facade_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "operator_control_policy_loaded": policy_loaded and not errors,
        "operator_control_facade_loaded": facade_loaded and not errors,
        "preview_only": True,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_operator_control_execution_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    item_count: int,
    detail_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "execution_collection_loaded": not errors,
        "execution_detail_loaded": detail_loaded and not errors,
        "item_count": item_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_daemon_operator_control_execution_worker_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    worker_result_loaded: bool,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "execution_worker_result_loaded": worker_result_loaded and not errors,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
        ],
    }


def _artifact_retention_automation_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    batch_plan_loaded: bool,
    scheduled_job_count: int,
    history_count: int,
    daemon_config_loaded: bool,
    daemon_process_snapshot_count: int = 0,
    daemon_process_snapshots_loaded: bool = False,
    operator_control_policy_loaded: bool = False,
    operator_control_facade_loaded: bool = False,
    errors: list[AeArtifactOperationsError],
    daemon_process_errors: list[AeArtifactOperationsError] | None = None,
    operator_control_errors: list[AeArtifactOperationsError] | None = None,
) -> dict[str, Any]:
    process_errors = daemon_process_errors or []
    control_errors = operator_control_errors or []
    status = "DEGRADED" if errors or process_errors or control_errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "batch_plan_loaded": batch_plan_loaded and not errors,
        "scheduled_jobs_loaded": not errors,
        "history_loaded": not errors,
        "daemon_config_loaded": daemon_config_loaded and not errors,
        "daemon_process_snapshots_loaded": (
            daemon_process_snapshots_loaded and not errors and not process_errors
        ),
        "operator_control_policy_loaded": operator_control_policy_loaded
        and not errors,
        "operator_control_facade_loaded": (
            operator_control_facade_loaded and not errors and not control_errors
        ),
        "scheduled_job_count": scheduled_job_count,
        "history_count": history_count,
        "daemon_process_snapshot_count": daemon_process_snapshot_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in [*errors, *process_errors, *control_errors]
        ],
    }


def _validate_artifact_collection_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_scope_missing",
            title="Artifact collection scope is required",
            detail="Artifact collection queries require tenant, workspace, and owner scope.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-scope-missing"
            ),
        )

    normalized_status = _normalized_status(status)
    if (
        normalized_status is not None
        and normalized_status not in SUPPORTED_ARTIFACT_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_status_invalid",
            title="Invalid artifact collection status",
            detail="Artifact collection status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_collection_limit_invalid",
            title="Invalid artifact collection limit",
            detail=f"Artifact collection limit must be between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-collection-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_daemon_run_query(
    request: Request,
    *,
    scheduler_id: str | None,
    result_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    normalized_status = _normalized_daemon_result_status(result_status)
    if (
        _present_text(result_status)
        and normalized_status not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_RESULT_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_run_status_invalid",
            title="Invalid artifact retention daemon run status",
            detail=(
                "Artifact retention daemon run result_status must be one of "
                "SUCCEEDED, FAILED, STOPPED, or SKIPPED."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-run-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_run_limit_invalid",
            title="Invalid artifact retention daemon run limit",
            detail=(
                "Artifact retention daemon run limit must be between 1 and "
                f"{MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-run-limit-invalid"
            ),
        )

    return {
        "scheduler_id": _text_or_none(scheduler_id.strip() if scheduler_id else None),
        "result_status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_daemon_supervisor_query(
    request: Request,
    *,
    scheduler_id: str | None,
    action: str | None,
    result_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    normalized_action = _normalized_daemon_supervisor_action(action)
    if (
        _present_text(action)
        and normalized_action
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_ACTIONS
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_supervisor_action_invalid",
            title="Invalid artifact retention daemon supervisor action",
            detail=(
                "Artifact retention daemon supervisor action must be one of "
                "status_probe, start_daemon, or stop_daemon."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-supervisor-action-invalid"
            ),
        )

    normalized_status = _normalized_daemon_supervisor_result_status(result_status)
    if (
        _present_text(result_status)
        and normalized_status
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_RESULT_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_supervisor_status_invalid",
            title="Invalid artifact retention daemon supervisor status",
            detail=(
                "Artifact retention daemon supervisor result_status must be one "
                "of READY, BLOCKED, NOOP, or FAILED."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-supervisor-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_supervisor_limit_invalid",
            title="Invalid artifact retention daemon supervisor limit",
            detail=(
                "Artifact retention daemon supervisor limit must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-supervisor-limit-invalid"
            ),
        )

    return {
        "scheduler_id": _text_or_none(scheduler_id.strip() if scheduler_id else None),
        "action": normalized_action,
        "result_status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_daemon_supervised_process_query(
    request: Request,
    *,
    scheduler_id: str | None,
    action: str | None,
    process_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    normalized_action = _normalized_daemon_supervisor_action(action)
    if (
        _present_text(action)
        and normalized_action
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_ACTIONS
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_process_action_invalid",
            title="Invalid artifact retention daemon process action",
            detail=(
                "Artifact retention daemon process action must be one of "
                "status_probe, start_daemon, or stop_daemon."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-process-action-invalid"
            ),
        )

    normalized_status = _normalized_daemon_supervised_process_status(
        process_status
    )
    if (
        _present_text(process_status)
        and normalized_status
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISED_PROCESS_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_process_status_invalid",
            title="Invalid artifact retention daemon process status",
            detail=(
                "Artifact retention daemon process_status must be one of "
                "MISSING, START_REQUESTED, RUNNING, STOP_REQUESTED, STOPPED, "
                "EXITED, STALE, FAILED, or BLOCKED."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-process-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_process_limit_invalid",
            title="Invalid artifact retention daemon process limit",
            detail=(
                "Artifact retention daemon process limit must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-process-limit-invalid"
            ),
        )

    return {
        "scheduler_id": _text_or_none(scheduler_id.strip() if scheduler_id else None),
        "action": normalized_action,
        "process_status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_daemon_operator_control_execution_query(
    request: Request,
    *,
    scheduler_id: str | None,
    action: str | None,
    execution_status: str | None,
    idempotency_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    normalized_action = _normalized_daemon_operator_control_action(action)
    if (
        _present_text(action)
        and normalized_action
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_ACTIONS
    ):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_execution_action_invalid"
            ),
            title="Invalid artifact retention daemon operator-control execution action",
            detail=(
                "Artifact retention daemon operator-control execution action "
                "must be one of status_probe, start_daemon, stop_daemon, "
                "or restart_daemon."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-execution-action-invalid"
            ),
        )

    normalized_execution_status = _normalized_operator_control_execution_status(
        execution_status
    )
    if (
        _present_text(execution_status)
        and normalized_execution_status
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_execution_status_invalid"
            ),
            title="Invalid artifact retention daemon operator-control execution status",
            detail=(
                "Artifact retention daemon operator-control execution_status "
                "must be one of ADMITTED, EXECUTING, SUCCEEDED, FAILED, "
                "BLOCKED, or NOOP."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-execution-status-invalid"
            ),
        )

    normalized_idempotency_status = (
        _normalized_operator_control_idempotency_status(idempotency_status)
    )
    if (
        _present_text(idempotency_status)
        and normalized_idempotency_status
        not in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_IDEMPOTENCY_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_execution_idempotency_status_invalid"
            ),
            title=(
                "Invalid artifact retention daemon operator-control execution "
                "idempotency status"
            ),
            detail=(
                "Artifact retention daemon operator-control "
                "idempotency_status must be one of NEW, REPLAYED, or CONFLICT."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-execution-idempotency-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_execution_limit_invalid"
            ),
            title="Invalid artifact retention daemon operator-control execution limit",
            detail=(
                "Artifact retention daemon operator-control execution limit "
                "must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-execution-limit-invalid"
            ),
        )

    return {
        "scheduler_id": _text_or_none(scheduler_id.strip() if scheduler_id else None),
        "action": normalized_action,
        "execution_status": normalized_execution_status,
        "idempotency_status": normalized_idempotency_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_history_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    mode: str | None,
    execution_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_history_scope_missing",
            title="Artifact retention history scope is required",
            detail=(
                "Artifact retention history queries require tenant, workspace, "
                "and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-history-scope-missing"
            ),
        )

    normalized_mode = _normalized_retention_mode(mode)
    if (
        normalized_mode is not None
        and normalized_mode not in SUPPORTED_ARTIFACT_RETENTION_MODES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_history_mode_invalid",
            title="Invalid artifact retention history mode",
            detail="Artifact retention history mode must be DRY_RUN or EXECUTE.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-history-mode-invalid"
            ),
        )

    normalized_status = _normalized_retention_status(execution_status)
    if (
        normalized_status is not None
        and normalized_status not in SUPPORTED_ARTIFACT_RETENTION_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_history_status_invalid",
            title="Invalid artifact retention history status",
            detail="Artifact retention history execution status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-history-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_history_limit_invalid",
            title="Invalid artifact retention history limit",
            detail=(
                "Artifact retention history limit must be between 1 and "
                f"{MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-history-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "mode": normalized_mode,
        "execution_status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_batch_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    retention_days: str | None,
    scan_limit: str | None,
    max_delete_count: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_batch_scope_missing",
            title="Artifact retention batch scope is required",
            detail=(
                "Artifact retention batch plans require tenant, workspace, "
                "and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-batch-scope-missing"
            ),
        )

    normalized_retention_days = _retention_days_filter(retention_days)
    if normalized_retention_days is None and _present_text(retention_days):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_batch_retention_days_invalid",
            title="Invalid artifact retention days",
            detail="Artifact retention days must be between 1 and 365.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-batch-retention-days-invalid"
            ),
        )

    normalized_scan_limit = _collection_limit(scan_limit)
    if normalized_scan_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_batch_scan_limit_invalid",
            title="Invalid artifact retention batch scan limit",
            detail=(
                "Artifact retention batch scan limit must be between 1 and "
                f"{MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-batch-scan-limit-invalid"
            ),
        )

    normalized_max_delete_count = _collection_limit(max_delete_count)
    if normalized_max_delete_count is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_batch_delete_limit_invalid",
            title="Invalid artifact retention batch delete limit",
            detail=(
                "Artifact retention batch delete limit must be between 1 and "
                f"{MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-batch-delete-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "retention_days": normalized_retention_days,
        "scan_limit": normalized_scan_limit,
        "max_delete_count": normalized_max_delete_count,
    }


def _validate_artifact_retention_scheduled_job_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_job_scope_missing",
            title="Artifact retention scheduled job scope is required",
            detail=(
                "Artifact retention scheduled job queries require tenant, "
                "workspace, and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-job-scope-missing"
            ),
        )

    normalized_status = _normalized_job_status(status)
    if normalized_status is not None and normalized_status not in JOB_STATUSES:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_job_status_invalid",
            title="Invalid artifact retention scheduled job status",
            detail="Artifact retention scheduled job status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-job-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_job_limit_invalid",
            title="Invalid artifact retention scheduled job limit",
            detail=(
                "Artifact retention scheduled job limit must be between 1 and "
                f"{MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-job-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "status": normalized_status,
        "limit": normalized_limit,
    }


def _validate_artifact_retention_scheduled_dispatch_request(
    request: Request,
    *,
    payload: Any,
) -> dict[str, Any] | JSONResponse:
    if not isinstance(payload, Mapping):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_dispatch_invalid",
            title="Artifact retention scheduled dispatch request is invalid",
            detail="Artifact retention scheduled dispatch request must be an object.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-invalid"
            ),
        )
    if payload.get("confirm_dispatch") is not True:
        return problem_response(
            request,
            status_code=409,
            error_code=(
                "ag.ae_artifact_retention_scheduled_dispatch_confirmation_required"
            ),
            title="Artifact retention scheduled dispatch confirmation is required",
            detail="Artifact retention scheduled dispatch requires confirm_dispatch=true.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-confirmation-required"
            ),
        )

    required = {
        "tenant_id": payload.get("tenant_id"),
        "workspace_id": payload.get("workspace_id"),
        "owner_user_id": payload.get("owner_user_id"),
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_dispatch_scope_missing",
            title="Artifact retention scheduled dispatch scope is required",
            detail=(
                "Artifact retention scheduled dispatch requires tenant, "
                "workspace, and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-scope-missing"
            ),
        )

    trigger_type = _normalized_scheduled_trigger(
        payload.get("trigger_type") or "operator_dispatch"
    )
    if trigger_type is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_dispatch_trigger_invalid",
            title="Artifact retention scheduled dispatch trigger is invalid",
            detail="Artifact retention scheduled dispatch trigger is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-trigger-invalid"
            ),
        )

    retention_days = _retention_days_filter(
        _text_or_none(payload.get("retention_days"))
    )
    if retention_days is None and _present_text(payload.get("retention_days")):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_scheduled_dispatch_retention_days_invalid"
            ),
            title="Artifact retention scheduled dispatch retention days are invalid",
            detail="Artifact retention scheduled dispatch retention days must be 1-365.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-retention-days-invalid"
            ),
        )

    scan_limit = _collection_limit(_text_or_none(payload.get("scan_limit")))
    if scan_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_scheduled_dispatch_scan_limit_invalid",
            title="Artifact retention scheduled dispatch scan limit is invalid",
            detail=(
                "Artifact retention scheduled dispatch scan limit must be "
                f"between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-scan-limit-invalid"
            ),
        )

    max_delete_count = _collection_limit(_text_or_none(payload.get("max_delete_count")))
    if max_delete_count is None:
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_scheduled_dispatch_delete_limit_invalid"
            ),
            title="Artifact retention scheduled dispatch delete limit is invalid",
            detail=(
                "Artifact retention scheduled dispatch delete limit must be "
                f"between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-scheduled-dispatch-delete-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(payload["tenant_id"]).strip(),
        "workspace_id": str(payload["workspace_id"]).strip(),
        "owner_user_id": str(payload["owner_user_id"]).strip(),
        "retention_days": retention_days,
        "as_of": _text_or_none(payload.get("as_of")),
        "scan_limit": scan_limit,
        "max_delete_count": max_delete_count,
        "checked_at": _text_or_none(payload.get("checked_at")),
        "trigger_type": trigger_type,
        "requested_at": _text_or_none(payload.get("requested_at")),
        "idempotency_key": _text_or_none(payload.get("idempotency_key")),
        "confirm_dispatch": True,
    }


def _validate_artifact_retention_daemon_manual_tick_request(
    request: Request,
    *,
    payload: Any,
    idempotency_key_header: str | None,
) -> dict[str, Any] | JSONResponse:
    if not isinstance(payload, Mapping):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_manual_tick_invalid",
            title="Artifact retention daemon manual tick request is invalid",
            detail="Artifact retention daemon manual tick request must be an object.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-invalid"
            ),
        )
    if payload.get("confirm_dispatch") is not True:
        return problem_response(
            request,
            status_code=409,
            error_code=(
                "ag.ae_artifact_retention_daemon_manual_tick_confirmation_required"
            ),
            title="Artifact retention daemon manual tick confirmation is required",
            detail=(
                "Artifact retention daemon manual tick requires "
                "confirm_dispatch=true."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-confirmation-required"
            ),
        )

    action = _normalized_daemon_action(payload.get("action") or "manual_tick_once")
    if action != "manual_tick_once":
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_manual_tick_action_invalid",
            title="Artifact retention daemon manual tick action is invalid",
            detail=(
                "Artifact retention daemon manual tick route only supports "
                "manual_tick_once."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-action-invalid"
            ),
        )

    required = {
        "tenant_id": payload.get("tenant_id"),
        "workspace_id": payload.get("workspace_id"),
        "owner_user_id": payload.get("owner_user_id"),
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_manual_tick_scope_missing",
            title="Artifact retention daemon manual tick scope is required",
            detail=(
                "Artifact retention daemon manual tick requires tenant, "
                "workspace, and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-scope-missing"
            ),
        )

    retention_days = _retention_days_filter(
        _text_or_none(payload.get("retention_days"))
    )
    if retention_days is None and _present_text(payload.get("retention_days")):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_manual_tick_retention_days_invalid"
            ),
            title="Artifact retention daemon manual tick retention days are invalid",
            detail="Artifact retention daemon manual tick retention days must be 1-365.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-retention-days-invalid"
            ),
        )

    scan_limit = _collection_limit(_text_or_none(payload.get("scan_limit")))
    if scan_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_manual_tick_scan_limit_invalid",
            title="Artifact retention daemon manual tick scan limit is invalid",
            detail=(
                "Artifact retention daemon manual tick scan limit must be "
                f"between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-scan-limit-invalid"
            ),
        )

    max_delete_count = _collection_limit(_text_or_none(payload.get("max_delete_count")))
    if max_delete_count is None:
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_manual_tick_delete_limit_invalid"
            ),
            title="Artifact retention daemon manual tick delete limit is invalid",
            detail=(
                "Artifact retention daemon manual tick delete limit must be "
                f"between 1 and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-delete-limit-invalid"
            ),
        )

    run_worker_raw = payload.get("run_worker")
    if run_worker_raw is not None and not isinstance(run_worker_raw, bool):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_manual_tick_worker_flag_invalid"
            ),
            title="Artifact retention daemon manual tick worker flag is invalid",
            detail="Artifact retention daemon manual tick run_worker must be boolean.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-worker-flag-invalid"
            ),
        )
    run_worker = run_worker_raw is True
    if run_worker and payload.get("confirm_worker_run") is not True:
        return problem_response(
            request,
            status_code=409,
            error_code=(
                "ag.ae_artifact_retention_daemon_manual_tick_worker_confirmation_required"
            ),
            title="Artifact retention daemon manual tick worker confirmation is required",
            detail=(
                "Artifact retention daemon manual tick with run_worker=true "
                "requires confirm_worker_run=true."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-manual-tick-worker-confirmation-required"
            ),
        )

    header_key = _text_or_none(idempotency_key_header)
    payload_key = _text_or_none(payload.get("idempotency_key"))
    idempotency_key = header_key if _present_text(header_key) else payload_key
    tenant_id = str(payload["tenant_id"]).strip()
    workspace_id = str(payload["workspace_id"]).strip()
    return {
        "action": "manual_tick_once",
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": str(payload["owner_user_id"]).strip(),
        "retention_days": retention_days,
        "as_of": _text_or_none(payload.get("as_of")),
        "scan_limit": scan_limit,
        "max_delete_count": max_delete_count,
        "requested_at": _text_or_none(payload.get("requested_at")),
        "requested_by": _artifact_retention_daemon_requested_by(
            request=request,
            payload=payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        ),
        "reason": _text_or_none(payload.get("reason")),
        "tick_at": _text_or_none(payload.get("tick_at")),
        "run_worker": run_worker,
        "worker_id": _text_or_none(payload.get("worker_id")),
        "idempotency_key": idempotency_key,
        "confirm_dispatch": True,
        "confirm_worker_run": payload.get("confirm_worker_run") is True,
    }


def _artifact_retention_daemon_requested_by(
    *,
    request: Request,
    payload: Mapping[str, Any],
    tenant_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    requested_by = _select_mapping(
        payload.get("requested_by"),
        (
            "actor_type",
            "actor_id",
            "tenant_id",
            "workspace_id",
            "request_id",
            "service_id",
        ),
    )
    if requested_by:
        return requested_by
    return {
        "actor_type": "operator",
        "actor_id": "nex-ag-artifact-retention-operator",
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "request_id": request_id_from_headers(request),
        "service_id": "nex-ag",
    }


def _artifact_retention_daemon_operator_subject(
    *,
    request: Request,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    operator_subject = _operator_control_safe_subject(
        payload.get("operator_subject")
    )
    if operator_subject:
        return operator_subject
    requested_by = _operator_control_safe_subject(payload.get("requested_by"))
    if requested_by:
        return requested_by
    return {
        "actor_type": "operator",
        "actor_id": "nex-ag-artifact-retention-operator",
        "request_id": request_id_from_headers(request),
        "service_id": "nex-ag",
    }


def _validate_artifact_retention_daemon_operator_control_preview_request(
    request: Request,
    *,
    payload: Any,
    idempotency_key_header: str | None,
) -> dict[str, Any] | JSONResponse:
    if not isinstance(payload, Mapping):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_operator_control_invalid",
            title="Artifact retention daemon operator control request is invalid",
            detail="Artifact retention daemon operator control request must be an object.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-invalid"
            ),
        )

    action = _normalized_daemon_operator_control_action(
        payload.get("action") or "status_probe"
    )
    if action is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_operator_control_action_invalid",
            title="Artifact retention daemon operator control action is invalid",
            detail=(
                "Artifact retention daemon operator control action must be "
                "status_probe, start_daemon, stop_daemon, or restart_daemon."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-action-invalid"
            ),
        )

    reason = _text_or_none(payload.get("reason"))
    if not _present_text(reason):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_daemon_operator_control_reason_missing",
            title="Artifact retention daemon operator control reason is required",
            detail="Artifact retention daemon operator control preview requires reason.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-reason-missing"
            ),
        )

    header_key = _text_or_none(idempotency_key_header)
    payload_key = _text_or_none(payload.get("idempotency_key"))
    idempotency_key = header_key if _present_text(header_key) else payload_key
    if not _present_text(idempotency_key):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_idempotency_key_missing"
            ),
            title="Artifact retention daemon operator control idempotency key is required",
            detail=(
                "Artifact retention daemon operator control preview requires "
                "an Idempotency-Key header or payload idempotency_key."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-idempotency-key-missing"
            ),
        )

    enabled = _operator_control_bool_field(
        request,
        payload=payload,
        field_name="enabled",
        default=False,
    )
    if isinstance(enabled, JSONResponse):
        return enabled
    explicit_opt_in = _operator_control_bool_field(
        request,
        payload=payload,
        field_name="explicit_opt_in",
        default=False,
    )
    if isinstance(explicit_opt_in, JSONResponse):
        return explicit_opt_in
    run_worker = _operator_control_bool_field(
        request,
        payload=payload,
        field_name="run_worker",
        default=False,
    )
    if isinstance(run_worker, JSONResponse):
        return run_worker

    max_cycles = _operator_control_max_cycles(
        request,
        payload.get("max_cycles", 1),
    )
    if isinstance(max_cycles, JSONResponse):
        return max_cycles

    current_process = payload.get("current_process")
    if current_process is not None and not isinstance(current_process, Mapping):
        return problem_response(
            request,
            status_code=400,
            error_code=(
                "ag.ae_artifact_retention_daemon_operator_control_current_process_invalid"
            ),
            title="Artifact retention daemon operator control current process is invalid",
            detail=(
                "Artifact retention daemon operator control current_process "
                "must be an object when supplied."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-daemon-operator-control-current-process-invalid"
            ),
        )

    return {
        "action": action,
        "operator_subject": _artifact_retention_daemon_operator_subject(
            request=request,
            payload=payload,
        ),
        "idempotency_key": str(idempotency_key).strip(),
        "reason": str(reason).strip(),
        "requested_at": _text_or_none(payload.get("requested_at")),
        "checked_at": _text_or_none(payload.get("checked_at")),
        "profile": _text_or_none(payload.get("profile")) or "test",
        "enabled": enabled,
        "explicit_opt_in": explicit_opt_in,
        "max_cycles": max_cycles,
        "run_worker": run_worker,
        "approval": payload.get("approval")
        if isinstance(payload.get("approval"), Mapping)
        else None,
        "current_process": dict(current_process)
        if isinstance(current_process, Mapping)
        else None,
    }


def _operator_control_bool_field(
    request: Request,
    *,
    payload: Mapping[str, Any],
    field_name: str,
    default: bool,
) -> bool | JSONResponse:
    if field_name not in payload or payload[field_name] is None:
        return default
    value = payload[field_name]
    if isinstance(value, bool):
        return value
    return problem_response(
        request,
        status_code=400,
        error_code=(
            "ag.ae_artifact_retention_daemon_operator_control_boolean_invalid"
        ),
        title="Artifact retention daemon operator control boolean is invalid",
        detail=(
            "Artifact retention daemon operator control "
            f"{field_name} must be boolean."
        ),
        type_uri=(
            "https://nex-platform.local/problems/"
            "ae-artifact-retention-daemon-operator-control-boolean-invalid"
        ),
    )


def _operator_control_max_cycles(
    request: Request,
    raw_value: Any,
) -> int | JSONResponse:
    try:
        max_cycles = int(raw_value)
    except (TypeError, ValueError):
        max_cycles = 0
    if 1 <= max_cycles <= 100:
        return max_cycles
    return problem_response(
        request,
        status_code=400,
        error_code=(
            "ag.ae_artifact_retention_daemon_operator_control_max_cycles_invalid"
        ),
        title="Artifact retention daemon operator control max cycles are invalid",
        detail="Artifact retention daemon operator control max_cycles must be 1-100.",
        type_uri=(
            "https://nex-platform.local/problems/"
            "ae-artifact-retention-daemon-operator-control-max-cycles-invalid"
        ),
    )


def _validate_artifact_retention_automation_query(
    request: Request,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    retention_days: str | None,
    scan_limit: str | None,
    max_delete_count: str | None,
    scheduled_status: str | None,
    history_mode: str | None,
    history_status: str | None,
    limit: str | None,
) -> dict[str, Any] | JSONResponse:
    required = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    missing = [name for name, value in required.items() if not _present_text(value)]
    if missing:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_scope_missing",
            title="Artifact retention automation scope is required",
            detail=(
                "Artifact retention automation queries require tenant, "
                "workspace, and owner scope."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-scope-missing"
            ),
        )

    normalized_retention_days = _retention_days_filter(retention_days)
    if normalized_retention_days is None and _present_text(retention_days):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_retention_days_invalid",
            title="Invalid artifact retention automation retention days",
            detail="Artifact retention automation retention days must be 1-365.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-retention-days-invalid"
            ),
        )

    normalized_scan_limit = _collection_limit(scan_limit)
    if normalized_scan_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_scan_limit_invalid",
            title="Invalid artifact retention automation scan limit",
            detail=(
                "Artifact retention automation scan limit must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-scan-limit-invalid"
            ),
        )

    normalized_max_delete_count = _collection_limit(max_delete_count)
    if normalized_max_delete_count is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_delete_limit_invalid",
            title="Invalid artifact retention automation delete limit",
            detail=(
                "Artifact retention automation delete limit must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-delete-limit-invalid"
            ),
        )

    normalized_scheduled_status = _normalized_job_status(scheduled_status)
    if (
        normalized_scheduled_status is not None
        and normalized_scheduled_status not in JOB_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_job_status_invalid",
            title="Invalid artifact retention automation job status",
            detail="Artifact retention automation scheduled job status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-job-status-invalid"
            ),
        )

    normalized_history_mode = _normalized_retention_mode(history_mode)
    if (
        normalized_history_mode is not None
        and normalized_history_mode not in SUPPORTED_ARTIFACT_RETENTION_MODES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_history_mode_invalid",
            title="Invalid artifact retention automation history mode",
            detail="Artifact retention automation history mode must be DRY_RUN or EXECUTE.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-history-mode-invalid"
            ),
        )

    normalized_history_status = _normalized_retention_status(history_status)
    if (
        normalized_history_status is not None
        and normalized_history_status not in SUPPORTED_ARTIFACT_RETENTION_STATUSES
    ):
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_history_status_invalid",
            title="Invalid artifact retention automation history status",
            detail="Artifact retention automation history status is not supported.",
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-history-status-invalid"
            ),
        )

    normalized_limit = _collection_limit(limit)
    if normalized_limit is None:
        return problem_response(
            request,
            status_code=400,
            error_code="ag.ae_artifact_retention_automation_limit_invalid",
            title="Invalid artifact retention automation limit",
            detail=(
                "Artifact retention automation limit must be between 1 "
                f"and {MAX_ARTIFACT_COLLECTION_LIMIT}."
            ),
            type_uri=(
                "https://nex-platform.local/problems/"
                "ae-artifact-retention-automation-limit-invalid"
            ),
        )

    return {
        "tenant_id": str(tenant_id).strip(),
        "workspace_id": str(workspace_id).strip(),
        "owner_user_id": str(owner_user_id).strip(),
        "retention_days": normalized_retention_days,
        "scan_limit": normalized_scan_limit,
        "max_delete_count": normalized_max_delete_count,
        "scheduled_status": normalized_scheduled_status,
        "history_mode": normalized_history_mode,
        "history_status": normalized_history_status,
        "limit": normalized_limit,
    }


def _artifact_collection_cache_key(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
    limit: int,
) -> str:
    return "|".join((tenant_id, workspace_id, owner_user_id, status or "", str(limit)))


def _artifact_retention_history_cache_key(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    mode: str | None,
    execution_status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            tenant_id,
            workspace_id,
            owner_user_id,
            _normalized_retention_mode(mode) or "",
            _normalized_retention_status(execution_status) or "",
            str(limit),
        )
    )


def _artifact_retention_batch_plan_cache_key(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    retention_days: int | None,
    as_of: str | None,
    scan_limit: int,
    max_delete_count: int,
    checked_at: str | None,
) -> str:
    return "|".join(
        (
            tenant_id,
            workspace_id,
            owner_user_id,
            str(retention_days or ""),
            as_of or "",
            str(scan_limit),
            str(max_delete_count),
            checked_at or "",
        )
    )


def _artifact_retention_scheduled_job_cache_key(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            tenant_id,
            workspace_id,
            owner_user_id,
            _normalized_job_status(status) or "",
            str(limit),
        )
    )


def _artifact_retention_scheduled_dispatch_cache_key(
    *,
    plan_id: str | None,
    trigger_type: str,
    idempotency_key: str | None,
) -> str:
    return "|".join((plan_id or "", trigger_type, idempotency_key or ""))


def _artifact_retention_scheduler_daemon_dispatch_cache_key(
    *,
    action: str,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    idempotency_key: str | None,
) -> str:
    return "|".join(
        (
            _normalized_daemon_action(action) or "",
            tenant_id or "",
            workspace_id or "",
            owner_user_id or "",
            idempotency_key or "",
        )
    )


def _artifact_retention_scheduler_daemon_run_cache_key(
    *,
    scheduler_id: str | None,
    result_status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            _text_or_none(scheduler_id) or "",
            _normalized_daemon_result_status(result_status) or "",
            str(limit),
        )
    )


def _artifact_retention_scheduler_daemon_supervisor_cache_key(
    *,
    scheduler_id: str | None,
    action: str | None,
    result_status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            _text_or_none(scheduler_id) or "",
            _normalized_daemon_supervisor_action(action) or "",
            _normalized_daemon_supervisor_result_status(result_status) or "",
            str(limit),
        )
    )


def _artifact_retention_scheduler_daemon_process_snapshot_cache_key(
    *,
    scheduler_id: str | None,
    action: str | None,
    process_status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            _text_or_none(scheduler_id) or "",
            _normalized_daemon_supervisor_action(action) or "",
            _normalized_daemon_supervised_process_status(process_status) or "",
            str(limit),
        )
    )


def _artifact_retention_scheduler_daemon_operator_control_preview_cache_key(
    *,
    action: str,
    idempotency_key: str | None,
    checked_at: str | None,
) -> str:
    return "|".join(
        (
            _normalized_daemon_operator_control_action(action) or "",
            idempotency_key or "",
            checked_at or "",
        )
    )


def _artifact_retention_scheduler_daemon_operator_control_execution_cache_key(
    *,
    scheduler_id: str | None,
    action: str | None,
    execution_status: str | None,
    idempotency_status: str | None,
    limit: int,
) -> str:
    return "|".join(
        (
            _text_or_none(scheduler_id) or "",
            _normalized_daemon_operator_control_action(action) or "",
            _normalized_operator_control_execution_status(execution_status) or "",
            _normalized_operator_control_idempotency_status(idempotency_status) or "",
            str(limit),
        )
    )


def _artifact_retention_scheduler_daemon_operator_control_execution_worker_cache_key(
    *,
    operator_control_execution_state_id: str | None,
    checked_at: str | None,
    worker_observed_at: str | None,
) -> str:
    return "|".join(
        (
            _text_or_none(operator_control_execution_state_id) or "",
            _text_or_none(checked_at) or "",
            _text_or_none(worker_observed_at) or "",
        )
    )


def _empty_artifact_retention_batch_plan_payload(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    retention_days: int | None,
    as_of: str | None,
    scan_limit: int,
    max_delete_count: int,
    checked_at: str | None,
) -> dict[str, Any]:
    effective_retention_days = retention_days or 30
    effective_as_of = as_of or "1970-01-01T00:00:00Z"
    effective_checked_at = checked_at or effective_as_of
    return {
        "artifact_retention_batch_plan_schema_version": (
            "ae_artifact_retention_batch_plan.v1"
        ),
        "plan_id": (
            "retention-batch-plan-empty:" f"{tenant_id}:{workspace_id}:{owner_user_id}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "schedule": {
            "schedule_id": "ae-artifact-retention-schedule-local-v1",
            "policy_id": "ae-artifact-logical-purge-30d-local-v1",
            "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "enabled": False,
            "planning_enabled": True,
            "default_mode": "DRY_RUN",
            "allowed_modes": list(SUPPORTED_ARTIFACT_RETENTION_MODES),
            "retention_days_presets": [15, 30],
            "default_retention_days_after_logical_purge": 30,
            "max_scan_limit": MAX_ARTIFACT_COLLECTION_LIMIT,
            "max_delete_count": MAX_ARTIFACT_COLLECTION_LIMIT,
            "timezone": "Asia/Seoul",
            "batch_window": {
                "start_local_time": "02:00",
                "end_local_time": "05:00",
            },
            "scheduler": {"daemon_enabled": False},
            "execution_guards": {
                "delete_enabled": False,
                "storage_mutation_enabled": False,
                "database_row_delete_enabled": False,
            },
            "ownership": {"system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID},
        },
        "candidate_filter": {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "status": "DELETED",
            "retention_days": effective_retention_days,
            "as_of": effective_as_of,
            "cutoff_at": effective_as_of,
            "limit": scan_limit,
            "dry_run": True,
        },
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "mode": "DRY_RUN",
        "plan_status": "NOOP",
        "scheduler_status": "DISABLED",
        "execution_advice": "No eligible artifacts are currently selected.",
        "as_of": effective_as_of,
        "cutoff_at": effective_as_of,
        "checked_at": effective_checked_at,
        "scan_limit": scan_limit,
        "max_delete_count": max_delete_count,
        "candidate_count": 0,
        "selected_count": 0,
        "unselected_count": 0,
        "estimated_deleted_counts": {
            "artifacts": 0,
            "source_refs": 0,
            "versions": 0,
            "render_jobs": 0,
            "files": 0,
            "links": 0,
            "storage_files": 0,
        },
        "selected_candidates": [],
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        },
        "idempotency_key": None,
        "metadata": {
            "metadata_only": True,
            "dry_run": True,
            "physical_delete_executed": False,
            "storage_mutation_executed": False,
            "database_row_delete_executed": False,
            "history_write_executed": False,
            "source_collection_count": 0,
        },
    }


def _empty_artifact_retention_scheduler_daemon_run_collection_payload(
    *,
    scheduler_id: str | None,
    result_status: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "daemon_run_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_run_collection.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "filter": {
            "scheduler_id": _text_or_none(scheduler_id),
            "result_status": _normalized_daemon_result_status(result_status),
        },
        "count": 0,
        "limit": limit,
        "items": [],
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": "ae_artifact_retention_scheduler_daemon_runs",
            "item_count": 0,
            "limit": limit,
            "has_more": False,
            "newest_completed_at": None,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def _empty_artifact_retention_scheduler_daemon_supervisor_collection_payload(
    *,
    scheduler_id: str | None,
    action: str | None,
    result_status: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "daemon_supervisor_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_supervisor_collection.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "filter": {
            "scheduler_id": _text_or_none(scheduler_id),
            "action": _normalized_daemon_supervisor_action(action),
            "result_status": _normalized_daemon_supervisor_result_status(
                result_status
            ),
        },
        "count": 0,
        "limit": limit,
        "items": [],
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_supervisor_results"
            ),
            "item_count": 0,
            "limit": limit,
            "has_more": False,
            "newest_observed_at": None,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def _empty_artifact_retention_scheduler_daemon_process_snapshot_collection_payload(
    *,
    scheduler_id: str | None,
    action: str | None,
    process_status: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "daemon_supervised_process_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_process_snapshot_collection.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "filter": {
            "scheduler_id": _text_or_none(scheduler_id),
            "action": _normalized_daemon_supervisor_action(action),
            "process_status": _normalized_daemon_supervised_process_status(
                process_status
            ),
        },
        "count": 0,
        "limit": limit,
        "items": [],
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "process_control_allowed": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "read_model": (
                "ae_artifact_retention_scheduler_daemon_process_snapshots"
            ),
            "item_count": 0,
            "limit": limit,
            "has_more": False,
            "newest_observed_at": None,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
        },
    }


def _empty_artifact_retention_scheduler_daemon_operator_control_execution_collection_payload(
    *,
    scheduler_id: str | None,
    action: str | None,
    execution_status: str | None,
    idempotency_status: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "operator_control_execution_collection_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_collection.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "filter": {
            "scheduler_id": _text_or_none(scheduler_id),
            "action": _normalized_daemon_operator_control_action(action),
            "execution_status": _normalized_operator_control_execution_status(
                execution_status
            ),
            "idempotency_status": _normalized_operator_control_idempotency_status(
                idempotency_status
            ),
        },
        "count": 0,
        "limit": limit,
        "items": [],
        "guardrails": {
            "read_only": True,
            "ae_owned_persistence": True,
            "ae_owned_execution_state": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "supervisor_dispatch_performed": False,
            "physical_delete_automation_enabled": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "raw_daemon_runtime_payload_included": False,
            "raw_supervised_process_snapshot_included": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "read_model": "ae_daemon_operator_control_execution_states",
            "item_count": 0,
            "limit": limit,
            "has_more": False,
            "newest_observed_at": None,
            "supervisor_dispatch_performed": False,
            "secrets_redacted": True,
        },
    }


def _empty_artifact_retention_scheduler_daemon_operator_control_execution_worker_payload(
    *,
    operator_control_execution_state_id: str | None,
    operator_control_execution_state: Mapping[str, Any],
    checked_at: str | None,
    worker_observed_at: str | None,
) -> dict[str, Any]:
    state = _mapping_or_empty(operator_control_execution_state)
    state_id = _text_or_none(
        operator_control_execution_state_id
        or state.get("operator_control_execution_state_id")
    )
    observed_at = worker_observed_at or checked_at or state.get("observed_at")
    scheduler_id = (
        _text_or_none(state.get("scheduler_id"))
        or "ae-artifact-retention-scheduler"
    )
    action = _normalized_daemon_operator_control_action(
        state.get("action")
    ) or "status_probe"
    return {
        "operator_control_execution_worker_result_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result.v1"
        ),
        "operator_control_execution_worker_result_id": (
            f"operator-control-execution-worker-result-empty:{state_id or 'missing'}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "operator_control_execution_worker_command_id": None,
        "operator_control_execution_worker_plan_id": None,
        "operator_control_execution_worker_transition_plan_id": None,
        "operator_control_execution_state_id": state_id,
        "operator_control_execution_request_id": _text_or_none(
            state.get("operator_control_execution_request_id")
        ),
        "action": action,
        "execution_mode": _text_or_none(state.get("execution_mode")),
        "worker_mode": "fake_dry_run_supervisor_dispatch",
        "worker_status": "BLOCKED",
        "decision_reason": "operator_control_execution_worker_result_missing",
        "observed_at": _text_or_none(observed_at),
        "supervisor_result_count": 0,
        "supervisor_results": [],
        "guardrails": {
            "worker_result_only": True,
            "source_worker_command_validated": False,
            "source_transition_plan_validated": False,
            "requires_ready_worker_command": True,
            "source_worker_command_ready": False,
            "ready_transition_plan_required": True,
            "source_transition_plan_ready": False,
            "transition_terminal_matches_worker_status": False,
            "fake_dry_run_worker_only": True,
            "uses_existing_supervisor_runner": False,
            "uses_fake_supervisor_adapter_first": True,
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "supervisor_result_persisted": False,
            "supervisor_event_persisted": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "transition_persistence_performed": False,
            "worker_succeeded": False,
            "worker_failed": False,
            "worker_blocked": True,
            "test_profile_required": True,
            "bounded_max_cycles_required": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "ag_direct_process_control_allowed": False,
            "physical_delete_automation_enabled": False,
            "secrets_redacted": True,
        },
        "metadata": {
            "safe_for_ag_projection": True,
            "metadata_only": True,
            "worker_result_only": True,
            "observed_at": _text_or_none(observed_at),
            "worker_status": "BLOCKED",
            "decision_reason": "operator_control_execution_worker_result_missing",
            "transition_plan_status": None,
            "transition_terminal_status": "BLOCKED",
            "status_path": [],
            "supervisor_result_count": 0,
            "supervisor_result_statuses": [],
            "supervisor_actions": [],
            "supervisor_result_ids": [],
            "supervisor_dispatch_performed": False,
            "supervisor_adapter_invoked": False,
            "supervisor_result_persisted": False,
            "supervisor_event_persisted": False,
            "subprocess_started": False,
            "subprocess_stopped": False,
            "database_write_performed": False,
            "job_queue_enqueue_performed": False,
            "worker_execution_performed": False,
            "transition_persistence_performed": False,
            "physical_delete_automation_enabled": False,
            "secrets_redacted": True,
        },
    }


def _empty_artifact_retention_scheduler_daemon_operator_control_policy_payload(
    *,
    checked_at: str | None,
) -> dict[str, Any]:
    effective_checked_at = checked_at or "2026-09-01T00:00:00Z"
    return {
        "operator_control_policy_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_policy.v1"
        ),
        "operator_control_policy_id": (
            "operator-control-policy-empty:"
            f"ae-artifact-retention-scheduler:{effective_checked_at}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": "ae-artifact-retention-scheduler",
        "checked_at": effective_checked_at,
        "supported_actions": [
            {
                "action": "status_probe",
                "mutates_process": False,
                "requires_approval": False,
                "requires_running_process": False,
                "starts_process": False,
                "stops_process": False,
            },
            {
                "action": "start_daemon",
                "mutates_process": True,
                "requires_approval": True,
                "requires_running_process": False,
                "starts_process": True,
                "stops_process": False,
            },
            {
                "action": "stop_daemon",
                "mutates_process": True,
                "requires_approval": False,
                "requires_running_process": True,
                "starts_process": False,
                "stops_process": True,
            },
            {
                "action": "restart_daemon",
                "mutates_process": True,
                "requires_approval": True,
                "requires_running_process": True,
                "starts_process": True,
                "stops_process": True,
            },
        ],
        "required_fields": {
            "operator_subject": True,
            "idempotency_key": True,
            "reason": True,
            "approval_required_for_start": True,
            "approval_required_for_restart": True,
            "profile": True,
            "max_cycles": True,
        },
        "profile_policy": {
            "default_profile": "test",
            "allowed_profiles": ["test"],
            "production_profiles_allowed": False,
            "production_continuous_start_enabled": False,
        },
        "restart_policy": {
            "restart_daemon_supported": True,
            "restart_semantics": "stop_then_start",
            "requires_distinct_stop_evidence": True,
            "requires_distinct_start_evidence": True,
        },
        "guardrails": _empty_operator_control_guardrails(policy_only=True),
        "metadata": _empty_operator_control_metadata(policy_only=True),
    }


def _memory_artifact_retention_scheduler_daemon_operator_control_preview_payload(
    *,
    action: str,
    operator_subject: Mapping[str, Any],
    idempotency_key: str,
    reason: str,
    requested_at: str | None,
    checked_at: str | None,
    profile: str,
    enabled: bool,
    explicit_opt_in: bool,
    max_cycles: int,
    run_worker: bool,
    approval: Mapping[str, Any] | None,
    current_process: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_action = _normalized_daemon_operator_control_action(action) or "status_probe"
    effective_checked_at = checked_at or requested_at or "2026-09-01T00:00:00Z"
    scheduler_id = "ae-artifact-retention-scheduler"
    policy = _empty_artifact_retention_scheduler_daemon_operator_control_policy_payload(
        checked_at=effective_checked_at,
    )
    request_payload = {
        "operator_control_request_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_request.v1"
        ),
        "operator_control_request_id": (
            "operator-control-request-empty:"
            f"{scheduler_id}:{normalized_action}:idempotency-key-present"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "action": normalized_action,
        "operator_subject": _operator_control_safe_subject(operator_subject),
        "idempotency_key": idempotency_key,
        "reason": reason,
        "requested_at": effective_checked_at,
        "profile": profile,
        "enabled": enabled,
        "explicit_opt_in": explicit_opt_in,
        "max_cycles": max_cycles,
        "run_worker": run_worker,
        "approval": _select_mapping(
            approval,
            ("approved", "approved_by", "approved_at", "approval_reason"),
        ),
        "execution_intent": _memory_operator_control_execution_intent(
            normalized_action
        ),
        "guardrails": _empty_operator_control_guardrails(policy_only=False),
        "metadata": {
            **_empty_operator_control_metadata(policy_only=False),
            "approval_required": normalized_action
            in {"start_daemon", "restart_daemon"},
            "approval_granted": (
                isinstance(approval, Mapping) and approval.get("approved") is True
            ),
            "mutating_action": normalized_action != "status_probe",
        },
    }
    process = _memory_operator_control_current_process(
        action=normalized_action,
        current_process=current_process,
        observed_at=effective_checked_at,
    )
    admission_status, decision_reason = (
        _memory_operator_control_admission_decision(
            action=normalized_action,
            process_status=_text_or_none(process.get("process_status")),
        )
    )
    next_actions = _memory_operator_control_next_supervisor_actions(
        action=normalized_action,
        admission_status=admission_status,
    )
    admission = {
        "operator_control_admission_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_admission.v1"
        ),
        "operator_control_admission_id": (
            "operator-control-admission-empty:"
            f"{request_payload['operator_control_request_id']}:{admission_status}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "operator_control_request_id": request_payload[
            "operator_control_request_id"
        ],
        "action": normalized_action,
        "admission_status": admission_status,
        "decision_reason": decision_reason,
        "checked_at": effective_checked_at,
        "operator_control_request": request_payload,
        "current_process": process,
        "next_supervisor_actions": next_actions,
        "execution_intent": _memory_operator_control_execution_intent(
            normalized_action
        ),
        "guardrails": {
            **_empty_operator_control_guardrails(policy_only=False),
            "admission_only": True,
            "ready_allows_supervisor_dispatch": admission_status == "READY",
        },
        "metadata": {
            **_empty_operator_control_metadata(policy_only=False),
            "admission_contract_only": True,
            "ready_for_dispatch": admission_status == "READY",
            "blocked": admission_status == "BLOCKED",
            "noop": admission_status == "NOOP",
            "next_supervisor_action_count": len(next_actions),
        },
    }
    command_previews = [
        _memory_operator_control_supervisor_command_preview_item(
            next_action=item,
            checked_at=effective_checked_at,
            max_cycles=max_cycles,
            run_worker=run_worker,
            enabled=item["action"] == "start_daemon",
            explicit_opt_in=item["action"] == "start_daemon"
            and explicit_opt_in,
        )
        for item in next_actions
    ]
    supervisor_actions = [item["action"] for item in command_previews]
    command_preview = {
        "operator_control_command_preview_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_command_preview.v1"
        ),
        "operator_control_command_preview_id": (
            "operator-control-command-preview-empty:"
            f"{admission['operator_control_admission_id']}:{len(command_previews)}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "operator_control_admission_id": admission[
            "operator_control_admission_id"
        ],
        "operator_control_request_id": request_payload[
            "operator_control_request_id"
        ],
        "action": normalized_action,
        "preview_status": admission_status,
        "checked_at": effective_checked_at,
        "operator_control_admission": admission,
        "supervisor_command_previews": command_previews,
        "guardrails": {
            **_empty_operator_control_guardrails(policy_only=False),
            "preview_only": True,
            "supervisor_adapter_invoked": False,
        },
        "metadata": {
            **_empty_operator_control_metadata(policy_only=False),
            "command_preview_contract_only": True,
            "ready_for_dispatch": admission_status == "READY",
            "blocked": admission_status == "BLOCKED",
            "noop": admission_status == "NOOP",
            "command_preview_count": len(command_previews),
            "supervisor_actions": supervisor_actions,
            "start_preview_count": supervisor_actions.count("start_daemon"),
            "stop_preview_count": supervisor_actions.count("stop_daemon"),
            "status_probe_preview_count": supervisor_actions.count("status_probe"),
            "restart_preview": normalized_action == "restart_daemon",
        },
    }
    return {
        "operator_control_facade_schema_version": (
            "ae_artifact_retention_scheduler_daemon_operator_control_facade.v1"
        ),
        "operator_control_facade_id": (
            "operator-control-facade-empty:"
            f"{policy['operator_control_policy_id']}:"
            f"{command_preview['operator_control_command_preview_id']}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "operator_control_policy_id": policy["operator_control_policy_id"],
        "operator_control_request_id": request_payload[
            "operator_control_request_id"
        ],
        "operator_control_admission_id": admission[
            "operator_control_admission_id"
        ],
        "operator_control_command_preview_id": command_preview[
            "operator_control_command_preview_id"
        ],
        "action": normalized_action,
        "facade_status": admission_status,
        "checked_at": effective_checked_at,
        "operator_control_policy": policy,
        "operator_control_request": request_payload,
        "operator_control_admission": admission,
        "operator_control_command_preview": command_preview,
        "guardrails": {
            **_empty_operator_control_guardrails(policy_only=False),
            "policy_evaluated": True,
            "request_validated": True,
            "admission_evaluated": True,
            "command_preview_evaluated": True,
            "preview_only": True,
            "process_control_allowed": False,
            "supervisor_dispatch_performed": False,
        },
        "metadata": {
            **_empty_operator_control_metadata(policy_only=False),
            "route_facade": True,
            "preview_only": True,
            "scheduler_id": scheduler_id,
            "action": normalized_action,
            "admission_status": admission_status,
            "decision_reason": decision_reason,
            "ready_for_dispatch": admission_status == "READY",
            "command_preview_count": len(command_previews),
            "supervisor_actions": supervisor_actions,
        },
    }


def _memory_operator_control_execution_intent(action: str) -> dict[str, Any]:
    mutates_process = action != "status_probe"
    return {
        "action": action,
        "mutates_process": mutates_process,
        "reads_status": action == "status_probe",
        "requests_start": action in {"start_daemon", "restart_daemon"},
        "requests_stop": action in {"stop_daemon", "restart_daemon"},
        "restart_decomposes_to_stop_then_start": action == "restart_daemon",
        "requires_running_process": action in {"stop_daemon", "restart_daemon"},
        "requires_bounded_subprocess_adapter": action
        in {"start_daemon", "restart_daemon"},
        "starts_continuous_loop": False,
        "enqueues_job_queue": False,
        "runs_worker": False,
        "physical_delete_enabled": False,
    }


def _memory_operator_control_current_process(
    *,
    action: str,
    current_process: Mapping[str, Any] | None,
    observed_at: str,
) -> dict[str, Any]:
    if isinstance(current_process, Mapping):
        process_status = (
            _normalized_daemon_supervised_process_status(
                current_process.get("process_status")
            )
            or "MISSING"
        )
        return {
            "process_source": _text_or_none(
                current_process.get("process_source")
            )
            or "read_model",
            "process_status": process_status,
            "process_running": process_status in {"RUNNING", "STOP_REQUESTED", "STALE"},
            "daemon_supervised_process_id": _text_or_none(
                current_process.get("daemon_supervised_process_id")
            ),
            "daemon_supervisor_command_id": _text_or_none(
                current_process.get("daemon_supervisor_command_id")
            ),
            "process_id": _int_or_zero(current_process.get("process_id")),
            "host_id": _text_or_none(current_process.get("host_id")),
            "observed_at": _text_or_none(current_process.get("observed_at"))
            or observed_at,
        }
    process_status = "RUNNING" if action in {"stop_daemon", "restart_daemon"} else "MISSING"
    return {
        "process_source": "read_model" if process_status == "RUNNING" else "none",
        "process_status": process_status,
        "process_running": process_status == "RUNNING",
        "daemon_supervised_process_id": (
            "daemon-supervised-process-memory" if process_status == "RUNNING" else None
        ),
        "daemon_supervisor_command_id": (
            "daemon-supervisor-command-memory"
            if process_status == "RUNNING"
            else None
        ),
        "process_id": 1 if process_status == "RUNNING" else None,
        "host_id": "memory" if process_status == "RUNNING" else None,
        "observed_at": observed_at,
    }


def _memory_operator_control_admission_decision(
    *,
    action: str,
    process_status: str | None,
) -> tuple[str, str]:
    status = process_status or "MISSING"
    if action == "status_probe":
        return "READY", "status_probe_allowed"
    if action == "start_daemon":
        if status in {"MISSING", "STOPPED", "EXITED"}:
            return "READY", "start_allowed_no_running_process"
        if status == "RUNNING":
            return "NOOP", "daemon_already_running"
        return "BLOCKED", "process_state_requires_review"
    if action == "stop_daemon":
        if status in {"RUNNING", "STALE", "START_REQUESTED"}:
            return "READY", "stop_allowed_for_observed_process"
        if status in {"MISSING", "STOPPED", "EXITED"}:
            return "NOOP", "daemon_not_running"
        return "BLOCKED", "process_state_requires_review"
    if action == "restart_daemon" and status in {"RUNNING", "STALE"}:
        return "READY", "restart_allowed_stop_then_start"
    if action == "restart_daemon":
        return "BLOCKED", "restart_requires_running_process"
    return "BLOCKED", "operator_control_action_invalid"


def _memory_operator_control_next_supervisor_actions(
    *,
    action: str,
    admission_status: str,
) -> list[dict[str, Any]]:
    if admission_status != "READY":
        return []
    if action == "restart_daemon":
        return [
            _memory_operator_control_next_supervisor_action(
                sequence=1,
                action="stop_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=False,
            ),
            _memory_operator_control_next_supervisor_action(
                sequence=2,
                action="start_daemon",
                requires_distinct_evidence=True,
                requires_follow_up_admission=True,
            ),
        ]
    return [
        _memory_operator_control_next_supervisor_action(
            sequence=1,
            action=(
                "status_probe"
                if action == "status_probe"
                else ("start_daemon" if action == "start_daemon" else "stop_daemon")
            ),
            requires_distinct_evidence=action != "status_probe",
            requires_follow_up_admission=False,
        )
    ]


def _memory_operator_control_next_supervisor_action(
    *,
    sequence: int,
    action: str,
    requires_distinct_evidence: bool,
    requires_follow_up_admission: bool,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "action": action,
        "mutates_process": action in {"start_daemon", "stop_daemon"},
        "requires_distinct_evidence": requires_distinct_evidence,
        "requires_follow_up_admission": requires_follow_up_admission,
    }


def _memory_operator_control_supervisor_command_preview_item(
    *,
    next_action: Mapping[str, Any],
    checked_at: str,
    max_cycles: int,
    run_worker: bool,
    enabled: bool,
    explicit_opt_in: bool,
) -> dict[str, Any]:
    action = _normalized_daemon_supervisor_action(next_action.get("action")) or "status_probe"
    return {
        "sequence": _int_or_zero(next_action.get("sequence")),
        "action": action,
        "requires_distinct_evidence": (
            next_action.get("requires_distinct_evidence") is True
        ),
        "requires_follow_up_admission": (
            next_action.get("requires_follow_up_admission") is True
        ),
        "supervisor_command": {
            "daemon_supervisor_command_schema_version": (
                "ae_artifact_retention_scheduler_daemon_supervisor_command.v1"
            ),
            "daemon_supervisor_command_id": (
                "daemon-supervisor-command-preview-empty:"
                f"{action}:{checked_at}"
            ),
            "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "scheduler_id": "ae-artifact-retention-scheduler",
            "command": {
                "action": action,
                "enabled": enabled,
                "explicit_opt_in": explicit_opt_in,
                "max_cycles": max_cycles,
                "run_worker": run_worker,
            },
        },
    }


def _empty_operator_control_guardrails(*, policy_only: bool) -> dict[str, Any]:
    return {
        "metadata_only": True,
        "operator_subject_required": True,
        "idempotency_key_required": True,
        "operator_reason_required": True,
        "approval_required_for_start_restart": True,
        "test_profile_required": True,
        "explicit_opt_in_required_for_start_restart": True,
        "bounded_max_cycles_required": True,
        "status_probe_before_mutation_required": True,
        "restart_is_stop_then_start": True,
        "production_continuous_start_enabled": False,
        "policy_evaluated": not policy_only,
        "preview_only": not policy_only,
        "process_control_allowed": False,
        "supervisor_dispatch_performed": False,
        "supervisor_adapter_invoked": False,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "raw_daemon_runtime_payload_included": False,
        "raw_supervised_process_snapshot_included": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
        "ag_direct_process_control_allowed": False,
        "physical_delete_automation_enabled": False,
    }


def _empty_operator_control_metadata(*, policy_only: bool) -> dict[str, Any]:
    return {
        "safe_for_ag_projection": True,
        "metadata_only": True,
        "policy_contract_only": policy_only,
        "preview_only": not policy_only,
        "subprocess_started": False,
        "subprocess_stopped": False,
        "database_write_performed": False,
        "job_queue_enqueue_performed": False,
        "worker_execution_performed": False,
        "secrets_redacted": True,
    }


def _empty_artifact_retention_scheduler_daemon_config_payload() -> dict[str, Any]:
    runtime = {
        "scheduler_daemon_enabled": False,
        "scheduler_daemon_started": False,
        "daemon_auto_start_allowed": False,
        "continuous_loop_enabled": False,
        "continuous_loop_started": False,
        "manual_tick_once_enabled": True,
        "manual_tick_once_requires_lease": True,
        "scheduler_tick_admission_enabled": True,
        "operator_dispatch_admission_enabled": True,
        "default_execution_mode": "DRY_RUN",
        "job_queue_available": False,
        "job_queue_backend": "unconfigured",
        "scheduler_tick_interval_seconds": 900,
        "scheduler_tick_jitter_seconds": 60,
        "scheduler_tick_lock_ttl_seconds": 120,
        "scheduler_tick_stale_after_seconds": 900,
        "scheduler_tick_max_jobs_per_tick": 1,
        "scheduler_tick_batch_window_enforced": True,
        "scheduler_tick_timezone": "Asia/Seoul",
        "scheduler_tick_window_start": "02:00",
        "scheduler_tick_window_end": "05:00",
    }
    lease_repository = {
        "required": True,
        "available": False,
        "backend": "not_configured",
        "lease_record_schema_version": (
            "ae_artifact_retention_scheduler_lease_record.v1"
        ),
        "failure_code": "lease_repository_unavailable",
    }
    return {
        "daemon_config_schema_version": (
            "ae_artifact_retention_scheduler_daemon_config.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": "ae-artifact-retention-scheduler",
        "checked_at": "2026-09-01T00:00:00Z",
        "source_scheduler_config_schema_version": (
            "ae_artifact_retention_scheduler_config.v1"
        ),
        "runtime": runtime,
        "lease_repository": lease_repository,
        "supported_actions": _empty_artifact_retention_scheduler_daemon_actions(
            runtime=runtime,
            lease_repository=lease_repository,
        ),
        "guardrails": _empty_artifact_retention_scheduler_daemon_guardrails(),
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }


def _empty_artifact_retention_scheduler_daemon_runtime_payload(
    *,
    daemon_config: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "runtime_observation_schema_version": (
            "ae_artifact_retention_scheduler_daemon_runtime_observation.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": _text_or_none(daemon_config.get("scheduler_id")),
        "checked_at": _text_or_none(daemon_config.get("checked_at")),
        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        "heartbeat_store": {
            "available": False,
            "backend": "not_configured",
            "failure_code": "heartbeat_not_observed",
        },
        "heartbeat": None,
        "heartbeat_count": 0,
        "daemon_config_checked_at": _text_or_none(daemon_config.get("checked_at")),
        "guardrails": {
            "metadata_only": True,
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
            "heartbeat_observation_read_only": True,
        },
        "metadata": {
            "metadata_only": True,
            "heartbeat_observed": False,
            "heartbeat_store_available": False,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }


def _empty_artifact_retention_scheduler_daemon_actions(
    *,
    runtime: Mapping[str, Any],
    lease_repository: Mapping[str, Any],
) -> list[dict[str, Any]]:
    manual_status = "READY"
    manual_block_reason = None
    if runtime.get("operator_dispatch_admission_enabled") is not True:
        manual_status = "BLOCKED"
        manual_block_reason = "operator_dispatch_admission_disabled"
    elif runtime.get("scheduler_tick_admission_enabled") is not True:
        manual_status = "BLOCKED"
        manual_block_reason = "scheduler_tick_admission_disabled"
    elif lease_repository.get("available") is not True:
        manual_status = "BLOCKED"
        manual_block_reason = "lease_repository_unavailable"
    elif runtime.get("job_queue_available") is not True:
        manual_status = "BLOCKED"
        manual_block_reason = "job_queue_unavailable"
    return [
        {
            "action": "status_probe",
            "decision_status": "NOOP",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": None,
        },
        {
            "action": "manual_tick_once",
            "decision_status": manual_status,
            "requires_lease": True,
            "runs_tick_once": manual_status == "READY",
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": manual_block_reason,
        },
        {
            "action": "start_daemon",
            "decision_status": "BLOCKED",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": "daemon_disabled_by_policy",
        },
        {
            "action": "stop_daemon",
            "decision_status": "NOOP",
            "requires_lease": False,
            "runs_tick_once": False,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "block_reason": None,
        },
    ]


def _empty_artifact_retention_scheduler_daemon_guardrails() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "manual_tick_once_only": True,
        "lease_required_before_tick": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
        "ag_direct_database_write_allowed": False,
        "ag_direct_job_enqueue_allowed": False,
    }


def _empty_artifact_retention_scheduler_daemon_dispatch_payload(
    *,
    daemon_config: Mapping[str, Any],
    action: str,
    tenant_id: str | None,
    workspace_id: str | None,
    owner_user_id: str | None,
    requested_at: str | None,
    requested_by: Mapping[str, Any] | None,
    reason: str | None,
) -> dict[str, Any]:
    normalized_action = _normalized_daemon_action(action) or "status_probe"
    action_item = _daemon_action_item(daemon_config, normalized_action)
    requested = requested_at or _text_or_none(daemon_config.get("checked_at"))
    scheduler_id = _text_or_none(daemon_config.get("scheduler_id"))
    control_plan = {
        "daemon_control_plan_schema_version": (
            "ae_artifact_retention_scheduler_daemon_control_plan.v1"
        ),
        "daemon_control_plan_id": (
            f"memory-daemon-control:{scheduler_id}:{normalized_action}:{requested}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "action": normalized_action,
        "decision_status": action_item.get("decision_status"),
        "block_reason": action_item.get("block_reason"),
        "requested_at": requested,
        "requested_by": (
            dict(requested_by)
            if requested_by is not None
            else {"actor_type": "service", "actor_id": "nex-ag"}
        ),
        "reason": reason,
        "daemon_config": deepcopy(dict(daemon_config)),
        "execution_plan": {
            "requires_lease": action_item.get("requires_lease") is True,
            "runs_tick_once": action_item.get("runs_tick_once") is True,
            "dispatches_job_queue": action_item.get("runs_tick_once") is True,
            "starts_daemon": False,
            "starts_continuous_loop": False,
            "writes_history": False,
            "physical_delete_enabled": False,
        },
        "guardrails": deepcopy(
            dict(daemon_config.get("guardrails") or {})
            or _empty_artifact_retention_scheduler_daemon_guardrails()
        ),
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "tick_once_dispatched": action_item.get("runs_tick_once") is True,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
    }
    guardrails = deepcopy(
        dict(daemon_config.get("guardrails") or {})
        or _empty_artifact_retention_scheduler_daemon_guardrails()
    )
    return {
        "daemon_dispatch_result_schema_version": (
            "ae_artifact_retention_scheduler_daemon_dispatch_result.v1"
        ),
        "daemon_dispatch_result_id": (
            f"memory-daemon-dispatch:{scheduler_id}:{normalized_action}:{requested}"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "scheduler_id": scheduler_id,
        "dispatch_status": (
            "DISPATCHED"
            if control_plan["decision_status"] == "READY"
            else control_plan["decision_status"]
        ),
        "control_plan": control_plan,
        "tick_once_result": None,
        "guardrails": {
            **guardrails,
            "daemon_control_plan_required": True,
            "tick_once_requires_ready_control_plan": True,
        },
        "metadata": {
            "metadata_only": True,
            "database_url_included": False,
            "storage_path_included": False,
            "raw_artifact_payload_included": False,
            "raw_execution_payload_included": False,
            "control_plan_ready": control_plan["decision_status"] == "READY",
            "tick_once_dispatched": False,
            "lease_acquired_before_tick": False,
            "lease_released": False,
            "job_enqueued": False,
            "worker_executed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "physical_delete_automation_enabled": False,
        },
        "debug_scope": {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
        },
    }


def _daemon_action_item(
    daemon_config: Mapping[str, Any],
    action: str,
) -> dict[str, Any]:
    for item in _list_value(daemon_config.get("supported_actions")):
        if isinstance(item, Mapping) and item.get("action") == action:
            return dict(item)
    return {
        "action": action,
        "decision_status": "BLOCKED",
        "requires_lease": False,
        "runs_tick_once": False,
        "starts_daemon": False,
        "starts_continuous_loop": False,
        "block_reason": "daemon_control_action_unavailable",
    }


def _empty_artifact_retention_scheduled_job_collection_payload(
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "artifact_retention_scheduled_job_collection_schema_version": (
            "ae_artifact_retention_scheduled_job_collection.v1"
        ),
        "filter": {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "status": _normalized_job_status(status),
            "limit": limit,
        },
        "count": 0,
        "limit": limit,
        "next_cursor": None,
        "items": [],
        "metadata": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
        },
    }


def _memory_artifact_retention_scheduled_dispatch_result(
    batch_plan: Mapping[str, Any],
    *,
    trigger_type: str,
    requested_at: str | None,
    idempotency_key: str | None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    plan_id = _text_or_none(batch_plan.get("plan_id")) or "retention-plan"
    command_id = f"command-{plan_id}-{trigger_type}"
    job_id = f"job-{command_id}"
    selected_count = _int_or_zero(batch_plan.get("selected_count"))
    candidate_count = _int_or_zero(batch_plan.get("candidate_count"))
    estimated_deleted_counts = _safe_deleted_counts(
        batch_plan.get("estimated_deleted_counts")
    )
    normalized_requested_at = (
        requested_at or _text_or_none(batch_plan.get("checked_at")) or _utc_now()
    )
    normalized_idempotency_key = (
        idempotency_key
        or f"ae-artifact-retention-scheduled-job-admission:{plan_id}:{trigger_type}"
    )
    command_summary = {
        "command_status": "READY",
        "trigger_type": trigger_type,
        "scheduler_status": _text_or_none(batch_plan.get("scheduler_status")),
        "execution_mode": _normalized_retention_mode(batch_plan.get("mode")),
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "estimated_deleted_artifacts": _int_or_zero(
            estimated_deleted_counts.get("artifacts")
        ),
        "estimated_deleted_storage_files": _int_or_zero(
            estimated_deleted_counts.get("storage_files")
        ),
        "command_created_at": normalized_requested_at,
        "next_action": _text_or_none(batch_plan.get("execution_advice")),
    }
    queue_admission = {
        "queue_service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "queue_backend": "service_job_queue",
        "target_job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
        "job_enqueued": True,
        "worker_execution_performed": False,
        "scheduler_daemon_started": False,
        "physical_delete_automation_enabled": False,
    }
    job_payload = {
        "payload_schema_version": "ae_artifact_retention_scheduled_job_payload.v1",
        "command_id": command_id,
        "source_plan_id": plan_id,
        "tenant_id": _text_or_none(batch_plan.get("tenant_id")),
        "workspace_id": _text_or_none(batch_plan.get("workspace_id")),
        "owner_user_id": _text_or_none(batch_plan.get("owner_user_id")),
        "trigger_type": trigger_type,
        "scheduler_status": _text_or_none(batch_plan.get("scheduler_status")),
        "command_status": "READY",
        "execution_mode": "DRY_RUN",
        "retention_days_after_logical_purge": _int_or_zero(
            batch_plan.get("candidate_filter", {}).get("retention_days")
            if isinstance(batch_plan.get("candidate_filter"), Mapping)
            else None
        ),
        "scan_limit": _int_or_zero(batch_plan.get("scan_limit")),
        "max_delete_count": _int_or_zero(batch_plan.get("max_delete_count")),
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "estimated_deleted_counts": estimated_deleted_counts,
        "command_summary": command_summary,
        "requested_by": {
            "actor_type": "service",
            "actor_id": "nex-ag",
            "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        },
        "idempotency_key": normalized_idempotency_key,
        "requested_at": normalized_requested_at,
        "redaction_summary": {
            "metadata_only": True,
            "scheduled_command_embedded": True,
            "batch_plan_embedded": False,
            "artifact_payload_included": False,
            "prompt_content_included": False,
            "generation_output_included": False,
            "storage_locator_included": False,
        },
    }
    enqueued_job = {
        "artifact_retention_scheduled_job_schema_version": (
            "ae_artifact_retention_scheduled_job.v1"
        ),
        "job_schema_version": "common_job.v1",
        "job_id": job_id,
        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
        "status": "QUEUED",
        "trace_id": trace_id,
        "request_id": request_id,
        "subject_ref": {
            "type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
            "id": command_id,
        },
        "idempotency_key": normalized_idempotency_key,
        "attempt_count": 0,
        "max_attempts": 3,
        "retryable": True,
        "links": {
            "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
            "ae_retention_purge": "/api/v1/artifact-retention/purge",
            "ae_retention_history": "/api/v1/artifact-retention/executions",
        },
        "payload": job_payload,
        "created_at": normalized_requested_at,
        "updated_at": normalized_requested_at,
    }
    return {
        "artifact_retention_scheduled_job_enqueue_result_schema_version": (
            "ae_artifact_retention_scheduled_job_enqueue_result.v1"
        ),
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_plan_id": plan_id,
        "command_id": command_id,
        "job_id": job_id,
        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
        "tenant_id": _text_or_none(batch_plan.get("tenant_id")),
        "workspace_id": _text_or_none(batch_plan.get("workspace_id")),
        "owner_user_id": _text_or_none(batch_plan.get("owner_user_id")),
        "trigger_type": trigger_type,
        "trace_id": trace_id,
        "request_id": request_id,
        "idempotency_key": normalized_idempotency_key,
        "enqueue_status": "ENQUEUED",
        "job_enqueued": True,
        "duplicate_returned": False,
        "queue_admission": queue_admission,
        "command_summary": command_summary,
        "job_summary": {
            "job_id": job_id,
            "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
            "status": "QUEUED",
            "command_id": command_id,
            "source_plan_id": plan_id,
            "trigger_type": trigger_type,
            "execution_mode": "DRY_RUN",
            "candidate_count": candidate_count,
            "selected_count": selected_count,
            "history_write_expected": True,
            "physical_delete_automation_enabled": False,
        },
        "enqueued_job": enqueued_job,
    }


def _normalized_retention_mode(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().replace("-", "_").upper()


def _normalized_retention_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().replace("-", "_").upper()


def _normalized_retention_batch_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().replace("-", "_").upper()


def _retention_days_filter(raw_value: str | None) -> int | None:
    if raw_value is None or not str(raw_value).strip():
        return None
    try:
        retention_days = int(str(raw_value))
    except ValueError:
        return None
    return retention_days if 1 <= retention_days <= 365 else None


def _safe_deleted_counts(raw_value: Any) -> dict[str, int]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        key: _int_or_zero(raw_value.get(key))
        for key in (
            "artifacts",
            "source_refs",
            "versions",
            "render_jobs",
            "files",
            "links",
            "storage_files",
        )
    }


def _retention_scheduled_job_matches_filter(
    job: Mapping[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
) -> bool:
    if _text_or_none(job.get("job_type")) != AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE:
        return False
    payload = job.get("payload")
    if not isinstance(payload, Mapping):
        return False
    if _text_or_none(payload.get("tenant_id")) != tenant_id:
        return False
    if _text_or_none(payload.get("workspace_id")) != workspace_id:
        return False
    if _text_or_none(payload.get("owner_user_id")) != owner_user_id:
        return False
    return status is None or _normalized_job_status(job.get("status")) == status


def _artifact_matches_collection_filter(
    artifact: Mapping[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str | None,
) -> bool:
    if _owner_tenant_id(artifact) != tenant_id:
        return False
    if _workspace_id(artifact) != workspace_id:
        return False
    if _owner_user_id(artifact) != owner_user_id:
        return False
    return (
        status is None or _normalized_status(artifact.get("artifact_status")) == status
    )


def _artifact_to_collection_item(artifact: Mapping[str, Any]) -> dict[str, Any]:
    versions = _list_value(artifact.get("versions"))
    files = _list_value(artifact.get("files"))
    links = _list_value(artifact.get("links"))
    render_jobs = _list_value(artifact.get("render_jobs"))
    source_ref = _first_mapping(artifact.get("source_refs"))
    artifact_id = _text_or_none(artifact.get("artifact_id"))
    return {
        "artifact_collection_item_schema_version": "ae_artifact_collection_item.v1",
        "artifact_id": artifact_id,
        "artifact_type": _text_or_none(artifact.get("artifact_type")),
        "artifact_status": _text_or_none(artifact.get("artifact_status")),
        "display_title": _text_or_none(artifact.get("display_title")),
        "language": _text_or_none(artifact.get("language")),
        "artifact_intent": _text_or_none(artifact.get("artifact_intent")),
        "target_formats": _text_list(artifact.get("target_formats")),
        "available_formats": _available_formats(files),
        "downloadable_formats": _linked_formats(files, links, "download"),
        "previewable_formats": _linked_formats(files, links, "preview"),
        "current_version_id": _text_or_none(artifact.get("current_version_id")),
        "current_version_no": _current_version_no(
            versions,
            _text_or_none(artifact.get("current_version_id")),
        ),
        "version_count": len(versions),
        "file_count": len(files),
        "link_count": len(links),
        "render_job_count": len(render_jobs),
        "latest_render_job": _latest_render_job_summary(render_jobs),
        "source_summary": _source_collection_summary(source_ref),
        "quality_summary": _safe_quality_summary(source_ref.get("quality_summary")),
        "routes": {
            "detail": f"/api/v1/artifacts/{artifact_id}",
            "versions": f"/api/v1/artifacts/{artifact_id}/versions",
        },
        "tenant_id": _owner_tenant_id(artifact),
        "workspace_id": _workspace_id(artifact),
        "owner_user_id": _owner_user_id(artifact),
        "chat_document_id": _text_or_none(artifact.get("chat_document_id")),
        "interaction_id": _text_or_none(artifact.get("interaction_id")),
        "created_at": _text_or_none(artifact.get("created_at")),
        "updated_at": _text_or_none(artifact.get("updated_at")),
    }


def _project_lifecycle_actions(
    artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    artifact_id = _text_or_none(artifact.get("artifact_id"))
    status = _normalized_status(artifact.get("artifact_status"))
    return [
        _project_lifecycle_action(
            artifact_id=artifact_id,
            current_status=status,
            action=action,
        )
        for action in SUPPORTED_ARTIFACT_LIFECYCLE_ACTIONS
    ]


def _project_lifecycle_action(
    *,
    artifact_id: str | None,
    current_status: str | None,
    action: str,
) -> dict[str, Any]:
    target_status, blocked_reason, idempotent = _artifact_lifecycle_target(
        current_status=current_status,
        action=action,
    )
    enabled = target_status is not None and artifact_id is not None
    if target_status is not None and artifact_id is None:
        blocked_reason = "artifact_id_missing"
    route = (
        f"/api/v1/artifacts/{artifact_id}/lifecycle-actions"
        if enabled and artifact_id
        else None
    )
    return {
        "action": action,
        "enabled": enabled,
        "previous_status": current_status,
        "target_status": target_status if enabled else None,
        "restore_status": (
            DEFAULT_ARTIFACT_RESTORE_STATUS if enabled and action == "RESTORE" else None
        ),
        "idempotent": idempotent if enabled else False,
        "reason_code": "user_requested" if enabled else None,
        "blocked_reason": None if enabled else blocked_reason,
        "route": _safe_artifact_route(route),
        "metadata_only": True,
    }


def _artifact_lifecycle_target(
    *,
    current_status: str | None,
    action: str,
) -> tuple[str | None, str | None, bool]:
    if current_status not in SUPPORTED_ARTIFACT_STATUSES:
        return None, "artifact_status_unsupported", False
    if action == "ARCHIVE":
        if current_status == "ARCHIVED":
            return "ARCHIVED", None, True
        if current_status in ARCHIVABLE_ARTIFACT_STATUSES:
            return "ARCHIVED", None, False
        return None, "artifact_status_not_archivable", False
    if action == "MARK_DELETED":
        if current_status == "DELETED":
            return "DELETED", None, True
        if current_status in DELETABLE_ARTIFACT_STATUSES:
            return "DELETED", None, False
        return None, "artifact_status_not_deletable", False
    if action == "RESTORE":
        if current_status in RESTORABLE_ARTIFACT_STATUSES:
            return DEFAULT_ARTIFACT_RESTORE_STATUS, None, False
        return None, "artifact_status_not_restorable", False
    return None, "artifact_lifecycle_action_unsupported", False


def _artifact_lifecycle_issues(
    artifact: Mapping[str, Any],
    actions: list[dict[str, Any]],
) -> list[dict[str, str]]:
    status = _normalized_status(artifact.get("artifact_status"))
    issues: list[dict[str, str]] = []
    if status not in SUPPORTED_ARTIFACT_STATUSES:
        issues.append(
            {
                "category": "source_contract",
                "subject": "artifact_status",
                "detail": "AE artifact status is not supported by AG lifecycle projection.",
            }
        )
    if not _text_or_none(artifact.get("artifact_id")):
        issues.append(
            {
                "category": "source_contract",
                "subject": "artifact_id",
                "detail": "AE artifact id is required for lifecycle action routing.",
            }
        )
    if status == "RENDERING" and not any(action["enabled"] for action in actions):
        issues.append(
            {
                "category": "operator_visibility",
                "subject": "rendering_artifact",
                "detail": "Lifecycle actions remain blocked until rendering completes.",
            }
        )
    return issues


def _handoff_id_from_artifact(record: Mapping[str, Any]) -> str | None:
    if record.get("artifact_handoff_id") is not None:
        return _text_or_none(record.get("artifact_handoff_id"))
    handoff_ref = record.get("handoff_ref")
    if isinstance(handoff_ref, Mapping):
        return _text_or_none(handoff_ref.get("artifact_handoff_id"))
    return None


def _owner_scope(raw_value: Any) -> dict[str, str | None]:
    if not isinstance(raw_value, Mapping):
        return {"tenant_id": None, "user_id": None, "actor_type": None}
    return {
        "tenant_id": _text_or_none(raw_value.get("tenant_id")),
        "user_id": _text_or_none(raw_value.get("user_id")),
        "actor_type": _text_or_none(raw_value.get("actor_type")),
    }


def _normalized_daemon_heartbeat_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value in {"STARTING", "BUSY", "IDLE", "ERROR"}:
        return value
    return None


def _normalized_daemon_lifecycle_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("-", "_").upper()
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_LIFECYCLE_STATUSES
        else None
    )


def _normalized_daemon_run_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("-", "_").upper()
    return (
        normalized
        if normalized in {"PENDING", "RUNNING", "STOPPING", "SUCCEEDED", "FAILED"}
        else None
    )


def _normalized_daemon_result_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("-", "_").upper()
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_RESULT_STATUSES
        else None
    )


def _normalized_daemon_supervisor_result_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("-", "_").upper()
    return (
        normalized
        if normalized
        in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_RESULT_STATUSES
        else None
    )


def _normalized_daemon_supervised_process_status(
    raw_value: Any,
) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().replace("-", "_").upper()
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISED_PROCESS_STATUSES
        else None
    )


def _daemon_lifecycle_status_and_source(
    *,
    daemon_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
) -> tuple[str, str]:
    runtime_status = _normalized_daemon_lifecycle_status(
        runtime_state.get("lifecycle_status")
    )
    if runtime_status is not None:
        return runtime_status, "runtime_state"

    heartbeat_status = _normalized_daemon_heartbeat_status(heartbeat.get("status"))
    if heartbeat_status == "STARTING":
        return "STARTING", "heartbeat"
    if heartbeat_status == "BUSY":
        return "RUNNING", "heartbeat"
    if heartbeat_status == "IDLE":
        return "STOPPED", "heartbeat"
    if heartbeat_status == "ERROR":
        return "ERROR", "heartbeat"

    runtime_config = _mapping_or_empty(daemon_config.get("runtime"))
    if (
        daemon_config.get("scheduler_id")
        and runtime_config.get("scheduler_daemon_enabled") is False
    ):
        return "DISABLED", "daemon_config"
    return "UNKNOWN", "missing"


def _daemon_lifecycle_reason(
    *,
    lifecycle_status: str,
    lifecycle_source: str,
    daemon_config: Mapping[str, Any],
    runtime_state: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
) -> str:
    runtime_reason = _text_or_none(runtime_state.get("lifecycle_reason"))
    if lifecycle_source == "runtime_state" and runtime_reason:
        return runtime_reason

    heartbeat_status = _normalized_daemon_heartbeat_status(heartbeat.get("status"))
    if lifecycle_source == "heartbeat" and heartbeat_status is not None:
        return f"heartbeat_{heartbeat_status.lower()}"

    runtime_config = _mapping_or_empty(daemon_config.get("runtime"))
    if lifecycle_status == "DISABLED":
        if runtime_config.get("daemon_auto_start_allowed") is False:
            return "explicit_opt_in_required"
        return "scheduler_daemon_disabled"
    return "runtime_state_missing"


def _daemon_lifecycle_attention(
    *,
    lifecycle_status: str,
    lifecycle_reason: str,
    bounded_loop_result: Mapping[str, Any],
    shutdown_transition: Mapping[str, Any],
    retry_circuit_guard: Mapping[str, Any],
) -> dict[str, Any]:
    retry_status = _text_or_none(retry_circuit_guard.get("decision_status"))
    retry_reason = _text_or_none(retry_circuit_guard.get("decision_reason"))
    shutdown_status = _text_or_none(shutdown_transition.get("decision_status"))
    bounded_status = _text_or_none(bounded_loop_result.get("result_status"))

    attention_status = "READY"
    attention_level = "OK"
    reason_code = lifecycle_reason
    operator_action = "monitor_ae_scheduler_daemon_lifecycle"
    operator_attention_required = False

    if lifecycle_status == "ERROR" or retry_status == "CIRCUIT_OPEN":
        attention_status = "ACTION_REQUIRED"
        attention_level = "ERROR"
        reason_code = retry_reason or lifecycle_reason
        operator_action = "review_ae_scheduler_daemon_failure"
        operator_attention_required = True
    elif bounded_status == "FAILED":
        attention_status = "ACTION_REQUIRED"
        attention_level = "ERROR"
        reason_code = "bounded_loop_failed"
        operator_action = "review_ae_scheduler_daemon_bounded_loop"
        operator_attention_required = True
    elif lifecycle_status == "STOPPING" or shutdown_status == "READY":
        attention_status = "SHUTDOWN_IN_PROGRESS"
        attention_level = "WARN"
        reason_code = lifecycle_reason
        operator_action = "wait_for_ae_scheduler_daemon_shutdown"
        operator_attention_required = True
    elif retry_status == "BACKING_OFF":
        attention_status = "RETRY_BACKOFF"
        attention_level = "INFO"
        reason_code = retry_reason or "backoff_window_active"
        operator_action = "wait_for_ae_scheduler_daemon_retry_window"
    elif lifecycle_status in {"DISABLED", "UNKNOWN"}:
        attention_status = "OBSERVATION_GAP"
        attention_level = "INFO"
        reason_code = lifecycle_reason
        operator_action = "inspect_ae_scheduler_daemon_runtime_route"

    return {
        "attention_status": attention_status,
        "attention_level": attention_level,
        "reason_code": reason_code,
        "operator_action": operator_action,
        "operator_attention_required": operator_attention_required,
        "metadata_only": True,
    }


def _select_mapping(raw_value: Any, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        key: _json_safe_value(raw_value.get(key))
        for key in allowed_keys
        if raw_value.get(key) is not None
    }


def _safe_quality_summary(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    allowed = (
        "citation_status",
        "citation_count",
        "validation_error_count",
        "warning_count",
        "grounding_required",
        "retrieval_package_id",
        "retrieval_package_hash",
        "evidence_ref_count",
        "quality_status",
        "error_code",
        "error_detail_sha256",
    )
    return _select_mapping(raw_value, allowed)


def _safe_action_mapping(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        key: value
        for key, value in _select_mapping(
            raw_value,
            ("preview", "download", "copy_link", "open_artifact"),
        ).items()
        if isinstance(value, (bool, str, int, float)) or value is None
    }


def _safe_route_mapping(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, Mapping):
        return {}
    routes: dict[str, str] = {}
    for key, value in raw_value.items():
        safe_route = _safe_route(value)
        if safe_route is not None:
            routes[str(key)] = safe_route
    return routes


def _safe_artifact_route_mapping(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, Mapping):
        return {}
    routes: dict[str, str] = {}
    for key, value in raw_value.items():
        route = _safe_artifact_route(value)
        if route is not None:
            routes[str(key)] = route
    return routes


def _safe_retention_scheduled_job_links(raw_value: Any) -> dict[str, str]:
    if not isinstance(raw_value, Mapping):
        return {}
    allowed = {
        "ae_retention_batch_plan": "/api/v1/artifact-retention/batch-plan",
        "ae_retention_purge": "/api/v1/artifact-retention/purge",
        "ae_retention_history": "/api/v1/artifact-retention/executions",
    }
    routes: dict[str, str] = {}
    for key, expected_route in allowed.items():
        value = _text_or_none(raw_value.get(key))
        if value == expected_route:
            routes[key] = value
    return routes


def _safe_daemon_run_summary(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "scheduler_id",
            "result_status",
            "stop_reason",
            "max_cycles",
            "cycle_count",
            "job_enqueued",
            "worker_executed",
            "run_record_persisted",
            "bounded_loop_started",
        ),
    )


def _safe_daemon_lifecycle_event_summary(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "event_type",
            "run_status",
            "result_status",
            "stop_reason",
            "cycle_count",
            "occurred_at",
        ),
    )


def _safe_daemon_supervisor_summary(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "scheduler_id",
            "action",
            "result_status",
            "decision_reason",
            "runtime_ready",
            "supervisor_adapter_available",
            "supervisor_adapter_invoked",
            "process_started",
            "process_stopped",
        ),
    )


def _safe_daemon_supervisor_event_summary(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "event_type",
            "scheduler_id",
            "action",
            "result_status",
            "decision_reason",
            "occurred_at",
        ),
    )


def _safe_daemon_supervised_process_summary(raw_value: Any) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "scheduler_id",
            "action",
            "process_status",
            "process_mode",
            "process_running",
            "process_started_observed",
            "process_stopped_observed",
            "subprocess_adapter_required",
            "observed_at",
        ),
    )


def _safe_daemon_supervised_process_event_summary(
    raw_value: Any,
) -> dict[str, Any]:
    return _select_mapping(
        raw_value,
        (
            "event_type",
            "scheduler_id",
            "action",
            "process_status",
            "occurred_at",
        ),
    )


def _safe_daemon_run_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "metadata_only": raw_value.get("metadata_only") is True,
        "safe_for_ag_projection": raw_value.get("safe_for_ag_projection") is True,
        "bounded_loop_started": raw_value.get("bounded_loop_started") is True,
        "job_enqueued": raw_value.get("job_enqueued") is True,
        "worker_executed": raw_value.get("worker_executed") is True,
        "run_record_persisted": raw_value.get("run_record_persisted") is True,
        "lifecycle_event_persisted": (
            raw_value.get("lifecycle_event_persisted") is True
        ),
        "persistence_endpoint_included": (
            raw_value.get("persistence_endpoint_included") is True
            or raw_value.get("database_url_included") is True
        ),
        "storage_locator_included": (
            raw_value.get("storage_locator_included") is True
            or raw_value.get("storage_path_included") is True
        ),
        "artifact_payload_included": (
            raw_value.get("artifact_payload_included") is True
            or raw_value.get("raw_artifact_payload_included") is True
        ),
        "execution_payload_included": (
            raw_value.get("execution_payload_included") is True
            or raw_value.get("raw_execution_payload_included") is True
        ),
        "daemon_runtime_payload_included": (
            raw_value.get("daemon_runtime_payload_included") is True
            or raw_value.get("raw_daemon_runtime_payload_included") is True
        ),
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _safe_daemon_supervisor_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "metadata_only": raw_value.get("metadata_only") is True,
        "safe_for_ag_projection": raw_value.get("safe_for_ag_projection") is True,
        "supervisor_result_persisted": (
            raw_value.get("supervisor_result_persisted") is True
        ),
        "supervisor_event_persisted": (
            raw_value.get("supervisor_event_persisted") is True
        ),
        "persistence_endpoint_included": (
            raw_value.get("persistence_endpoint_included") is True
            or raw_value.get("database_url_included") is True
        ),
        "storage_locator_included": (
            raw_value.get("storage_locator_included") is True
            or raw_value.get("storage_path_included") is True
        ),
        "artifact_payload_included": (
            raw_value.get("artifact_payload_included") is True
            or raw_value.get("raw_artifact_payload_included") is True
        ),
        "execution_payload_included": (
            raw_value.get("execution_payload_included") is True
            or raw_value.get("raw_execution_payload_included") is True
        ),
        "daemon_runtime_payload_included": (
            raw_value.get("daemon_runtime_payload_included") is True
            or raw_value.get("raw_daemon_runtime_payload_included") is True
        ),
        "process_control_allowed": raw_value.get("process_control_allowed") is True,
        "ag_direct_process_control_allowed": (
            raw_value.get("ag_direct_process_control_allowed") is True
        ),
        "ag_direct_database_write_allowed": (
            raw_value.get("ag_direct_database_write_allowed") is True
        ),
        "ag_direct_job_enqueue_allowed": (
            raw_value.get("ag_direct_job_enqueue_allowed") is True
        ),
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _safe_daemon_supervised_process_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        "metadata_only": raw_value.get("metadata_only") is True,
        "safe_for_ag_projection": raw_value.get("safe_for_ag_projection") is True,
        "supervised_process_record_persisted": (
            raw_value.get("supervised_process_record_persisted") is True
        ),
        "supervised_process_event_persisted": (
            raw_value.get("supervised_process_event_persisted") is True
        ),
        "persistence_endpoint_included": (
            raw_value.get("persistence_endpoint_included") is True
            or raw_value.get("database_url_included") is True
        ),
        "storage_locator_included": (
            raw_value.get("storage_locator_included") is True
            or raw_value.get("storage_path_included") is True
        ),
        "artifact_payload_included": (
            raw_value.get("artifact_payload_included") is True
            or raw_value.get("raw_artifact_payload_included") is True
        ),
        "execution_payload_included": (
            raw_value.get("execution_payload_included") is True
            or raw_value.get("raw_execution_payload_included") is True
        ),
        "daemon_runtime_payload_included": (
            raw_value.get("daemon_runtime_payload_included") is True
            or raw_value.get("raw_daemon_runtime_payload_included") is True
        ),
        "process_control_allowed": raw_value.get("process_control_allowed") is True,
        "ag_direct_process_control_allowed": (
            raw_value.get("ag_direct_process_control_allowed") is True
        ),
        "ag_direct_database_write_allowed": (
            raw_value.get("ag_direct_database_write_allowed") is True
        ),
        "ag_direct_job_enqueue_allowed": (
            raw_value.get("ag_direct_job_enqueue_allowed") is True
        ),
        "process_started": raw_value.get("process_started") is True,
        "process_stopped": raw_value.get("process_stopped") is True,
        "physical_delete_automation_enabled": (
            raw_value.get("physical_delete_automation_enabled") is True
        ),
    }


def _safe_route(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_ARTIFACT_FILE_ROUTE_PREFIX) else None


def _safe_artifact_route(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_ARTIFACT_ROUTE_PREFIX) else None


def _safe_storage_ref(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None:
        return None
    return value if value.startswith(SAFE_STORAGE_REF_PREFIX) else None


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _timeout_seconds(raw_value: str | None) -> float:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError:
        return DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS


def _validate_artifact_service_filter(
    request: Request,
    service_id: str | None,
) -> JSONResponse | None:
    if service_id is None or service_id == AE_ARTIFACT_SOURCE_SERVICE_ID:
        return None
    return problem_response(
        request,
        status_code=400,
        error_code="ag.ae_artifact_service_invalid",
        title="Invalid AE artifact service filter",
        detail=(
            "Artifact operations are currently available only for "
            f"{AE_ARTIFACT_SOURCE_SERVICE_ID}."
        ),
        type_uri="https://nex-platform.local/problems/ae-artifact-service-invalid",
    )


def _collection_limit(raw_value: str | None) -> int | None:
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_ARTIFACT_COLLECTION_LIMIT
    try:
        limit = int(str(raw_value))
    except ValueError:
        return None
    return limit if 1 <= limit <= MAX_ARTIFACT_COLLECTION_LIMIT else None


def _normalized_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().upper()


def _normalized_job_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    return value.strip().replace("-", "_").upper()


def _normalized_scheduled_trigger(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_")
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_SCHEDULED_TRIGGERS
        else None
    )


def _normalized_daemon_action(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_")
    return (
        normalized if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_ACTIONS else None
    )


def _normalized_daemon_supervisor_action(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_")
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_SUPERVISOR_ACTIONS
        else None
    )


def _normalized_daemon_supervisor_actions(raw_value: Any) -> list[str]:
    actions = []
    for value in _list_value(raw_value):
        normalized = _normalized_daemon_supervisor_action(value)
        if normalized is not None:
            actions.append(normalized)
    return actions


def _normalized_daemon_operator_control_action(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_")
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_ACTIONS
        else None
    )


def _normalized_operator_control_admission_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper().replace("-", "_")
    return (
        normalized
        if normalized in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_STATUSES
        else None
    )


def _normalized_operator_control_execution_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper().replace("-", "_")
    return (
        normalized
        if normalized
        in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_STATUSES
        else None
    )


def _normalized_operator_control_execution_statuses(raw_value: Any) -> list[str]:
    statuses = []
    for value in _list_value(raw_value):
        normalized = _normalized_operator_control_execution_status(value)
        if normalized is not None:
            statuses.append(normalized)
    return statuses


def _normalized_operator_control_execution_worker_status(
    raw_value: Any,
) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper().replace("-", "_")
    return (
        normalized
        if normalized
        in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_EXECUTION_WORKER_STATUSES
        else None
    )


def _normalized_daemon_supervisor_result_statuses(raw_value: Any) -> list[str]:
    statuses = []
    for value in _list_value(raw_value):
        normalized = _normalized_daemon_supervisor_result_status(value)
        if normalized is not None:
            statuses.append(normalized)
    return statuses


def _normalized_operator_control_idempotency_status(raw_value: Any) -> str | None:
    value = _text_or_none(raw_value)
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper().replace("-", "_")
    return (
        normalized
        if normalized
        in SUPPORTED_ARTIFACT_RETENTION_DAEMON_OPERATOR_CONTROL_IDEMPOTENCY_STATUSES
        else None
    )


def _latest_timestamp_text(*values: str | None) -> str | None:
    latest: str | None = None
    for value in values:
        if value is not None and (latest is None or value > latest):
            latest = value
    return latest


def _artifact_operations_problem_response(
    request: Request,
    exc: AeArtifactOperationsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="AE artifact source unavailable",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/ae-artifact-source-unavailable",
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


def _deepcopy_or_none(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return deepcopy(value) if value is not None else None


def _list_value(raw_value: Any) -> list[Any]:
    return list(raw_value) if isinstance(raw_value, list) else []


def _mapping_or_empty(raw_value: Any) -> dict[str, Any]:
    return dict(raw_value) if isinstance(raw_value, Mapping) else {}


def _first_mapping(raw_value: Any) -> dict[str, Any]:
    for value in _list_value(raw_value):
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _text_list(raw_value: Any) -> list[str]:
    return [str(value) for value in _list_value(raw_value) if value is not None]


def _text_or_none(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    return str(raw_value)


def _present_text(raw_value: Any) -> bool:
    return bool(_text_or_none(raw_value) and str(raw_value).strip())


def _int_or_zero(raw_value: Any) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _owner_tenant_id(record: Mapping[str, Any]) -> str | None:
    owner = record.get("owner_actor_ref")
    if isinstance(owner, Mapping):
        return _text_or_none(owner.get("tenant_id"))
    return _text_or_none(record.get("tenant_id"))


def _owner_user_id(record: Mapping[str, Any]) -> str | None:
    owner = record.get("owner_actor_ref")
    if isinstance(owner, Mapping):
        return _text_or_none(owner.get("actor_id") or owner.get("user_id"))
    return _text_or_none(record.get("owner_user_id") or record.get("user_id"))


def _workspace_id(record: Mapping[str, Any]) -> str | None:
    workspace = record.get("workspace_ref")
    if isinstance(workspace, Mapping):
        return _text_or_none(workspace.get("workspace_id"))
    return _text_or_none(record.get("workspace_id"))


def _available_formats(files: list[Any]) -> list[str]:
    formats = [
        _text_or_none(file.get("format")) for file in files if isinstance(file, Mapping)
    ]
    return sorted({value for value in formats if value})


def _linked_formats(files: list[Any], links: list[Any], link_type: str) -> list[str]:
    file_formats = {
        file.get("artifact_file_id"): _text_or_none(file.get("format"))
        for file in files
        if isinstance(file, Mapping)
    }
    linked = [
        file_formats.get(link.get("artifact_file_id"))
        for link in links
        if isinstance(link, Mapping)
        and _text_or_none(link.get("link_type")) == link_type
        and _safe_route(link.get("link_route")) is not None
    ]
    return sorted({value for value in linked if value})


def _current_version_no(versions: list[Any], current_version_id: str | None) -> int:
    for version in versions:
        if (
            isinstance(version, Mapping)
            and _text_or_none(version.get("artifact_version_id")) == current_version_id
        ):
            return _int_or_zero(version.get("version_no"))
    return 0


def _latest_render_job_summary(render_jobs: list[Any]) -> dict[str, Any]:
    candidates = [job for job in render_jobs if isinstance(job, Mapping)]
    candidates.sort(key=lambda job: str(job.get("created_at") or ""), reverse=True)
    if not candidates:
        return {}
    return _select_mapping(
        candidates[0],
        (
            "render_job_id",
            "artifact_version_id",
            "render_status",
            "renderer_policy_id",
            "target_formats",
            "started_at",
            "completed_at",
            "created_at",
        ),
    )


def _source_collection_summary(source_ref: Mapping[str, Any]) -> dict[str, Any]:
    return _select_mapping(
        source_ref,
        (
            "cx_generation_id",
            "structured_draft_id",
            "structured_draft_content_hash",
            "generation_response_hash",
            "retrieval_package_id",
            "retrieval_package_hash",
        ),
    )


def _json_safe_value(raw_value: Any) -> Any:
    if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
        return raw_value
    if isinstance(raw_value, list):
        return [_json_safe_value(value) for value in raw_value]
    if isinstance(raw_value, Mapping):
        return {
            str(key): _json_safe_value(value)
            for key, value in raw_value.items()
            if value is not None
        }
    return str(raw_value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
