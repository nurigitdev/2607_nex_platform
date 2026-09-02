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
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
    build_artifact_retention_scheduler_daemon_config,
    build_artifact_retention_scheduler_daemon_runtime_config,
    run_artifact_retention_scheduler_daemon_one_cycle,
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


SCHEMA_VERSION = "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.v1"
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = "2026-08-31T17:30:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT
WORKER_CLOCK_TICKS = (
    "2026-09-01T03:10:01Z",
    "2026-09-01T03:10:02Z",
    "2026-09-01T03:10:03Z",
    "2026-09-01T03:10:04Z",
    "2026-09-01T03:10:05Z",
)


def run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduler_daemon_one_cycle_smoke(
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


def _execute_ae_artifact_retention_scheduler_daemon_one_cycle_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-daemon-one-cycle-{suffix}"
    workspace_id = f"workspace-artifact-daemon-one-cycle-{suffix}"
    owner_user_id = f"owner-artifact-daemon-one-cycle-{suffix}"
    scheduler_id = f"ae-artifact-retention-daemon-one-cycle-{suffix}"
    lease_owner_id = f"ae-retention-daemon-one-cycle-runner-{suffix}"
    worker_id = f"ae-artifact-retention-daemon-one-cycle-worker-{suffix}"
    idempotency_key = f"retention-daemon-one-cycle-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    job_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        lease_store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
        history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
            session_factory
        )
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-daemon-one-cycle-smoke-",
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
                    label="daemon-one-cycle-old-first",
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
                    label="daemon-one-cycle-old-second",
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
                    label="daemon-one-cycle-recent",
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
                runtime_config = build_artifact_retention_scheduler_daemon_runtime_config(
                    scheduler_config=scheduler_config,
                    enabled=True,
                    explicit_opt_in=True,
                    checked_at=TICK_AT,
                )
                daemon_config = build_artifact_retention_scheduler_daemon_config(
                    scheduler_config=scheduler_config,
                    lease_store=lease_store,
                    checked_at=TICK_AT,
                )
                one_cycle_result = run_artifact_retention_scheduler_daemon_one_cycle(
                    artifact_store=artifact_store,
                    job_queue=job_queue,
                    lease_store=lease_store,
                    history_store=history_store,
                    scheduler_config=scheduler_config,
                    runtime_config=runtime_config,
                    daemon_config=daemon_config,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    lease_owner_id=lease_owner_id,
                    retention_days=30,
                    as_of=AS_OF,
                    scan_limit=10,
                    max_delete_count=1,
                    requested_at=TICK_AT,
                    trace_id=trace_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    run_worker=True,
                    worker_id=worker_id,
                    clock=worker_pg._clock_from_sequence(WORKER_CLOCK_TICKS),
                )
                tick_once_result = once_pg._mapping_value(
                    one_cycle_result.get("tick_once_result")
                )
                scheduled_enqueue = once_pg._mapping_value(
                    once_pg._mapping_value(tick_once_result.get("enqueue_result")).get(
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
                checks = _scheduler_daemon_one_cycle_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    runtime_config=runtime_config,
                    daemon_config=daemon_config,
                    one_cycle_result=one_cycle_result,
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
                        "AE artifact retention scheduler daemon one-cycle "
                        f"PostgreSQL smoke checks failed: {', '.join(failed_checks)}"
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
                    lease_owner_id=lease_owner_id,
                )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                loop_plan = once_pg._mapping_value(one_cycle_result.get("loop_plan"))
                batch_plan = once_pg._mapping_value(tick_once_result.get("batch_plan"))
                tick_plan = once_pg._mapping_value(tick_once_result.get("tick_plan"))
                enqueue_result = once_pg._mapping_value(
                    tick_once_result.get("enqueue_result")
                )
                worker_result = once_pg._mapping_value(
                    tick_once_result.get("worker_result")
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "one_cycle": {
                        "schema_version": one_cycle_result[
                            "daemon_one_cycle_result_schema_version"
                        ],
                        "result_status": one_cycle_result["result_status"],
                        "skip_reason": one_cycle_result["skip_reason"],
                        "loop_decision_status": loop_plan["decision_status"],
                        "loop_decision_reason": loop_plan["decision_reason"],
                        "tick_once_ran": one_cycle_result["metadata"][
                            "tick_once_ran"
                        ],
                        "job_enqueued": one_cycle_result["metadata"]["job_enqueued"],
                        "lease_released": one_cycle_result["metadata"][
                            "lease_released"
                        ],
                    },
                    "runtime_config": {
                        "enablement_status": runtime_config["enablement"][
                            "enablement_status"
                        ],
                        "explicit_opt_in": runtime_config["enablement"][
                            "explicit_opt_in"
                        ],
                        "continuous_loop_started": runtime_config["loop_policy"][
                            "continuous_loop_started"
                        ],
                    },
                    "daemon_config": {
                        "scheduler_id": daemon_config["scheduler_id"],
                        "lease_backend": daemon_config["lease_repository"]["backend"],
                        "scheduler_daemon_started": daemon_config["runtime"][
                            "scheduler_daemon_started"
                        ],
                    },
                    "tick_once": {
                        "schema_version": tick_once_result[
                            "tick_once_result_schema_version"
                        ],
                        "result_status": tick_once_result["result_status"],
                        "skip_reason": tick_once_result["skip_reason"],
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
                        "retention_execution_id": once_pg._history_execution_id(
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
        once_pg._cleanup_scheduler_once_lease_rows(
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


def _scheduler_daemon_one_cycle_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    one_cycle_result: Mapping[str, Any],
    tick_once_result: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    job_observation: Mapping[str, Any],
    history_rows: list[dict[str, Any]],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    tick_once_checks = once_pg._scheduler_tick_once_checks(
        database_url=database_url,
        database_env=database_env,
        storage_root=storage_root,
        scheduler_config_response=scheduler_config_response,
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
    loop_plan = once_pg._mapping_value(one_cycle_result.get("loop_plan"))
    execution_plan = once_pg._mapping_value(one_cycle_result.get("execution_plan"))
    metadata = once_pg._mapping_value(one_cycle_result.get("metadata"))
    return {
        "one_cycle_contract": one_cycle_result.get(
            "daemon_one_cycle_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_RESULT_SCHEMA_VERSION
        and one_cycle_result.get("result_status") == "SUCCEEDED"
        and one_cycle_result.get("skip_reason") is None
        and one_cycle_result.get("tick_once_result") is not None,
        "loop_plan_ready": loop_plan.get("decision_status") == "READY"
        and loop_plan.get("decision_reason") is None
        and once_pg._mapping_value(loop_plan.get("execution_plan")).get(
            "runs_tick_once"
        )
        is True
        and once_pg._mapping_value(loop_plan.get("execution_plan")).get(
            "starts_continuous_loop"
        )
        is False,
        "runtime_opt_in_ready": runtime_config.get("enablement", {}).get(
            "enablement_status"
        )
        == "READY"
        and runtime_config.get("enablement", {}).get("explicit_opt_in") is True
        and runtime_config.get("loop_policy", {}).get("continuous_loop_started")
        is False,
        "daemon_config_ready": daemon_config.get("scheduler_id")
        == scheduler_config.get("scheduler_id")
        and daemon_config.get("lease_repository", {}).get("available") is True
        and daemon_config.get("lease_repository", {}).get("backend") == "sqlalchemy",
        "one_cycle_metadata": metadata.get("tick_once_ran") is True
        and metadata.get("lease_acquired_before_tick") is True
        and metadata.get("lease_released") is True
        and metadata.get("job_enqueued") is True
        and metadata.get("worker_executed") is True
        and metadata.get("history_write_executed") is True
        and metadata.get("scheduler_daemon_started") is False
        and metadata.get("continuous_loop_started") is False,
        "one_cycle_execution_plan": execution_plan.get("runs_tick_once") is True
        and execution_plan.get("starts_daemon") is False
        and execution_plan.get("starts_continuous_loop") is False
        and execution_plan.get("physical_delete_enabled") is False,
        "metadata_only_one_cycle_evidence": once_pg._metadata_only(
            runtime_config,
            daemon_config,
            one_cycle_result,
            forbidden_fragments=[
                database_url,
                database_env,
                once_pg._database_url_password(database_url),
                str(storage_root),
                "/data/nex-platform",
                "storage_ref",
                "content_base64",
                "rendered_payloads",
            ],
        ),
        **tick_once_checks,
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
                    "AE artifact retention scheduler daemon one-cycle smoke "
                    "contains a database password."
                )
            raise ValueError(
                "AE artifact retention scheduler daemon one-cycle smoke contains "
                f"raw {key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention scheduler daemon one-cycle smoke contains a "
            "local data path."
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
            "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"one_cycle={evidence['one_cycle']['result_status']} "
            f"loop={evidence['one_cycle']['loop_decision_status']} "
            f"tick_once={evidence['tick_once']['result_status']} "
            f"lease={evidence['lease']['lease_status']} "
            f"job={evidence['job']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon one-cycle PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
