#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_ag.generation_remediation import (  # noqa: E402
    SqlAlchemyGenerationRemediationTaskStore,
)
from nex_ag.remediation_execution_status_sync_jobs import (  # noqa: E402
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
    build_remediation_execution_status_sync_job,
)
from nex_ag.remediation_execution_status_sync_worker import (  # noqa: E402
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION,
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
    run_remediation_execution_status_sync_worker_once,
)
from nex_cx.remediation_execution import (  # noqa: E402
    SqlAlchemyRemediationExecutionStore,
)
from nex_runtime import (  # noqa: E402
    IDLE,
    SUCCEEDED,
    ServiceLogEmitter,
    SqlAlchemyJobQueue,
    SqlAlchemyServiceLogStore,
    SqlAlchemyWorkerHeartbeatStore,
    WorkerHeartbeatEmitter,
    build_engine,
    build_session_factory,
    database_pool_settings,
    load_env_file,
    redact_database_url,
)
from run_ag_remediation_execution_status_sync_postgres_smoke import (  # noqa: E402
    CX_SERVICE_ID,
    InProcessCxRemediationExecutionStatusClient,
    _ag_db_observations,
    _ag_remediation_record,
    _build_cx_client,
    _cleanup_cx_smoke_rows,
    _cx_db_observations,
    _cx_execution_record,
    _migration_evidence,
    _redaction_safe,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ag_remediation_execution_status_sync_worker_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_POSTGRES_SMOKE_PROFILE"
)
DEFAULT_PROFILE = "test"
AG_SERVICE_ID = "nex-ag"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
OBSERVED_AT = "2026-08-27T00:00:00Z"


def run_ag_remediation_execution_status_sync_worker_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        ag_database_env = service_database_env(AG_SERVICE_ID, profile=profile)
        cx_database_env = service_database_env(CX_SERVICE_ID, profile=profile)
        ag_database_url = service_database_url(
            AG_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        cx_database_url = service_database_url(
            CX_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        ag_migration = run_service_migrations(
            AG_SERVICE_ID,
            database_url=ag_database_url,
            profile=profile,
        )
        cx_migration = run_service_migrations(
            CX_SERVICE_ID,
            database_url=cx_database_url,
            profile=profile,
        )
        execution = _execute_status_sync_worker_smoke(
            env=env,
            ag_database_env=ag_database_env,
            ag_database_url=ag_database_url,
            cx_database_env=cx_database_env,
            cx_database_url=cx_database_url,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": AG_SERVICE_ID,
            "profile": profile,
            "ag_database_env": ag_database_env,
            "cx_database_env": cx_database_env,
            "redacted_ag_database_url": redact_database_url(ag_database_url),
            "redacted_cx_database_url": redact_database_url(cx_database_url),
            "migration": {
                AG_SERVICE_ID: _migration_evidence(ag_migration),
                CX_SERVICE_ID: _migration_evidence(cx_migration),
            },
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        evidence = _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else exc.__class__.__name__
        evidence = _failure("execution_failed", detail, profile=profile)

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_status_sync_worker_smoke(
    *,
    env: Mapping[str, str],
    ag_database_env: str,
    ag_database_url: str,
    cx_database_env: str,
    cx_database_url: str,
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    request_id = f"ag-remediation-status-sync-worker-smoke-{suffix}"
    action_id = f"ag-remediation-status-sync-worker-{suffix}"
    generation_id = f"cx-gen-remediation-status-sync-worker-{suffix}"
    repair_generation_id = f"cx-gen-remediation-worker-repair-{suffix}"
    result_ref_id = f"cx-worker-repair-run-{suffix}"
    worker_id = f"ag-status-sync-worker-{suffix}"
    ag_engine = None
    cx_engine = None
    try:
        ag_engine = build_engine(
            ag_database_url,
            pool_settings=database_pool_settings(
                AG_SERVICE_ID,
                workload="worker",
                environ=env,
            ),
        )
        cx_engine = build_engine(cx_database_url)
        ag_session_factory = build_session_factory(ag_engine)
        cx_session_factory = build_session_factory(cx_engine)
        ag_store = SqlAlchemyGenerationRemediationTaskStore(
            ag_session_factory,
            database_env=ag_database_env,
            redacted_database_url=redact_database_url(ag_database_url),
        )
        cx_store = SqlAlchemyRemediationExecutionStore(
            cx_session_factory,
            database_env=cx_database_env,
            redacted_database_url=redact_database_url(cx_database_url),
        )
        job_queue = SqlAlchemyJobQueue(ag_session_factory)
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(ag_session_factory)
        service_log_store = SqlAlchemyServiceLogStore(ag_session_factory)
        ag_store.save(
            _ag_remediation_record(
                suffix=suffix,
                request_id=request_id,
                action_id=action_id,
                generation_id=generation_id,
            )
        )
        cx_store.save(
            _cx_execution_record(
                suffix=suffix,
                request_id=request_id,
                action_id=action_id,
                generation_id=generation_id,
                repair_generation_id=repair_generation_id,
                result_ref_id=result_ref_id,
            )
        )
        job = build_remediation_execution_status_sync_job(
            _status_sync_operation(
                suffix=suffix,
                request_id=request_id,
                action_id=action_id,
                generation_id=generation_id,
            ),
            requested_at=OBSERVED_AT,
        )
        enqueued_job = job_queue.enqueue(job)
        cx_status_client = InProcessCxRemediationExecutionStatusClient(
            _build_cx_client(cx_store),
        )
        heartbeat_emitter = WorkerHeartbeatEmitter(
            service_id=AG_SERVICE_ID,
            worker_id=worker_id,
            worker_type=AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_TYPE,
            store=heartbeat_store,
            started_at=OBSERVED_AT,
            metadata={"queue": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE},
        )
        service_log_emitter = ServiceLogEmitter(
            service_id=AG_SERVICE_ID,
            logger_name="nex_ag.remediation_execution_status_sync_worker",
            store=service_log_store,
            default_attributes={"runtime_component": "ag_status_sync_worker"},
        )
        execution = run_remediation_execution_status_sync_worker_once(
            queue=job_queue,
            store=ag_store,
            cx_status_client=cx_status_client,
            heartbeat_emitter=heartbeat_emitter,
            service_log_emitter=service_log_emitter,
            worker_id=worker_id,
        )
        final_job = job_queue.get_job(job["job_id"])
        final_record = ag_store.get(action_id)
        heartbeat = heartbeat_store.get_heartbeat(AG_SERVICE_ID, worker_id)
        logs = service_log_store.list_logs(
            service_id=AG_SERVICE_ID,
            job_id=job["job_id"],
            limit=10,
        )
        ag_task_observations = _ag_db_observations(
            ag_engine,
            remediation_action_id=action_id,
        )
        ag_worker_observations = _ag_worker_db_observations(
            ag_engine,
            remediation_action_id=action_id,
            job_id=job["job_id"],
            worker_id=worker_id,
        )
        cx_observations = _cx_db_observations(
            cx_engine,
            remediation_action_id=action_id,
        )
        checks = {
            "job_enqueued": enqueued_job["status"] == "QUEUED",
            "worker_execution_succeeded": execution.status == SUCCEEDED,
            "worker_result_schema": execution.handler_result is not None
            and execution.handler_result["worker_result_schema_version"]
            == AG_REMEDIATION_EXECUTION_STATUS_SYNC_WORKER_RESULT_SCHEMA_VERSION,
            "worker_result_updated": execution.handler_result is not None
            and execution.handler_result["sync_status"] == "UPDATED",
            "final_job_succeeded": final_job is not None
            and final_job["status"] == SUCCEEDED,
            "final_job_attempted_once": final_job is not None
            and final_job["attempt_count"] == 1,
            "ag_task_completed": final_record is not None
            and final_record["action_status"] == "COMPLETED",
            "result_ref_round_tripped": final_record is not None
            and final_record["result_ref"]["ref_id"] == result_ref_id,
            "cx_status_client_called_once": cx_status_client.call_count == 1,
            "heartbeat_idle": heartbeat is not None and heartbeat["status"] == IDLE,
            "service_logs_written": len(logs) >= 2,
            "ag_task_row_status": (
                ag_task_observations["action_status"] == "COMPLETED"
            ),
            "ag_job_row_status": ag_worker_observations["job_status"] == SUCCEEDED,
            "ag_job_payload_schema": ag_worker_observations[
                "job_payload_schema_version"
            ]
            == AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_PAYLOAD_SCHEMA_VERSION,
            "ag_heartbeat_row_status": (
                ag_worker_observations["heartbeat_status"] == IDLE
            ),
            "ag_service_log_row_count": (
                ag_worker_observations["service_log_row_count"] >= 3
            ),
            "cx_row_status": cx_observations["execution_status"] == "SUCCEEDED",
            "raw_payload_absent": _redaction_safe(
                {
                    "worker_result": execution.handler_result,
                    "ag_task_observations": ag_task_observations,
                    "ag_worker_observations": ag_worker_observations,
                    "cx_observations": cx_observations,
                }
            ),
        }
        if not all(checks.values()):
            failed_checks = ",".join(
                key for key, passed in checks.items() if not passed
            )
            raise RuntimeError(
                "AG remediation execution status sync worker smoke failed: "
                f"{failed_checks}"
            )
        return {
            "request_id": request_id,
            "trace_id": TRACE_ID,
            "remediation_action_id": action_id,
            "cx_generation_id": generation_id,
            "worker_id": worker_id,
            "job_id": job["job_id"],
            "cx_status_client": {
                "mode": "in_process_cx_read_model",
                "call_count": cx_status_client.call_count,
                "last_path": cx_status_client.last_path,
            },
            "worker": {
                "status": execution.status,
                "claimed_count": 1 if execution.job is not None else 0,
                "completed_job_status": (
                    execution.completed_job["status"]
                    if execution.completed_job is not None
                    else None
                ),
                "result_schema_version": (
                    execution.handler_result["worker_result_schema_version"]
                    if execution.handler_result is not None
                    else None
                ),
                "sync_status": (
                    execution.handler_result["sync_status"]
                    if execution.handler_result is not None
                    else None
                ),
                "final_action_status": (
                    execution.handler_result["final_action_status"]
                    if execution.handler_result is not None
                    else None
                ),
            },
            "observations": {
                AG_SERVICE_ID: {
                    "task": ag_task_observations,
                    "worker_runtime": ag_worker_observations,
                },
                CX_SERVICE_ID: cx_observations,
            },
            "checks": checks,
            "cleanup": {
                AG_SERVICE_ID: _cleanup_ag_worker_smoke_rows(
                    ag_engine,
                    remediation_action_id=action_id,
                    job_id=job["job_id"],
                    worker_id=worker_id,
                    request_id=request_id,
                ),
                CX_SERVICE_ID: _cleanup_cx_smoke_rows(
                    cx_engine,
                    remediation_action_id=action_id,
                ),
            },
        }
    finally:
        if ag_engine is not None:
            _cleanup_ag_worker_smoke_rows(
                ag_engine,
                remediation_action_id=action_id,
                job_id=(
                    build_remediation_execution_status_sync_job(
                        _status_sync_operation(
                            suffix=suffix,
                            request_id=request_id,
                            action_id=action_id,
                            generation_id=generation_id,
                        ),
                        requested_at=OBSERVED_AT,
                    )["job_id"]
                ),
                worker_id=worker_id,
                request_id=request_id,
            )
            ag_engine.dispose()
        if cx_engine is not None:
            _cleanup_cx_smoke_rows(cx_engine, remediation_action_id=action_id)
            cx_engine.dispose()


def _status_sync_operation(
    *,
    suffix: str,
    request_id: str,
    action_id: str,
    generation_id: str,
) -> dict[str, Any]:
    return {
        "operation_timestamp": OBSERVED_AT,
        "remediation_action_id": action_id,
        "cx_generation_id": generation_id,
        "trace_id": TRACE_ID,
        "request_id": request_id,
        "tenant_id": f"tenant-status-sync-worker-smoke-{suffix}",
        "task_status": "WAITING_ON_CX",
        "execution_status": "SUCCEEDED",
        "target_task_status": "COMPLETED",
        "status_sync_state": "SYNC_REQUIRED",
        "attention_required": True,
        "attempt_no": 1,
    }


def _ag_worker_db_observations(
    engine: Any,
    *,
    remediation_action_id: str,
    job_id: str,
    worker_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        job_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(status) AS job_status,
                        max(attempt_count) AS attempt_count,
                        max(job_type) AS job_type,
                        max(payload->>'payload_schema_version')
                            AS job_payload_schema_version
                    FROM service_jobs
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .first()
        )
        heartbeat_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(status) AS heartbeat_status,
                        max(active_job_id) AS active_job_id,
                        max(worker_type) AS worker_type
                    FROM service_worker_heartbeats
                    WHERE service_id = :service_id AND worker_id = :worker_id
                    """
                ),
                {"service_id": AG_SERVICE_ID, "worker_id": worker_id},
            )
            .mappings()
            .first()
        )
        log_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        array_agg(message ORDER BY observed_at DESC, log_id DESC)
                            AS messages
                    FROM service_log_entries
                    WHERE service_id = :service_id
                      AND (
                          job_id = :job_id
                          OR attributes->>'worker_id' = :worker_id
                      )
                    """
                ),
                {
                    "service_id": AG_SERVICE_ID,
                    "job_id": job_id,
                    "worker_id": worker_id,
                },
            )
            .mappings()
            .first()
        )
    return {
        "remediation_action_id": remediation_action_id,
        "job_row_count": int(job_row["row_count"]) if job_row else 0,
        "job_status": job_row["job_status"] if job_row else None,
        "job_attempt_count": int(job_row["attempt_count"])
        if job_row and job_row["attempt_count"] is not None
        else None,
        "job_type": job_row["job_type"] if job_row else None,
        "job_payload_schema_version": (
            job_row["job_payload_schema_version"] if job_row else None
        ),
        "heartbeat_row_count": int(heartbeat_row["row_count"])
        if heartbeat_row
        else 0,
        "heartbeat_status": (
            heartbeat_row["heartbeat_status"] if heartbeat_row else None
        ),
        "heartbeat_active_job_id": (
            heartbeat_row["active_job_id"] if heartbeat_row else None
        ),
        "heartbeat_worker_type": heartbeat_row["worker_type"] if heartbeat_row else None,
        "service_log_row_count": int(log_row["row_count"]) if log_row else 0,
        "service_log_messages": list(log_row["messages"] or []) if log_row else [],
    }


def _cleanup_ag_worker_smoke_rows(
    engine: Any,
    *,
    remediation_action_id: str,
    job_id: str,
    worker_id: str,
    request_id: str,
) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            log_result = connection.execute(
                text(
                    """
                    DELETE FROM service_log_entries
                    WHERE service_id = :service_id
                      AND (
                          job_id = :job_id
                          OR request_id = :request_id
                          OR attributes->>'worker_id' = :worker_id
                      )
                    """
                ),
                {
                    "service_id": AG_SERVICE_ID,
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "request_id": request_id,
                },
            )
            heartbeat_result = connection.execute(
                text(
                    """
                    DELETE FROM service_worker_heartbeats
                    WHERE service_id = :service_id AND worker_id = :worker_id
                    """
                ),
                {"service_id": AG_SERVICE_ID, "worker_id": worker_id},
            )
            job_result = connection.execute(
                text(
                    """
                    DELETE FROM service_jobs
                    WHERE job_id = :job_id
                       OR (job_type = :job_type AND request_id = :request_id)
                    """
                ),
                {
                    "job_id": job_id,
                    "job_type": AG_REMEDIATION_EXECUTION_STATUS_SYNC_JOB_TYPE,
                    "request_id": request_id,
                },
            )
            task_result = connection.execute(
                text(
                    """
                    DELETE FROM ag_generation_remediation_tasks
                    WHERE remediation_action_id = :remediation_action_id
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
    except SQLAlchemyError:
        return {
            "service_log_entries": 0,
            "service_worker_heartbeats": 0,
            "service_jobs": 0,
            "ag_generation_remediation_tasks": 0,
        }
    return {
        "service_log_entries": _rowcount(log_result),
        "service_worker_heartbeats": _rowcount(heartbeat_result),
        "service_jobs": _rowcount(job_result),
        "ag_generation_remediation_tasks": _rowcount(task_result),
    }


def _rowcount(result: Any) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _failure(failure_code: str, detail: str, *, profile: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": AG_SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for service_id in (AG_SERVICE_ID, CX_SERVICE_ID):
        raw_url = environ.get(service_database_env(service_id, profile="test"))
        if raw_url and raw_url in serialized_evidence:
            raise ValueError(
                "AG remediation execution status sync worker smoke contains raw DB URL."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_remediation_execution_status_sync_worker_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"][AG_SERVICE_ID]
        return (
            "ag_remediation_execution_status_sync_worker_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"ag_db_env={evidence['ag_database_env']} "
            f"cx_db_env={evidence['cx_database_env']} "
            f"worker_status={evidence['worker']['status']} "
            f"job_cleanup={cleanup['service_jobs']} "
            f"log_cleanup={cleanup['service_log_entries']}"
        )
    return (
        "ag_remediation_execution_status_sync_worker_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AG remediation execution status-sync worker "
            "PostgreSQL smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_remediation_execution_status_sync_worker_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, default=str)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
