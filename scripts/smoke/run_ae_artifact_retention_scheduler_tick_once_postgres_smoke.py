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
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_artifact_retention_scheduled_worker_postgres_smoke as worker_pg  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
    artifact_retention_scheduler_lease_table_sql,
    run_artifact_retention_scheduler_tick_once,
)
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
    SqlAlchemyArtifactRecordStore,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    build_default_rendered_artifact_storage,
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


SCHEMA_VERSION = "ae_artifact_retention_scheduler_tick_once_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = "2026-08-31T17:30:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT
WORKER_CLOCK_TICKS = (
    "2026-09-01T03:05:01Z",
    "2026-09-01T03:05:02Z",
    "2026-09-01T03:05:03Z",
    "2026-09-01T03:05:04Z",
    "2026-09-01T03:05:05Z",
)


def run_ae_artifact_retention_scheduler_tick_once_postgres_smoke(
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
        worker_pg.base_auth._require_test_database_url(
            database_url,
            env_name=database_env,
        )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_retention_scheduler_tick_once_smoke(
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


def _execute_ae_artifact_retention_scheduler_tick_once_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-scheduler-once-{suffix}"
    workspace_id = f"workspace-artifact-scheduler-once-{suffix}"
    owner_user_id = f"owner-artifact-scheduler-once-{suffix}"
    scheduler_id = f"ae-artifact-retention-scheduler-once-smoke-{suffix}"
    lease_owner_id = f"ae-retention-scheduler-once-runner-{suffix}"
    worker_id = f"ae-artifact-retention-scheduler-once-worker-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    idempotency_key = f"retention-scheduler-once-{suffix}"
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        _ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        lease_store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-scheduler-once-smoke-",
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
                    label="tick-once-old-first",
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
                    label="tick-once-old-second",
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
                    label="tick-once-recent",
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
                if isinstance(scheduler_config, dict):
                    scheduler_config["scheduler_id"] = scheduler_id

                artifact_store = SqlAlchemyArtifactRecordStore(
                    session_factory,
                    rendered_storage=build_default_rendered_artifact_storage(),
                )
                history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
                    session_factory
                )
                tick_once_result = run_artifact_retention_scheduler_tick_once(
                    artifact_store=artifact_store,
                    job_queue=job_queue,
                    lease_store=lease_store,
                    history_store=history_store,
                    scheduler_config=scheduler_config,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    lease_owner_id=lease_owner_id,
                    retention_days=30,
                    as_of=AS_OF,
                    scan_limit=10,
                    max_delete_count=1,
                    tick_at=TICK_AT,
                    trace_id=trace_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    run_worker=True,
                    worker_id=worker_id,
                    clock=worker_pg._clock_from_sequence(WORKER_CLOCK_TICKS),
                )
                scheduled_enqueue = _mapping_value(
                    _mapping_value(tick_once_result.get("enqueue_result")).get(
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
                lease_observation = _scheduler_once_lease_observation(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=lease_owner_id,
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
                checks = _scheduler_tick_once_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    tick_once_result=tick_once_result,
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
                        "AE artifact retention scheduler tick-once PostgreSQL "
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
                cleanup_lease = _cleanup_scheduler_once_lease_rows(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=lease_owner_id,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                batch_plan = _mapping_value(tick_once_result.get("batch_plan"))
                tick_plan = _mapping_value(tick_once_result.get("tick_plan"))
                enqueue_result = _mapping_value(tick_once_result.get("enqueue_result"))
                worker_result = _mapping_value(tick_once_result.get("worker_result"))
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "tick_once": {
                        "schema_version": tick_once_result[
                            "tick_once_result_schema_version"
                        ],
                        "result_status": tick_once_result["result_status"],
                        "skip_reason": tick_once_result["skip_reason"],
                        "scheduler_id": tick_once_result["scheduler_id"],
                        "lease_owner_id": tick_once_result["lease_owner_id"],
                        "lease_acquired": tick_once_result["lease_decision"][
                            "lease_acquired"
                        ],
                        "lease_released": tick_once_result["metadata"][
                            "lease_released"
                        ],
                        "job_enqueued": tick_once_result["metadata"][
                            "job_enqueued"
                        ],
                        "worker_executed": tick_once_result["metadata"][
                            "worker_executed"
                        ],
                        "history_write_executed": tick_once_result["metadata"][
                            "history_write_executed"
                        ],
                    },
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
                        "tick_status": tick_plan["tick_status"],
                        "skip_reason": tick_plan["skip_reason"],
                        "tick_id": tick_plan["tick_id"],
                        "source_plan_id": tick_plan["source_plan_id"],
                        "enqueue_status": enqueue_result["enqueue_status"],
                        "job_enqueued": enqueue_result["job_enqueued"],
                        "admission_performed": enqueue_result[
                            "admission_performed"
                        ],
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
                    "worker": {
                        "worker_id": worker_id,
                        "runner_status": worker_result.get("status"),
                    },
                    "history": {
                        "row_count": len(history_rows),
                        "retention_execution_id": _history_execution_id(
                            tick_once_result
                        ),
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
        _cleanup_scheduler_once_lease_rows(
            engine,
            scheduler_id=scheduler_id,
            lease_owner_id=lease_owner_id,
        )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _ensure_sqlite_scheduler_lease_table(engine: Any) -> None:
    if getattr(engine.dialect, "name", "") != "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(text(artifact_retention_scheduler_lease_table_sql("sqlite")))


def _scheduler_once_lease_observation(
    engine: Any,
    *,
    scheduler_id: str,
    lease_owner_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        scheduler_id,
                        lease_owner_id,
                        lease_status,
                        fencing_token,
                        idempotency_key,
                        guardrails,
                        metadata
                    FROM ae_artifact_retention_scheduler_leases
                    WHERE scheduler_id = :scheduler_id
                      AND lease_owner_id = :lease_owner_id
                    """
                ),
                {
                    "scheduler_id": scheduler_id,
                    "lease_owner_id": lease_owner_id,
                },
            )
            .mappings()
            .all()
        )
    if not rows:
        return {
            "row_count": 0,
            "scheduler_id": scheduler_id,
            "lease_owner_id": lease_owner_id,
            "lease_status": None,
            "fencing_token": None,
        }
    row = rows[0]
    return {
        "row_count": len(rows),
        "scheduler_id": row["scheduler_id"],
        "lease_owner_id": row["lease_owner_id"],
        "lease_status": row["lease_status"],
        "fencing_token": int(row["fencing_token"]),
        "idempotency_key": row["idempotency_key"],
        "guardrails": _json_value(row["guardrails"], {}),
        "metadata": _json_value(row["metadata"], {}),
    }


def _cleanup_scheduler_once_lease_rows(
    engine: Any,
    *,
    scheduler_id: str,
    lease_owner_id: str,
) -> int:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM ae_artifact_retention_scheduler_leases
                    WHERE scheduler_id = :scheduler_id
                      AND lease_owner_id = :lease_owner_id
                    """
                ),
                {
                    "scheduler_id": scheduler_id,
                    "lease_owner_id": lease_owner_id,
                },
            )
            return int(result.rowcount or 0)
    except SQLAlchemyError:
        return 0


def _scheduler_tick_once_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    tick_once_result: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    job_observation: Mapping[str, Any],
    history_rows: list[dict[str, Any]],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    runtime = _mapping_value(scheduler_config.get("runtime"))
    tick_plan = _mapping_value(tick_once_result.get("tick_plan"))
    enqueue_result = _mapping_value(tick_once_result.get("enqueue_result"))
    metadata = _mapping_value(tick_once_result.get("metadata"))
    lease_guardrails = _mapping_value(lease_observation.get("guardrails"))
    lease_metadata = _mapping_value(lease_observation.get("metadata"))
    history_id = _history_execution_id(tick_once_result)
    job_id = _mapping_value(
        _mapping_value(enqueue_result.get("scheduled_job_enqueue_result")).get(
            "enqueued_job"
        )
    ).get("job_id")
    return {
        "scheduler_config_route_ok": scheduler_config_response == 200,
        "scheduler_config_sqlalchemy_queue": runtime.get("job_queue_available") is True
        and runtime.get("job_queue_backend") == "SqlAlchemyJobQueue",
        "tick_once_contract": tick_once_result.get("tick_once_result_schema_version")
        == AE_ARTIFACT_RETENTION_SCHEDULER_TICK_ONCE_RESULT_SCHEMA_VERSION
        and tick_once_result.get("result_status") == "SUCCEEDED"
        and tick_once_result.get("skip_reason") is None,
        "tick_once_metadata": metadata.get("lease_acquired_before_tick") is True
        and metadata.get("lease_released") is True
        and metadata.get("job_enqueued") is True
        and metadata.get("worker_executed") is True
        and metadata.get("history_write_executed") is True
        and metadata.get("scheduler_daemon_started") is False
        and metadata.get("continuous_loop_started") is False
        and metadata.get("physical_delete_automation_enabled") is False,
        "batch_plan_ready": _mapping_value(tick_once_result.get("batch_plan")).get(
            "plan_status"
        )
        == "READY"
        and _mapping_value(tick_once_result.get("batch_plan")).get("selected_count")
        == 1,
        "tick_plan_ready": tick_plan.get("tick_status") == "READY"
        and tick_plan.get("skip_reason") is None
        and _mapping_value(tick_plan.get("runtime")).get("in_batch_window") is True,
        "enqueue_job_enqueued": enqueue_result.get("enqueue_status") == "ENQUEUED"
        and enqueue_result.get("job_enqueued") is True
        and enqueue_result.get("admission_performed") is True,
        "lease_row_persisted_released": lease_observation.get("row_count") == 1
        and lease_observation.get("lease_status") == "RELEASED"
        and lease_observation.get("fencing_token") == 1
        and lease_guardrails.get("scheduler_daemon_started") is False
        and lease_metadata.get("job_enqueued") is False,
        "job_completed": job_observation.get("row_count") == 1
        and job_observation.get("job_id") == job_id
        and job_observation.get("status") == "SUCCEEDED"
        and job_observation.get("attempt_count") == 1
        and job_observation.get("payload_command_status") == "READY",
        "history_persisted_dry_run": len(history_rows) == 1
        and history_rows[0].get("mode") == "DRY_RUN"
        and history_rows[0].get("execution_status") == "SUCCEEDED"
        and history_rows[0].get("retention_execution_id") == history_id,
        "db_rows_retained": dict(after) == dict(before),
        "storage_files_retained": materialized_after == materialized_before
        and materialized_before >= 6,
        "metadata_only_evidence": _metadata_only(
            scheduler_config,
            tick_once_result,
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


def _history_execution_id(tick_once_result: Mapping[str, Any]) -> str | None:
    worker_result = _mapping_value(tick_once_result.get("worker_result"))
    handler_result = _mapping_value(worker_result.get("handler_result"))
    history = _mapping_value(handler_result.get("history"))
    return history.get("retention_execution_id")


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


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
                    "AE artifact retention scheduler tick-once smoke contains "
                    "a database password."
                )
            raise ValueError(
                "AE artifact retention scheduler tick-once smoke contains raw "
                f"{key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduler tick-once smoke contains a local "
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
            "ae_artifact_retention_scheduler_tick_once_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_tick_once_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"tick_once={evidence['tick_once']['result_status']} "
            f"lease={evidence['lease']['lease_status']} "
            f"job={evidence['job']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_tick_once_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention scheduler tick-once PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_tick_once_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
