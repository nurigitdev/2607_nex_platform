#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operations import (  # noqa: E402
    OperationsQueryError,
    build_operations_dashboard_snapshot_projection,
    build_operator_review_escalation_dispatch_daemon_process_control_api_projection,
)
from nex_ag.operator_review_dispatch_daemon import (  # noqa: E402
    execute_dispatch_execution_daemon_cli,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV,
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED,
    DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED,
)
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_PROCESS_POSTGRES_SMOKE"
)
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TRACE_ID_PREFIX = "ag-dispatch-daemon-process-smoke"
RAW_PROCESS_SECRET = "raw-process-secret-0778"


def run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV)
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
    except MigrationError as exc:
        return _failure("migration_failed", str(exc))

    suffix = uuid4().hex[:12]
    request_id = f"ag-dispatch-daemon-process-smoke-{suffix}"
    trace_id = f"{TRACE_ID_PREFIX}-{suffix}"
    engine: Any | None = None
    cleanup_done = False
    try:
        window_start = datetime.now(UTC) - timedelta(seconds=3)
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        cli_result, lifecycle_event_ids = _emit_process_lifecycle_events(
            event_store,
            request_id=request_id,
            trace_id=trace_id,
        )
        dashboard = build_operations_dashboard_snapshot_projection(
            event_store=event_store,
            service_id=SERVICE_ID,
            recent_limit=20,
            request_trace_id=trace_id,
        )
        daemon_process = dashboard["operator_review_escalation_dispatches"][
            "daemon_process"
        ]
        process_control = (
            build_operator_review_escalation_dispatch_daemon_process_control_api_projection(
                payload={
                    "action": "status_probe",
                    "enabled": True,
                    "dry_run": True,
                    "operator_ref": {
                        "operator_type": "service",
                        "operator_id": "nex-ag-smoke",
                        "secret": RAW_PROCESS_SECRET,
                    },
                    "reason_codes": ["postgres_smoke"],
                    "database_url": database_url,
                },
                request_id=request_id,
                trace_id=trace_id,
            )
        )
        observations = _db_lifecycle_observations(
            engine,
            trace_id=trace_id,
            event_ids=lifecycle_event_ids,
        )
        expected_event_types = {
            DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_STARTED,
            DISPATCH_EXECUTION_DAEMON_LIFECYCLE_EVENT_COMPLETED,
        }
        observed_event_types = set(observations.get("event_type_counts", {}))
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "lifecycle_events_emitted": len(lifecycle_event_ids) == 2,
            "db_rows_persisted": observations.get("event_count") == 2,
            "expected_event_ids_persisted": observations.get(
                "expected_event_ids_persisted"
            )
            is True,
            "expected_event_types_persisted": expected_event_types.issubset(
                observed_event_types
            ),
            "dashboard_process_ready": daemon_process.get("projection_status")
            == "READY",
            "dashboard_process_control_path_ready": daemon_process.get(
                "process_control_path"
            )
            == "/admin/v1/operator-review/dispatch-daemon/process-controls",
            "dashboard_process_has_no_new_tables": daemon_process.get(
                "summary",
                {},
            ).get("new_tables_required")
            is False,
            "process_control_ready": process_control.get("projection_status")
            == "READY",
            "process_control_is_contract_only": (
                process_control.get("route", {}).get("protected") is True
                and process_control.get("route", {}).get("mutation") is False
                and process_control.get("summary", {}).get(
                    "subprocess_mutation_performed"
                )
                is False
            ),
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
        }
        cleanup = _cleanup_smoke_events(engine, trace_id=trace_id)
        cleanup_done = True
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "failure_code": None if all(checks.values()) else "checks_failed",
            "service": SERVICE_ID,
            "profile": PROFILE,
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "request_id": request_id,
            "trace_id": trace_id,
            "window_start": _to_zulu(window_start),
            "lifecycle_event_ids": lifecycle_event_ids,
            "cli_summary": _cli_summary(cli_result),
            "dashboard_process_summary": daemon_process.get("summary", {}),
            "process_control_summary": process_control.get("summary", {}),
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (OperationsQueryError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            if not cleanup_done:
                _cleanup_smoke_events(engine, trace_id=trace_id)
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _emit_process_lifecycle_events(
    event_store: Any,
    *,
    request_id: str,
    trace_id: str,
) -> tuple[dict[str, Any], list[str]]:
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    result = execute_dispatch_execution_daemon_cli(
        action="run_once",
        environ={
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_CYCLE_LIMIT_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_INTERVAL_SECONDS_ENV: "1",
        },
        request_id=request_id,
        trace_id=trace_id,
        worker_id="ag-dispatch-execution-daemon-smoke",
        confirm_tick=True,
        dry_run=True,
        cycle_limit=1,
        started_at=_to_zulu(datetime.now(UTC)),
        lifecycle_emitter=emitter,
    )
    lifecycle_events = result.get("lifecycle_events", [])
    if not isinstance(lifecycle_events, list):
        raise ValueError("dispatch daemon lifecycle result is not a list")
    failed = [
        event
        for event in lifecycle_events
        if not isinstance(event, Mapping) or event.get("ok") is not True
    ]
    if failed:
        detail = "; ".join(str(event.get("error_code") or event) for event in failed)
        raise ValueError(f"dispatch daemon lifecycle event emission failed: {detail}")
    event_ids = [
        str(event["event_id"])
        for event in lifecycle_events
        if isinstance(event, Mapping) and event.get("event_id")
    ]
    if len(event_ids) != 2:
        raise ValueError("dispatch daemon lifecycle event count mismatch")
    return result, event_ids


def _db_lifecycle_observations(
    engine: Any,
    *,
    trace_id: str,
    event_ids: list[str],
) -> dict[str, Any]:
    with engine.begin() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT event_id, event_type, severity, details::text AS details_text
                    FROM service_operational_events
                    WHERE trace_id = :trace_id
                    ORDER BY created_at ASC, event_id ASC
                    """
                ),
                {"trace_id": trace_id},
            ).mappings()
        )
    persisted_ids = {str(row["event_id"]) for row in rows}
    event_type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    raw_value_leak_count = 0
    for row in rows:
        event_type = str(row["event_type"])
        severity = str(row["severity"])
        details_text = str(row.get("details_text") or "")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if RAW_PROCESS_SECRET in details_text:
            raw_value_leak_count += 1
    return {
        "event_count": len(rows),
        "expected_event_count": len(event_ids),
        "expected_event_ids_persisted": set(event_ids).issubset(persisted_ids),
        "event_type_counts": event_type_counts,
        "severity_counts": severity_counts,
        "raw_value_leak_count": raw_value_leak_count,
    }


def _cleanup_smoke_events(engine: Any, *, trace_id: str) -> dict[str, int]:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE trace_id = :trace_id
                """
            ),
            {"trace_id": trace_id},
        )
    return {"events": int(result.rowcount or 0)}


def _cli_summary(cli_result: Mapping[str, Any]) -> dict[str, Any]:
    loop_summary = cli_result.get("loop_summary", {})
    plan = cli_result.get("plan", {})
    return {
        "result_status": cli_result.get("result_status"),
        "action": plan.get("action") if isinstance(plan, Mapping) else None,
        "lifecycle_event_count": len(
            cli_result.get("lifecycle_events", [])
            if isinstance(cli_result.get("lifecycle_events"), list)
            else []
        ),
        "loop_status": (
            loop_summary.get("loop_status") if isinstance(loop_summary, Mapping) else None
        ),
        "processed_count": (
            loop_summary.get("processed_count")
            if isinstance(loop_summary, Mapping)
            else None
        ),
    }


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = [
        value
        for value in (
            RAW_PROCESS_SECRET,
            env.get(DATABASE_ENV, ""),
        )
        if value
    ]
    leaked = [value for value in forbidden if value in serialized_evidence]
    if leaked:
        raise ValueError("smoke evidence contains unredacted sensitive value")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return (
            "ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    cleanup = evidence.get("cleanup", {})
    process_summary = evidence.get("dashboard_process_summary", {})
    control_summary = evidence.get("process_control_summary", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"events={observations.get('event_count')} "
        f"process={process_summary.get('process_status')} "
        f"control_action={control_summary.get('action')} "
        f"deleted_events={cleanup.get('events')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
