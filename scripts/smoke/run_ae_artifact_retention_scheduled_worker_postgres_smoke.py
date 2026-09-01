#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_batch_plan_postgres_smoke as batch_plan_pg  # noqa: E402
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
    SqlAlchemyArtifactRecordStore,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    build_artifact_retention_scheduled_job_admission,
    build_default_rendered_artifact_storage,
    enqueue_artifact_retention_scheduled_job,
    register_artifact_handoff_routes,
    run_artifact_retention_scheduled_worker_once,
    summarize_artifact_retention_scheduled_execution_worker_result,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_artifact_retention_scheduled_worker_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
CHECKED_AT = batch_plan_pg.CHECKED_AT
COMMAND_CREATED_AT = "2026-09-01T03:05:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT
WORKER_STARTED_AT = "2026-09-01T03:05:00Z"
WORKER_CLOCK_TICKS = (
    "2026-09-01T03:05:01Z",
    "2026-09-01T03:05:02Z",
    "2026-09-01T03:05:03Z",
    "2026-09-01T03:05:04Z",
    "2026-09-01T03:05:05Z",
)


def run_ae_artifact_retention_scheduled_worker_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduled_worker_smoke(
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


def _execute_ae_artifact_retention_scheduled_worker_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduled-worker-{suffix}"
    workspace_id = f"workspace-artifact-scheduled-worker-{suffix}"
    owner_user_id = f"owner-artifact-scheduled-worker-{suffix}"
    worker_id = f"ae-artifact-retention-scheduled-worker-smoke-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    idempotency_key: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-scheduled-worker-smoke-",
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = artifact_pg.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = artifact_pg._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                first_old = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-first",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=OLD_LOGICAL_PURGE_AT,
                )
                second_old = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-second",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at="2026-07-31T01:00:00Z",
                )
                recent = batch_plan_pg._create_deleted_artifact(
                    client,
                    headers,
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
                plan_response = client.get(
                    "/api/v1/artifact-retention/batch-plan",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "checked_at": CHECKED_AT,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                    },
                    headers={
                        **headers,
                        "Idempotency-Key": f"retention-scheduled-worker-plan-{suffix}",
                    },
                )
                plan_payload = (
                    plan_response.json() if plan_response.status_code == 200 else {}
                )
                admission = build_artifact_retention_scheduled_job_admission(
                    plan_payload,
                    trace_id=trace_id,
                    request_id=request_id,
                    trigger_type="scheduler_tick",
                    command_created_at=COMMAND_CREATED_AT,
                    requested_by={"actor_type": "service", "actor_id": "nex-ag"},
                    idempotency_key=f"retention-scheduled-worker-job-{suffix}",
                )
                job_id = admission["job_id"]
                idempotency_key = admission["idempotency_key"]
                _cleanup_worker_rows(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    worker_id=worker_id,
                )

                queue = SqlAlchemyJobQueue(session_factory)
                enqueue_result = enqueue_artifact_retention_scheduled_job(
                    queue,
                    admission,
                )
                duplicate_result = enqueue_artifact_retention_scheduled_job(
                    queue,
                    admission,
                )
                queued_job = queue.get_job(job_id)
                queued_observation = _job_observation(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                )

                artifact_store = SqlAlchemyArtifactRecordStore(
                    session_factory,
                    rendered_storage=build_default_rendered_artifact_storage(),
                )
                history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
                    session_factory
                )
                heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
                heartbeat_emitter = WorkerHeartbeatEmitter(
                    service_id=SERVICE_ID,
                    worker_id=worker_id,
                    worker_type=AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
                    store=heartbeat_store,
                    started_at=WORKER_STARTED_AT,
                    metadata={"job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE},
                )
                worker_execution = run_artifact_retention_scheduled_worker_once(
                    job_queue=queue,
                    artifact_store=artifact_store,
                    history_store=history_store,
                    worker_id=worker_id,
                    worker_heartbeat_emitter=heartbeat_emitter,
                    clock=_clock_from_sequence(WORKER_CLOCK_TICKS),
                )
                worker_summary = (
                    summarize_artifact_retention_scheduled_execution_worker_result(
                        worker_execution.handler_result or {}
                    )
                    if worker_execution.handler_result is not None
                    else {}
                )
                completed_job = queue.get_job(job_id)
                completed_observation = _job_observation(
                    engine,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                )
                heartbeat = heartbeat_store.get_heartbeat(SERVICE_ID, worker_id)
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
                checks = {
                    "plan_route_ok": plan_response.status_code == 200,
                    "plan_ready": plan_payload.get("plan_status") == "READY",
                    "admission_ready": admission["admission_status"] == "READY",
                    "enqueue_status": enqueue_result["enqueue_status"] == "ENQUEUED",
                    "duplicate_idempotent": (
                        duplicate_result["enqueued_job"]["job_id"] == job_id
                        and queued_observation["row_count"] == 1
                    ),
                    "queued_job_observed": (
                        isinstance(queued_job, Mapping)
                        and queued_job["status"] == "QUEUED"
                        and queued_observation["status"] == "QUEUED"
                        and queued_observation["attempt_count"] == 0
                    ),
                    "worker_succeeded": worker_execution.status == "SUCCEEDED",
                    "worker_claimed_job": (
                        isinstance(worker_execution.job, Mapping)
                        and worker_execution.job["job_id"] == job_id
                        and worker_execution.job["status"] == "RUNNING"
                        and worker_execution.job["attempt_count"] == 1
                    ),
                    "worker_completed_job": (
                        isinstance(worker_execution.completed_job, Mapping)
                        and worker_execution.completed_job["job_id"] == job_id
                        and worker_execution.completed_job["status"] == "SUCCEEDED"
                    ),
                    "completed_job_persisted": (
                        isinstance(completed_job, Mapping)
                        and completed_job["status"] == "SUCCEEDED"
                        and completed_observation["status"] == "SUCCEEDED"
                        and completed_observation["attempt_count"] == 1
                        and completed_observation["completed_at"] is not None
                        and completed_observation["locked_by"] is None
                    ),
                    "history_written": worker_summary.get("history_written") is True,
                    "history_row_persisted": (
                        len(history_rows) == 1
                        and history_rows[0]["execution"]["execution_id"]
                        == worker_summary.get("retention_execution_id")
                    ),
                    "heartbeat_persisted": (
                        isinstance(heartbeat, Mapping)
                        and heartbeat["status"] == "IDLE"
                        and heartbeat["active_job_id"] is None
                        and heartbeat["worker_type"]
                        == AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE
                        and heartbeat["metadata"].get("job_status") == "SUCCEEDED"
                    ),
                    "db_rows_retained": after == before,
                    "storage_files_retained": (
                        materialized_after == materialized_before
                        and materialized_before >= 6
                    ),
                    "metadata_only_evidence": _metadata_only(
                        admission,
                        enqueue_result,
                        duplicate_result,
                        worker_execution.to_summary(),
                        worker_summary,
                        queued_observation,
                        completed_observation,
                        heartbeat,
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
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduled worker PostgreSQL "
                        f"smoke checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup_worker = _cleanup_worker_rows(
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
                    "batch_plan": {
                        "plan_status": plan_payload["plan_status"],
                        "scheduler_status": plan_payload["scheduler_status"],
                        "candidate_count": plan_payload["candidate_count"],
                        "selected_count": plan_payload["selected_count"],
                        "selected_artifact_ids": batch_plan_pg._selected_artifact_ids(
                            plan_payload
                        ),
                    },
                    "job": {
                        "job_id": job_id,
                        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                        "enqueue_status": enqueue_result["enqueue_status"],
                        "duplicate_job_id": duplicate_result["enqueued_job"]["job_id"],
                        "queued_status": queued_observation["status"],
                        "completed_status": completed_observation["status"],
                        "attempt_count": completed_observation["attempt_count"],
                    },
                    "worker": {
                        "worker_id": worker_id,
                        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_TYPE,
                        "runner_status": worker_execution.status,
                        "handler_status": worker_summary["worker_status"],
                        "heartbeat_status": heartbeat["status"],
                    },
                    "history": {
                        "row_count": len(history_rows),
                        "retention_execution_id": worker_summary[
                            "retention_execution_id"
                        ],
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
                    },
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        if job_id and idempotency_key:
            _cleanup_worker_rows(
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


def _job_observation(
    engine: Any,
    *,
    job_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        job_id,
                        job_type,
                        status,
                        attempt_count,
                        max_attempts,
                        retryable,
                        locked_by,
                        locked_at,
                        started_at,
                        completed_at,
                        payload,
                        error,
                        replay_lineage,
                        available_at,
                        created_at,
                        updated_at
                    FROM service_jobs
                    WHERE job_id = :job_id
                       OR (
                            job_type = :job_type
                        AND idempotency_key = :idempotency_key
                       )
                    ORDER BY created_at ASC, job_id ASC
                    """
                ),
                {
                    "job_id": job_id,
                    "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                    "idempotency_key": idempotency_key,
                },
            )
            .mappings()
            .all()
        )
    if not rows:
        return {
            "row_count": 0,
            "job_id": job_id,
            "status": None,
            "attempt_count": None,
        }
    row = rows[0]
    payload = _json_value(row["payload"], {})
    return {
        "row_count": len(rows),
        "job_id": row["job_id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "attempt_count": int(row["attempt_count"]),
        "max_attempts": int(row["max_attempts"]),
        "retryable": bool(row["retryable"]),
        "locked_by": row["locked_by"],
        "locked_at": _datetime_value_or_none(row["locked_at"]),
        "started_at": _datetime_value_or_none(row["started_at"]),
        "completed_at": _datetime_value_or_none(row["completed_at"]),
        "payload_command_id": payload.get("command_id"),
        "payload_command_status": payload.get("command_status"),
        "error": _json_value(row["error"], None),
        "replay_lineage": _json_value(row["replay_lineage"], None),
        "available_at": history_pg._datetime_value(row["available_at"]),
        "created_at": history_pg._datetime_value(row["created_at"]),
        "updated_at": history_pg._datetime_value(row["updated_at"]),
    }


def _cleanup_worker_rows(
    engine: Any,
    *,
    job_id: str,
    idempotency_key: str,
    worker_id: str,
) -> dict[str, int]:
    deleted = {"job_rows": 0, "heartbeat_rows": 0}
    try:
        with engine.begin() as connection:
            heartbeat_result = connection.execute(
                text(
                    """
                    DELETE FROM service_worker_heartbeats
                    WHERE service_id = :service_id
                      AND worker_id = :worker_id
                    """
                ),
                {"service_id": SERVICE_ID, "worker_id": worker_id},
            )
            deleted["heartbeat_rows"] += int(heartbeat_result.rowcount or 0)
            job_result = connection.execute(
                text(
                    """
                    DELETE FROM service_jobs
                    WHERE job_id = :job_id
                       OR (
                            job_type = :job_type
                        AND idempotency_key = :idempotency_key
                       )
                    """
                ),
                {
                    "job_id": job_id,
                    "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                    "idempotency_key": idempotency_key,
                },
            )
            deleted["job_rows"] += int(job_result.rowcount or 0)
    except SQLAlchemyError:
        return deleted
    return deleted


def _clock_from_sequence(timestamps: tuple[str, ...]) -> Callable[[], str]:
    remaining = iter(timestamps)
    last = timestamps[-1]

    def clock() -> str:
        nonlocal last
        try:
            last = next(remaining)
        except StopIteration:
            pass
        return last

    return clock


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _datetime_value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return history_pg._datetime_value(value)


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
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(
        fragment not in serialized
        for fragment in forbidden_fragments
        if fragment
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
                    "AE artifact retention scheduled worker smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE artifact retention scheduled worker smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduled worker smoke contains a local "
            "data path."
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
            "ae_artifact_retention_scheduled_worker_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduled_worker_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"job_status={evidence['job']['completed_status']} "
            f"worker_status={evidence['worker']['runner_status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"heartbeat={evidence['worker']['heartbeat_status']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_jobs={evidence['cleanup']['job_rows']}"
        )
    return (
        "ae_artifact_retention_scheduled_worker_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention scheduled worker PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduled_worker_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
