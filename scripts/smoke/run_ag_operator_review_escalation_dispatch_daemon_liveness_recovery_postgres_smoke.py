#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping
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
    AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED,
    OperationsQueryError,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan,
    emit_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SqlAlchemyOperationalEventStore,
    SqlAlchemyWorkerHeartbeatStore,
    build_engine,
    build_session_factory,
    build_worker_heartbeat,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_RECOVERY_POSTGRES_SMOKE"
)
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
RAW_RECOVERY_SECRET = "raw-recovery-secret-0797"


def run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke(
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
        return _failure(
            "migration_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    request_id = f"ag-dispatch-daemon-liveness-recovery-smoke-{suffix}"
    trace_id = uuid4().hex
    checked_at = _to_zulu(datetime.now(UTC))
    engine: Any | None = None
    heartbeat_store: Any | None = None
    original_heartbeat: dict[str, Any] | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        original_heartbeat = heartbeat_store.get_heartbeat(SERVICE_ID, WORKER_ID)

        stale_heartbeat = _smoke_heartbeat(
            suffix=suffix,
            status="IDLE",
            trace_id=trace_id,
            last_seen_at=datetime.now(UTC)
            - timedelta(seconds=STALE_AFTER_SECONDS + 30),
        )
        heartbeat_store.upsert_heartbeat(stale_heartbeat)

        with _temporary_environ(
            {
                DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
                DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
            }
        ):
            liveness_projection = (
                build_operator_review_escalation_dispatch_daemon_liveness_projection(
                    worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                    worker_id=WORKER_ID,
                    stale_after_seconds=STALE_AFTER_SECONDS,
                    checked_at=checked_at,
                    request_trace_id=trace_id,
                )
            )
            preliminary_dashboard = build_operations_dashboard_snapshot_projection(
                event_store=event_store,
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                service_id=SERVICE_ID,
                recent_limit=20,
                request_trace_id=trace_id,
            )
            preliminary_dispatches = preliminary_dashboard[
                "operator_review_escalation_dispatches"
            ]
            recovery_plan = (
                build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
                    liveness_projection,
                    process_section=preliminary_dispatches.get("daemon_process"),
                    checked_at=checked_at,
                    request_trace_id=trace_id,
                )
            )
            audit_result = (
                emit_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event(
                    OperationalEventEmitter(service_id=SERVICE_ID, store=event_store),
                    http_method="GET",
                    request_id=request_id,
                    trace_id=trace_id,
                    recovery_plan=recovery_plan,
                )
            )
            dashboard = build_operations_dashboard_snapshot_projection(
                event_store=event_store,
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                service_id=SERVICE_ID,
                recent_limit=20,
                request_trace_id=trace_id,
            )
            issue_projection = build_operations_issue_candidate_projection(
                event_store=event_store,
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                service_id=SERVICE_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=checked_at,
                request_trace_id=trace_id,
            )

        dispatches = dashboard["operator_review_escalation_dispatches"]
        dashboard_liveness = dispatches["daemon_liveness"]
        dashboard_recovery = dispatches["daemon_recovery"]
        issue_candidate = _liveness_issue_candidate(issue_projection)
        audit_event_ids = [
            str(audit_result.event["event_id"])
            for audit_result in (audit_result,)
            if audit_result.ok
            and audit_result.event is not None
            and audit_result.event.get("event_id")
        ]
        observations = _db_recovery_observations(
            engine,
            worker_id=WORKER_ID,
            trace_id=trace_id,
            audit_event_ids=audit_event_ids,
        )
        recovery_summary = recovery_plan.get("summary", {})
        recovery_policy = recovery_plan.get("acknowledgement_suppression_policy", {})
        issue_policy = _issue_candidate_ack_policy(issue_candidate)
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
            "heartbeat_row_persisted": observations.get("heartbeat_row_count") == 1,
            "heartbeat_table_used": observations.get("heartbeat_table")
            == "service_worker_heartbeats",
            "audit_event_emitted": audit_result.ok is True,
            "audit_event_row_persisted": observations.get("event_count") == 1,
            "audit_event_id_persisted": observations.get(
                "expected_audit_event_ids_persisted"
            )
            is True,
            "audit_event_type_ready": observations.get("event_type_counts", {}).get(
                AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_EVENT_PLANNED
            )
            == 1,
            "liveness_stale_ready": (
                liveness_projection.get("projection_status") == "READY"
                and liveness_projection.get("summary", {}).get("liveness_status")
                == "STALE"
            ),
            "recovery_plan_actionable": (
                recovery_plan.get("projection_status") == "ACTION_RECOMMENDED"
                and recovery_summary.get("requires_operator_action") is True
                and recovery_summary.get("acknowledgement_suppression_available")
                is True
            ),
            "recovery_plan_read_only": (
                recovery_plan.get("recovery_plan_route", {}).get("mutation") is False
                and recovery_plan.get("process_control_route", {}).get(
                    "subprocess_mutation_performed"
                )
                is False
            ),
            "recovery_policy_ready": (
                recovery_policy.get("policy_status") == "ACTIONABLE"
                and recovery_policy.get("state_storage", {}).get(
                    "new_tables_required"
                )
                is False
            ),
            "dashboard_liveness_stale": (
                dashboard_liveness.get("summary", {}).get("liveness_status")
                == "STALE"
            ),
            "dashboard_recovery_actionable": (
                dashboard_recovery.get("recovery_plan_status")
                == "ACTION_RECOMMENDED"
                and dashboard_recovery.get("summary", {}).get(
                    "requires_operator_action"
                )
                is True
            ),
            "dashboard_ack_policy_ready": (
                dashboard_recovery.get("acknowledgement_suppression_policy", {}).get(
                    "policy_status"
                )
                == "ACTIONABLE"
            ),
            "issue_candidate_ack_policy_ready": (
                issue_candidate is not None
                and issue_policy.get("policy_status") == "ACTIONABLE"
                and issue_policy.get("new_tables_required") is False
            ),
            "no_new_tables_required": (
                liveness_projection.get("new_tables_required") is False
                and recovery_plan.get("new_tables_required") is False
                and dashboard_liveness.get("summary", {}).get("new_tables_required")
                is False
                and dashboard_recovery.get("summary", {}).get("new_tables_required")
                is False
            ),
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
        }
        cleanup = _cleanup_smoke_rows(
            heartbeat_store,
            engine,
            original_heartbeat=original_heartbeat,
            worker_id=WORKER_ID,
            trace_id=trace_id,
        )
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
            "worker_id": WORKER_ID,
            "liveness_summary": liveness_projection.get("summary", {}),
            "recovery_plan_summary": recovery_summary,
            "recovery_policy_summary": _recovery_policy_summary(recovery_policy),
            "dashboard_recovery_summary": dashboard_recovery.get("summary", {}),
            "dashboard_recovery_status": dashboard_recovery.get(
                "recovery_plan_status"
            ),
            "audit_event": _audit_emit_summary(audit_result),
            "issue_candidate": _issue_candidate_summary(issue_candidate),
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (OperationsQueryError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None:
            if not cleanup_done and heartbeat_store is not None:
                _cleanup_smoke_rows(
                    heartbeat_store,
                    engine,
                    original_heartbeat=original_heartbeat,
                    worker_id=WORKER_ID,
                    trace_id=trace_id,
                )
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _smoke_heartbeat(
    *,
    suffix: str,
    status: str,
    trace_id: str,
    last_seen_at: datetime,
) -> dict[str, Any]:
    started_at = last_seen_at - timedelta(seconds=15)
    return build_worker_heartbeat(
        service_id=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
        worker_id=WORKER_ID,
        worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
        status=status,
        trace_id=trace_id,
        started_at=_to_zulu(started_at),
        last_seen_at=_to_zulu(last_seen_at),
        metadata={
            "source": "postgres_smoke",
            "slice": "0797",
            "smoke_id": suffix,
            "secret_included": False,
        },
    )


def _db_recovery_observations(
    engine: Any,
    *,
    worker_id: str,
    trace_id: str,
    audit_event_ids: list[str],
) -> dict[str, Any]:
    with engine.begin() as connection:
        heartbeat_rows = list(
            connection.execute(
                text(
                    """
                    SELECT service_id,
                           worker_id,
                           worker_type,
                           status,
                           trace_id,
                           metadata::text AS metadata_text
                    FROM service_worker_heartbeats
                    WHERE service_id = :service_id AND worker_id = :worker_id
                    """
                ),
                {"service_id": SERVICE_ID, "worker_id": worker_id},
            ).mappings()
        )
        event_rows = list(
            connection.execute(
                text(
                    """
                    SELECT event_id,
                           event_type,
                           severity,
                           subject_type,
                           subject_id,
                           details::text AS details_text
                    FROM service_operational_events
                    WHERE service_id = :service_id AND trace_id = :trace_id
                    ORDER BY created_at ASC, event_id ASC
                    """
                ),
                {"service_id": SERVICE_ID, "trace_id": trace_id},
            ).mappings()
        )
    persisted_event_ids = {str(row["event_id"]) for row in event_rows}
    event_type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    raw_value_leak_count = 0
    trace_ids: set[str] = set()
    for row in heartbeat_rows:
        if row.get("trace_id"):
            trace_ids.add(str(row["trace_id"]))
        if RAW_RECOVERY_SECRET in str(row.get("metadata_text") or ""):
            raw_value_leak_count += 1
    for row in event_rows:
        event_type = str(row["event_type"])
        severity = str(row["severity"])
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if RAW_RECOVERY_SECRET in str(row.get("details_text") or ""):
            raw_value_leak_count += 1
    return {
        "heartbeat_table": "service_worker_heartbeats",
        "event_table": "service_operational_events",
        "heartbeat_row_count": len(heartbeat_rows),
        "event_count": len(event_rows),
        "backend": _engine_backend(engine),
        "database": _engine_database(engine),
        "heartbeat_trace_id_persisted": trace_id in trace_ids,
        "expected_audit_event_count": len(audit_event_ids),
        "expected_audit_event_ids_persisted": set(audit_event_ids).issubset(
            persisted_event_ids
        ),
        "event_type_counts": event_type_counts,
        "severity_counts": severity_counts,
        "raw_value_leak_count": raw_value_leak_count,
    }


def _cleanup_smoke_rows(
    heartbeat_store: Any,
    engine: Any,
    *,
    original_heartbeat: dict[str, Any] | None,
    worker_id: str,
    trace_id: str,
) -> dict[str, Any]:
    heartbeat_cleanup = _restore_or_delete_heartbeat(
        heartbeat_store,
        engine,
        original_heartbeat=original_heartbeat,
        worker_id=worker_id,
    )
    return {
        **heartbeat_cleanup,
        "deleted_audit_event_rows": _delete_smoke_events(
            engine,
            trace_id=trace_id,
        ),
    }


def _restore_or_delete_heartbeat(
    heartbeat_store: Any,
    engine: Any,
    *,
    original_heartbeat: dict[str, Any] | None,
    worker_id: str,
) -> dict[str, Any]:
    if original_heartbeat is not None:
        heartbeat_store.upsert_heartbeat(original_heartbeat)
        return {
            "restored_original_heartbeat": True,
            "deleted_heartbeat_rows": 0,
        }
    return {
        "restored_original_heartbeat": False,
        "deleted_heartbeat_rows": _delete_smoke_heartbeat(
            engine,
            worker_id=worker_id,
        ),
    }


def _delete_smoke_heartbeat(engine: Any, *, worker_id: str) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM service_worker_heartbeats
                WHERE service_id = :service_id AND worker_id = :worker_id
                """
            ),
            {"service_id": SERVICE_ID, "worker_id": worker_id},
        )
    return int(result.rowcount or 0)


def _delete_smoke_events(engine: Any, *, trace_id: str) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE service_id = :service_id AND trace_id = :trace_id
                """
            ),
            {"service_id": SERVICE_ID, "trace_id": trace_id},
        )
    return int(result.rowcount or 0)


def _liveness_issue_candidate(
    projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    candidates = projection.get("issue_candidates", [])
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if (
            isinstance(candidate, Mapping)
            and candidate.get("rule_id")
            == "operator_review_dispatch_daemon_liveness_attention_required.v1"
        ):
            return dict(candidate)
    return None


def _issue_candidate_ack_policy(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if candidate is None:
        return {}
    signal = candidate.get("signal") if isinstance(candidate.get("signal"), Mapping) else {}
    policy = signal.get("acknowledgement_suppression_policy")
    return dict(policy) if isinstance(policy, Mapping) else {}


def _issue_candidate_summary(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {"present": False}
    signal = candidate.get("signal") if isinstance(candidate.get("signal"), Mapping) else {}
    policy = _issue_candidate_ack_policy(candidate)
    return {
        "present": True,
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "signal_status": signal.get("status"),
        "worker_id": signal.get("worker_id"),
        "ack_policy_status": policy.get("policy_status"),
        "ack_policy_new_tables_required": policy.get("new_tables_required"),
    }


def _audit_emit_summary(result: Any) -> dict[str, Any]:
    summary = result.to_summary()
    return {
        "ok": summary.get("ok"),
        "event_id": summary.get("event_id"),
        "event_type": summary.get("event_type"),
        "severity": summary.get("severity"),
        "error_code": summary.get("error_code"),
    }


def _recovery_policy_summary(policy: object) -> dict[str, Any]:
    if not isinstance(policy, Mapping):
        return {"present": False}
    state_storage = policy.get("state_storage")
    return {
        "present": True,
        "policy_status": policy.get("policy_status"),
        "liveness_status": policy.get("liveness_status"),
        "supported_actions": list(policy.get("supported_actions") or []),
        "new_tables_required": (
            state_storage.get("new_tables_required")
            if isinstance(state_storage, Mapping)
            else None
        ),
    }


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    if callable(get_backend_name):
        return str(get_backend_name())
    return "unknown"


def _engine_database(engine: Any) -> str | None:
    url = getattr(engine, "url", None)
    database = getattr(url, "database", None)
    return str(database) if database else None


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


@contextmanager
def _temporary_environ(updates: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = [
        value
        for value in (
            RAW_RECOVERY_SECRET,
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
            "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
            f"postgres_smoke=skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
            f"postgres_smoke=fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    cleanup = evidence.get("cleanup", {})
    recovery = evidence.get("recovery_plan_summary", {})
    dashboard_status = evidence.get("dashboard_recovery_status")
    issue = evidence.get("issue_candidate", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
        "postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"backend={observations.get('backend')} "
        f"heartbeat_rows={observations.get('heartbeat_row_count')} "
        f"event_rows={observations.get('event_count')} "
        f"recovery={recovery.get('liveness_status')} "
        f"dashboard={dashboard_status} "
        f"issue_ack={issue.get('ack_policy_status')} "
        f"deleted_audit_event_rows={cleanup.get('deleted_audit_event_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
