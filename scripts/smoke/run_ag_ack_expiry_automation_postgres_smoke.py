#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import UTC, datetime
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

from nex_ag.liveness_ack_expiry_automation import (  # noqa: E402
    ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV,
    ACK_EXPIRY_AUTOMATION_ENABLED_ENV,
    ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
    ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
)
from nex_ag.liveness_ack_expiry_automation_cli import (  # noqa: E402
    main as automation_cli_main,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateError,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (  # noqa: E402
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_ack_expiry_automation_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_ACK_EXPIRY_AUTOMATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
ACK_STATE_TABLE = "ag_op_review_ack_state"
EVENT_TABLE = "service_operational_events"
RAW_COMMENT = "private-comment-0828"
RAW_IDEMPOTENCY_KEY = "private-idempotency-0828"


def run_ag_ack_expiry_automation_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
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

    engine: Any | None = None
    store: Any | None = None
    state_id: str | None = None
    run_request_id: str | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        store = SqlAlchemyOperatorReviewLivenessAckStateStore(session_factory)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        evidence, state_id, run_request_id = _execute_smoke(
            engine,
            store,
            event_store,
            migration=migration,
            database_url=database_url,
            environ=env,
        )
        cleanup = _cleanup_owned_rows(
            engine,
            store,
            state_id=state_id,
            request_id=run_request_id,
        )
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_state_deleted"] = (
            cleanup["deleted_state_rows"] == 1
            and cleanup["remaining_state_rows"] == 0
        )
        evidence["checks"]["owned_events_deleted"] = (
            cleanup["deleted_event_rows"] == 2
            and cleanup["remaining_event_rows"] == 0
        )
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        JSONDecodeError,
        OperatorReviewLivenessAckStateError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None and store is not None and not cleanup_done:
            _cleanup_owned_rows(
                engine,
                store,
                state_id=state_id,
                request_id=run_request_id,
            )
        if engine is not None:
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


class JSONDecodeError(ValueError):
    pass


def _execute_smoke(
    engine: Any,
    store: Any,
    event_store: Any,
    *,
    migration: Any,
    database_url: str,
    environ: Mapping[str, str],
) -> tuple[dict[str, Any], str, str]:
    suffix = uuid4().hex[:12]
    state_id = f"ack-automation-smoke-0828-{suffix}"
    plan_request_id = f"ag-ack-automation-plan-0828-{suffix}"
    run_request_id = f"ag-ack-automation-run-0828-{suffix}"
    trace_id = uuid4().hex
    observed_at = datetime.now(UTC).replace(microsecond=0)
    target = _smoke_state(state_id, suffix=suffix)
    store.save(target)
    selected = store.list_expiry_candidates(observed_at=observed_at, limit=1)
    selected_id = str(selected[0].get("ack_state_id")) if selected else None

    runtime_env = dict(environ)
    runtime_env[ACK_EXPIRY_AUTOMATION_ENABLED_ENV] = "1"
    runtime_env[ACK_EXPIRY_AUTOMATION_BATCH_LIMIT_ENV] = "1"
    plan = _invoke_cli(
        [
            "--plan",
            "--database-env",
            DATABASE_ENV,
            "--request-id",
            plan_request_id,
            "--trace-id",
            trace_id,
            "--observed-at",
            _to_zulu(observed_at),
        ],
        environ=runtime_env,
    )
    run = _invoke_cli(
        [
            "--run-once",
            "--confirm-tick",
            "--database-env",
            DATABASE_ENV,
            "--request-id",
            run_request_id,
            "--trace-id",
            trace_id,
            "--observed-at",
            _to_zulu(observed_at),
        ],
        environ=runtime_env,
    )
    persisted = store.get(state_id)
    events = [
        event
        for event_type in (
            ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
            ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
        )
        for event in event_store.list_events(
            service_id=SERVICE_ID,
            event_type=event_type,
            limit=50,
        )
        if event.get("request_id") == run_request_id
    ]
    database = _database_observations(
        engine,
        state_id=state_id,
        request_id=run_request_id,
    )
    tick = run.get("tick_result") if isinstance(run.get("tick_result"), Mapping) else {}
    checks = {
        "migration_ran": migration.service_id == SERVICE_ID,
        "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
        "test_database_selected": _engine_database(engine) == "nex_ag_test",
        "ack_state_table_present": database["ack_state_table_present"],
        "event_table_present": database["event_table_present"],
        "smoke_candidate_selected_first": selected_id == state_id,
        "plan_ready_without_mutation": (
            plan.get("result_status") == "PLANNED"
            and _mapping(plan.get("plan")).get("plan_status") == "READY"
            and _mapping(plan.get("plan")).get("will_mutate") is False
        ),
        "confirmed_cli_tick_executed": (
            run.get("result_status") == "EXECUTED"
            and tick.get("tick_status") == "COMPLETED"
            and tick.get("candidate_count") == 1
            and tick.get("applied_count") == 1
        ),
        "expired_state_persisted": (
            persisted is not None and persisted.get("state_status") == "EXPIRED"
        ),
        "direct_state_select_confirmed": database["state_status"] == "EXPIRED",
        "lifecycle_events_persisted": (
            {event.get("event_type") for event in events}
            == {
                ACK_EXPIRY_AUTOMATION_EVENT_STARTED,
                ACK_EXPIRY_AUTOMATION_EVENT_COMPLETED,
            }
            and database["event_count"] == 2
        ),
    }
    return (
        {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PENDING",
            "failure_code": None,
            "service": SERVICE_ID,
            "profile": PROFILE,
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "database": database,
            "plan": {
                "result_status": plan.get("result_status"),
                "plan_status": _mapping(plan.get("plan")).get("plan_status"),
                "candidate_count": _mapping(plan.get("plan")).get(
                    "candidate_count"
                ),
            },
            "run": {
                "result_status": run.get("result_status"),
                "tick_status": tick.get("tick_status"),
                "candidate_count": tick.get("candidate_count"),
                "applied_count": tick.get("applied_count"),
                "conflict_count": tick.get("conflict_count"),
                "lifecycle_event_count": len(events),
            },
            "checks": checks,
        },
        state_id,
        run_request_id,
    )


def _invoke_cli(
    argv: list[str],
    *,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    stdout = io.StringIO()
    exit_code = automation_cli_main(argv, stdout, environ=environ)
    if exit_code != 0:
        raise JSONDecodeError(f"automation CLI failed with exit code {exit_code}")
    try:
        payload = json.loads(stdout.getvalue())
    except json.JSONDecodeError as exc:
        raise JSONDecodeError("automation CLI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise JSONDecodeError("automation CLI result must be an object")
    return payload


def _smoke_state(state_id: str, *, suffix: str) -> dict[str, Any]:
    timestamp = "1900-01-01T00:00:00Z"
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=state_id,
        acknowledgement_key=f"nex-ag:smoke-0828-{suffix}:stale",
        service_id=SERVICE_ID,
        worker_id=f"ag-automation-smoke-0828-{suffix}",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={
            "operator_type": "service",
            "operator_id": "postgres-smoke-0828",
        },
        reason_codes=["smoke_0828_ack_expiry_automation"],
        comment=RAW_COMMENT,
        idempotency_key=RAW_IDEMPOTENCY_KEY,
        requested_ttl_seconds=300,
        suppressed_until="1900-01-01T00:05:00Z",
        metadata={"source": "postgres_smoke", "slice": "0828"},
        created_at=timestamp,
        updated_at=timestamp,
    )


def _database_observations(
    engine: Any,
    *,
    state_id: str,
    request_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       to_regclass('public.ag_op_review_ack_state')::text
                           AS ack_state_table,
                       to_regclass('public.service_operational_events')::text
                           AS event_table,
                       (SELECT state_status
                        FROM ag_op_review_ack_state
                        WHERE ack_state_id = :state_id) AS state_status,
                       (SELECT count(*)
                        FROM service_operational_events
                        WHERE request_id = :request_id) AS event_count
                """
            ),
            {"state_id": state_id, "request_id": request_id},
        ).mappings().one()
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "ack_state_table_present": _regclass_matches(
            row.get("ack_state_table"), ACK_STATE_TABLE
        ),
        "event_table_present": _regclass_matches(row.get("event_table"), EVENT_TABLE),
        "state_status": row.get("state_status"),
        "event_count": int(row.get("event_count") or 0),
    }


def _cleanup_owned_rows(
    engine: Any,
    store: Any,
    *,
    state_id: str | None,
    request_id: str | None,
) -> dict[str, int]:
    deleted_state_rows = store.delete(state_id) if state_id else 0
    deleted_event_rows = 0
    if request_id:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id},
            )
            deleted_event_rows = int(result.rowcount or 0)
    remaining_state_rows = int(bool(state_id and store.get(state_id) is not None))
    remaining_event_rows = 0
    if request_id:
        with engine.begin() as connection:
            remaining_event_rows = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM service_operational_events "
                        "WHERE request_id = :request_id"
                    ),
                    {"request_id": request_id},
                ).scalar_one()
            )
    return {
        "deleted_state_rows": deleted_state_rows,
        "deleted_event_rows": deleted_event_rows,
        "remaining_state_rows": remaining_state_rows,
        "remaining_event_rows": remaining_event_rows,
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _regclass_matches(value: object, expected: str) -> bool:
    return str(value or "").rsplit(".", 1)[-1] == expected


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    return str(get_backend_name()) if callable(get_backend_name) else "unknown"


def _engine_database(engine: Any) -> str | None:
    database = getattr(getattr(engine, "url", None), "database", None)
    return str(database) if database else None


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = (
        env.get(DATABASE_ENV, ""),
        RAW_COMMENT,
        RAW_IDEMPOTENCY_KEY,
    )
    if any(value and value in serialized_evidence for value in forbidden):
        raise ValueError("smoke evidence contains a sensitive value")


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
        return f"ag_ack_expiry_automation_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_ack_expiry_automation_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    database = _mapping(evidence.get("database"))
    run = _mapping(evidence.get("run"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_ack_expiry_automation_postgres_smoke=pass "
        f"database={database.get('database')} "
        f"backend={database.get('backend')} "
        f"applied={run.get('applied_count')} "
        f"events={run.get('lifecycle_event_count')} "
        f"cleaned={cleanup.get('deleted_state_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_ack_expiry_automation_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
