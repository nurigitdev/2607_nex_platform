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
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
)
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    register_artifact_handoff_routes,
)
from nex_ag.artifact_operations import (  # noqa: E402
    AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION,
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

SCHEMA_VERSION = "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
AG_SERVICE_ID = "nex-ag"
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = "2026-08-31T17:30:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT


class AeTestClientSchedulerDaemonOperationsClient:
    source_kind = "ae_test_client"
    base_url = "testclient://nex-ae-api"

    def __init__(self, client: TestClient, headers: Mapping[str, str]) -> None:
        self.client = client
        self.headers = dict(headers)
        self.daemon_config_statuses: list[int] = []
        self.daemon_control_statuses: list[int] = []
        self.last_daemon_dispatch: dict[str, Any] = {}

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
        self.daemon_config_statuses.append(response.status_code)
        return self._json_or_error(response)

    def dispatch_artifact_retention_scheduler_daemon_control(
        self,
        *,
        action: str,
        tenant_id: str | None,
        workspace_id: str | None,
        owner_user_id: str | None,
        retention_days: int | None,
        as_of: str | None,
        scan_limit: int,
        max_delete_count: int,
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
        headers = self._headers(request_id=request_id, trace_id=trace_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.client.post(
            "/api/v1/artifact-retention/scheduler-daemon-controls",
            json={
                "action": action,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "retention_days": retention_days,
                "as_of": as_of,
                "scan_limit": scan_limit,
                "max_delete_count": max_delete_count,
                "requested_at": requested_at,
                "requested_by": dict(requested_by) if requested_by else None,
                "reason": reason,
                "tick_at": tick_at,
                "run_worker": run_worker,
                "worker_id": worker_id,
                "idempotency_key": idempotency_key,
            },
            headers=headers,
        )
        self.daemon_control_statuses.append(response.status_code)
        payload = self._json_or_error(response)
        self.last_daemon_dispatch = dict(payload)
        return payload

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
                    "ag.ae_artifact_retention_scheduler_daemon_source_failed",
                ),
                detail=payload.get("detail", "AE scheduler daemon source failed."),
                status_code=response.status_code,
            )
        return payload if isinstance(payload, dict) else {}


def run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke(
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
        execution = _execute_ae_ag_artifact_retention_scheduler_daemon_smoke(
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


def _execute_ae_ag_artifact_retention_scheduler_daemon_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-ag-daemon-{suffix}"
    workspace_id = f"workspace-artifact-ag-daemon-{suffix}"
    owner_user_id = f"owner-artifact-ag-daemon-{suffix}"
    worker_id = f"ae-artifact-ag-daemon-worker-{suffix}"
    idempotency_key = f"ag-retention-daemon-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    scheduler_id = ""
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
            session_factory
        )
        with tempfile.TemporaryDirectory(prefix="nex-ae-ag-daemon-smoke-") as storage_dir:
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

                created_artifacts = (
                    batch_plan_pg._create_deleted_artifact(
                        ae_client,
                        ae_headers,
                        engine=engine,
                        suffix=suffix,
                        label="ag-daemon-old-first",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at=OLD_LOGICAL_PURGE_AT,
                    ),
                    batch_plan_pg._create_deleted_artifact(
                        ae_client,
                        ae_headers,
                        engine=engine,
                        suffix=suffix,
                        label="ag-daemon-old-second",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at="2026-07-31T01:00:00Z",
                    ),
                    batch_plan_pg._create_deleted_artifact(
                        ae_client,
                        ae_headers,
                        engine=engine,
                        suffix=suffix,
                        label="ag-daemon-recent",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                    ),
                )
                for created in created_artifacts:
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

                bridge = AeTestClientSchedulerDaemonOperationsClient(
                    ae_client,
                    headers=ae_headers,
                )
                ag_app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
                register_artifact_operation_routes(ag_app, client=bridge)
                ag_client = TestClient(ag_app)
                ag_headers = _ag_auth_headers(request_id=request_id, trace_id=trace_id)

                config_response = ag_client.get(
                    "/admin/v1/operations/artifact-retention/scheduler-daemon",
                    headers=ag_headers,
                )
                config_projection = (
                    config_response.json() if config_response.status_code == 200 else {}
                )
                manual_response = ag_client.post(
                    (
                        "/admin/v1/operations/artifact-retention/"
                        "scheduler-daemon/manual-tick-once"
                    ),
                    json={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                        "requested_at": TICK_AT,
                        "requested_by": {
                            "actor_type": "operator",
                            "actor_id": "ag-retention-operator",
                            "tenant_id": tenant_id,
                            "workspace_id": workspace_id,
                        },
                        "reason": "protected AG daemon route postgres smoke",
                        "tick_at": TICK_AT,
                        "run_worker": True,
                        "confirm_worker_run": True,
                        "confirm_dispatch": True,
                    },
                    headers={**ag_headers, "Idempotency-Key": idempotency_key},
                )
                manual_projection = (
                    manual_response.json()
                    if manual_response.status_code == 200
                    else {}
                )
                raw_dispatch = bridge.last_daemon_dispatch
                raw_tick_once = _mapping_value(raw_dispatch.get("tick_once_result"))
                scheduler_id = str(
                    raw_dispatch.get("scheduler_id")
                    or _mapping_value(config_projection.get("daemon_config")).get(
                        "scheduler_id"
                    )
                    or ""
                )
                scheduled_enqueue = _mapping_value(
                    _mapping_value(raw_tick_once.get("enqueue_result")).get(
                        "scheduled_job_enqueue_result"
                    )
                )
                job_id = str(scheduled_enqueue.get("job_id") or "")
                job_observation = (
                    worker_pg._job_observation(
                        engine,
                        job_id=job_id,
                        idempotency_key=idempotency_key,
                    )
                    if job_id
                    else {"row_count": 0, "status": None}
                )
                lease_observation = once_pg._scheduler_once_lease_observation(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
                )
                history_rows = history_store.list_executions(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    limit=5,
                )
                after = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_after = candidate_pg._count_files(storage_root)
                checks = _ag_scheduler_daemon_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    config_response=config_response.status_code,
                    config_projection=config_projection,
                    manual_response=manual_response.status_code,
                    manual_projection=manual_projection,
                    bridge=bridge,
                    raw_dispatch=raw_dispatch,
                    raw_tick_once=raw_tick_once,
                    lease_observation=lease_observation,
                    job_observation=job_observation,
                    history_rows=history_rows,
                    before=before,
                    after=after,
                    materialized_before=materialized_before,
                    materialized_after=materialized_after,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE/AG artifact retention scheduler daemon PostgreSQL "
                        f"smoke checks failed: {', '.join(failed_checks)}"
                    )

                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup_worker = worker_pg._cleanup_worker_rows(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    worker_id=worker_id,
                )
                cleanup_lease = once_pg._cleanup_scheduler_once_lease_rows(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                manual_summary = _mapping_value(manual_projection.get("summary"))
                config_summary = _mapping_value(config_projection.get("summary"))
                projected_tick_once = _mapping_value(
                    _mapping_value(manual_projection.get("dispatch_response")).get(
                        "tick_once_result"
                    )
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "routes": {
                        "ag_daemon_config_status": config_response.status_code,
                        "ag_manual_tick_once_status": manual_response.status_code,
                        "ae_daemon_config_statuses": bridge.daemon_config_statuses,
                        "ae_daemon_control_statuses": bridge.daemon_control_statuses,
                    },
                    "ag_daemon_config": {
                        "projection_schema_version": config_projection[
                            "projection_schema_version"
                        ],
                        "projection_status": config_projection["projection_status"],
                        "scheduler_id": config_summary["scheduler_id"],
                        "manual_tick_once_available": config_summary[
                            "manual_tick_once_available"
                        ],
                        "start_daemon_available": config_summary[
                            "start_daemon_available"
                        ],
                        "source_kind": config_projection["source_status"][
                            "source_kind"
                        ],
                    },
                    "ag_manual_tick": {
                        "projection_schema_version": manual_projection[
                            "projection_schema_version"
                        ],
                        "projection_status": manual_projection["projection_status"],
                        "dispatch_status": manual_summary["last_dispatch_status"],
                        "dispatch_action": manual_summary["last_dispatch_action"],
                        "job_enqueued": manual_summary[
                            "last_dispatch_job_enqueued"
                        ],
                        "tick_once_dispatched": manual_summary[
                            "last_dispatch_tick_once_dispatched"
                        ],
                        "tick_once_result_status": projected_tick_once[
                            "result_status"
                        ],
                    },
                    "ae_raw_dispatch": {
                        "schema_version": raw_dispatch[
                            "daemon_dispatch_result_schema_version"
                        ],
                        "dispatch_status": raw_dispatch["dispatch_status"],
                        "control_status": raw_dispatch["control_plan"][
                            "decision_status"
                        ],
                        "tick_once_present": bool(raw_tick_once),
                        "tick_once_result_status": raw_tick_once["result_status"],
                    },
                    "lease": lease_observation,
                    "job": {
                        "job_id": job_id,
                        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                        "status": job_observation["status"],
                        "attempt_count": job_observation["attempt_count"],
                        "payload_command_status": job_observation[
                            "payload_command_status"
                        ],
                    },
                    "history": {
                        "row_count": len(history_rows),
                        "mode": history_rows[0]["mode"] if history_rows else None,
                        "execution_status": (
                            history_rows[0]["execution_status"]
                            if history_rows
                            else None
                        ),
                    },
                    "db_before": before,
                    "db_after_worker": after,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_worker": materialized_after,
                    },
                    "checks": checks,
                    "cleanup": {
                        **cleanup,
                        "history_rows": cleanup_history,
                        **cleanup_worker,
                        "lease_rows": cleanup_lease,
                    },
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
        history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        if scheduler_id:
            once_pg._cleanup_scheduler_once_lease_rows(
                engine,
                scheduler_id=scheduler_id,
                lease_owner_id=DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
            )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _ag_scheduler_daemon_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    config_response: int,
    config_projection: Mapping[str, Any],
    manual_response: int,
    manual_projection: Mapping[str, Any],
    bridge: AeTestClientSchedulerDaemonOperationsClient,
    raw_dispatch: Mapping[str, Any],
    raw_tick_once: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    job_observation: Mapping[str, Any],
    history_rows: list[dict[str, Any]],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    config_summary = _mapping_value(config_projection.get("summary"))
    manual_summary = _mapping_value(manual_projection.get("summary"))
    manual_dispatch = _mapping_value(manual_projection.get("dispatch_response"))
    projected_tick_once = _mapping_value(manual_dispatch.get("tick_once_result"))
    raw_metadata = _mapping_value(raw_dispatch.get("metadata"))
    return {
        "ag_config_route_ok": config_response == 200,
        "ag_config_projection_ready": config_projection.get("projection_schema_version")
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
        and config_projection.get("projection_status") == "READY",
        "ag_config_manual_ready": config_summary.get("manual_tick_once_available")
        is True
        and config_summary.get("start_daemon_available") is False,
        "ag_manual_tick_route_ok": manual_response == 200,
        "ag_manual_tick_projection_ready": manual_projection.get(
            "projection_schema_version"
        )
        == AG_ARTIFACT_OPERATION_RETENTION_DAEMON_PROJECTION_SCHEMA_VERSION
        and manual_projection.get("projection_status") == "READY",
        "ag_manual_tick_dispatch_ready": manual_summary.get("last_dispatch_status")
        == "DISPATCHED"
        and manual_summary.get("last_dispatch_action") == "manual_tick_once"
        and manual_summary.get("last_dispatch_job_enqueued") is True
        and manual_summary.get("last_dispatch_tick_once_dispatched") is True
        and projected_tick_once.get("result_status") == "SUCCEEDED",
        "ae_bridge_called_source_routes": bridge.daemon_config_statuses == [200, 200]
        and bridge.daemon_control_statuses == [200],
        "ae_raw_dispatch_contract": raw_dispatch.get(
            "daemon_dispatch_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_DISPATCH_RESULT_SCHEMA_VERSION
        and raw_dispatch.get("dispatch_status") == "DISPATCHED"
        and raw_tick_once.get("tick_once_result_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
        and raw_tick_once.get("result_status") == "SUCCEEDED"
        and raw_metadata.get("tick_once_dispatched") is True
        and raw_metadata.get("job_enqueued") is True
        and raw_metadata.get("worker_executed") is True
        and raw_metadata.get("scheduler_daemon_started") is False
        and raw_metadata.get("continuous_loop_started") is False,
        "lease_released": lease_observation.get("lease_status") == "RELEASED",
        "job_succeeded": job_observation.get("row_count") == 1
        and job_observation.get("status") == "SUCCEEDED"
        and job_observation.get("attempt_count") == 1
        and job_observation.get("payload_command_status") == "READY",
        "history_written": len(history_rows) == 1
        and history_rows[0].get("mode") == "DRY_RUN"
        and history_rows[0].get("execution_status") == "SUCCEEDED",
        "db_rows_retained": dict(after) == dict(before),
        "storage_files_retained": materialized_after == materialized_before
        and materialized_before >= 6,
        "metadata_only_evidence": _metadata_only(
            config_projection,
            manual_projection,
            raw_dispatch,
            lease_observation,
            job_observation,
            history_rows,
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


def _ag_auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized for fragment in forbidden_fragments if fragment
    )


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
                    "AE/AG artifact retention scheduler daemon smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE/AG artifact retention scheduler daemon smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE/AG artifact retention scheduler daemon smoke contains a local data path."
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
            "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"ag_service={evidence['ag_service_id']} "
            f"db_env={evidence['database_env']} "
            f"dispatch={evidence['ag_manual_tick']['dispatch_status']} "
            f"tick_once={evidence['ag_manual_tick']['tick_once_result_status']} "
            f"job={evidence['job']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_ag_artifact_retention_scheduler_daemon_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"ag_service={evidence.get('ag_service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE/AG artifact retention scheduler daemon PostgreSQL smoke."
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
    evidence = run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
