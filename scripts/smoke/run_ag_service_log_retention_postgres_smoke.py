#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_ag.operations import (  # noqa: E402
    AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
    AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
    AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION,
    register_service_log_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION,
    SERVICE_SPECS,
    SqlAlchemyServiceLogStore,
    build_engine,
    build_service_app,
    build_service_log_entry,
    build_session_factory,
    database_pool_settings,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
    register_service_log_retention_routes,
)
from run_ag_service_log_retention_smoke import (  # noqa: E402
    LocalAgServiceLogRetentionClient,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE"
SMOKE_SERVICE_ENV = "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_SERVICE"
SMOKE_PROFILE_ENV = "NEX_AG_SERVICE_LOG_RETENTION_POSTGRES_SMOKE_PROFILE"
DEFAULT_SERVICE_ID = "nex-cx"
DEFAULT_PROFILE = "test"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID_PREFIX = "ag-service-log-retention-postgres-smoke"
JOB_ID = "ag-service-log-retention-postgres-smoke-job"
LOGGER_NAME = "nex.smoke.ag_service_log_retention_postgres"
RETENTION_CUTOFF = "1970-01-03T00:00:00Z"
CHECKED_AT = "2026-08-05T00:00:00Z"
RETENTION_DAYS = 30
MAX_DELETE_COUNT = 1
SCHEMA_VERSION = "ag_service_log_retention_postgres_smoke.v1"


def run_ag_service_log_retention_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for AG PostgreSQL smoke execution.",
            service_id=service_id,
            profile=profile,
        )
    if service_id not in SERVICE_SPECS:
        return _failure(
            "service_invalid",
            f"unknown service id: {service_id}",
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
            local_client = _build_local_retention_client(
                service_id=service_id,
                store=store,
            )
            audit_store = InMemoryOperationalEventStore()
            ag_client = _build_ag_client(
                local_client=local_client,
                audit_store=audit_store,
                service_id=service_id,
                store=store,
            )
            dry_run = _post_ag_json(
                ag_client,
                service_id=service_id,
                request_id=request_id,
                payload={
                    "retention_cutoff": RETENTION_CUTOFF,
                    "checked_at": CHECKED_AT,
                    "retention_days": RETENTION_DAYS,
                    "max_delete_count": MAX_DELETE_COUNT,
                    "idempotency_key": "smoke-ag-retention-postgres-dry-run",
                },
            )
            calls_after_dry_run = len(local_client.calls)
            blocked = _post_ag_json(
                ag_client,
                service_id=service_id,
                request_id=request_id,
                payload={
                    "retention_cutoff": RETENTION_CUTOFF,
                    "checked_at": CHECKED_AT,
                    "dry_run": False,
                    "idempotency_key": "smoke-ag-retention-postgres-blocked",
                },
            )
            calls_after_blocked = len(local_client.calls)
            execute = _post_ag_json(
                ag_client,
                service_id=service_id,
                request_id=request_id,
                payload={
                    "retention_cutoff": RETENTION_CUTOFF,
                    "checked_at": CHECKED_AT,
                    "dry_run": False,
                    "delete_enabled": True,
                    "max_delete_count": MAX_DELETE_COUNT,
                    "requested_by": {
                        "actor_type": "service",
                        "actor_id": "nex-ag",
                        "service_id": "nex-ag",
                    },
                    "idempotency_key": "smoke-ag-retention-postgres-execute",
                },
            )
            audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
            history = _get_ag_retention_history(
                ag_client,
                service_id=service_id,
                request_id=request_id,
            )
            state = _remaining_state(store, log_ids)
            checks = _checks(
                dry_run=dry_run,
                blocked=blocked,
                execute=execute,
                history=history,
                state=state,
                audit_events=audit_events,
                calls_after_dry_run=calls_after_dry_run,
                calls_after_blocked=calls_after_blocked,
                service_call_count=len(local_client.calls),
            )
            if not all(checks.values()):
                return _failure(
                    "checks_failed",
                    "AG service log retention PostgreSQL smoke checks failed.",
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
                "projection_versions": {
                    "dry_run": dry_run.get("projection_schema_version"),
                    "execute": execute.get("projection_schema_version"),
                    "service_response": execute.get("service_response", {}).get(
                        "retention_execution_schema_version"
                    ),
                    "history": history.get("projection_schema_version"),
                },
                "http_statuses": {
                    "dry_run": dry_run["_http_status"],
                    "blocked": blocked["_http_status"],
                    "execute": execute["_http_status"],
                    "history": history["_http_status"],
                },
                "counts": {
                    "candidate_count": execute.get("summary", {}).get(
                        "candidate_count"
                    ),
                    "deleted_count": execute.get("summary", {}).get("deleted_count"),
                    "history_count": history.get("summary", {}).get("total"),
                    "history_deleted_count": history.get("summary", {}).get(
                        "deleted_count"
                    ),
                    "audit_events": len(audit_events),
                    "service_calls": len(local_client.calls),
                    "remaining_old_count": int(state["old_001_remaining"])
                    + int(state["old_002_remaining"]),
                    "remaining_fresh_count": int(state["fresh_remaining"]),
                },
                "checks": checks,
            }
            if not _redaction_safe(evidence):
                return _failure(
                    "evidence_redaction_failed",
                    "AG service log retention PostgreSQL smoke evidence leaked private data.",
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


def _build_local_retention_client(
    *,
    service_id: str,
    store: SqlAlchemyServiceLogStore,
) -> LocalAgServiceLogRetentionClient:
    service_app = build_service_app(SERVICE_SPECS[service_id])
    register_service_log_retention_routes(
        service_app,
        service_id=service_id,
        store=store,
    )
    return LocalAgServiceLogRetentionClient({service_id: TestClient(service_app)})


def _build_ag_client(
    *,
    local_client: LocalAgServiceLogRetentionClient,
    audit_store: InMemoryOperationalEventStore,
    service_id: str,
    store: SqlAlchemyServiceLogStore,
) -> TestClient:
    ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        ag_app,
        service_log_stores={service_id: store},
        retention_control_client=local_client,
        audit_event_store=audit_store,
    )
    return TestClient(ag_app)


def _post_ag_json(
    client: TestClient,
    *,
    service_id: str,
    request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/admin/v1/operations/logs/retention/{service_id}/purge",
        json=payload,
        headers=_ag_headers(request_id=request_id),
    )
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def _get_ag_retention_history(
    client: TestClient,
    *,
    service_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.get(
        "/admin/v1/operations/logs/retention/history",
        params={
            "service_id": service_id,
            "request_id": request_id,
            "limit": 10,
        },
        headers=_ag_headers(request_id=request_id),
    )
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def _ag_headers(*, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _smoke_log_ids() -> dict[str, str]:
    run_id = uuid4().hex
    return {
        "old_001": f"ag-service-log-retention-smoke-old-001-{run_id}",
        "old_002": f"ag-service-log-retention-smoke-old-002-{run_id}",
        "fresh": f"ag-service-log-retention-smoke-fresh-{run_id}",
    }


def _seed_retention_logs(
    store: SqlAlchemyServiceLogStore,
    *,
    service_id: str,
    request_id: str,
    log_ids: dict[str, str],
) -> None:
    for key, observed_at in (
        ("old_001", "1970-01-01T00:00:00Z"),
        ("old_002", "1970-01-02T00:00:00Z"),
        ("fresh", "2026-08-04T00:00:00Z"),
    ):
        log_id = log_ids[key]
        store.append(
            build_service_log_entry(
                log_id=log_id,
                service_id=service_id,
                severity="ERROR" if key.startswith("old") else "INFO",
                logger_name=LOGGER_NAME,
                message="AG service log retention PostgreSQL smoke entry.",
                trace_id=TRACE_ID,
                request_id=request_id,
                job_id=JOB_ID,
                subject_ref={"type": "smoke.ag_retention_log", "id": log_id},
                attributes={"authorization": "Bearer private", "log_id": log_id},
                observed_at=observed_at,
            )
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
    history: dict[str, Any],
    state: dict[str, bool],
    audit_events: list[dict[str, Any]],
    calls_after_dry_run: int,
    calls_after_blocked: int,
    service_call_count: int,
) -> dict[str, bool]:
    return {
        "dry_run_dispatch_reached_postgres_service": (
            dry_run["_http_status"] == 200
            and dry_run["projection_schema_version"]
            == "ag_service_log_retention_dispatch.v1"
            and dry_run["summary"]["candidate_count"] == 2
            and dry_run["summary"]["deleted_count"] == 0
            and dry_run["service_response"]["retention_execution_schema_version"]
            == SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
        ),
        "blocked_before_service_call": (
            blocked["_http_status"] == 409
            and blocked["error_code"]
            == "ag.service_log_retention_delete_not_enabled"
            and calls_after_dry_run == 1
            and calls_after_blocked == calls_after_dry_run
        ),
        "execute_dispatch_deleted_one": (
            execute["_http_status"] == 200
            and execute["summary"]["candidate_count"] == 2
            and execute["summary"]["deleted_count"] == 1
            and execute["service_response"]["retention_execution_schema_version"]
            == SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
            and service_call_count == 2
        ),
        "ag_history_projection_reads_postgres_history": (
            history["_http_status"] == 200
            and history["projection_schema_version"]
            == AG_SERVICE_LOG_RETENTION_HISTORY_PROJECTION_SCHEMA_VERSION
            and history["projection_status"] == "READY"
            and history["source_statuses"][execute["service_response"]["service_id"]][
                "status"
            ]
            == "READY"
            and history["summary"]["total"] == 2
            and history["summary"]["by_mode"]["DRY_RUN"] == 1
            and history["summary"]["by_mode"]["EXECUTE"] == 1
            and history["summary"]["by_status"]["SUCCEEDED"] == 2
            and history["summary"]["deleted_count"] == 1
        ),
        "postgres_store_state_guarded": (
            state["old_001_remaining"] is False
            and state["old_002_remaining"] is True
            and state["fresh_remaining"] is True
        ),
        "ag_audit_events_recorded": (
            len(audit_events) == 3
            and [event["event_type"] for event in audit_events]
            == [
                AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
                AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
                AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
            ]
        ),
        "private_values_redacted": _redaction_safe(
            {
                "dry_run": dry_run,
                "blocked": blocked,
                "execute": execute,
                "history": history,
            }
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
        connection.execute(
            text(
                """
                DELETE FROM service_log_retention_history
                WHERE request_id = :request_id
                """
            ),
            {"request_id": request_id},
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
        return f"ag_service_log_retention_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_service_log_retention_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"audit_events={counts['audit_events']} "
            f"service_calls={counts['service_calls']} "
            f"deleted={counts['deleted_count']} "
            f"history={counts['history_count']}"
        )
    return (
        "ag_service_log_retention_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AG-to-service PostgreSQL service log retention smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_service_log_retention_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
