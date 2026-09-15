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
    OperationsQueryError,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_runtime import (  # noqa: E402
    SqlAlchemyWorkerHeartbeatStore,
    build_engine,
    build_session_factory,
    build_worker_heartbeat,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_POSTGRES_SMOKE"
)
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
RAW_HEARTBEAT_SECRET = "raw-heartbeat-secret-0788"


def run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke(
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
    request_id = f"ag-dispatch-daemon-liveness-smoke-{suffix}"
    trace_id = uuid4().hex
    engine: Any | None = None
    heartbeat_store: Any | None = None
    original_heartbeat: dict[str, Any] | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
        original_heartbeat = heartbeat_store.get_heartbeat(SERVICE_ID, WORKER_ID)

        checked_at = _to_zulu(datetime.now(UTC))
        fresh_heartbeat = _smoke_heartbeat(
            suffix=suffix,
            status="IDLE",
            trace_id=trace_id,
            last_seen_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        heartbeat_store.upsert_heartbeat(fresh_heartbeat)
        fresh_projection = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=checked_at,
                request_trace_id=trace_id,
            )
        )
        dashboard = build_operations_dashboard_snapshot_projection(
            worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
            service_id=SERVICE_ID,
            recent_limit=5,
            request_trace_id=trace_id,
        )

        stale_heartbeat = _smoke_heartbeat(
            suffix=suffix,
            status="IDLE",
            trace_id=trace_id,
            last_seen_at=datetime.now(UTC) - timedelta(
                seconds=STALE_AFTER_SECONDS + 30
            ),
        )
        heartbeat_store.upsert_heartbeat(stale_heartbeat)
        stale_projection = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=checked_at,
                request_trace_id=trace_id,
            )
        )
        with _temporary_environ(
            {
                DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
                DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
            }
        ):
            issue_projection = build_operations_issue_candidate_projection(
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                service_id=SERVICE_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=checked_at,
                request_trace_id=trace_id,
            )
        issue_candidate = _liveness_issue_candidate(issue_projection)
        observations = _db_heartbeat_observations(
            engine,
            worker_id=WORKER_ID,
            trace_id=trace_id,
        )

        dashboard_liveness = dashboard["operator_review_escalation_dispatches"][
            "daemon_liveness"
        ]
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
            "heartbeat_row_persisted": observations.get("row_count") == 1,
            "heartbeat_table_used": observations.get("table_name")
            == "service_worker_heartbeats",
            "fresh_liveness_ready": (
                fresh_projection.get("projection_status") == "READY"
                and fresh_projection.get("summary", {}).get("liveness_status")
                == "FRESH"
            ),
            "stale_liveness_ready": (
                stale_projection.get("projection_status") == "READY"
                and stale_projection.get("summary", {}).get("liveness_status")
                == "STALE"
            ),
            "dashboard_liveness_ready": (
                dashboard_liveness.get("projection_status") == "READY"
                and dashboard_liveness.get("summary", {}).get("liveness_status")
                == "FRESH"
            ),
            "issue_candidate_ready": (
                issue_candidate is not None
                and issue_candidate.get("rule_id")
                == "operator_review_dispatch_daemon_liveness_attention_required.v1"
            ),
            "no_new_tables_required": (
                fresh_projection.get("new_tables_required") is False
                and stale_projection.get("new_tables_required") is False
                and dashboard_liveness.get("summary", {}).get("new_tables_required")
                is False
            ),
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
        }
        cleanup = _restore_or_delete_heartbeat(
            heartbeat_store,
            engine,
            original_heartbeat=original_heartbeat,
            worker_id=WORKER_ID,
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
            "fresh_liveness_summary": fresh_projection.get("summary", {}),
            "stale_liveness_summary": stale_projection.get("summary", {}),
            "dashboard_liveness_summary": dashboard_liveness.get("summary", {}),
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
                _restore_or_delete_heartbeat(
                    heartbeat_store,
                    engine,
                    original_heartbeat=original_heartbeat,
                    worker_id=WORKER_ID,
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
            "slice": "0788",
            "smoke_id": suffix,
            "secret_included": False,
        },
    )


def _db_heartbeat_observations(
    engine: Any,
    *,
    worker_id: str,
    trace_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT service_id,
                           worker_id,
                           worker_type,
                           status,
                           active_job_id,
                           trace_id,
                           metadata::text AS metadata_text
                    FROM service_worker_heartbeats
                    WHERE service_id = :service_id AND worker_id = :worker_id
                    """
                ),
                {"service_id": SERVICE_ID, "worker_id": worker_id},
            ).mappings()
        )
    raw_value_leak_count = 0
    statuses: list[str] = []
    trace_ids: set[str] = set()
    for row in rows:
        statuses.append(str(row.get("status") or ""))
        if row.get("trace_id"):
            trace_ids.add(str(row["trace_id"]))
        if RAW_HEARTBEAT_SECRET in str(row.get("metadata_text") or ""):
            raw_value_leak_count += 1
    return {
        "table_name": "service_worker_heartbeats",
        "row_count": len(rows),
        "backend": _engine_backend(engine),
        "database": _engine_database(engine),
        "statuses": sorted(status for status in statuses if status),
        "trace_id_persisted": trace_id in trace_ids,
        "raw_value_leak_count": raw_value_leak_count,
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
            "restored_original": True,
            "deleted_heartbeat_rows": 0,
        }
    return {
        "restored_original": False,
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


def _issue_candidate_summary(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {"present": False}
    signal = candidate.get("signal") if isinstance(candidate.get("signal"), Mapping) else {}
    return {
        "present": True,
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "signal_status": signal.get("status"),
        "worker_id": signal.get("worker_id"),
        "runbook_ids": list(signal.get("runbook_ids") or []),
        "recommended_operator_actions": list(
            signal.get("recommended_operator_actions") or []
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
            RAW_HEARTBEAT_SECRET,
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
            "ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    cleanup = evidence.get("cleanup", {})
    fresh = evidence.get("fresh_liveness_summary", {})
    stale = evidence.get("stale_liveness_summary", {})
    issue = evidence.get("issue_candidate", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"backend={observations.get('backend')} "
        f"rows={observations.get('row_count')} "
        f"fresh={fresh.get('liveness_status')} "
        f"stale={stale.get('liveness_status')} "
        f"issue={issue.get('signal_status')} "
        f"deleted_heartbeat_rows={cleanup.get('deleted_heartbeat_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
