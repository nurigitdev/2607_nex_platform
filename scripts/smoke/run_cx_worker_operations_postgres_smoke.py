#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_cx.worker_leases import (  # noqa: E402
    CxWorkerLeaseError,
    SqlAlchemyCxWorkerLeaseStore,
    claim_next_worker_execution,
)
from nex_cx.worker_operations import register_worker_operations_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    CX_WORKER_CANCELLATION_REQUESTED_EVENT,
    CX_WORKER_RECONCILIATION_APPLIED_EVENT,
    IDLE,
    SERVICE_SPECS,
    OperationalEventEmitter,
    WorkerHeartbeatEmitter,
    attach_service_persistence_runtime,
    build_common_job,
    build_service_app,
    build_subject_ref,
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


SCHEMA_VERSION = "cx_worker_operations_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
LATEST_MIGRATION_VERSION = "0966_cx_generation_admissions"
CONCURRENT_JOB_COUNT = 6


def run_cx_worker_operations_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=dict(env),
        )
        if not _target_url_allowed(database_url):
            return _failure(
                "target_not_allowed",
                f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
                profile=profile,
            )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_worker_operations_smoke(
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            }
        )
        failed_checks = execution.get("failed_checks") or []
        if failed_checks:
            return _failure(
                "worker_operations_smoke_failed",
                ",".join(str(item) for item in failed_checks),
                profile=profile,
                execution=execution,
            )
        return {
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
            "dgx_live_provider_required": False,
            **execution,
        }
    except (MigrationError, OSError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
            profile=profile,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            profile=profile,
        )


def _execute_worker_operations_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    runtime_environ: Mapping[str, str],
) -> dict[str, Any]:
    probe_id = uuid4().hex
    trace_id = uuid4().hex
    request_id = str(uuid4())
    worker_prefix = f"s98-{probe_id}"
    job_ids = [f"{worker_prefix}-job-{index}" for index in range(CONCURRENT_JOB_COUNT)]
    cancel_job_id = f"{worker_prefix}-cancel"
    poison_job_id = job_ids[-1]
    created_at_dt = datetime.now(UTC) - timedelta(seconds=131)
    claimed_at_dt = created_at_dt + timedelta(seconds=1)
    reconciled_at_dt = claimed_at_dt + timedelta(seconds=121)
    renewed_at_dt = claimed_at_dt + timedelta(seconds=60)
    created_at = _wire_timestamp(created_at_dt)
    claimed_at = _wire_timestamp(claimed_at_dt)
    reconciled_at = _wire_timestamp(reconciled_at_dt)
    renewed_at = _wire_timestamp(renewed_at_dt)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    app = build_service_app(SERVICE_SPEC)
    runtime = attach_service_persistence_runtime(
        app,
        SERVICE_SPEC,
        environ=runtime_environ,
    )
    if (
        runtime.api_engine is None
        or runtime.worker_engine is None
        or runtime.worker_session_factory is None
    ):
        raise RuntimeError("CX PostgreSQL worker persistence runtime is unavailable")
    lease_store = SqlAlchemyCxWorkerLeaseStore(runtime.worker_session_factory)
    emitter = OperationalEventEmitter(
        service_id=SERVICE_ID,
        store=runtime.operational_event_store,
    )
    register_worker_operations_routes(
        app,
        job_queue=runtime.job_queue,
        heartbeat_store=runtime.worker_heartbeat_store,
        lease_store=lease_store,
        event_emitter=emitter,
    )

    try:
        foreign_running_count = _foreign_running_count(runtime.api_engine, trace_id)
        if foreign_running_count:
            raise RuntimeError(
                "nex_cx_test contains unrelated RUNNING jobs; smoke refused mutation"
            )

        for index, job_id in enumerate(job_ids):
            runtime.job_queue.enqueue(
                build_common_job(
                    job_id=job_id,
                    job_type="cx.document_processing",
                    trace_id=trace_id,
                    request_id=request_id,
                    subject_ref=build_subject_ref(
                        "cx.worker.probe",
                        f"{worker_prefix}-subject-{index}",
                    ),
                    idempotency_key=f"{worker_prefix}-idempotency-{index}",
                    created_at=created_at,
                    max_attempts=1 if job_id == poison_job_id else 3,
                )
            )

        def claim(index: int) -> dict[str, Any] | None:
            return claim_next_worker_execution(
                job_queue=runtime.job_queue,
                lease_store=lease_store,
                worker_id=f"{worker_prefix}-worker-{index}",
                worker_type="cx.processing.worker",
                workload="document_processing",
                observed_at=claimed_at,
            )

        with ThreadPoolExecutor(max_workers=CONCURRENT_JOB_COUNT) as executor:
            claimed = list(executor.map(claim, range(CONCURRENT_JOB_COUNT)))
        executions = [item for item in claimed if item is not None]
        claimed_by_job = {str(item["job_id"]): item for item in executions}
        exhausted_claim = claim_next_worker_execution(
            job_queue=runtime.job_queue,
            lease_store=lease_store,
            worker_id=f"{worker_prefix}-worker-extra",
            worker_type="cx.processing.worker",
            workload="document_processing",
            observed_at=claimed_at,
        )
        claim_probe = _claim_probe(runtime.api_engine, trace_id=trace_id)

        protected_job_ids = [job_id for job_id in job_ids if job_id != poison_job_id]
        renewed_job_id, heartbeat_job_id = protected_job_ids[:2]
        renewed_execution = claimed_by_job[renewed_job_id]
        heartbeat_execution = claimed_by_job[heartbeat_job_id]
        original_lease = lease_store.inspect(
            renewed_job_id,
            observed_at=claimed_at,
        )
        if original_lease is None:
            raise RuntimeError("claimed lease was not persisted")
        renewed_lease = lease_store.renew(
            renewed_job_id,
            worker_id=str(renewed_execution["worker_id"]),
            expected_locked_at=str(original_lease["locked_at"]),
            observed_at=renewed_at,
        )
        stale_renewal_error = None
        try:
            lease_store.renew(
                renewed_job_id,
                worker_id=str(renewed_execution["worker_id"]),
                expected_locked_at=str(original_lease["locked_at"]),
                observed_at=_wire_timestamp(renewed_at_dt + timedelta(seconds=1)),
            )
        except CxWorkerLeaseError as exc:
            stale_renewal_error = exc.error_code

        WorkerHeartbeatEmitter(
            service_id=SERVICE_ID,
            worker_id=str(heartbeat_execution["worker_id"]),
            worker_type="cx.processing.worker",
            store=runtime.worker_heartbeat_store,
            started_at=claimed_at,
        ).emit(status=IDLE, observed_at=reconciled_at)

        token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        }
        with TestClient(app) as client:
            unauthorized = client.get(
                "/internal/v1/workers/reconciliation-plan"
            )
            readiness = client.get(
                f"/internal/v1/workers/{heartbeat_execution['worker_id']}/readiness",
                headers=headers,
            )
            plan_response = client.get(
                "/internal/v1/workers/reconciliation-plan",
                headers=headers,
                params={"observed_at": reconciled_at},
            )
            plan_response.raise_for_status()
            plan = plan_response.json()
            reconcile_response = client.post(
                "/internal/v1/workers/reconcile",
                headers=headers,
                params={"observed_at": reconciled_at},
            )
            reconcile_response.raise_for_status()
            reconciliation = reconcile_response.json()

            runtime.job_queue.enqueue(
                build_common_job(
                    job_id=cancel_job_id,
                    job_type="cx.document_processing",
                    trace_id=trace_id,
                    request_id=request_id,
                    subject_ref=build_subject_ref(
                        "cx.worker.probe",
                        f"{worker_prefix}-cancel-subject",
                    ),
                    idempotency_key=f"{worker_prefix}-cancel-idempotency",
                    created_at=_wire_timestamp(datetime.now(UTC)),
                    max_attempts=3,
                )
            )
            cancellation = client.post(
                f"/internal/v1/workers/jobs/{cancel_job_id}/cancel",
                headers=headers,
            )
            cancellation.raise_for_status()
            dead_letters = client.get(
                "/internal/v1/workers/dead-letters?limit=500",
                headers=headers,
            )
            dead_letters.raise_for_status()

        persisted = _persisted_probe(
            runtime.api_engine,
            trace_id=trace_id,
            request_id=request_id,
        )
        plan_by_job = {item["job_id"]: item for item in plan["entries"]}
        result_by_job = {
            item["job_id"]: item
            for item in reconciliation["result"]["results"]
        }
        projected_dead_letter_ids = {
            item["job_id"] for item in dead_letters.json()["dead_letters"]
        }
        details = {
            "concurrent_workers": CONCURRENT_JOB_COUNT,
            "claimed_job_count": len(executions),
            "unique_claimed_job_count": len(claimed_by_job),
            "running_after_claim": claim_probe["running_count"],
            "distinct_lock_owner_count": claim_probe["lock_owner_count"],
            "recoverable_count": plan["recoverable_count"],
            "applied_count": reconciliation["result"]["applied_count"],
            "stale_renewal_error": stale_renewal_error,
            "persisted_status_counts": persisted["status_counts"],
            "persisted_event_types": persisted["event_types"],
        }
        checks.update(
            {
                "actual_test_database": persisted["database"]
                == EXPECTED_DATABASE,
                "actual_test_role": persisted["role"] == EXPECTED_ROLE,
                "latest_migration_recorded": persisted["migration_count"] == 1,
                "foreign_running_jobs_absent": foreign_running_count == 0,
                "all_jobs_claimed_concurrently": len(executions)
                == CONCURRENT_JOB_COUNT,
                "claims_are_unique": len(claimed_by_job)
                == CONCURRENT_JOB_COUNT,
                "database_claims_are_running": claim_probe["running_count"]
                == CONCURRENT_JOB_COUNT,
                "database_lock_owners_are_unique": claim_probe[
                    "lock_owner_count"
                ]
                == CONCURRENT_JOB_COUNT,
                "queue_exhausted_after_claims": exhausted_claim is None,
                "lease_renewed_with_cas": renewed_lease["locked_at"]
                == renewed_at,
                "stale_lease_renewal_rejected": stale_renewal_error
                == "cx.worker_lease.changed",
                "renewed_lease_not_recovered": plan_by_job[renewed_job_id][
                    "action"
                ]
                == "WAIT_LEASE",
                "fresh_heartbeat_not_recovered": plan_by_job[
                    heartbeat_job_id
                ]["action"]
                == "WAIT_HEARTBEAT",
                "expired_unowned_workers_recovered": plan["recoverable_count"]
                == CONCURRENT_JOB_COUNT - 2
                and reconciliation["result"]["applied_count"]
                == CONCURRENT_JOB_COUNT - 2,
                "poison_attempt_dead_lettered": result_by_job[poison_job_id][
                    "result"
                ]
                == "DEAD_LETTERED",
                "bounded_retries_scheduled": sum(
                    item["result"] == "RETRY_SCHEDULED"
                    for item in result_by_job.values()
                )
                == CONCURRENT_JOB_COUNT - 3,
                "operations_api_is_protected": unauthorized.status_code == 401,
                "heartbeat_readiness_is_ready": readiness.status_code == 200
                and readiness.json()["readiness"] == "READY",
                "cancellation_persisted": cancellation.json()["result"][
                    "status"
                ]
                == "CANCELLED",
                "dead_letter_projection_contains_poison_job": poison_job_id
                in projected_dead_letter_ids,
                "operational_events_persisted": {
                    CX_WORKER_CANCELLATION_REQUESTED_EVENT,
                    CX_WORKER_RECONCILIATION_APPLIED_EVENT,
                }.issubset(set(persisted["event_types"])),
                "only_metadata_evidence_returned": "payload"
                not in json.dumps(
                    {
                        "plan": plan,
                        "reconciliation": reconciliation,
                        "cancellation": cancellation.json(),
                        "dead_letters": dead_letters.json(),
                    },
                    sort_keys=True,
                ).lower(),
            }
        )
    finally:
        _cleanup_probe_rows(
            runtime.api_engine,
            trace_id=trace_id,
            request_id=request_id,
            worker_prefix=worker_prefix,
        )
        residue = _probe_residue(
            runtime.api_engine,
            trace_id=trace_id,
            request_id=request_id,
            worker_prefix=worker_prefix,
        )
        checks["cleanup_verified"] = residue == 0
        runtime.api_engine.dispose()
        runtime.worker_engine.dispose()

    return {
        "database": EXPECTED_DATABASE,
        "role": EXPECTED_ROLE,
        "probe_id": probe_id,
        "probe_residue": residue,
        "details": details,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _foreign_running_count(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    trace_id: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM service_jobs
                    WHERE status = 'RUNNING' AND trace_id <> :trace_id
                    """
                ),
                {"trace_id": trace_id},
            ).scalar_one()
        )


def _claim_probe(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
) -> dict[str, int]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT count(*) AS running_count,
                       count(DISTINCT locked_by) AS lock_owner_count
                FROM service_jobs
                WHERE trace_id = :trace_id AND status = 'RUNNING'
                """
            ),
            {"trace_id": trace_id},
        ).mappings().one()
    return {
        "running_count": int(row["running_count"]),
        "lock_owner_count": int(row["lock_owner_count"]),
    }


def _persisted_probe(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        database, role = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        migration_count = connection.execute(
            text("SELECT count(*) FROM schema_migrations WHERE version = :version"),
            {"version": LATEST_MIGRATION_VERSION},
        ).scalar_one()
        statuses = connection.execute(
            text(
                """
                SELECT status, count(*) AS count
                FROM service_jobs
                WHERE trace_id = :trace_id
                GROUP BY status
                """
            ),
            {"trace_id": trace_id},
        ).mappings()
        event_types = connection.execute(
            text(
                """
                SELECT event_type
                FROM service_operational_events
                WHERE trace_id = :trace_id OR request_id = :request_id
                ORDER BY event_type
                """
            ),
            {"trace_id": trace_id, "request_id": request_id},
        ).scalars()
        return {
            "database": database,
            "role": role,
            "migration_count": int(migration_count),
            "status_counts": {
                str(item["status"]): int(item["count"]) for item in statuses
            },
            "event_types": [str(item) for item in event_types],
        }


def _cleanup_probe_rows(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
    worker_prefix: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE trace_id = :trace_id OR request_id = :request_id
                """
            ),
            {"trace_id": trace_id, "request_id": request_id},
        )
        connection.execute(
            text(
                """
                DELETE FROM service_worker_heartbeats
                WHERE worker_id LIKE :worker_prefix
                """
            ),
            {"worker_prefix": f"{worker_prefix}%"},
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )


def _probe_residue(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    request_id: str,
    worker_prefix: str,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM service_operational_events
                         WHERE trace_id = :trace_id OR request_id = :request_id)
                      + (SELECT count(*) FROM service_worker_heartbeats
                         WHERE worker_id LIKE :worker_prefix)
                      + (SELECT count(*) FROM service_jobs
                         WHERE trace_id = :trace_id)
                    """
                ),
                {
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "worker_prefix": f"{worker_prefix}%",
                },
            ).scalar_one()
        )


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == EXPECTED_ROLE
            and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
        )
    except ValueError:
        return False


def _redact_detail(detail: str, *, database_url: str) -> str:
    if not database_url:
        return detail
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if execution is not None:
        result.update(execution)
    return result


def _wire_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return f"cx_worker_operations_postgres_smoke=skipped reason={SMOKE_ENV}"
    details = result.get("details") or {}
    return (
        "cx_worker_operations_postgres_smoke="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"database={result.get('database', 'not-run')} "
        f"claims={details.get('unique_claimed_job_count', 'not-run')}/"
        f"{details.get('concurrent_workers', 'not-run')} "
        f"recovered={details.get('applied_count', 'not-run')} "
        f"residue={result.get('probe_residue', 'not-run')} "
        f"failed_checks={len(result.get('failed_checks') or [])} "
        f"dgx_required={result.get('dgx_live_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected CX worker operations PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    result = run_cx_worker_operations_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
