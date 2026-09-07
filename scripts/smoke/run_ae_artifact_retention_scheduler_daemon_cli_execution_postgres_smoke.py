#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
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
import run_ae_artifact_retention_scheduler_daemon_bounded_loop_postgres_smoke as bounded_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke as one_cycle_pg  # noqa: E402
import run_ae_artifact_retention_scheduler_tick_once_postgres_smoke as once_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifact_retention_scheduler import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
    DEFAULT_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_LEASE_OWNER_ID,
    SqlAlchemyArtifactRetentionSchedulerLeaseStore,
)
from nex_ae_api.artifact_retention_scheduler_daemon import (  # noqa: E402
    AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionSchedulerDaemonRunStore,
    execution_result_summary_line,
    main as daemon_cli_main,
    summarize_artifact_retention_scheduler_daemon_cli_execution_result,
)
from nex_ae_api.artifacts import (  # noqa: E402
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
    "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE"
)
SMOKE_PROFILE_ENV = (
    "NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = batch_plan_pg.AS_OF
TICK_AT = bounded_pg.TICK_AT
SECOND_TICK_AT = bounded_pg.SECOND_TICK_AT
CUTOFF_AT = bounded_pg.CUTOFF_AT
OLD_LOGICAL_PURGE_AT = batch_plan_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = batch_plan_pg.RECENT_LOGICAL_PURGE_AT
WORKER_CLOCK_TICKS = bounded_pg.WORKER_CLOCK_TICKS


def run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_scheduler_daemon_cli_execution_smoke(
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


def _execute_ae_artifact_retention_scheduler_daemon_cli_execution_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-daemon-cli-execution-{suffix}"
    workspace_id = f"workspace-artifact-daemon-cli-execution-{suffix}"
    owner_user_id = f"owner-artifact-daemon-cli-execution-{suffix}"
    scheduler_id = f"ae-artifact-retention-daemon-cli-execution-{suffix}"
    worker_id = f"ae-artifact-retention-cli-execution-worker-{suffix}"
    daemon_worker_id = f"ae-artifact-retention-cli-execution-heartbeat-{suffix}"
    idempotency_key = f"retention-daemon-cli-execution-{suffix}"
    process_id = 5556
    host_id = f"ae-cli-execution-postgres-smoke-{suffix[:8]}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        once_pg._ensure_sqlite_scheduler_lease_table(engine)
        job_queue = SqlAlchemyJobQueue(session_factory)
        lease_store = SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
        run_store = SqlAlchemyArtifactRetentionSchedulerDaemonRunStore(
            session_factory
        )
        run_store.ensure_schema()
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
        history_store = SqlAlchemyArtifactRetentionExecutionHistoryStore(
            session_factory
        )
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-daemon-cli-execution-smoke-",
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
                        label="daemon-cli-execution-old-first",
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
                        label="daemon-cli-execution-old-second",
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
                        label="daemon-cli-execution-recent",
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
                daemon_heartbeat_emitter = WorkerHeartbeatEmitter(
                    service_id=SERVICE_ID,
                    worker_id=daemon_worker_id,
                    worker_type=AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_WORKER_TYPE,
                    store=heartbeat_store,
                    started_at=TICK_AT,
                    metadata={
                        "smoke_schema_version": SCHEMA_VERSION,
                        "cli_execution": True,
                    },
                )
                cli_output = io.StringIO()
                cli_exit_code = daemon_cli_main(
                    [
                        "--execute",
                        "--enabled",
                        "--explicit-opt-in",
                        "--checked-at",
                        TICK_AT,
                        "--interval-seconds",
                        "120",
                        "--jitter-seconds",
                        "0",
                        "--max-cycles",
                        "2",
                        "--run-worker",
                    ],
                    out=cli_output,
                    execution_context={
                        "artifact_store": artifact_store,
                        "job_queue": job_queue,
                        "lease_store": lease_store,
                        "history_store": history_store,
                        "run_store": run_store,
                        "scheduler_config": scheduler_config,
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "process_id": process_id,
                        "host_id": host_id,
                        "stale_after_seconds": "900",
                        "retention_days": 30,
                        "as_of": AS_OF,
                        "scan_limit": 10,
                        "max_delete_count": 1,
                        "trace_id": trace_id,
                        "request_id": request_id,
                        "idempotency_key": idempotency_key,
                        "worker_id": worker_id,
                        "clock": worker_pg._clock_from_sequence(WORKER_CLOCK_TICKS),
                        "daemon_heartbeat_emitter": daemon_heartbeat_emitter,
                    },
                )
                if cli_exit_code != 0:
                    raise RuntimeError(
                        "AE artifact retention scheduler daemon CLI execution "
                        f"returned {cli_exit_code}: {cli_output.getvalue()}"
                    )
                cli_result = json.loads(cli_output.getvalue())
                cli_summary = (
                    summarize_artifact_retention_scheduler_daemon_cli_execution_result(
                        cli_result
                    )
                )
                loop_result = cli_result["bounded_loop_result"]
                runtime_config = loop_result["runtime_config"]
                daemon_config = loop_result["daemon_config"]
                job_observations = bounded_pg._bounded_loop_job_observations(
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
                run_record = run_store.get_run_record_by_execution_result_id(
                    cli_result["daemon_cli_execution_result_id"]
                )
                lifecycle_events = (
                    run_store.list_lifecycle_events(
                        run_record["daemon_run_record_id"]
                    )
                    if run_record is not None
                    else []
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
                checks = _cli_execution_checks(
                    database_url=database_url,
                    database_env=database_env,
                    storage_root=storage_root,
                    scheduler_config_response=scheduler_config_response.status_code,
                    scheduler_config=scheduler_config,
                    cli_exit_code=cli_exit_code,
                    cli_result=cli_result,
                    cli_summary=cli_summary,
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
                    run_record=run_record,
                    lifecycle_events=lifecycle_events,
                    process_id=process_id,
                    host_id=host_id,
                )
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact retention scheduler daemon CLI execution "
                        f"PostgreSQL smoke checks failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = history_pg._cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                cleanup_jobs = bounded_pg._cleanup_bounded_loop_runtime_rows(
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
                cleanup_run = (
                    run_store.delete_run_record(run_record["daemon_run_record_id"])
                    if run_record is not None
                    else {"daemon_lifecycle_events": 0, "daemon_run_records": 0}
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
                    "cli_execution": _cli_execution_evidence(cli_result),
                    "bounded_loop": bounded_pg._bounded_loop_evidence(loop_result),
                    "cycles": bounded_pg._bounded_loop_cycle_evidence(loop_result),
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
                    "process": {
                        "process_id": process_id,
                        "host_id": host_id,
                    },
                    "run_record": _daemon_run_record_evidence(run_record),
                    "lifecycle_events": _daemon_lifecycle_event_evidence(
                        lifecycle_events
                    ),
                    "lease": lease_observation,
                    "jobs": job_observations,
                    "daemon_heartbeat": bounded_pg._daemon_heartbeat_evidence(
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
                        **cleanup_run,
                    },
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        bounded_pg._cleanup_bounded_loop_runtime_rows(
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


def _cli_execution_checks(
    *,
    database_url: str,
    database_env: str,
    storage_root: Path,
    scheduler_config_response: int,
    scheduler_config: Mapping[str, Any],
    cli_exit_code: int,
    cli_result: Mapping[str, Any],
    cli_summary: Mapping[str, Any],
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
    run_record: Mapping[str, Any] | None,
    lifecycle_events: list[dict[str, Any]],
    process_id: int,
    host_id: str,
) -> dict[str, bool]:
    checks = bounded_pg._bounded_loop_checks(
        database_url=database_url,
        database_env=database_env,
        storage_root=storage_root,
        scheduler_config_response=scheduler_config_response,
        scheduler_config=scheduler_config,
        runtime_config=runtime_config,
        daemon_config=daemon_config,
        loop_result=loop_result,
        job_observations=job_observations,
        lease_observation=lease_observation,
        daemon_heartbeat=daemon_heartbeat,
        daemon_runtime_response=daemon_runtime_response,
        daemon_runtime=daemon_runtime,
        history_rows=history_rows,
        before=before,
        after=after,
        materialized_before=materialized_before,
        materialized_after=materialized_after,
    )
    command = once_pg._mapping_value(cli_result.get("execute_command")).get(
        "command",
        {},
    )
    execution_plan = once_pg._mapping_value(cli_result.get("execution_plan"))
    guardrails = once_pg._mapping_value(cli_result.get("guardrails"))
    metadata = once_pg._mapping_value(cli_result.get("metadata"))
    process = once_pg._mapping_value(cli_result.get("process_lock")).get(
        "process",
        {},
    )
    started_lifecycle = once_pg._mapping_value(
        once_pg._mapping_value(cli_result.get("started_run_metadata")).get(
            "lifecycle"
        )
    )
    completed_lifecycle = once_pg._mapping_value(
        once_pg._mapping_value(cli_result.get("completed_run_metadata")).get(
            "lifecycle"
        )
    )
    run_record_value = once_pg._mapping_value(run_record)
    lifecycle_event_types = [item.get("event_type") for item in lifecycle_events]
    lifecycle_run_statuses = [item.get("run_status") for item in lifecycle_events]
    checks.update(
        {
            "cli_main_exit_zero": cli_exit_code == 0,
            "cli_execution_contract": cli_result.get(
                "daemon_cli_execution_result_schema_version"
            )
            == AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_RESULT_SCHEMA_VERSION
            and cli_result.get("service_id") == SERVICE_ID
            and cli_result.get("result_status") == "SUCCEEDED"
            and cli_result.get("stop_reason") == "max_cycles_reached",
            "cli_command_execute_mode": command.get("mode") == "bounded_loop"
            and command.get("profile") == DEFAULT_PROFILE
            and command.get("enabled") is True
            and command.get("explicit_opt_in") is True
            and command.get("plan_only") is False
            and command.get("run_worker") is True
            and command.get("max_cycles") == 2,
            "cli_process_run_metadata": process.get("process_id")
            == process_id
            and process.get("host_id") == host_id
            and started_lifecycle.get("run_status") == "RUNNING"
            and started_lifecycle.get("started_at") == TICK_AT
            and completed_lifecycle.get("run_status") == "SUCCEEDED"
            and completed_lifecycle.get("completed_at") == SECOND_TICK_AT,
            "cli_execution_plan": execution_plan.get(
                "runs_existing_bounded_loop_adapter"
            )
            is True
            and execution_plan.get("cycles_executed") == 2
            and execution_plan.get("job_queue_enqueue_performed") is True
            and execution_plan.get("worker_execution_performed") is True
            and execution_plan.get("writes_run_record") is True
            and execution_plan.get("writes_lifecycle_event") is True,
            "cli_execution_guardrails": guardrails.get("bounded_loop_is_finite")
            is True
            and guardrails.get("process_lock_required") is True
            and guardrails.get("process_lock_acquired") is False
            and guardrails.get("run_record_persisted") is True
            and guardrails.get("lifecycle_event_persisted") is True
            and guardrails.get("database_url_included") is False
            and guardrails.get("storage_path_included") is False
            and guardrails.get("physical_delete_automation_enabled") is False,
            "cli_execution_metadata": metadata.get("bounded_loop_started") is True
            and metadata.get("cycle_count") == 2
            and metadata.get("max_cycles") == 2
            and metadata.get("job_enqueued") is True
            and metadata.get("worker_executed") is True
            and metadata.get("run_started") is True
            and metadata.get("run_completed") is True
            and metadata.get("completed_run_status") == "SUCCEEDED"
            and metadata.get("process_id") == process_id
            and metadata.get("host_id") == host_id
            and metadata.get("run_record_persisted") is True
            and metadata.get("lifecycle_event_persisted") is True,
            "cli_summary_matches_db_effects": cli_summary.get("cycle_count") == 2
            and cli_summary.get("job_enqueued") is True
            and cli_summary.get("worker_executed") is True
            and cli_summary.get("run_record_persisted") is True
            and job_observations.get("row_count") == 2
            and len(history_rows) == 2,
            "daemon_run_record_persisted": run_record is not None
            and run_record_value.get("daemon_cli_execution_result_id")
            == cli_result.get("daemon_cli_execution_result_id")
            and run_record_value.get("scheduler_id")
            == scheduler_config.get("scheduler_id")
            and run_record_value.get("run_status") == "SUCCEEDED"
            and run_record_value.get("result_status") == "SUCCEEDED"
            and run_record_value.get("cycle_count") == 2
            and run_record_value.get("job_enqueued") is True
            and run_record_value.get("worker_executed") is True
            and run_record_value.get("process_id") == process_id
            and run_record_value.get("host_id") == host_id,
            "daemon_lifecycle_events_persisted": len(lifecycle_events) == 2
            and lifecycle_event_types == ["RUN_STARTED", "RUN_COMPLETED"]
            and lifecycle_run_statuses == ["RUNNING", "SUCCEEDED"]
            and lifecycle_events[0].get("cycle_count") == 0
            and lifecycle_events[1].get("cycle_count") == 2
            and lifecycle_events[1].get("result_status") == "SUCCEEDED"
            and lifecycle_events[1].get("stop_reason") == "max_cycles_reached",
            "metadata_only_cli_execution_evidence": once_pg._metadata_only(
                cli_result,
                cli_summary,
                run_record_value,
                lifecycle_events,
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
    )
    return checks


def _cli_execution_evidence(cli_result: Mapping[str, Any]) -> dict[str, Any]:
    summary = summarize_artifact_retention_scheduler_daemon_cli_execution_result(
        cli_result
    )
    return {
        "schema_version": cli_result["daemon_cli_execution_result_schema_version"],
        "result_status": summary["result_status"],
        "stop_reason": summary["stop_reason"],
        "max_cycles": summary["max_cycles"],
        "cycle_count": summary["cycle_count"],
        "completed_run_status": summary["completed_run_status"],
        "bounded_loop_started": summary["bounded_loop_started"],
        "job_enqueued": summary["job_enqueued"],
        "worker_executed": summary["worker_executed"],
        "run_record_persisted": summary["run_record_persisted"],
        "summary_line": execution_result_summary_line(cli_result),
    }


def _daemon_run_record_evidence(
    run_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(run_record, Mapping):
        return {"row_found": False}
    return {
        "row_found": True,
        "schema_version": run_record["daemon_run_record_schema_version"],
        "run_status": run_record["run_status"],
        "result_status": run_record["result_status"],
        "stop_reason": run_record["stop_reason"],
        "cycle_count": run_record["cycle_count"],
        "job_enqueued": run_record["job_enqueued"],
        "worker_executed": run_record["worker_executed"],
        "process_id": run_record["process_id"],
        "host_id": run_record["host_id"],
    }


def _daemon_lifecycle_event_evidence(
    lifecycle_events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "row_count": len(lifecycle_events),
        "event_types": [item["event_type"] for item in lifecycle_events],
        "run_statuses": [item["run_status"] for item in lifecycle_events],
        "cycle_counts": [item["cycle_count"] for item in lifecycle_events],
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
        "detail": once_pg._safe_detail(detail, env),
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    try:
        once_pg.assert_smoke_evidence_redacted(serialized_evidence, environ)
    except ValueError as exc:
        raise ValueError(str(exc).replace("tick-once", "CLI execution")) from exc


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"cli_execution={evidence['cli_execution']['result_status']} "
            f"cycles={evidence['cli_execution']['cycle_count']} "
            f"lease={evidence['lease']['lease_status']} "
            f"jobs={evidence['jobs']['row_count']} "
            f"run_record={int(evidence['run_record']['row_found'])} "
            f"events={evidence['lifecycle_events']['row_count']} "
            f"daemon_heartbeat={evidence['daemon_heartbeat']['stored']['status']} "
            f"history_rows={evidence['history']['row_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_leases={evidence['cleanup']['lease_rows']}"
        )
    return (
        "ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE scheduler daemon CLI execution PostgreSQL smoke."
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
    evidence = run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
