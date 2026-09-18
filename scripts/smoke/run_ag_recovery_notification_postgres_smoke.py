#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateError,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    acknowledgement_key_for_liveness,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (  # noqa: E402
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_recovery_notification_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_RECOVERY_NOTIFICATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
ACK_STATE_TABLE = "ag_op_review_ack_state"
DISPATCH_TABLE = "ag_op_esc_dispatches"
EVENT_TABLE = "service_operational_events"
PREVIEW_PATH = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-preview"
)
RAW_COMMENT = "private-recovery-comment-0838"
RAW_IDEMPOTENCY_KEY = "private-recovery-idempotency-0838"


def run_ag_recovery_notification_postgres_smoke(
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
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        store = SqlAlchemyOperatorReviewLivenessAckStateStore(
            build_session_factory(engine)
        )
        state_id = f"recovery-notification-smoke-0838-{uuid4().hex[:12]}"
        evidence = _execute_smoke(
            engine,
            store,
            state_id=state_id,
            migration=migration,
            database_url=database_url,
        )
        cleanup = _cleanup_owned_state(store, state_id=state_id)
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_state_deleted"] = (
            cleanup["deleted_state_rows"] == 1
            and cleanup["remaining_state_rows"] == 0
        )
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        OperatorReviewLivenessAckStateError,
        SQLAlchemyError,
        RuntimeError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if store is not None and state_id is not None and not cleanup_done:
            _cleanup_owned_state(store, state_id=state_id)
        if engine is not None:
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_smoke(
    engine: Any,
    store: Any,
    *,
    state_id: str,
    migration: Any,
    database_url: str,
) -> dict[str, Any]:
    suffix = state_id.rsplit("-", 1)[-1]
    worker_id = f"ag-recovery-notification-smoke-0838-{suffix}"
    trace_id = uuid4().hex
    acknowledgement_key = acknowledgement_key_for_liveness(
        service_id=SERVICE_ID,
        worker_id=worker_id,
        liveness_status="MISSING",
    )
    state = _smoke_state(
        state_id=state_id,
        worker_id=worker_id,
        acknowledgement_key=acknowledgement_key,
    )
    store.save(state)
    before = _database_observation(engine, state_id=state_id, trace_id=trace_id)
    api = _invoke_preview(
        store,
        worker_id=worker_id,
        trace_id=trace_id,
    )
    after = _database_observation(engine, state_id=state_id, trace_id=trace_id)
    payload = api["payload"]
    decision = _mapping(payload.get("decision"))
    delivery = _mapping(payload.get("delivery"))
    checks = {
        "migration_ran": migration.service_id == SERVICE_ID,
        "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
        "test_database_selected": _engine_database(engine) == "nex_ag_test",
        "ack_state_table_present": before["ack_state_table_present"],
        "dispatch_table_present": before["dispatch_table_present"],
        "event_table_present": before["event_table_present"],
        "suppressed_state_persisted": (
            before["row_count"] == 1
            and before["state_status"] == "SUPPRESSED"
        ),
        "protected_route_rejects_missing_auth": api["unauthorized_status"] == 401,
        "protected_route_reads_persisted_suppression": (
            api["status_code"] == 200
            and payload.get("plan_status") == "SUPPRESSED"
            and decision.get("effective_ack_state") == "SUPPRESSED"
            and decision.get("reason_codes") == ["active_suppression"]
        ),
        "provider_invocation_not_performed": (
            delivery.get("performed") is False
            and delivery.get("provider_invocation_performed") is False
        ),
        "state_row_unchanged_by_preview": before["row_fingerprint"]
        == after["row_fingerprint"],
        "no_dispatch_or_event_persisted": (
            after["dispatch_count"] == 0 and after["event_count"] == 0
        ),
    }
    return {
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
        "database": after,
        "route": {
            "path": PREVIEW_PATH,
            "unauthorized_status": api["unauthorized_status"],
            "authorized_status": api["status_code"],
            "plan_status": payload.get("plan_status"),
            "decision_status": decision.get("decision_status"),
            "effective_ack_state": decision.get("effective_ack_state"),
            "provider_invocation_performed": delivery.get(
                "provider_invocation_performed"
            ),
        },
        "checks": checks,
    }


def _smoke_state(
    *,
    state_id: str,
    worker_id: str,
    acknowledgement_key: str,
) -> dict[str, Any]:
    timestamp = "2026-09-18T00:00:00Z"
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=state_id,
        acknowledgement_key=acknowledgement_key,
        service_id=SERVICE_ID,
        worker_id=worker_id,
        worker_type="operator_review_dispatch_daemon",
        liveness_status="MISSING",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={
            "operator_type": "service",
            "operator_id": "postgres-smoke-0838",
        },
        reason_codes=["smoke_0838_recovery_notification"],
        comment=RAW_COMMENT,
        idempotency_key=RAW_IDEMPOTENCY_KEY,
        requested_ttl_seconds=86400,
        suppressed_until="2999-01-01T00:00:00Z",
        metadata={"source": "postgres_smoke", "slice": "0838"},
        created_at=timestamp,
        updated_at=timestamp,
    )


def _invoke_preview(
    state_store: Any,
    *,
    worker_id: str,
    trace_id: str,
) -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(
        app,
        worker_heartbeat_stores={SERVICE_ID: InMemoryWorkerHeartbeatStore()},
        operator_review_liveness_ack_state_store=state_store,
    )
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    with TestClient(app) as client:
        unauthorized = client.get(PREVIEW_PATH, params={"worker_id": worker_id})
        response = client.get(
            PREVIEW_PATH,
            params={"worker_id": worker_id},
            headers={
                "Authorization": f"Bearer {issued.access_token}",
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
            },
        )
    if response.status_code != 200:
        raise ValueError(
            f"recovery notification preview returned HTTP {response.status_code}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("recovery notification preview must return an object")
    return {
        "unauthorized_status": unauthorized.status_code,
        "status_code": response.status_code,
        "payload": payload,
    }


def _database_observation(
    engine: Any,
    *,
    state_id: str,
    trace_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       to_regclass('public.ag_op_review_ack_state')::text
                           AS ack_state_table,
                       to_regclass('public.ag_op_esc_dispatches')::text
                           AS dispatch_table,
                       to_regclass('public.service_operational_events')::text
                           AS event_table,
                       (SELECT count(*) FROM ag_op_review_ack_state
                        WHERE ack_state_id = :state_id) AS row_count,
                       (SELECT state_status FROM ag_op_review_ack_state
                        WHERE ack_state_id = :state_id) AS state_status,
                       (SELECT md5(row_to_json(state_row)::text)
                        FROM ag_op_review_ack_state AS state_row
                        WHERE ack_state_id = :state_id) AS row_fingerprint,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE trace_id = :trace_id) AS dispatch_count,
                       (SELECT count(*) FROM service_operational_events
                        WHERE trace_id = :trace_id) AS event_count
                """
            ),
            {"state_id": state_id, "trace_id": trace_id},
        ).mappings().one()
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "ack_state_table_present": _regclass_matches(
            row.get("ack_state_table"), ACK_STATE_TABLE
        ),
        "dispatch_table_present": _regclass_matches(
            row.get("dispatch_table"), DISPATCH_TABLE
        ),
        "event_table_present": _regclass_matches(row.get("event_table"), EVENT_TABLE),
        "row_count": int(row.get("row_count") or 0),
        "state_status": row.get("state_status"),
        "row_fingerprint": row.get("row_fingerprint"),
        "dispatch_count": int(row.get("dispatch_count") or 0),
        "event_count": int(row.get("event_count") or 0),
    }


def _cleanup_owned_state(store: Any, *, state_id: str) -> dict[str, int]:
    deleted = store.delete(state_id)
    remaining = int(store.get(state_id) is not None)
    return {
        "deleted_state_rows": deleted,
        "remaining_state_rows": remaining,
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


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = (env.get(DATABASE_ENV, ""), RAW_COMMENT, RAW_IDEMPOTENCY_KEY)
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
        return f"ag_recovery_notification_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_recovery_notification_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    database = _mapping(evidence.get("database"))
    route = _mapping(evidence.get("route"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_recovery_notification_postgres_smoke=pass "
        f"database={database.get('database')} "
        f"backend={database.get('backend')} "
        f"plan={route.get('plan_status')} "
        f"dispatches={database.get('dispatch_count')} "
        f"events={database.get('event_count')} "
        f"cleaned={cleanup.get('deleted_state_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_recovery_notification_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
