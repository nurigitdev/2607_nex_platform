#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_runtime import (  # noqa: E402
    SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION,
    SqlAlchemyServiceLogStore,
    build_engine,
    build_service_log_entry,
    build_session_factory,
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


SMOKE_ENV = "NEX_DB_SERVICE_LOG_RETENTION_SMOKE"
SMOKE_SERVICE_ENV = "NEX_DB_SERVICE_LOG_RETENTION_SMOKE_SERVICE"
SMOKE_PROFILE_ENV = "NEX_DB_SERVICE_LOG_RETENTION_SMOKE_PROFILE"
DEFAULT_SERVICE_ID = "nex-cx"
DEFAULT_PROFILE = "test"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID_PREFIX = "service-log-retention-smoke"
JOB_ID = "service-log-retention-smoke-job"
LOGGER_NAME = "nex.smoke.service_log_retention"
RETENTION_CUTOFF = "2026-07-06T00:00:00Z"
CHECKED_AT = "2026-08-05T00:00:00Z"
RETENTION_DAYS = 30
MAX_DELETE_COUNT = 1
SCHEMA_VERSION = "postgres_service_log_retention_smoke.v1"


def run_postgres_service_log_retention_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    service_id = env.get(SMOKE_SERVICE_ENV, DEFAULT_SERVICE_ID)
    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for destructive smoke execution.",
            service_id=service_id,
            profile=profile,
        )

    try:
        database_env = service_database_env(service_id, profile=profile)
        database_url = service_database_url(service_id, profile=profile, environ=env)
        run_service_migrations(service_id, database_url=database_url, profile=profile)
        pool_settings = database_pool_settings(service_id, workload="api", environ=env)
        engine = build_engine(database_url, pool_settings=pool_settings)
        request_id = f"{REQUEST_ID_PREFIX}-{uuid4()}"
        log_ids = _smoke_log_ids()
        _delete_smoke_logs(engine, request_id=request_id, log_ids=log_ids)
        try:
            store = SqlAlchemyServiceLogStore(build_session_factory(engine))
            _seed_retention_logs(
                store,
                service_id=service_id,
                request_id=request_id,
                log_ids=log_ids,
            )
            dry_run = _purge(
                store,
                service_id=service_id,
                request_id=request_id,
                dry_run=True,
                delete_enabled=False,
                idempotency_key="smoke-retention-postgres-dry-run",
            )
            blocked = _purge(
                store,
                service_id=service_id,
                request_id=request_id,
                dry_run=False,
                delete_enabled=False,
                idempotency_key="smoke-retention-postgres-blocked",
            )
            execute = _purge(
                store,
                service_id=service_id,
                request_id=request_id,
                dry_run=False,
                delete_enabled=True,
                idempotency_key="smoke-retention-postgres-execute",
            )
            state = _remaining_state(store, log_ids)
            checks = _checks(dry_run=dry_run, blocked=blocked, execute=execute, state=state)
            if not all(checks.values()):
                return _failure(
                    "checks_failed",
                    "PostgreSQL service log retention smoke checks failed.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                    checks=checks,
                )
            evidence = {
                "smoke_schema_version": SCHEMA_VERSION,
                "status": "PASS",
                "service_id": service_id,
                "profile": profile,
                "database_env": database_env,
                "redacted_database_url": redact_database_url(database_url),
                "request_id": request_id,
                "retention_cutoff": RETENTION_CUTOFF,
                "checked_at": CHECKED_AT,
                "execution_ids": {
                    "dry_run": dry_run["execution_id"],
                    "blocked": blocked["execution_id"],
                    "execute": execute["execution_id"],
                },
                "counts": {
                    "dry_run_candidate_count": dry_run["candidate_count"],
                    "blocked_candidate_count": blocked["candidate_count"],
                    "execute_candidate_count": execute["candidate_count"],
                    "execute_deleted_count": execute["deleted_count"],
                    "remaining_old_count": int(state["old_001_remaining"])
                    + int(state["old_002_remaining"]),
                    "remaining_fresh_count": int(state["fresh_remaining"]),
                },
                "checks": checks,
            }
            if not _redaction_safe(evidence):
                return _failure(
                    "evidence_redaction_failed",
                    "PostgreSQL service log retention smoke evidence leaked private data.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                )
            return evidence
        finally:
            _delete_smoke_logs(engine, request_id=request_id, log_ids=log_ids)
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


def _smoke_log_ids() -> dict[str, str]:
    run_id = uuid4().hex
    return {
        "old_001": f"service-log-retention-smoke-old-001-{run_id}",
        "old_002": f"service-log-retention-smoke-old-002-{run_id}",
        "fresh": f"service-log-retention-smoke-fresh-{run_id}",
    }


def _seed_retention_logs(
    store: SqlAlchemyServiceLogStore,
    *,
    service_id: str,
    request_id: str,
    log_ids: dict[str, str],
) -> None:
    for key, observed_at in (
        ("old_001", "2026-06-01T00:00:00Z"),
        ("old_002", "2026-06-02T00:00:00Z"),
        ("fresh", "2026-08-04T00:00:00Z"),
    ):
        log_id = log_ids[key]
        store.append(
            build_service_log_entry(
                log_id=log_id,
                service_id=service_id,
                severity="ERROR" if key.startswith("old") else "INFO",
                logger_name=LOGGER_NAME,
                message="Service log retention PostgreSQL smoke entry.",
                trace_id=TRACE_ID,
                request_id=request_id,
                job_id=JOB_ID,
                subject_ref={"type": "smoke.retention_log", "id": log_id},
                attributes={"authorization": "Bearer private", "log_id": log_id},
                observed_at=observed_at,
            )
        )


def _purge(
    store: SqlAlchemyServiceLogStore,
    *,
    service_id: str,
    request_id: str,
    dry_run: bool,
    delete_enabled: bool,
    idempotency_key: str,
) -> dict[str, Any]:
    return store.purge_retention_candidates(
        service_id=service_id,
        retention_cutoff=RETENTION_CUTOFF,
        retention_days=RETENTION_DAYS,
        checked_at=CHECKED_AT,
        dry_run=dry_run,
        delete_enabled=delete_enabled,
        max_delete_count=MAX_DELETE_COUNT,
        idempotency_key=idempotency_key,
        trace_id=TRACE_ID,
        request_id=request_id,
    )


def _remaining_state(
    store: SqlAlchemyServiceLogStore,
    log_ids: dict[str, str],
) -> dict[str, bool]:
    return {
        "old_001_remaining": store.get_log(log_ids["old_001"]) is not None,
        "old_002_remaining": store.get_log(log_ids["old_002"]) is not None,
        "fresh_remaining": store.get_log(log_ids["fresh"]) is not None,
    }


def _checks(
    *,
    dry_run: dict[str, Any],
    blocked: dict[str, Any],
    execute: dict[str, Any],
    state: dict[str, bool],
) -> dict[str, bool]:
    return {
        "dry_run_succeeded_without_delete": (
            dry_run["retention_execution_schema_version"]
            == SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
            and dry_run["mode"] == "DRY_RUN"
            and dry_run["execution_status"] == "SUCCEEDED"
            and dry_run["candidate_count"] == 2
            and dry_run["deleted_count"] == 0
            and dry_run["delete_enabled"] is False
        ),
        "execute_without_delete_enabled_blocked": (
            blocked["mode"] == "EXECUTE"
            and blocked["execution_status"] == "BLOCKED"
            and blocked["candidate_count"] == 2
            and blocked["deleted_count"] == 0
            and blocked["blocked_reason"] == "delete_not_enabled"
        ),
        "execute_deleted_one_candidate": (
            execute["mode"] == "EXECUTE"
            and execute["execution_status"] == "SUCCEEDED"
            and execute["candidate_count"] == 2
            and execute["deleted_count"] == 1
            and execute["delete_enabled"] is True
            and execute["max_delete_count"] == MAX_DELETE_COUNT
        ),
        "store_state_guarded": (
            state["old_001_remaining"] is False
            and state["old_002_remaining"] is True
            and state["fresh_remaining"] is True
        ),
        "retention_window_fixed": (
            dry_run["retention_cutoff"] == RETENTION_CUTOFF
            and execute["checked_at"] == CHECKED_AT
        ),
    }


def _delete_smoke_logs(
    engine: object,
    *,
    request_id: str,
    log_ids: dict[str, str],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_log_entries
                WHERE request_id = :request_id
                   OR log_id IN (:old_001, :old_002, :fresh)
                """
            ),
            {
                "request_id": request_id,
                "old_001": log_ids["old_001"],
                "old_002": log_ids["old_002"],
                "fresh": log_ids["fresh"],
            },
        )


def _redaction_safe(evidence: dict[str, object]) -> bool:
    serialized = json.dumps(evidence, ensure_ascii=False)
    return "Bearer private" not in serialized and "secret" not in serialized


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
        "smoke_schema_version": SCHEMA_VERSION,
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
        return f"postgres_service_log_retention_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "postgres_service_log_retention_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"deleted={counts['execute_deleted_count']}"
        )
    return (
        "postgres_service_log_retention_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional PostgreSQL service log retention purge smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_service_log_retention_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
