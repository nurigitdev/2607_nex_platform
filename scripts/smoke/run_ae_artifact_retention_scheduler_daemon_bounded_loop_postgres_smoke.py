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
import run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke as one_cycle_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
    build_artifact_retention_scheduler_daemon_config,
    build_artifact_retention_scheduler_daemon_runtime_config,
    run_artifact_retention_scheduler_daemon_bounded_loop,
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


SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = "2026-08-31T17:30:00Z"
SECOND_TICK_AT = "2026-08-31T17:32:00Z"
CUTOFF_AT = "2026-08-02T00:00:00Z"
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT
WORKER_CLOCK_TICKS = (
    "2026-09-01T03:20:01Z",
    "2026-09-01T03:20:02Z",
    "2026-09-01T03:20:03Z",
    "2026-09-01T03:20:04Z",
    "2026-09-01T03:20:05Z",
    "2026-09-01T03:20:06Z",
    "2026-09-01T03:20:07Z",
    "2026-09-01T03:20:08Z",
    "2026-09-01T03:20:09Z",
    "2026-09-01T03:20:10Z",
)


def run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduler_daemon_bounded_loop_smoke(
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


def _execute_ae_artifact_retention_scheduler_daemon_bounded_loop_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-daemon-bounded-loop-{suffix}"
    workspace_id = f"workspace-artifact-daemon-bounded-loop-{suffix}"
    owner_user_id = f"owner-artifact-daemon-bounded-loop-{suffix}"
    scheduler_id = f"ae-artifact-retention-daemon-bounded-loop-{suffix}"
    worker_id = f"ae-artifact-retention-bounded-loop-worker-{suffix}"
    daemon_worker_id = f"ae-artifact-retention-bounded-loop-heartbeat-{suffix}"
    idempotency_key = f"retention-daemon-bounded-loop-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        lease_store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
        history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
            session_factory
        )
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-daemon-bounded-loop-smoke-",
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
                    worker_heartbeat_store=heartbeat_store,
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

                for created in (
                    batch_plan_pg._create_deleted_artifact(
                        client,
                        headers,
                        engine=engine,
                        suffix=suffix,
                        label="daemon-bounded-loop-old-first",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at=OLD_LOGICAL_PURGE_AT,
                    ),
                    batch_plan_pg._create_deleted_artifact(
                        client,
                        headers,
                        engine=engine,
                        suffix=suffix,
                        label="daemon-bounded-loop-old-second",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at="2026-07-31T01:00:00Z",
                    ),
                    batch_plan_pg._create_deleted_artifact(
                        client,
                        headers,
                        engine=engine,
                        suffix=suffix,
                        label="daemon-bounded-loop-recent",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        owner_user_id=owner_user_id,
                        logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                    ),
                ):
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
                    interval_seconds=120,
                    jitter_seconds=0,
                )
                daemon_config = build_artifact_retention_scheduler_daemon_config(
                    scheduler_config=scheduler_config,
                    lease_store=lease_store,
                    checked_at=TICK_AT,
                )
                daemon_heartbeat_emitter = WorkerHeartbeatEmitter(
                    service_id=SERVICE_ID,
                    worker_id=daemon_worker_id,
                    worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
                    store=heartbeat_store,
                    started_at=TICK_AT,
                    metadata={
                        "smoke_schema_version": SCHEMA_VERSION,
                        "bounded_loop": True,
                    },
                )
                loop_result = run_artifact_retention_scheduler_daemon_bounded_loop(
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
                    max_cycles=2,
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
                    daemon_heartbeat_emitter=daemon_heartbeat_emitter,
                )
                job_observations = _bounded_loop_job_observations(
                    engine,
                    idempotency_key=idempotency_key,
                )
                lease_observation = once_pg._scheduler_once_lease_observation(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=(
                        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
                    ),
                )
                history_rows = history_store.list_executions(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    limit=10,
                )
                daemon_heartbeat = heartbeat_store.get_heartbeat(
                    SERVICE_ID,
                    daemon_worker_id,
                )
                daemon_runtime_response = client.get(
                    "/api/v1/artifact-retention/scheduler-daemon-runtime",
                    params={"checked_at": SECOND_TICK_AT},
                    headers=headers,
                )
                daemon_runtime = (
                    daemon_runtime_response.json()
                    if daemon_runtime_response.status_code == 200
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
                checks = _bounded_loop_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    runtime_config=runtime_config,
                    daemon_config=daemon_config,
                    loop_result=loop_result,
                    job_observations=job_observations,
                    lease_observation=lease_observation,
                    daemon_heartbeat=daemon_heartbeat,
                    daemon_runtime_response=daemon_runtime_response.status_code,
                    daemon_runtime=daemon_runtime,
                    history_rows=history_rows,
                    before=before,
                    after=after,
                    materialized_before=materialized_before,
                    materialized_after=materialized_after,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduler daemon bounded-loop "
                        f"PostgreSQL smoke checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup_jobs = _cleanup_bounded_loop_runtime_rows(
                    engine,
                    idempotency_key=idempotency_key,
                    worker_id=worker_id,
                    daemon_worker_id=daemon_worker_id,
                )
                cleanup_lease = once_pg._cleanup_scheduler_once_lease_rows(
                    engine,
                    scheduler_id=scheduler_id,
                    lease_owner_id=(
                        DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
                    ),
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
                    "bounded_loop": _bounded_loop_evidence(loop_result),
                    "cycles": _bounded_loop_cycle_evidence(loop_result),
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
                    "lease": lease_observation,
                    "jobs": job_observations,
                    "daemon_heartbeat": _daemon_heartbeat_evidence(
                        daemon_worker_id=daemon_worker_id,
                        daemon_heartbeat=daemon_heartbeat,
                    ),
                    "daemon_runtime": one_cycle_pg._daemon_runtime_evidence(
                        daemon_runtime=daemon_runtime,
                    ),
                    "history": {
                        "row_count": len(history_rows),
                        "modes": [row["mode"] for row in history_rows],
                        "execution_statuses": [
                            row["execution_status"] for row in history_rows
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
                        **cleanup_jobs,
                        "lease_rows": cleanup_lease,
                    },
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_bounded_loop_runtime_rows(
            engine,
            idempotency_key=idempotency_key,
            worker_id=worker_id,
            daemon_worker_id=daemon_worker_id,
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
            lease_owner_id=(
                DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID
            ),
        )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _bounded_loop_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    daemon_config: Mapping[str, Any],
    loop_result: Mapping[str, Any],
    job_observations: Mapping[str, Any],
    lease_observation: Mapping[str, Any],
    daemon_heartbeat: Mapping[str, Any] | None,
    daemon_runtime_response: int,
    daemon_runtime: Mapping[str, Any],
    history_rows: list[dict[str, Any]],
    before: Mapping[str, int],
    after: Mapping[str, int],
    materialized_before: int,
    materialized_after: int,
) -> dict[str, bool]:
    runtime = once_pg._mapping_value(scheduler_config.get("runtime"))
    initial_state = once_pg._mapping_value(loop_result.get("initial_state"))
    final_state = once_pg._mapping_value(loop_result.get("final_state"))
    execution_plan = once_pg._mapping_value(loop_result.get("execution_plan"))
    guardrails = once_pg._mapping_value(loop_result.get("guardrails"))
    metadata = once_pg._mapping_value(loop_result.get("metadata"))
    cycle_results = [
        once_pg._mapping_value(item)
        for item in loop_result.get("cycle_results", [])
        if isinstance(item, Mapping)
    ]
    cycle_summaries = [
        once_pg._mapping_value(item.get("one_cycle_result"))
        for item in cycle_results
    ]
    daemon_metadata = (
        once_pg._mapping_value(daemon_heartbeat.get("metadata"))
        if isinstance(daemon_heartbeat, Mapping)
        else {}
    )
    runtime_heartbeat = once_pg._mapping_value(daemon_runtime.get("heartbeat"))
    runtime_metadata = once_pg._mapping_value(daemon_runtime.get("metadata"))
    lease_guardrails = once_pg._mapping_value(lease_observation.get("guardrails"))
    return {
        "scheduler_config_route_ok": scheduler_config_response == 200,
        "scheduler_config_sqlalchemy_queue": runtime.get("job_queue_available") is True
        and runtime.get("job_queue_backend") == "SqlAlchemyJobQueue",
        "bounded_loop_contract": loop_result.get(
            "daemon_bounded_loop_result_schema_version"
        )
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_BOUNDED_LOOP_RESULT_SCHEMA_VERSION
        and loop_result.get("result_status") == "SUCCEEDED"
        and loop_result.get("stop_reason") == "max_cycles_reached"
        and loop_result.get("max_cycles") == 2
        and loop_result.get("cycle_count") == 2
        and loop_result.get("consecutive_failure_count") == 0,
        "bounded_loop_runtime_state": initial_state.get("lifecycle_status")
        == "STARTING"
        and final_state.get("lifecycle_status") == "STOPPED"
        and final_state.get("cycle_count") == 2
        and final_state.get("consecutive_failure_count") == 0
        and once_pg._mapping_value(final_state.get("last_cycle")).get(
            "result_status"
        )
        == "SUCCEEDED",
        "bounded_loop_cycle_sequence": [item.get("cycle_index") for item in cycle_results]
        == [1, 2]
        and [item.get("requested_at") for item in cycle_results]
        == [TICK_AT, SECOND_TICK_AT]
        and all(item.get("error") is None for item in cycle_results)
        and all(item.get("result_status") == "SUCCEEDED" for item in cycle_summaries)
        and all(item.get("tick_once_ran") is True for item in cycle_summaries)
        and all(item.get("job_enqueued") is True for item in cycle_summaries)
        and all(item.get("worker_executed") is True for item in cycle_summaries)
        and all(
            item.get("history_write_executed") is True for item in cycle_summaries
        ),
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
        "bounded_loop_execution_plan": execution_plan.get("bounded_loop_adapter_used")
        is True
        and execution_plan.get("max_cycles_enforced") is True
        and execution_plan.get("cycles_executed") == 2
        and execution_plan.get("worker_requested") is True
        and execution_plan.get("runs_tick_once") is True
        and execution_plan.get("starts_continuous_loop") is False
        and execution_plan.get("physical_delete_enabled") is False,
        "bounded_loop_guardrails": guardrails.get("daemon_process_owner_ae") is True
        and guardrails.get("bounded_loop_is_finite") is True
        and guardrails.get("retention_work_uses_job_queue") is True
        and guardrails.get("direct_database_write_allowed") is False
        and guardrails.get("physical_delete_automation_enabled") is False,
        "bounded_loop_metadata": metadata.get("bounded_loop_started") is True
        and metadata.get("bounded_loop_finished") is True
        and metadata.get("tick_once_ran") is True
        and metadata.get("job_enqueued") is True
        and metadata.get("worker_executed") is True
        and metadata.get("history_write_executed") is True
        and metadata.get("continuous_loop_started") is False,
        "lease_row_persisted_released": lease_observation.get("row_count") == 1
        and lease_observation.get("lease_status") == "RELEASED"
        and lease_observation.get("fencing_token") == 2
        and lease_guardrails.get("scheduler_daemon_started") is False,
        "jobs_completed": job_observations.get("row_count") == 2
        and job_observations.get("statuses") == ["SUCCEEDED", "SUCCEEDED"]
        and job_observations.get("attempt_counts") == [1, 1]
        and job_observations.get("payload_command_statuses") == ["READY", "READY"],
        "history_persisted_dry_run": len(history_rows) == 2
        and {row.get("mode") for row in history_rows} == {"DRY_RUN"}
        and {row.get("execution_status") for row in history_rows} == {"SUCCEEDED"},
        "daemon_heartbeat_persisted": isinstance(daemon_heartbeat, Mapping)
        and daemon_heartbeat.get("worker_type")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE
        and daemon_heartbeat.get("status") == "IDLE"
        and daemon_heartbeat.get("active_job_id") is None
        and daemon_metadata.get("phase") == "one_cycle_finished"
        and daemon_metadata.get("loop_decision_status") == "READY",
        "daemon_runtime_route_observed": daemon_runtime_response == 200
        and daemon_runtime.get("service_id") == SERVICE_ID
        and daemon_runtime.get("worker_type")
        == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE
        and daemon_runtime.get("heartbeat_count") == 1
        and runtime_heartbeat.get("status") == "IDLE"
        and runtime_heartbeat.get("active_job_id") is None
        and runtime_metadata.get("heartbeat_observed") is True,
        "db_rows_retained": dict(after) == dict(before),
        "storage_files_retained": materialized_after == materialized_before
        and materialized_before >= 6,
        "metadata_only_bounded_loop_evidence": once_pg._metadata_only(
            runtime_config,
            daemon_config,
            loop_result,
            job_observations,
            lease_observation,
            daemon_heartbeat,
            daemon_runtime,
            history_rows,
            before,
            after,
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
    }


def _bounded_loop_evidence(loop_result: Mapping[str, Any]) -> dict[str, Any]:
    final_state = once_pg._mapping_value(loop_result.get("final_state"))
    metadata = once_pg._mapping_value(loop_result.get("metadata"))
    return {
        "schema_version": loop_result["daemon_bounded_loop_result_schema_version"],
        "result_status": loop_result["result_status"],
        "stop_reason": loop_result["stop_reason"],
        "max_cycles": loop_result["max_cycles"],
        "cycle_count": loop_result["cycle_count"],
        "consecutive_failure_count": loop_result["consecutive_failure_count"],
        "final_lifecycle_status": final_state.get("lifecycle_status"),
        "final_lifecycle_reason": final_state.get("lifecycle_reason"),
        "tick_once_ran": metadata.get("tick_once_ran"),
        "job_enqueued": metadata.get("job_enqueued"),
        "worker_executed": metadata.get("worker_executed"),
        "history_write_executed": metadata.get("history_write_executed"),
    }


def _bounded_loop_cycle_evidence(loop_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "cycle_index": item["cycle_index"],
            "requested_at": item["requested_at"],
            "result_status": once_pg._mapping_value(item["one_cycle_result"]).get(
                "result_status"
            ),
            "job_enqueued": once_pg._mapping_value(item["one_cycle_result"]).get(
                "job_enqueued"
            ),
            "worker_executed": once_pg._mapping_value(item["one_cycle_result"]).get(
                "worker_executed"
            ),
        }
        for item in loop_result.get("cycle_results", [])
        if isinstance(item, Mapping)
    ]


def _bounded_loop_job_observations(
    engine: Any,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    pattern = f"{idempotency_key}:cycle:%"
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        job_id,
                        status,
                        attempt_count,
                        payload,
                        idempotency_key
                    FROM service_jobs
                    WHERE job_type = :job_type
                      AND idempotency_key LIKE :idempotency_key_pattern
                    ORDER BY idempotency_key ASC, created_at ASC
                    """
                ),
                {
                    "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                    "idempotency_key_pattern": pattern,
                },
            )
            .mappings()
            .all()
        )
    payloads = [worker_pg._json_value(row["payload"], {}) for row in rows]
    return {
        "row_count": len(rows),
        "job_ids": [row["job_id"] for row in rows],
        "statuses": [row["status"] for row in rows],
        "attempt_counts": [int(row["attempt_count"]) for row in rows],
        "idempotency_keys": [row["idempotency_key"] for row in rows],
        "payload_command_statuses": [
            payload.get("command_status") for payload in payloads
        ],
    }


def _cleanup_bounded_loop_runtime_rows(
    engine: Any,
    *,
    idempotency_key: str,
    worker_id: str,
    daemon_worker_id: str,
) -> dict[str, int]:
    deleted = {
        "job_rows": 0,
        "worker_heartbeat_rows": 0,
        "daemon_heartbeat_rows": 0,
    }
    try:
        with engine.begin() as connection:
            for key, heartbeat_worker_id in (
                ("worker_heartbeat_rows", worker_id),
                ("daemon_heartbeat_rows", daemon_worker_id),
            ):
                result = connection.execute(
                    text(
                        """
                        DELETE FROM service_worker_heartbeats
                        WHERE service_id = :service_id
                          AND worker_id = :worker_id
                        """
                    ),
                    {
                        "service_id": SERVICE_ID,
                        "worker_id": heartbeat_worker_id,
                    },
                )
                deleted[key] += int(result.rowcount or 0)
            result = connection.execute(
                text(
                    """
                    DELETE FROM service_jobs
                    WHERE job_type = :job_type
                      AND idempotency_key LIKE :idempotency_key_pattern
                    """
                ),
                {
                    "job_type": AE_ARTIFACT_RETENTION_SCHEDULED_JOB_TYPE,
                    "idempotency_key_pattern": f"{idempotency_key}:cycle:%",
                },
            )
            deleted["job_rows"] += int(result.rowcount or 0)
    except SQLAlchemyError:
        return deleted
    return deleted


def _daemon_heartbeat_evidence(
    *,
    daemon_worker_id: str,
    daemon_heartbeat: Mapping[str, Any] | None,
) -> dict[str, Any]:
    heartbeat_metadata = (
        once_pg._mapping_value(daemon_heartbeat.get("metadata"))
        if isinstance(daemon_heartbeat, Mapping)
        else {}
    )
    return {
        "worker_id": daemon_worker_id,
        "worker_type": AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
        "stored": {
            "row_found": isinstance(daemon_heartbeat, Mapping),
            "status": (
                daemon_heartbeat.get("status")
                if isinstance(daemon_heartbeat, Mapping)
                else None
            ),
            "active_job_id": (
                daemon_heartbeat.get("active_job_id")
                if isinstance(daemon_heartbeat, Mapping)
                else None
            ),
            "metadata_phase": heartbeat_metadata.get("phase"),
            "loop_decision_status": heartbeat_metadata.get("loop_decision_status"),
        },
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
        "detail": one_cycle_pg._safe_detail(detail, env),
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    try:
        one_cycle_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    except ValueError as exc:
        raise ValueError(str(exc).replace("one-cycle", "bounded-loop")) from exc


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"bounded_loop={evidence['bounded_loop']['result_status']} "
            f"cycles={evidence['bounded_loop']['cycle_count']} "
            f"lease={evidence['lease']['lease_status']} "
            f"jobs={evidence['jobs']['row_count']} "
            f"daemon_heartbeat={evidence['daemon_heartbeat']['stored']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon bounded-loop PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
