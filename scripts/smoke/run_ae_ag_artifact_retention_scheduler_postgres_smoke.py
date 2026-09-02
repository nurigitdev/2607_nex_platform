#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_batch_plan_postgres_smoke as batch_plan_pg  # noqa: E402
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_artifact_retention_scheduled_worker_postgres_smoke as worker_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    register_artifact_handoff_routes,
)
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION,
    AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION,
    AeArtifactOperationsError,
    register_artifact_operation_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)

SCHEMA_VERSION = "ae_ag_artifact_retention_scheduler_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
CHECKED_AT = batch_plan_pg.CHECKED_AT
REQUESTED_AT = "2026-09-01T03:10:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT


class AeTestClientArtifactOperationsClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.batch_plans: dict[str, dict[str, Any]] = {}

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
        response = self.client.get(
            "/api/v1/artifact-retention/batch-plan",
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
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        payload = self._json_or_error(response)
        plan_id = payload.get("plan_id")
        if plan_id:
            self.batch_plans[str(plan_id)] = dict(payload)
        return payload

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
        response = self.client.get(
            "/api/v1/artifact-retention/scheduled-jobs",
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"status": status} if status else {}),
            },
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        return self._json_or_error(response)

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
        response = self.client.get(
            "/api/v1/artifact-retention/executions",
            params={
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "limit": str(limit),
                **({"mode": mode} if mode else {}),
                **({"execution_status": execution_status} if execution_status else {}),
            },
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        return self._json_or_error(response)

    def get_artifact_retention_scheduler_daemon_config(
        self,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.get(
            "/api/v1/artifact-retention/scheduler-daemon-config",
            headers=self._headers(request_id=request_id, trace_id=trace_id),
        )
        return self._json_or_error(response)

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
        headers = self._headers(request_id=request_id, trace_id=trace_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        plan_id = batch_plan.get("plan_id")
        admission_plan = self.batch_plans.get(str(plan_id), dict(batch_plan))
        response = self.client.post(
            "/api/v1/artifact-retention/scheduled-jobs/admission",
            json={
                "batch_plan": admission_plan,
                "trigger_type": trigger_type,
                **({"requested_at": requested_at} if requested_at else {}),
                **({"idempotency_key": idempotency_key} if idempotency_key else {}),
            },
            headers=headers,
        )
        return self._json_or_error(response)

    def _headers(self, *, request_id: str, trace_id: str) -> dict[str, str]:
        return {
            **self.headers,
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }

    @staticmethod
    def _json_or_error(response: Any) -> dict[str, Any]:
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            raise AeArtifactOperationsError(
                error_code=payload.get(
                    "error_code",
                    "ag.ae_artifact_retention_scheduler_source_failed",
                ),
                detail=payload.get("detail", "AE artifact scheduler source failed."),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        base_auth._require_test_database_url(database_url, env_name=database_env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_ag_artifact_retention_scheduler_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _failure("execution_failed", detail, profile=profile, env=env)

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "ag_service_id": AG_SERVICE_ID,
        "profile": profile,
        "database_env": database_env,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_ag_artifact_retention_scheduler_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduler-{suffix}"
    workspace_id = f"workspace-artifact-scheduler-{suffix}"
    owner_user_id = f"owner-artifact-scheduler-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    idempotency_key = f"retention-scheduler-dispatch-{suffix}"
    worker_id = f"ae-artifact-retention-scheduler-smoke-{suffix}"
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-ag-artifact-scheduler-smoke-",
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                ae_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                ae_app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory,
                    job_queue=job_queue,
                )
                cx_client = artifact_pg.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(ae_app, cx_client=cx_client)
                ae_client = TestClient(ae_app)
                ae_headers = artifact_pg._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                first_old = batch_plan_pg._create_deleted_artifact(
                    ae_client,
                    ae_headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-first",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=OLD_LOGICAL_PURGE_AT,
                )
                second_old = batch_plan_pg._create_deleted_artifact(
                    ae_client,
                    ae_headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-second",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at="2026-07-31T01:00:00Z",
                )
                recent = batch_plan_pg._create_deleted_artifact(
                    ae_client,
                    ae_headers,
                    engine=engine,
                    suffix=suffix,
                    label="recent",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                )
                for created in (first_old, second_old, recent):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                before = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_before = candidate_pg._count_files(storage_root)
                scheduler_config_response = ae_client.get(
                    "/api/v1/artifact-retention/scheduler-config",
                    headers=ae_headers,
                )
                scheduler_config = (
                    scheduler_config_response.json()
                    if scheduler_config_response.status_code == 200
                    else {}
                )

                ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
                bridge = AeTestClientArtifactOperationsClient(
                    ae_client,
                    headers=artifact_pg._auth_headers(
                        request_id=request_id,
                        trace_id=trace_id,
                    ),
                )
                register_artifact_operation_routes(ag_app, client=bridge)
                ag_client = TestClient(ag_app)
                ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

                dispatch_response = ag_client.post(
                    "/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch",
                    json={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                        "checked_at": CHECKED_AT,
                        "trigger_type": "operator_dispatch",
                        "requested_at": REQUESTED_AT,
                        "idempotency_key": idempotency_key,
                        "confirm_dispatch": True,
                    },
                    headers=ag_headers,
                )
                dispatch_projection = (
                    dispatch_response.json()
                    if dispatch_response.status_code == 200
                    else {}
                )
                job_id = (
                    dispatch_projection.get("summary", {}).get("job_id")
                    if isinstance(dispatch_projection.get("summary"), Mapping)
                    else None
                )
                if not job_id:
                    raw_job_id = dispatch_projection.get("dispatch_response", {}).get(
                        "job_id"
                    )
                    job_id = str(raw_job_id) if raw_job_id else None

                scheduled_jobs_response = ag_client.get(
                    "/admin/v1/operations/artifact-retention/scheduled-jobs",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "status": "QUEUED",
                        "limit": "10",
                    },
                    headers=ag_headers,
                )
                scheduled_jobs_projection = (
                    scheduled_jobs_response.json()
                    if scheduled_jobs_response.status_code == 200
                    else {}
                )
                automation_response = ag_client.get(
                    "/admin/v1/operations/artifact-retention/automation",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                        "checked_at": CHECKED_AT,
                        "limit": "10",
                    },
                    headers=ag_headers,
                )
                automation_projection = (
                    automation_response.json()
                    if automation_response.status_code == 200
                    else {}
                )
                db_job = (
                    worker_pg._job_observation(
                        engine,
                        job_id=job_id,
                        idempotency_key=idempotency_key,
                    )
                    if job_id
                    else {"row_count": 0, "status": None}
                )
                after = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_after = candidate_pg._count_files(storage_root)
                checks = _scheduler_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    dispatch_response=dispatch_response.status_code,
                    dispatch_projection=dispatch_projection,
                    scheduled_jobs_response=scheduled_jobs_response.status_code,
                    scheduled_jobs_projection=scheduled_jobs_projection,
                    automation_response=automation_response.status_code,
                    automation_projection=automation_projection,
                    db_job=db_job,
                    before=before,
                    after=after,
                    materialized_before=materialized_before,
                    materialized_after=materialized_after,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE/AG artifact retention scheduler PostgreSQL smoke "
                        f"checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_worker = worker_pg._cleanup_worker_rows(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    worker_id=worker_id,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "scheduler_config": {
                        "schema_version": scheduler_config[
                            "artifact_retention_scheduler_config_schema_version"
                        ],
                        "scheduler_status": _scheduler_status(scheduler_config),
                        "job_queue_backend": scheduler_config["runtime"][
                            "job_queue_backend"
                        ],
                        "scheduled_job_route": scheduler_config["api_routes"][
                            "scheduled_jobs"
                        ],
                        "admission_route": scheduler_config["api_routes"][
                            "scheduled_job_admission"
                        ],
                    },
                    "ag_dispatch": {
                        "projection_schema_version": dispatch_projection[
                            "projection_schema_version"
                        ],
                        "projection_status": dispatch_projection["projection_status"],
                        "enqueue_status": dispatch_projection["summary"][
                            "enqueue_status"
                        ],
                        "job_enqueued": dispatch_projection["summary"]["job_enqueued"],
                        "job_status": dispatch_projection["summary"]["job_status"],
                        "trigger_type": dispatch_projection["summary"]["trigger_type"],
                    },
                    "ag_scheduled_jobs": {
                        "projection_schema_version": scheduled_jobs_projection[
                            "projection_schema_version"
                        ],
                        "projection_status": scheduled_jobs_projection[
                            "projection_status"
                        ],
                        "count": scheduled_jobs_projection["count"],
                        "queued_count": scheduled_jobs_projection["summary"][
                            "queued_count"
                        ],
                    },
                    "ag_automation": {
                        "projection_schema_version": automation_projection[
                            "projection_schema_version"
                        ],
                        "projection_status": automation_projection["projection_status"],
                        "safety_status": automation_projection["summary"][
                            "safety_status"
                        ],
                        "dispatch_available": automation_projection["summary"][
                            "dispatch_available"
                        ],
                        "scheduled_job_count": automation_projection["summary"][
                            "scheduled_job_count"
                        ],
                        "queued_job_count": automation_projection["summary"][
                            "queued_job_count"
                        ],
                        "history_count": automation_projection["summary"][
                            "history_count"
                        ],
                        "daemon_manual_tick_once_available": (
                            automation_projection["summary"][
                                "daemon_manual_tick_once_available"
                            ]
                        ),
                        "daemon_start_daemon_available": (
                            automation_projection["summary"][
                                "daemon_start_daemon_available"
                            ]
                        ),
                        "daemon_scheduler_daemon_started": (
                            automation_projection["summary"][
                                "daemon_scheduler_daemon_started"
                            ]
                        ),
                        "physical_delete_automation_enabled": (
                            automation_projection["summary"][
                                "physical_delete_automation_enabled"
                            ]
                        ),
                    },
                    "db_job": db_job,
                    "db_before": before,
                    "db_after_dispatch": after,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_dispatch": materialized_after,
                    },
                    "checks": checks,
                    "cleanup": {**cleanup, **cleanup_worker},
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if job_id:
            worker_pg._cleanup_worker_rows(
                engine,
                job_id=job_id,
                idempotency_key=idempotency_key,
                worker_id=worker_id,
            )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _scheduler_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    dispatch_response: int,
    dispatch_projection: Mapping[str, Any],
    scheduled_jobs_response: int,
    scheduled_jobs_projection: Mapping[str, Any],
    automation_response: int,
    automation_projection: Mapping[str, Any],
    db_job: Mapping[str, Any],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    dispatch_summary = dispatch_projection.get("summary")
    if not isinstance(dispatch_summary, Mapping):
        dispatch_summary = {}
    scheduled_summary = scheduled_jobs_projection.get("summary")
    if not isinstance(scheduled_summary, Mapping):
        scheduled_summary = {}
    automation_summary = automation_projection.get("summary")
    if not isinstance(automation_summary, Mapping):
        automation_summary = {}
    automation_guidance = automation_projection.get("operator_guidance")
    if not isinstance(automation_guidance, Mapping):
        automation_guidance = {}
    automation_daemon = automation_projection.get("scheduler_daemon")
    if not isinstance(automation_daemon, Mapping):
        automation_daemon = {}
    daemon_summary = automation_daemon.get("summary")
    if not isinstance(daemon_summary, Mapping):
        daemon_summary = {}
    return {
        "scheduler_config_route_ok": scheduler_config_response == 200,
        "scheduler_daemon_disabled": _scheduler_status(scheduler_config) == "DISABLED",
        "scheduler_uses_sqlalchemy_queue": scheduler_config.get("runtime", {}).get(
            "job_queue_backend"
        )
        == "SqlAlchemyJobQueue",
        "ag_dispatch_route_ok": dispatch_response == 200,
        "ag_dispatch_projection_ready": dispatch_projection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_DISPATCH_SCHEMA_VERSION
        and dispatch_projection.get("projection_status") == "READY",
        "ag_dispatch_enqueued_queued_job": dispatch_summary.get("enqueue_status")
        == "ENQUEUED"
        and dispatch_summary.get("job_enqueued") is True
        and dispatch_summary.get("job_status") == "QUEUED",
        "ag_dispatch_trigger_operator": dispatch_summary.get("trigger_type")
        == "operator_dispatch",
        "ag_scheduled_jobs_route_ok": scheduled_jobs_response == 200,
        "ag_scheduled_jobs_projection_ready": scheduled_jobs_projection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_SCHEDULED_JOB_PROJECTION_SCHEMA_VERSION
        and scheduled_jobs_projection.get("projection_status") == "READY",
        "ag_scheduled_jobs_sees_queue": scheduled_jobs_projection.get("count") == 1
        and scheduled_summary.get("queued_count") == 1,
        "ag_automation_route_ok": automation_response == 200,
        "ag_automation_projection_ready": automation_projection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_AUTOMATION_PROJECTION_SCHEMA_VERSION
        and automation_projection.get("projection_status") == "READY",
        "ag_automation_sees_queue": automation_summary.get("scheduled_job_count") == 1
        and automation_summary.get("queued_job_count") == 1,
        "ag_automation_sees_daemon": automation_summary.get(
            "daemon_scheduler_id"
        )
        is not None
        and automation_summary.get("daemon_start_daemon_available") is False
        and automation_summary.get("daemon_scheduler_daemon_started") is False
        and automation_summary.get("daemon_continuous_loop_started") is False
        and daemon_summary.get("scheduler_id") is not None
        and automation_guidance.get("ae_daemon_config_route")
        == "/api/v1/artifact-retention/scheduler-daemon-config",
        "ag_automation_keeps_execute_disabled": automation_summary.get(
            "physical_delete_automation_enabled"
        )
        is False
        and automation_guidance.get("ag_direct_database_write_allowed") is False
        and automation_guidance.get("ag_direct_job_enqueue_allowed") is False,
        "db_job_persisted_once": db_job.get("row_count") == 1,
        "db_job_queued": db_job.get("status") == "QUEUED"
        and db_job.get("attempt_count") == 0
        and db_job.get("payload_command_status") == "READY",
        "db_rows_retained": dict(after) == dict(before),
        "storage_files_retained": materialized_after == materialized_before
        and materialized_before >= 6,
        "metadata_only_evidence": _metadata_only(
            scheduler_config,
            dispatch_projection,
            scheduled_jobs_projection,
            automation_projection,
            db_job,
            before,
            after,
            forbidden_fragments=[
                database_url,
                database_env,
                _database_url_password(database_url),
                str(storage_root),
                "/data/nex-platform",
                "storage_ref",
                "content_base64",
                "rendered_payloads",
            ],
        ),
    }


def _scheduler_status(scheduler_config: Mapping[str, Any]) -> str | None:
    status = scheduler_config.get("scheduler_status")
    if isinstance(status, str) and status.strip():
        return status.strip().upper()
    runtime = scheduler_config.get("runtime")
    if (
        isinstance(runtime, Mapping)
        and runtime.get("scheduler_daemon_enabled") is False
    ):
        return "DISABLED"
    return None


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "ag_service_id": AG_SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized for fragment in forbidden_fragments if fragment
    )


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    for key, value in _sensitive_env_values(env):
        replacement = "***" if key.endswith(":password") else f"<redacted:{key}>"
        safe = safe.replace(value, replacement)
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key, value in _sensitive_env_values(environ):
        if value in serialized_evidence:
            if key.endswith(":password"):
                raise ValueError(
                    "AE/AG artifact retention scheduler smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE/AG artifact retention scheduler smoke contains raw " f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE/AG artifact retention scheduler smoke contains a local data path."
        )


def _sensitive_env_values(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    sensitive: list[tuple[str, str]] = []
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = environ.get(key)
        if value:
            sensitive.append((key, value))
            password = _database_url_password(value)
            if password:
                sensitive.append((f"{key}:password", password))
    return sensitive


def _database_url_password(database_url: str | None) -> str | None:
    if database_url is None:
        return None
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return None
    if parsed.password is None:
        return None
    return unquote(parsed.password)


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_ag_artifact_retention_scheduler_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_ag_artifact_retention_scheduler_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"dispatch={evidence['ag_dispatch']['enqueue_status']} "
            f"job_status={evidence['db_job']['status']} "
            f"scheduled_jobs={evidence['ag_scheduled_jobs']['count']} "
            f"automation={evidence['ag_automation']['safety_status']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_jobs={evidence['cleanup']['job_rows']}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG artifact retention scheduler PostgreSQL smoke."
        )
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_ag_artifact_retention_scheduler_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
