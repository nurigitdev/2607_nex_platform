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

from nex_ag.operator_review_cases import (  # noqa: E402
    OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_case_workbench_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_CASE_WORKBENCH_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_ACTION_COMMENT = (
    "AG case workbench smoke raw action comment must stay out of evidence."
)


def run_ag_operator_review_case_workbench_postgres_smoke(
    environ: dict[str, str] | None = None,
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
    request_id = f"ag-op-case-workbench-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    target_id = f"ag-op-case-workbench-smoke-target-{suffix}"
    create_idempotency_key = f"ag-op-case-workbench-create-idem-{suffix}"
    action_idempotency_key = f"ag-op-case-workbench-action-idem-{suffix}"
    case_id: str | None = None
    action_id: str | None = None
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_case_routes(
            app,
            store=case_store,
            audit_event_store=event_store,
        )
        client = TestClient(app)
        create_response = client.post(
            "/admin/v1/operator-review/cases",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=create_idempotency_key,
            ),
            json=_case_payload(suffix=suffix, target_id=target_id),
        )
        create_body = create_response.json()
        case_id = (
            create_body.get("case", {}).get("case_id")
            if isinstance(create_body, dict)
            else None
        )
        action_response = client.post(
            f"/admin/v1/operator-review/cases/{case_id}/actions",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=action_idempotency_key,
            ),
            json=_action_payload(suffix=suffix),
        )
        action_body = action_response.json()
        action_id = (
            action_body.get("action", {}).get("action_id")
            if isinstance(action_body, dict)
            else None
        )
        query = (
            "target_service=nex-ag"
            "&target_kind=operator_review_case_workbench_smoke"
            f"&target_id={target_id}"
            "&latest_action_type=ASSIGN"
            "&attention_status=BLOCKED"
            "&sort_by=attention"
            "&sort_direction=asc"
        )
        queue_response = client.get(
            f"/admin/v1/operator-review/cases/queue?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        detail_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        timeline_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}/timeline?limit=10",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=trace_id,
            case_id=case_id,
            raw_action_comment=RAW_ACTION_COMMENT,
        )
        queue_body = queue_response.json()
        detail_body = detail_response.json()
        timeline_body = timeline_response.json()
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "case_create_status": create_response.status_code == 201,
            "case_action_status": action_response.status_code == 201,
            "queue_status": queue_response.status_code == 200,
            "queue_filtered_count": queue_body.get("summary", {}).get("case_count")
            == 1,
            "queue_latest_action_assign": _queue_latest_action_type(queue_body)
            == "ASSIGN",
            "queue_redaction_flags": _redaction_flags_are_false(
                queue_body.get("redaction", {}),
                (
                    "raw_case_comment_included",
                    "raw_action_comment_included",
                    "raw_resolution_comment_included",
                    "idempotency_keys_included",
                ),
            ),
            "detail_status": detail_response.status_code == 200,
            "detail_case_matches": detail_body.get("case", {}).get("case_id")
            == case_id,
            "detail_timeline_link": (
                detail_body.get("timeline", {}).get("timeline_path")
                == f"/admin/v1/operator-review/cases/{case_id}/timeline"
            ),
            "detail_action_controls": (
                detail_body.get("action_controls", {}).get("requires_idempotency_key")
                is True
            ),
            "detail_redaction_flags": _redaction_flags_are_false(
                detail_body.get("redaction", {}),
                (
                    "raw_case_comment_included",
                    "raw_action_comment_included",
                    "raw_resolution_comment_included",
                    "idempotency_keys_included",
                    "metadata_payload_included",
                ),
            ),
            "timeline_status": timeline_response.status_code == 200,
            "timeline_source_ready": timeline_body.get("summary", {}).get(
                "timeline_status"
            )
            == "READY",
            "timeline_case_event": timeline_body.get("summary", {}).get(
                "case_recorded_event_count"
            )
            == 1,
            "timeline_action_event": timeline_body.get("summary", {}).get(
                "case_action_event_count"
            )
            == 1,
            "timeline_redaction_flags": _redaction_flags_are_false(
                timeline_body.get("redaction", {}),
                (
                    "raw_case_comment_included",
                    "raw_action_comment_included",
                    "raw_resolution_comment_included",
                    "idempotency_keys_included",
                    "storage_paths_included",
                ),
            ),
            "tables_present": observations.get("tables_present") == {
                "ag_op_cases": True,
                "service_operational_events": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "event_rows_persisted": observations.get("event_count") == 2,
            "event_types_persisted": observations.get("event_type_counts")
            == {
                OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE: 1,
                OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE: 1,
            },
            "event_details_jsonb": observations.get("event_details_type") == "jsonb",
            "event_details_case_scoped": observations.get("event_details_case_count")
            == 2,
            "event_details_redacted": observations.get("raw_action_comment_leak_count")
            == 0,
        }
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
            "case_id": case_id,
            "action_id": action_id,
            "target_id": target_id,
            "observations": observations,
            "checks": checks,
            "cleanup": _cleanup_smoke_rows(engine, case_id, target_id, trace_id),
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_smoke_rows(engine, case_id, target_id, trace_id)
            engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        raw_action_comment=RAW_ACTION_COMMENT,
        idempotency_keys=(create_idempotency_key, action_idempotency_key),
    )
    return evidence


def _case_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_case_workbench_smoke",
            "target_id": target_id,
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": target_id,
            "source_service": "nex-ag",
            "workbench_path": "/admin/v1/operator-review/workbench",
        },
        "reason_codes": ["postgres_smoke", "operator_review_case_workbench"],
        "metadata": {"source": "postgres_smoke", "slice": "0658"},
    }


def _action_payload(*, suffix: str) -> dict[str, Any]:
    return {
        "action_type": "ASSIGN",
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "assignment_ref": {
            "assignee_type": "user",
            "assignee_id": f"smoke-assignee-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "reason_codes": ["operator_review_case_workbench_postgres_smoke"],
        "action_comment": RAW_ACTION_COMMENT,
        "metadata": {"source": "postgres_smoke", "slice": "0658"},
    }


def _admin_headers(
    *,
    request_id: str,
    trace_id: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="smoke-tenant",
        user_id="smoke-admin",
        audience="nex-ag",
        roles=["admin"],
    )
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _db_observations(
    engine: Any,
    *,
    target_id: str,
    trace_id: str,
    case_id: str | None,
    raw_action_comment: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        case_table = connection.execute(
            text("SELECT to_regclass('public.ag_op_cases')")
        ).scalar()
        event_table = connection.execute(
            text("SELECT to_regclass('public.service_operational_events')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                        ) AS case_count,
                        (
                            SELECT count(*)
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND event_type IN (
                                    :case_event_type,
                                    :action_event_type
                                )
                        ) AS event_count,
                        (
                            SELECT count(*)
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND event_type = :case_event_type
                        ) AS case_event_count,
                        (
                            SELECT count(*)
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND event_type = :action_event_type
                        ) AS action_event_count,
                        (
                            SELECT pg_typeof(details)::text
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                            LIMIT 1
                        ) AS event_details_type,
                        (
                            SELECT count(*)
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND details->>'case_id' = :case_id
                        ) AS event_details_case_count,
                        (
                            SELECT count(*)
                            FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND details::text LIKE '%' || :raw_action_comment || '%'
                        ) AS raw_action_comment_leak_count
                    """
                ),
                {
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "case_id": case_id or "",
                    "case_event_type": OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
                    "action_event_type": OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
                    "raw_action_comment": raw_action_comment,
                },
            )
            .mappings()
            .one()
        )
    return {
        "tables_present": {
            "ag_op_cases": _regclass_matches(case_table, "ag_op_cases"),
            "service_operational_events": _regclass_matches(
                event_table,
                "service_operational_events",
            ),
        },
        "case_count": int(row["case_count"]),
        "event_count": int(row["event_count"]),
        "event_type_counts": {
            OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE: int(row["case_event_count"]),
            OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE: int(
                row["action_event_count"]
            ),
        },
        "event_details_type": row["event_details_type"],
        "event_details_case_count": int(row["event_details_case_count"]),
        "raw_action_comment_leak_count": int(row["raw_action_comment_leak_count"]),
    }


def _queue_latest_action_type(queue_body: Mapping[str, Any]) -> str | None:
    items = queue_body.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, Mapping):
        return None
    latest_action = first.get("latest_action")
    if not isinstance(latest_action, Mapping):
        return None
    return latest_action.get("action_type")


def _redaction_flags_are_false(
    redaction: object,
    keys: tuple[str, ...],
) -> bool:
    if not isinstance(redaction, Mapping):
        return False
    return all(redaction.get(key) is False for key in keys)


def _regclass_matches(value: object, table_name: str) -> bool:
    if value is None:
        return False
    return str(value).split(".")[-1] == table_name


def _cleanup_smoke_rows(
    engine: Any,
    case_id: str | None,
    target_id: str | None,
    trace_id: str | None,
) -> dict[str, int]:
    if not case_id and not target_id and not trace_id:
        return {"cases": 0, "events": 0}
    deleted_cases = 0
    deleted_events = 0
    try:
        with engine.begin() as connection:
            event_where: list[str] = []
            event_params: dict[str, str] = {}
            if case_id:
                event_where.append("details->>'case_id' = :case_id")
                event_params["case_id"] = case_id
            if target_id:
                event_where.append("details->>'target_id' = :target_id")
                event_params["target_id"] = target_id
            if event_where:
                result = connection.execute(
                    text(
                        "DELETE FROM service_operational_events "
                        f"WHERE {' OR '.join(event_where)}"
                    ),
                    event_params,
                )
                deleted_events = int(result.rowcount or 0)
            case_where: list[str] = []
            case_params: dict[str, str] = {}
            if case_id:
                case_where.append("case_id = :case_id")
                case_params["case_id"] = case_id
            if target_id:
                case_where.append("target_id = :target_id")
                case_params["target_id"] = target_id
            if case_where:
                result = connection.execute(
                    text(
                        "DELETE FROM ag_op_cases "
                        f"WHERE {' OR '.join(case_where)}"
                    ),
                    case_params,
                )
                deleted_cases = int(result.rowcount or 0)
    except (AttributeError, SQLAlchemyError):
        return {"cases": 0, "events": 0}
    return {"cases": deleted_cases, "events": deleted_events}


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
    *,
    raw_action_comment: str,
    idempotency_keys: tuple[str, str],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG case workbench smoke evidence contains raw DB URL.")
    if raw_action_comment and raw_action_comment in serialized_evidence:
        raise ValueError(
            "AG case workbench smoke evidence contains raw action comment."
        )
    for idempotency_key in idempotency_keys:
        if idempotency_key and idempotency_key in serialized_evidence:
            raise ValueError(
                "AG case workbench smoke evidence contains raw idempotency key."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_case_workbench_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_case_workbench_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"cases={evidence['observations']['case_count']} "
            f"events={evidence['observations']['event_count']} "
            f"deleted_cases={cleanup['cases']} "
            f"deleted_events={cleanup['events']}"
        )
    return (
        "ag_operator_review_case_workbench_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review case workbench PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_case_workbench_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
