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
from nex_ag.operator_review_cases import (  # noqa: E402
    OPERATOR_REVIEW_ESCALATION_ACTION_RECORDED_EVENT_TYPE,
    SqlAlchemyOperatorReviewCaseStore,
    SqlAlchemyOperatorReviewEscalationStore,
    build_operator_review_case_record,
    build_operator_review_escalation_record,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_postgres_smoke"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REFERENCE_TIME = "2026-09-12T12:00:00Z"
RAW_ACTION_COMMENT = "AG escalation smoke raw action comment must stay out."


def run_ag_operator_review_escalation_postgres_smoke(
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
    request_id = f"ag-op-escalation-smoke-{suffix}"
    target_id = f"ag-op-escalation-smoke-target-{suffix}"
    case_id = f"ag-op-escalation-smoke-case-{suffix}"
    case_idempotency_key = f"ag-op-escalation-case-idem-{suffix}"
    record_idempotency_key = f"ag-op-escalation-record-idem-{suffix}"
    action_idempotency_key = f"ag-op-escalation-action-idem-{suffix}"
    escalation_id: str | None = None
    action_id: str | None = None
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        escalation_store = SqlAlchemyOperatorReviewEscalationStore(session_factory)
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        case_store.save(
            build_operator_review_case_record(
                _case_payload(suffix=suffix, case_id=case_id, target_id=target_id),
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=case_idempotency_key,
                created_at=REFERENCE_TIME,
            )
        )
        seed_record = build_operator_review_escalation_record(
            _escalation_candidate(
                suffix=suffix,
                case_id=case_id,
                target_id=target_id,
            ),
            {
                "operator_ref": _operator_ref(suffix),
                "action_comment": "Seed S70 PostgreSQL smoke escalation safely.",
                "metadata": {"source": "postgres_smoke", "slice": "0699"},
            },
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=record_idempotency_key,
            created_at=REFERENCE_TIME,
        )
        escalation_id = seed_record["escalation_id"]
        escalation_store.save(seed_record)
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_case_routes(
            app,
            store=case_store,
            escalation_store=escalation_store,
            audit_event_store=event_store,
        )
        register_unified_operation_routes(
            app,
            event_store=event_store,
            operator_review_case_store=case_store,
            operator_review_escalation_store=escalation_store,
        )
        client = TestClient(app)
        query = (
            f"target_service={TARGET_SERVICE}"
            f"&target_kind={TARGET_KIND}"
            f"&target_id={target_id}"
        )
        list_response = client.get(
            f"/admin/v1/operator-review/escalations?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        detail_response = client.get(
            f"/admin/v1/operator-review/escalations/{escalation_id}",
            headers=_admin_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        dashboard_response = client.get(
            f"/admin/v1/operations/dashboard?service_id={TARGET_SERVICE}&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        issue_response = client.get(
            f"/admin/v1/operations/issue-candidates?service_id={TARGET_SERVICE}"
            "&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        action_response = client.post(
            f"/admin/v1/operator-review/escalations/{escalation_id}/actions",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=action_idempotency_key,
            ),
            json={
                "action_type": "ACKNOWLEDGE",
                "operator_ref": _operator_ref(suffix),
                "reason_codes": ["postgres_smoke_acknowledged"],
                "action_comment": "Acknowledge S70 smoke escalation safely.",
                "metadata": {"source": "postgres_smoke_action", "slice": "0699"},
            },
        )
        replay_response = client.post(
            f"/admin/v1/operator-review/escalations/{escalation_id}/actions",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=action_idempotency_key,
            ),
            json={
                "action_type": "ACKNOWLEDGE",
                "operator_ref": _operator_ref(suffix),
                "reason_codes": ["postgres_smoke_acknowledged"],
                "action_comment": "Acknowledge S70 smoke escalation safely.",
                "metadata": {"source": "postgres_smoke_action", "slice": "0699"},
            },
        )
        final_detail_response = client.get(
            f"/admin/v1/operator-review/escalations/{escalation_id}",
            headers=_admin_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        list_body = list_response.json()
        detail_body = detail_response.json()
        dashboard_body = dashboard_response.json()
        issue_body = issue_response.json()
        action_body = action_response.json()
        replay_body = replay_response.json()
        final_detail_body = final_detail_response.json()
        action_id = (
            action_body.get("action", {}).get("action_id")
            if isinstance(action_body, dict)
            else None
        )
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=TRACE_ID,
            case_id=case_id,
            escalation_id=escalation_id,
            action_id=action_id,
            record_idempotency_key=record_idempotency_key,
            action_idempotency_key=action_idempotency_key,
            raw_action_comment=RAW_ACTION_COMMENT,
        )
        issue_candidates = [
            candidate
            for candidate in issue_body.get("issue_candidates", [])
            if isinstance(candidate, dict)
            and candidate.get("rule_id")
            == "operator_review_escalation_action_required.v1"
        ]
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "list_status": list_response.status_code == 200,
            "list_schema": list_body.get("escalation_list_schema_version")
            == "ag_operator_review_escalation_list.v1",
            "list_count": list_body.get("summary", {}).get("count") == 1,
            "detail_status": detail_response.status_code == 200,
            "detail_active": detail_body.get("escalation_status") == "ACTIVE",
            "dashboard_status": dashboard_response.status_code == 200,
            "dashboard_action_required": (
                dashboard_body.get("operator_review_escalations", {})
                .get("summary", {})
                .get("action_required_count")
                == 1
            ),
            "issue_status": issue_response.status_code == 200,
            "issue_candidate_count": len(issue_candidates) == 1,
            "action_status": action_response.status_code == 201,
            "action_schema": action_body.get(
                "escalation_action_mutation_schema_version"
            )
            == "ag_operator_review_escalation_action_mutation.v1",
            "action_acknowledged": action_body.get("escalation", {}).get(
                "escalation_status"
            )
            == "ACKNOWLEDGED",
            "replay_status": replay_response.status_code == 200,
            "replay_idempotent": replay_body.get("idempotency_status") == "REPLAYED",
            "final_detail_acknowledged": final_detail_body.get("escalation_status")
            == "ACKNOWLEDGED",
            "tables_present": observations.get("tables_present")
            == {
                "ag_op_cases": True,
                "ag_op_escalations": True,
                "service_operational_events": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "escalation_row_persisted": observations.get("escalation_count") == 1,
            "acknowledged_row_persisted": observations.get("acknowledged_count") == 1,
            "event_rows_persisted": observations.get("event_count") == 1,
            "event_details_escalation_scoped": observations.get(
                "event_details_escalation_count"
            )
            == 1,
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
            "idempotency_values_redacted": observations.get("idempotency_leak_count")
            == 0,
        }
        cleanup = _cleanup_smoke_rows(engine, case_id, escalation_id, target_id, TRACE_ID)
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
            "trace_id": TRACE_ID,
            "escalation_id": escalation_id,
            "action_id": action_id,
            "target_id": target_id,
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_smoke_rows(engine, case_id, escalation_id, target_id, TRACE_ID)
            engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        forbidden_values=(
            RAW_ACTION_COMMENT,
            case_idempotency_key,
            record_idempotency_key,
            action_idempotency_key,
        ),
    )
    return evidence


def _case_payload(
    *,
    suffix: str,
    case_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "target_ref": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": target_id,
        },
        "operator_ref": _operator_ref(suffix),
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": target_id,
            "source_service": SERVICE_ID,
            "workbench_path": "/admin/v1/operator-review/workbench",
        },
        "assignment_ref": None,
        "reason_codes": ["postgres_smoke", "operator_review_escalation"],
        "metadata": {"source": "postgres_smoke", "slice": "0699"},
    }


def _escalation_candidate(
    *,
    suffix: str,
    case_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "candidate_id": f"{case_id}:overdue:blocked",
        "case_id": case_id,
        "target_ref": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": target_id,
        },
        "assignment_ref": {
            "assignee_type": None,
            "assignee_id": None,
            "tenant_id": "smoke-tenant",
        },
        "escalation_level": "BLOCKED",
        "sla_state": "OVERDUE",
        "escalation_reasons": ["postgres_smoke", "operator_action_required"],
        "runbook_ids": ["ag.operator_review_escalation.postgres_smoke.v1"],
        "recommended_operator_actions": [
            "acknowledge_or_resolve_operator_review_escalation"
        ],
        "metadata": {"suffix": suffix},
    }


def _operator_ref(suffix: str) -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": f"smoke-operator-{suffix}",
        "tenant_id": "smoke-tenant",
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
        audience=SERVICE_ID,
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


def _service_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _db_observations(
    engine: Any,
    *,
    target_id: str,
    trace_id: str,
    case_id: str | None,
    escalation_id: str | None,
    action_id: str | None,
    record_idempotency_key: str,
    action_idempotency_key: str,
    raw_action_comment: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        tables = {
            table: _regclass_matches(
                connection.execute(text(f"SELECT to_regclass('public.{table}')")).scalar(),
                table,
            )
            for table in (
                "ag_op_cases",
                "ag_op_escalations",
                "service_operational_events",
            )
        }
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*) FROM ag_op_cases
                            WHERE case_id = :case_id
                                AND target_id = :target_id
                        ) AS case_count,
                        (
                            SELECT count(*) FROM ag_op_escalations
                            WHERE target_id = :target_id
                        ) AS escalation_count,
                        (
                            SELECT count(*) FROM ag_op_escalations
                            WHERE escalation_id = :escalation_id
                                AND escalation_status = 'ACKNOWLEDGED'
                        ) AS acknowledged_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND event_type = :action_event_type
                        ) AS event_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND details->>'escalation_id' = :escalation_id
                                AND details->>'action_id' = :action_id
                        ) AS event_details_escalation_count,
                        (
                            SELECT count(*) FROM ag_op_escalations
                            WHERE target_id = :target_id
                                AND (
                                    metadata::text LIKE '%' || :raw_action_comment || '%'
                                    OR metadata::text LIKE '%' || :record_idempotency_key || '%'
                                    OR metadata::text LIKE '%' || :action_idempotency_key || '%'
                                    OR idempotency_key_hash = :record_idempotency_key
                                )
                        ) AS row_secret_leak_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND (
                                    details::text LIKE '%' || :raw_action_comment || '%'
                                    OR details::text LIKE '%' || :record_idempotency_key || '%'
                                    OR details::text LIKE '%' || :action_idempotency_key || '%'
                                )
                        ) AS event_secret_leak_count
                    """
                ),
                {
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "case_id": case_id or "",
                    "escalation_id": escalation_id or "",
                    "action_id": action_id or "",
                    "action_event_type": OPERATOR_REVIEW_ESCALATION_ACTION_RECORDED_EVENT_TYPE,
                    "raw_action_comment": raw_action_comment,
                    "record_idempotency_key": record_idempotency_key,
                    "action_idempotency_key": action_idempotency_key,
                },
            )
            .mappings()
            .one()
        )
    row_secret_leak_count = int(row["row_secret_leak_count"])
    event_secret_leak_count = int(row["event_secret_leak_count"])
    return {
        "tables_present": tables,
        "case_count": int(row["case_count"]),
        "escalation_count": int(row["escalation_count"]),
        "acknowledged_count": int(row["acknowledged_count"]),
        "event_count": int(row["event_count"]),
        "event_details_escalation_count": int(row["event_details_escalation_count"]),
        "raw_value_leak_count": row_secret_leak_count + event_secret_leak_count,
        "idempotency_leak_count": row_secret_leak_count + event_secret_leak_count,
    }


def _cleanup_smoke_rows(
    engine: Any,
    case_id: str | None,
    escalation_id: str | None,
    target_id: str | None,
    trace_id: str | None,
) -> dict[str, int]:
    if not case_id and not escalation_id and not target_id and not trace_id:
        return {"cases": 0, "escalations": 0, "events": 0}
    deleted_cases = deleted_escalations = deleted_events = 0
    try:
        with engine.begin() as connection:
            params = {
                "case_id": case_id or "",
                "escalation_id": escalation_id or "",
                "target_id": target_id or "",
                "trace_id": trace_id or "",
            }
            deleted_events = int(
                (
                    connection.execute(
                        text(
                            """
                            DELETE FROM service_operational_events
                            WHERE trace_id = :trace_id
                                OR details->>'escalation_id' = :escalation_id
                                OR details->>'target_id' = :target_id
                            """
                        ),
                        params,
                    )
                ).rowcount
                or 0
            )
            deleted_escalations = int(
                (
                    connection.execute(
                        text(
                            """
                            DELETE FROM ag_op_escalations
                            WHERE escalation_id = :escalation_id
                                OR target_id = :target_id
                            """
                        ),
                        params,
                    )
                ).rowcount
                or 0
            )
            deleted_cases = int(
                (
                    connection.execute(
                        text(
                            """
                            DELETE FROM ag_op_cases
                            WHERE case_id = :case_id
                                OR target_id = :target_id
                            """
                        ),
                        params,
                    )
                ).rowcount
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {"cases": 0, "escalations": 0, "events": 0}
    return {
        "cases": deleted_cases,
        "escalations": deleted_escalations,
        "events": deleted_events,
    }


def _regclass_matches(value: object, table_name: str) -> bool:
    if value is None:
        return False
    return str(value).split(".")[-1] == table_name


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
    forbidden_values: tuple[str, ...],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG escalation smoke evidence contains raw DB URL.")
    for value in forbidden_values:
        if value and value in serialized_evidence:
            raise ValueError("AG escalation smoke evidence contains raw secret.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_escalation_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_escalation_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"cases={evidence['observations']['case_count']} "
            f"escalations={evidence['observations']['escalation_count']} "
            f"events={evidence['observations']['event_count']} "
            f"deleted_cases={cleanup['cases']} "
            f"deleted_escalations={cleanup['escalations']} "
            f"deleted_events={cleanup['events']}"
        )
    return (
        "ag_operator_review_escalation_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review escalation PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_escalation_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
