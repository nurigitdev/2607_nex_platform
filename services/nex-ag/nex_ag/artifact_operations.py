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
AE_ARTIFACT_SOURCE_SERVICE_ID = "nex-ae-api"
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
    artifact_retention_scheduler_daemon_dispatch_results: dict[
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
        except AeArtifactOperationsError as exc:
            return _artifact_operations_problem_response(request, exc)

        return build_artifact_operation_retention_automation_projection(
            plan=plan,
            scheduled_jobs=scheduled_jobs,
            history=history,
            source_client=selected_client,
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

        return build_artifact_operation_retention_daemon_projection(
            daemon_config=daemon_config,
            source_client=selected_client,
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
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_plan = _project_retention_batch_plan(plan)
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
    errors = source_errors or []
    projection = {
        "projection_schema_version": (
            AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": "DEGRADED" if errors else "READY",
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
        "summary": summarize_artifact_retention_automation_operations(
            batch_plan=projected_plan,
            scheduled_jobs=scheduled_items,
            history=history_items,
        ),
        "source_status": _artifact_retention_automation_source_status(
            source_client=source_client,
            batch_plan_loaded=bool(projected_plan.get("plan_id")),
            scheduled_job_count=len(scheduled_items),
            history_count=len(history_items),
            errors=errors,
        ),
        "operator_guidance": {
            "metadata_only": True,
            "system_of_record": AE_ARTIFACT_SOURCE_SERVICE_ID,
            "ae_scheduler_config_route": "/api/v1/artifact-retention/scheduler-config",
            "ae_batch_plan_route": "/api/v1/artifact-retention/batch-plan",
            "ae_scheduled_jobs_route": ("/api/v1/artifact-retention/scheduled-jobs"),
            "ae_scheduled_job_admission_route": (
                "/api/v1/artifact-retention/scheduled-jobs/admission"
            ),
            "ae_retention_history_route": "/api/v1/artifact-retention/executions",
            "ae_purge_route": "/api/v1/artifact-retention/purge",
            "ag_direct_database_write_allowed": False,
            "ag_direct_job_enqueue_allowed": False,
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
    dispatch_response: Mapping[str, Any] | None = None,
    source_client: AeArtifactOperationsClient | None = None,
    source_errors: list[AeArtifactOperationsError] | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    projected_config = _project_retention_scheduler_daemon_config(daemon_config)
    projected_dispatch = _project_retention_scheduler_daemon_dispatch_response(
        dispatch_response
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
        "dispatch_response": projected_dispatch or None,
        "summary": summarize_artifact_retention_daemon_operations(
            daemon_config=projected_config,
            dispatch_response=projected_dispatch,
        ),
        "source_status": _artifact_retention_daemon_source_status(
            source_client=source_client,
            config_loaded=bool(projected_config.get("scheduler_id")),
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


def summarize_artifact_retention_daemon_operations(
    *,
    daemon_config: Mapping[str, Any],
    dispatch_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = _mapping_or_empty(daemon_config.get("runtime"))
    lease_repository = _mapping_or_empty(daemon_config.get("lease_repository"))
    manual_action = _daemon_action_item(daemon_config, "manual_tick_once")
    start_action = _daemon_action_item(daemon_config, "start_daemon")
    dispatch = _mapping_or_empty(dispatch_response)
    dispatch_metadata = _mapping_or_empty(dispatch.get("metadata"))
    control_plan = _mapping_or_empty(dispatch.get("control_plan"))
    manual_status = _text_or_none(manual_action.get("decision_status"))
    start_status = _text_or_none(start_action.get("decision_status"))
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
        "operator_attention_required": manual_status != "READY"
        or bool(dispatch)
        or lease_repository.get("available") is not True,
        "metadata_only": True,
    }


def summarize_artifact_retention_automation_operations(
    *,
    batch_plan: Mapping[str, Any],
    scheduled_jobs: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    batch_summary = summarize_artifact_retention_batch_operations(batch_plan)
    job_summary = summarize_artifact_retention_scheduled_job_operations(scheduled_jobs)
    history_summary = summarize_artifact_retention_history_operations(history)
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
        ),
        "automated_execute_enabled": False,
        "physical_delete_automation_enabled": False,
        "physical_delete_operator_approval_required": True,
        "latest_activity_at": _latest_timestamp_text(
            batch_summary["latest_checked_at"],
            job_summary["latest_updated_at"],
            history_summary["latest_checked_at"],
        ),
    }


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
        "lease_acquired_before_tick": (
            raw_value.get("lease_acquired_before_tick") is True
        ),
        "lease_released": raw_value.get("lease_released") is True,
        "job_enqueued": raw_value.get("job_enqueued") is True,
        "worker_executed": raw_value.get("worker_executed") is True,
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
        "guardrails": _project_retention_scheduler_daemon_guardrails(
            raw_value.get("guardrails")
        ),
        "metadata": _project_retention_scheduler_daemon_metadata(
            raw_value.get("metadata")
        ),
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
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "daemon_config_loaded": config_loaded and not errors,
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


def _artifact_retention_automation_source_status(
    *,
    source_client: AeArtifactOperationsClient | None,
    batch_plan_loaded: bool,
    scheduled_job_count: int,
    history_count: int,
    errors: list[AeArtifactOperationsError],
) -> dict[str, Any]:
    status = "DEGRADED" if errors else "READY"
    return {
        "status": status,
        "service_id": AE_ARTIFACT_SOURCE_SERVICE_ID,
        "source_kind": getattr(source_client, "source_kind", "provided"),
        "base_url": getattr(source_client, "base_url", None),
        "batch_plan_loaded": batch_plan_loaded and not errors,
        "scheduled_jobs_loaded": not errors,
        "history_loaded": not errors,
        "scheduled_job_count": scheduled_job_count,
        "history_count": history_count,
        "errors": [
            {
                "error_code": error.error_code,
                "detail": error.detail,
                "status_code": error.status_code,
            }
            for error in errors
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
