#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_runtime import (  # noqa: E402
    SqlAlchemyJobQueue,
    build_common_job,
    build_engine,
    build_session_factory,
    build_subject_ref,
    database_pool_settings,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_DB_JOBQUEUE_SMOKE"
SMOKE_SERVICE_ENV = "NEX_DB_JOBQUEUE_SMOKE_SERVICE"
SMOKE_PROFILE_ENV = "NEX_DB_JOBQUEUE_SMOKE_PROFILE"
DEFAULT_SERVICE_ID = "nex-cx"
DEFAULT_PROFILE = "test"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "jobqueue-smoke-request"
NOW = "2026-08-05T00:00:00Z"
LATER = "2026-08-05T00:00:01Z"


def run_postgres_jobqueue_smoke(environ: dict[str, str] | None = None) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "postgres_jobqueue_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    service_id = env.get(SMOKE_SERVICE_ENV, DEFAULT_SERVICE_ID)
    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            service_id=service_id,
            profile=profile,
        )

    try:
        database_env = service_database_env(service_id, profile=profile)
        database_url = service_database_url(service_id, profile=profile, environ=env)
        run_service_migrations(service_id, database_url=database_url, profile=profile)
        pool_settings = database_pool_settings(service_id, workload="worker", environ=env)
        engine = build_engine(database_url, pool_settings=pool_settings)
        job_id = f"jobqueue-smoke-{uuid4()}"
        idempotency_key = job_id
        _delete_smoke_jobs(engine, job_id=job_id, idempotency_key=idempotency_key)
        try:
            queue = SqlAlchemyJobQueue(build_session_factory(engine))
            job = build_common_job(
                job_id=job_id,
                job_type="smoke.jobqueue",
                trace_id=TRACE_ID,
                request_id=REQUEST_ID,
                subject_ref=build_subject_ref("smoke.job", job_id),
                idempotency_key=idempotency_key,
                created_at=NOW,
                max_attempts=2,
            )
            enqueued = queue.enqueue(job)
            duplicate = queue.enqueue({**job, "job_id": f"{job_id}-duplicate"})
            claimed = queue.claim_next_job("postgres-smoke-worker", updated_at=LATER)
            if claimed is None:
                return _failure(
                    "claim_missing",
                    "job queue smoke could not claim the enqueued job.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                )
            completed = queue.complete_job(claimed["job_id"], updated_at="2026-08-05T00:00:02Z")
            return {
                "smoke_schema_version": "postgres_jobqueue_smoke.v1",
                "status": "PASS",
                "service_id": service_id,
                "profile": profile,
                "database_env": database_env,
                "redacted_database_url": redact_database_url(database_url),
                "job_id": job_id,
                "checks": {
                    "enqueue": enqueued["job_id"] == job_id,
                    "idempotency": duplicate["job_id"] == job_id,
                    "claim": claimed["status"] == "RUNNING",
                    "complete": completed["status"] == "SUCCEEDED",
                },
            }
        finally:
            _delete_smoke_jobs(engine, job_id=job_id, idempotency_key=idempotency_key)
    except (MigrationError, ValueError) as exc:
        return _failure(
            "configuration_invalid",
            str(exc),
            service_id=service_id,
            profile=profile,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            service_id=service_id,
            profile=profile,
        )


def _delete_smoke_jobs(engine: object, *, job_id: str, idempotency_key: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_jobs
                WHERE job_id = :job_id
                   OR (job_type = :job_type AND idempotency_key = :idempotency_key)
                """
            ),
            {
                "job_id": job_id,
                "job_type": "smoke.jobqueue",
                "idempotency_key": idempotency_key,
            },
        )


def _failure(
    failure_code: str,
    detail: str,
    *,
    service_id: str,
    profile: str,
    database_env: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "smoke_schema_version": "postgres_jobqueue_smoke.v1",
        "status": "FAIL",
        "service_id": service_id,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if database_env is not None:
        payload["database_env"] = database_env
    return payload


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"postgres_jobqueue_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "postgres_jobqueue_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "postgres_jobqueue_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run optional PostgreSQL JobQueue write smoke.")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_jobqueue_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
