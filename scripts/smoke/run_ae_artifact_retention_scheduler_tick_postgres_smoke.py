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
import run_ae_artifact_retention_scheduled_worker_postgres_smoke as worker_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ENQUEUE_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION,
    build_artifact_retention_scheduler_tick_plan,
    enqueue_artifact_retention_scheduler_tick_job,
    register_artifact_handoff_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
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


SCHEMA_VERSION = "ae_artifact_retention_scheduler_tick_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
CHECKED_AT = batch_plan_pg.CHECKED_AT
TICK_AT = "2026-08-31T17:30:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT


def run_ae_artifact_retention_scheduler_tick_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduler_tick_smoke(
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


def _execute_ae_artifact_retention_scheduler_tick_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduler-tick-{suffix}"
    workspace_id = f"workspace-artifact-scheduler-tick-{suffix}"
    owner_user_id = f"owner-artifact-scheduler-tick-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    idempotency_key = f"retention-scheduler-tick-{suffix}"
    worker_id = f"ae-artifact-retention-scheduler-tick-smoke-{suffix}"
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-scheduler-tick-smoke-",
        ) as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory,
                    job_queue=job_queue,
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
                    label="tick-old-first",
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
                    label="tick-old-second",
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
                    label="tick-recent",
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
                scheduler_config_response = client.get(
                    "/api/v1/artifact-retention/scheduler-config",
                    headers=headers,
                )
                scheduler_config = (
                    scheduler_config_response.json()
                    if scheduler_config_response.status_code == 200
                    else {}
                )
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
                        "Idempotency-Key": f"retention-scheduler-tick-plan-{suffix}",
                    },
                )
                batch_plan = plan_response.json() if plan_response.status_code == 200 else {}
                tick_plan = build_artifact_retention_scheduler_tick_plan(
                    batch_plan,
                    scheduler_config=scheduler_config,
                    tick_at=TICK_AT,
                    trace_id=trace_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
                enqueue_result = enqueue_artifact_retention_scheduler_tick_job(
                    job_queue,
                    tick_plan,
                )
                duplicate_result = enqueue_artifact_retention_scheduler_tick_job(
                    job_queue,
                    tick_plan,
                )
                scheduled_result = enqueue_result.get("scheduled_job_enqueue_result")
                if isinstance(scheduled_result, Mapping):
                    job_id = str(scheduled_result.get("job_id") or "")
                db_job = (
                    _scheduler_tick_job_observation(
                        engine,
                        job_id=job_id,
                        idempotency_key=idempotency_key,
                    )
                    if job_id
                    else {"row_count": 0, "status": None}
                )
                scheduled_jobs_response = client.get(
                    "/api/v1/artifact-retention/scheduled-jobs",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "status": "QUEUED",
                        "limit": "10",
                    },
                    headers=headers,
                )
                scheduled_jobs = (
                    scheduled_jobs_response.json()
                    if scheduled_jobs_response.status_code == 200
                    else {}
                )
                after = batch_plan_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                materialized_after = candidate_pg._count_files(storage_root)
                checks = _scheduler_tick_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    plan_response=plan_response.status_code,
                    batch_plan=batch_plan,
                    tick_plan=tick_plan,
                    enqueue_result=enqueue_result,
                    duplicate_result=duplicate_result,
                    scheduled_jobs_response=scheduled_jobs_response.status_code,
                    scheduled_jobs=scheduled_jobs,
                    db_job=db_job,
                    before=before,
                    after=after,
                    materialized_before=materialized_before,
                    materialized_after=materialized_after,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduler tick PostgreSQL smoke "
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
                    "batch_plan": {
                        "plan_status": batch_plan["plan_status"],
                        "scheduler_status": batch_plan["scheduler_status"],
                        "candidate_count": batch_plan["candidate_count"],
                        "selected_count": batch_plan["selected_count"],
                        "selected_artifact_ids": batch_plan_pg._selected_artifact_ids(
                            batch_plan
                        ),
                    },
                    "scheduler_tick": {
                        "tick_schema_version": tick_plan[
                            "artifact_retention_scheduler_tick_plan_schema_version"
                        ],
                        "tick_enqueue_schema_version": enqueue_result[
                            "artifact_retention_scheduler_tick_enqueue_result_schema_version"
                        ],
                        "tick_status": tick_plan["tick_status"],
                        "skip_reason": tick_plan["skip_reason"],
                        "tick_id": tick_plan["tick_id"],
                        "source_plan_id": tick_plan["source_plan_id"],
                        "in_batch_window": tick_plan["runtime"]["in_batch_window"],
                        "enqueue_status": enqueue_result["enqueue_status"],
                        "job_enqueued": enqueue_result["job_enqueued"],
                        "admission_performed": enqueue_result["admission_performed"],
                        "duplicate_job_id": duplicate_result[
                            "scheduled_job_enqueue_result"
                        ]["job_id"],
                    },
                    "job": {
                        "job_id": job_id,
                        "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                        "status": db_job["status"],
                        "attempt_count": db_job["attempt_count"],
                        "payload_trigger_type": db_job["payload_trigger_type"],
                        "payload_command_status": db_job["payload_command_status"],
                    },
                    "scheduled_jobs": {
                        "schema_version": scheduled_jobs[
                            "artifact_retention_scheduled_job_collection_schema_version"
                        ],
                        "count": scheduled_jobs["count"],
                        "queued_count": scheduled_jobs["summary"]["status_counts"][
                            "QUEUED"
                        ],
                        "job_ids": _scheduled_job_ids(scheduled_jobs),
                    },
                    "db_before": before,
                    "db_after_enqueue": after,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_enqueue": materialized_after,
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


def _scheduler_tick_job_observation(
    engine: Any,
    *,
    job_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    observation = worker_pg._job_observation(
        engine,
        job_id=job_id,
        idempotency_key=idempotency_key,
    )
    if observation.get("row_count") != 1:
        return {
            **observation,
        "idempotency_key_matches": False,
        "payload_trigger_type": None,
        "payload_execution_mode": None,
        "payload_selected_count": None,
        "payload_source_plan_id": None,
            "subject_type": None,
            "subject_id": None,
        }
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        trace_id,
                        request_id,
                        idempotency_key,
                        subject_type,
                        subject_id,
                        payload
                    FROM service_jobs
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one()
        )
    payload = worker_pg._json_value(row["payload"], {})
    scheduled_command = (
        payload.get("scheduled_command") if isinstance(payload, Mapping) else None
    )
    if not isinstance(scheduled_command, Mapping):
        scheduled_command = {}
    return {
        **observation,
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "idempotency_key_matches": row["idempotency_key"] == idempotency_key,
        "payload_trigger_type": scheduled_command.get("trigger_type"),
        "payload_execution_mode": scheduled_command.get("execution_mode"),
        "payload_selected_count": scheduled_command.get("selected_count"),
        "payload_source_plan_id": scheduled_command.get("source_plan_id"),
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
    }


def _scheduler_tick_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    plan_response: int,
    batch_plan: Mapping[str, Any],
    tick_plan: Mapping[str, Any],
    enqueue_result: Mapping[str, Any],
    duplicate_result: Mapping[str, Any],
    scheduled_jobs_response: int,
    scheduled_jobs: Mapping[str, Any],
    db_job: Mapping[str, Any],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    runtime = scheduler_config.get("runtime")
    if not isinstance(runtime, Mapping):
        runtime = {}
    tick_runtime = tick_plan.get("runtime")
    if not isinstance(tick_runtime, Mapping):
        tick_runtime = {}
    scheduled_enqueue = enqueue_result.get("scheduled_job_enqueue_result")
    if not isinstance(scheduled_enqueue, Mapping):
        scheduled_enqueue = {}
    duplicate_enqueue = duplicate_result.get("scheduled_job_enqueue_result")
    if not isinstance(duplicate_enqueue, Mapping):
        duplicate_enqueue = {}
    queue_admission = enqueue_result.get("queue_admission")
    if not isinstance(queue_admission, Mapping):
        queue_admission = {}
    scheduled_items = scheduled_jobs.get("items")
    if not isinstance(scheduled_items, list):
        scheduled_items = []
    scheduled_summary = scheduled_jobs.get("summary")
    if not isinstance(scheduled_summary, Mapping):
        scheduled_summary = {}
    scheduled_status_counts = scheduled_summary.get("status_counts")
    if not isinstance(scheduled_status_counts, Mapping):
        scheduled_status_counts = {}
    job_id = scheduled_enqueue.get("job_id")
    return {
        "scheduler_config_route_ok": scheduler_config_response == 200,
        "scheduler_tick_config_sqlalchemy_queue": runtime.get("job_queue_available")
        is True
        and runtime.get("job_queue_backend") == "SqlAlchemyJobQueue"
        and runtime.get("scheduler_tick_admission_enabled") is True
        and runtime.get("scheduler_daemon_enabled") is False,
        "batch_plan_route_ok": plan_response == 200,
        "batch_plan_ready": batch_plan.get("plan_status") == "READY"
        and batch_plan.get("selected_count") == 1,
        "tick_plan_ready": tick_plan.get(
            "artifact_retention_scheduler_tick_plan_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_TICK_PLAN_SCHEMA_VERSION
        and tick_plan.get("tick_status") == "READY"
        and tick_plan.get("skip_reason") is None,
        "tick_plan_window_enforced": tick_runtime.get("batch_window_enforced") is True
        and tick_runtime.get("in_batch_window") is True,
        "tick_plan_command_preview": isinstance(tick_plan.get("command_preview"), Mapping)
        and tick_plan["command_preview"].get("trigger_type") == "scheduler_tick"
        and tick_plan["command_preview"].get("command_status") == "READY"
        and tick_plan["command_preview"].get("execution_mode") == "DRY_RUN",
        "tick_enqueue_contract": enqueue_result.get(
            "artifact_retention_scheduler_tick_enqueue_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ENQUEUE_RESULT_SCHEMA_VERSION
        and enqueue_result.get("enqueue_status") == "ENQUEUED"
        and enqueue_result.get("job_enqueued") is True
        and enqueue_result.get("admission_performed") is True,
        "tick_enqueue_queue_admission": queue_admission.get("job_enqueued") is True
        and queue_admission.get("scheduler_daemon_started") is False
        and queue_admission.get("worker_execution_performed") is False
        and queue_admission.get("physical_delete_automation_enabled") is False,
        "scheduled_job_enqueue_result": scheduled_enqueue.get("enqueue_status")
        == "ENQUEUED"
        and scheduled_enqueue.get("trigger_type") == "scheduler_tick"
        and _mapping_value(scheduled_enqueue.get("enqueued_job")).get("status")
        == "QUEUED",
        "duplicate_idempotent": duplicate_enqueue.get("job_id") == job_id
        and db_job.get("row_count") == 1,
        "db_job_persisted_once": db_job.get("row_count") == 1,
        "db_job_queued": db_job.get("status") == "QUEUED"
        and db_job.get("attempt_count") == 0
        and db_job.get("idempotency_key_matches") is True
        and db_job.get("payload_trigger_type") == "scheduler_tick"
        and db_job.get("payload_command_status") == "READY"
        and db_job.get("payload_execution_mode") == "DRY_RUN"
        and db_job.get("payload_selected_count") == 1,
        "ae_scheduled_jobs_route_reads_tick_job": scheduled_jobs_response == 200
        and scheduled_jobs.get(
            "artifact_retention_scheduled_job_collection_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULED_JOB_COLLECTION_SCHEMA_VERSION
        and scheduled_jobs.get("count") == 1
        and scheduled_status_counts.get("QUEUED") == 1
        and _scheduled_job_ids({"items": scheduled_items}) == [job_id],
        "db_rows_retained": dict(after) == dict(before),
        "storage_files_retained": materialized_after == materialized_before
        and materialized_before >= 6,
        "metadata_only_evidence": _metadata_only(
            scheduler_config,
            batch_plan,
            tick_plan,
            enqueue_result,
            duplicate_result,
            scheduled_jobs,
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


def _scheduled_job_ids(collection: Mapping[str, Any]) -> list[str]:
    items = collection.get("items")
    if not isinstance(items, list):
        return []
    return [
        str(item["job_id"])
        for item in items
        if isinstance(item, Mapping) and item.get("job_id")
    ]


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
                    "AE artifact retention scheduler tick smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE artifact retention scheduler tick smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduler tick smoke contains a local "
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
            "ae_artifact_retention_scheduler_tick_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_tick_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"tick_status={evidence['scheduler_tick']['tick_status']} "
            f"enqueue={evidence['scheduler_tick']['enqueue_status']} "
            f"job_status={evidence['job']['status']} "
            f"scheduled_jobs={evidence['scheduled_jobs']['count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_jobs={evidence['cleanup']['job_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_tick_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention scheduler tick PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_tick_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
