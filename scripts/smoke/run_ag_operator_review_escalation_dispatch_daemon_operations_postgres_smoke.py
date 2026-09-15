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
    build_operation_query_options,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_control_history_projection,
    emit_operator_review_escalation_dispatch_daemon_control_audit_event,
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
    "ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_OPERATIONS_POSTGRES_SMOKE"
)
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TRACE_ID_PREFIX = "ag-dispatch-daemon-ops-smoke"
RAW_REQUEST_PAYLOAD = "raw-control-request-secret-0768"
RAW_PROVIDER_PAYLOAD = "raw-control-provider-secret-0768"
RAW_OPERATOR_COMMENT = "raw-operator-comment-secret-0768"


def run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke(
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
    request_id = f"ag-dispatch-daemon-ops-smoke-{suffix}"
    trace_id = f"{TRACE_ID_PREFIX}-{suffix}"
    engine: Any | None = None
    event_ids: list[str] = []
    try:
        window_start = datetime.now(UTC) - timedelta(seconds=3)
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        events = _emit_smoke_control_events(
            event_store,
            request_id=request_id,
            trace_id=trace_id,
        )
        event_ids = [str(event["event_id"]) for event in events]
        query_options = build_operation_query_options(
            limit=50,
            since=_to_zulu(window_start),
            until=_to_zulu(datetime.now(UTC) + timedelta(seconds=3)),
            sort="desc",
        )
        history = (
            build_operator_review_escalation_dispatch_daemon_control_history_projection(
                event_store,
                trace_id=trace_id,
                limit=50,
                query_options=query_options,
                request_trace_id=trace_id,
            )
        )
        dashboard = build_operations_dashboard_snapshot_projection(
            event_store=event_store,
            service_id=SERVICE_ID,
            recent_limit=50,
            query_options=query_options,
            request_trace_id=trace_id,
        )
        issue_projection = build_operations_issue_candidate_projection(
            event_store=event_store,
            service_id=SERVICE_ID,
            recent_limit=50,
            query_options=query_options,
            request_trace_id=trace_id,
        )
        daemon_controls = (
            dashboard.get("operator_review_escalation_dispatches", {}).get(
                "daemon_controls",
                {},
            )
        )
        issue_candidate = _dispatch_daemon_issue_candidate(issue_projection)
        observations = _db_event_observations(
            engine,
            trace_id=trace_id,
            event_ids=event_ids,
        )
        history_event_ids = _control_event_ids(history.get("controls", []))
        dashboard_event_ids = _control_event_ids(daemon_controls.get("recent", []))
        candidate_event_ids = (
            set(issue_candidate.get("signal", {}).get("control_event_ids", []))
            if issue_candidate is not None
            else set()
        )
        failed_rejected_ids = {
            str(event["event_id"])
            for event in events
            if event["event_type"].endswith((".failed", ".rejected"))
        }
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "events_emitted": len(events) == 3,
            "db_rows_persisted": observations.get("event_count") == 3,
            "history_ready": history.get("projection_status") == "READY",
            "history_trace_scoped": history.get("filters", {}).get("trace_id")
            == trace_id,
            "history_has_all_events": set(event_ids).issubset(history_event_ids),
            "dashboard_controls_ready": daemon_controls.get("projection_status")
            == "READY",
            "dashboard_has_smoke_events": set(event_ids).issubset(
                dashboard_event_ids
            ),
            "dashboard_failed_rejected_visible": (
                daemon_controls.get("summary", {}).get("failed_count", 0) >= 1
                and daemon_controls.get("summary", {}).get("rejected_count", 0) >= 1
            ),
            "issue_candidate_ready": issue_candidate is not None,
            "issue_candidate_covers_failed_rejected": failed_rejected_ids.issubset(
                candidate_event_ids
            ),
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
        }
        cleanup = _cleanup_smoke_events(engine, trace_id=trace_id)
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
            "event_ids": event_ids,
            "history_summary": history.get("summary", {}),
            "dashboard_control_summary": daemon_controls.get("summary", {}),
            "issue_candidate": _issue_candidate_summary(issue_candidate),
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (OperationsQueryError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_smoke_events(engine, trace_id=trace_id)
            engine.dispose()
    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        forbidden_values=(
            RAW_REQUEST_PAYLOAD,
            RAW_PROVIDER_PAYLOAD,
            RAW_OPERATOR_COMMENT,
        ),
    )
    return evidence


def _emit_smoke_control_events(
    event_store: Any,
    *,
    request_id: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    results = [
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_plan",
            http_method="GET",
            request_id=request_id,
            trace_id=trace_id,
            projection=_tick_plan_projection(),
        ),
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_once",
            http_method="POST",
            request_id=f"{request_id}-rejected",
            trace_id=trace_id,
            error=OperationsQueryError(
                error_code=(
                    "ag.operator_review_escalation_dispatch_daemon_control_denied"
                ),
                detail="Synthetic rejected control for PostgreSQL smoke.",
                status_code=409,
            ),
        ),
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_once",
            http_method="POST",
            request_id=f"{request_id}-failed",
            trace_id=trace_id,
            error=OperationsQueryError(
                error_code=(
                    "ag.operator_review_escalation_dispatch_daemon_dispatch_source_"
                    "unavailable"
                ),
                detail="Synthetic failed control for PostgreSQL smoke.",
                status_code=503,
            ),
        ),
    ]
    failed = [result for result in results if not result.ok or result.event is None]
    if failed:
        detail = "; ".join(
            str(result.error_code or result.detail or "unknown") for result in failed
        )
        raise ValueError(f"dispatch daemon control event emission failed: {detail}")
    return [dict(result.event or {}) for result in results]


def _tick_plan_projection() -> dict[str, Any]:
    return {
        "projection_schema_version": (
            "ag_operator_review_escalation_dispatch_daemon_tick_plan_api.v1"
        ),
        "summary": {
            "plan_status": "READY",
            "candidate_count": 1,
            "processed_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "retry_wait_count": 0,
            "skipped_count": 0,
            "mutation_performed": False,
        },
        "route": {
            "method": "GET",
            "path": "/admin/v1/operator-review/dispatch-daemon/tick-plan",
            "mutation": False,
            "requires_confirm_tick": False,
        },
        "control_request": {
            "confirm_tick": False,
            "dry_run": True,
        },
        "control_admission": {
            "admission_status": "ACCEPTED",
            "rejection_reason": None,
        },
        "policy": {
            "enabled": True,
            "batch_limit": 1,
            "effective_provider_mode": "mock_first_only",
        },
        "redaction_probe": {
            "raw_request_payload": RAW_REQUEST_PAYLOAD,
            "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
            "raw_operator_comment": RAW_OPERATOR_COMMENT,
        },
    }


def _db_event_observations(
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
                    ORDER BY created_at DESC, event_id DESC
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
        if any(
            raw_value in details_text
            for raw_value in (
                RAW_REQUEST_PAYLOAD,
                RAW_PROVIDER_PAYLOAD,
                RAW_OPERATOR_COMMENT,
            )
        ):
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


def _dispatch_daemon_issue_candidate(
    issue_projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    for candidate in issue_projection.get("issue_candidates", []):
        if (
            isinstance(candidate, Mapping)
            and candidate.get("rule_id")
            == "operator_review_dispatch_daemon_control_attention_required.v1"
        ):
            return dict(candidate)
    return None


def _issue_candidate_summary(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    signal = candidate.get("signal", {})
    return {
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "status": signal.get("status") if isinstance(signal, Mapping) else None,
        "count": signal.get("count") if isinstance(signal, Mapping) else None,
        "failed_count": (
            signal.get("failed_count") if isinstance(signal, Mapping) else None
        ),
        "rejected_count": (
            signal.get("rejected_count") if isinstance(signal, Mapping) else None
        ),
    }


def _control_event_ids(items: object) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        str(item["control_event_id"])
        for item in items
        if isinstance(item, Mapping) and item.get("control_event_id")
    }


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
    *,
    forbidden_values: tuple[str, ...],
) -> None:
    forbidden = [value for value in (*forbidden_values, env.get(DATABASE_ENV, "")) if value]
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
            "ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    cleanup = evidence.get("cleanup", {})
    dashboard_summary = evidence.get("dashboard_control_summary", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"events={observations.get('event_count')} "
        f"failed={dashboard_summary.get('failed_count')} "
        f"rejected={dashboard_summary.get('rejected_count')} "
        f"deleted_events={cleanup.get('events')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
