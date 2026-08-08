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
    REDACTED_LOG_VALUE,
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


SMOKE_ENV = "NEX_DB_SERVICE_LOG_SMOKE"
SMOKE_SERVICE_ENV = "NEX_DB_SERVICE_LOG_SMOKE_SERVICE"
SMOKE_PROFILE_ENV = "NEX_DB_SERVICE_LOG_SMOKE_PROFILE"
DEFAULT_SERVICE_ID = "nex-cx"
DEFAULT_PROFILE = "test"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "service-log-smoke-request"
JOB_ID = "service-log-smoke-job"
LOGGER_NAME = "nex.smoke.service_log"
NOW = "2026-08-05T00:00:00Z"


def run_postgres_service_log_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "postgres_service_log_smoke.v1",
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
        pool_settings = database_pool_settings(service_id, workload="api", environ=env)
        engine = build_engine(database_url, pool_settings=pool_settings)
        log_id = f"service-log-smoke-{uuid4()}"
        _delete_smoke_logs(engine, log_id=log_id, request_id=REQUEST_ID)
        try:
            store = SqlAlchemyServiceLogStore(build_session_factory(engine))
            entry = build_service_log_entry(
                service_id=service_id,
                severity="ERROR",
                logger_name=LOGGER_NAME,
                message="Service log PostgreSQL smoke completed.",
                trace_id=TRACE_ID,
                request_id=REQUEST_ID,
                job_id=JOB_ID,
                subject_ref={"type": "smoke.log", "id": log_id},
                attributes={
                    "safe_count": 1,
                    "authorization": "Bearer private",
                    "nested": {
                        "attempt": 1,
                        "api_key": "secret-token-value",
                    },
                },
                observed_at=NOW,
                log_id=log_id,
            )
            appended = store.append(entry)
            duplicate = store.append({**entry, "severity": "CRITICAL"})
            readback = store.get_log(log_id)
            listed = store.list_logs(
                service_id=service_id,
                severity="error",
                logger_name=LOGGER_NAME,
                trace_id=TRACE_ID,
                request_id=REQUEST_ID,
                job_id=JOB_ID,
                subject_type="smoke.log",
                subject_id=log_id,
                limit=5,
            )
            summary = store.summary()
            checks = {
                "append": appended["log_id"] == log_id,
                "idempotency": duplicate["severity"] == "ERROR",
                "readback": readback is not None and readback["log_id"] == log_id,
                "jsonb_redaction": _jsonb_redaction_check(readback),
                "redaction": _redaction_safe(appended),
                "list_filter": [log["log_id"] for log in listed] == [log_id],
                "summary": (
                    summary["by_service"].get(service_id, 0) >= 1
                    and summary["by_severity"].get("ERROR", 0) >= 1
                ),
            }
            if not all(checks.values()):
                return _failure(
                    "checks_failed",
                    "PostgreSQL service log smoke checks failed.",
                    service_id=service_id,
                    profile=profile,
                    database_env=database_env,
                    checks=checks,
                )
            return {
                "smoke_schema_version": "postgres_service_log_smoke.v1",
                "status": "PASS",
                "service_id": service_id,
                "profile": profile,
                "database_env": database_env,
                "redacted_database_url": redact_database_url(database_url),
                "log_id": log_id,
                "checks": checks,
            }
        finally:
            _delete_smoke_logs(engine, log_id=log_id, request_id=REQUEST_ID)
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


def _delete_smoke_logs(engine: object, *, log_id: str, request_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_log_entries
                WHERE log_id = :log_id
                   OR (logger_name = :logger_name AND request_id = :request_id)
                """
            ),
            {
                "log_id": log_id,
                "logger_name": LOGGER_NAME,
                "request_id": request_id,
            },
        )


def _jsonb_redaction_check(entry: dict[str, object] | None) -> bool:
    if entry is None:
        return False
    attributes = entry.get("attributes")
    if not isinstance(attributes, dict):
        return False
    nested = attributes.get("nested")
    if not isinstance(nested, dict):
        return False
    redacted_keys = entry.get("redacted_attribute_keys")
    return (
        attributes.get("safe_count") == 1
        and "authorization" not in attributes
        and nested.get("api_key") == REDACTED_LOG_VALUE
        and isinstance(redacted_keys, list)
        and "authorization" in redacted_keys
        and "nested.api_key" in redacted_keys
    )


def _redaction_safe(entry: dict[str, object]) -> bool:
    serialized = json.dumps(entry, ensure_ascii=False)
    return "Bearer private" not in serialized and "secret-token-value" not in serialized


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
        "smoke_schema_version": "postgres_service_log_smoke.v1",
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
        return f"postgres_service_log_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "postgres_service_log_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "postgres_service_log_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional PostgreSQL ServiceLogStore write smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_service_log_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
