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
    plan_dead_letter_replay,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_DB_JOB_REPLAY_SMOKE"
SMOKE_SERVICE_ENV = "NEX_DB_JOB_REPLAY_SMOKE_SERVICE"
SMOKE_PROFILE_ENV = "NEX_DB_JOB_REPLAY_SMOKE_PROFILE"
DEFAULT_SERVICE_ID = "nex-cx"
DEFAULT_PROFILE = "test"
JOB_TYPE = "smoke.job_replay"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "job-replay-smoke-request"
NOW = "2026-08-05T00:00:00Z"


def run_postgres_job_replay_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "postgres_job_replay_smoke.v1",
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
        source_job_id = f"job-replay-smoke-source-{uuid4()}"
        replay_job_id = f"job-replay-smoke-replay-{uuid4()}"
        source_idempotency_key = source_job_id
        replay_idempotency_key = replay_job_id
        cleanup_ids = {
            "source_job_id": source_job_id,
            "replay_job_id": replay_job_id,
            "source_idempotency_key": source_idempotency_key,
            "replay_idempotency_key": replay_idempotency_key,
        }
        _delete_smoke_jobs(engine, **cleanup_ids)
        try:
            queue = SqlAlchemyJobQueue(build_session_factory(engine))
            source_payload = {
                "source_file_id": "postgres-replay-smoke-source",
                "owner_user_id": "operator-smoke",
            }
            source_job = build_common_job(
                job_id=source_job_id,
                job_type=JOB_TYPE,
                trace_id=TRACE_ID,
                request_id=REQUEST_ID,
                subject_ref=build_subject_ref("smoke.job", source_job_id),
                idempotency_key=source_idempotency_key,
                created_at=NOW,
                max_attempts=1,
            )
            source_job["payload"] = source_payload

            enqueued = queue.enqueue(source_job)
            claimed = queue.claim_next_job(
                "postgres-replay-smoke-worker",
                job_type=JOB_TYPE,
                updated_at="2026-08-05T00:00:01Z",
            )
            if claimed is None:
                return _failure(
                    "claim_missing",
                    "job replay smoke could not claim the source job.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                )
            dead_lettered = queue.retry_job(
                claimed["job_id"],
                error={
                    "error_code": "smoke.source_failed",
                    "detail": "PostgreSQL replay smoke source failed.",
                },
                failed_at="2026-08-05T00:00:02Z",
            )
            decision = plan_dead_letter_replay(
                dead_lettered,
                replay_job_id=replay_job_id,
                idempotency_key=replay_idempotency_key,
                requested_by="postgres-replay-smoke",
                reason="verify PostgreSQL dead-letter replay persistence",
                replayed_at="2026-08-05T00:00:03Z",
            )
            replay = queue.enqueue(decision.replay_job)
            duplicate = queue.enqueue(
                {
                    **decision.replay_job,
                    "job_id": f"{replay_job_id}-duplicate",
                }
            )
            replay_readback = queue.get_job(replay_job_id)
            checks = {
                "source_enqueued": enqueued["job_id"] == source_job_id,
                "source_claimed": claimed["status"] == "RUNNING",
                "source_dead_lettered": (
                    dead_lettered["status"] == "FAILED"
                    and dead_lettered["error"]["dead_lettered"] is True
                ),
                "replay_enqueued": replay["status"] == "QUEUED",
                "payload_copied": replay["payload"] == source_payload,
                "lineage_persisted": (
                    replay["replay_lineage"]["source_job_id"] == source_job_id
                    and replay["replay_lineage"]["requested_by"]
                    == "postgres-replay-smoke"
                ),
                "idempotency": duplicate["job_id"] == replay_job_id,
                "readback": (
                    replay_readback is not None
                    and replay_readback["replay_lineage"]["source_job_id"]
                    == source_job_id
                ),
            }
            if not all(checks.values()):
                return _failure(
                    "checks_failed",
                    "PostgreSQL job replay smoke checks failed.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                    checks=checks,
                )
            return {
                "smoke_schema_version": "postgres_job_replay_smoke.v1",
                "status": "PASS",
                "service_id": service_id,
                "profile": profile,
                "database_env": database_env,
                "redacted_database_url": redact_database_url(database_url),
                "source_job_id": source_job_id,
                "replay_job_id": replay_job_id,
                "checks": checks,
            }
        finally:
            _delete_smoke_jobs(engine, **cleanup_ids)
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


def _delete_smoke_jobs(
    engine: object,
    *,
    source_job_id: str,
    replay_job_id: str,
    source_idempotency_key: str,
    replay_idempotency_key: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_jobs
                WHERE job_id IN (:source_job_id, :replay_job_id)
                   OR (
                        job_type = :job_type
                    AND idempotency_key IN (
                        :source_idempotency_key,
                        :replay_idempotency_key
                    )
                   )
                """
            ),
            {
                "source_job_id": source_job_id,
                "replay_job_id": replay_job_id,
                "job_type": JOB_TYPE,
                "source_idempotency_key": source_idempotency_key,
                "replay_idempotency_key": replay_idempotency_key,
            },
        )


def _failure(
    failure_code: str,
    detail: str,
    *,
    service_id: str,
    profile: str,
    database_env: str | None = None,
    checks: dict[str, bool] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "smoke_schema_version": "postgres_job_replay_smoke.v1",
        "status": "FAIL",
        "service_id": service_id,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if database_env is not None:
        payload["database_env"] = database_env
    if checks is not None:
        payload["checks"] = checks
    return payload


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"postgres_job_replay_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "postgres_job_replay_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "postgres_job_replay_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run optional PostgreSQL job replay smoke.")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_job_replay_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
