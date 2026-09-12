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
    OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
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
    issue_mock_service_token,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_case_sla_escalation_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_CASE_SLA_ESCALATION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_CASE_COMMENT = "AG SLA escalation smoke raw case comment must stay out."


def run_ag_operator_review_case_sla_escalation_postgres_smoke(
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
    request_id = f"ag-op-case-sla-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    target_id = f"ag-op-case-sla-smoke-target-{suffix}"
    idempotency_key = f"ag-op-case-sla-create-idem-{suffix}"
    case_id: str | None = None
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
        register_unified_operation_routes(
            app,
            event_store=event_store,
            operator_review_case_store=case_store,
        )
        client = TestClient(app)
        create_response = client.post(
            "/admin/v1/operator-review/cases",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            ),
            json=_case_payload(suffix=suffix, target_id=target_id),
        )
        create_body = create_response.json()
        case_id = (
            create_body.get("case", {}).get("case_id")
            if isinstance(create_body, dict)
            else None
        )
        query = (
            "target_service=nex-ag"
            "&target_kind=operator_review_case_sla_smoke"
            f"&target_id={target_id}"
            "&now=2026-09-12T12:00:00Z"
        )
        policy_response = client.get(
            "/admin/v1/operator-review/cases/sla-policy",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        aging_response = client.get(
            f"/admin/v1/operator-review/cases/aging?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        escalation_response = client.get(
            f"/admin/v1/operator-review/cases/escalations?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        dashboard_response = client.get(
            "/admin/v1/operations/dashboard?service_id=nex-ag&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=trace_id),
        )
        policy_body = policy_response.json()
        aging_body = aging_response.json()
        escalation_body = escalation_response.json()
        dashboard_body = dashboard_response.json()
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=trace_id,
            case_id=case_id,
            raw_case_comment=RAW_CASE_COMMENT,
        )
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "case_create_status": create_response.status_code == 201,
            "policy_status": policy_response.status_code == 200,
            "policy_schema": policy_body.get("case_sla_policy_schema_version")
            == "ag_operator_review_case_sla_policy.v1",
            "aging_status": aging_response.status_code == 200,
            "aging_schema": aging_body.get("case_aging_schema_version")
            == "ag_operator_review_case_aging.v1",
            "aging_case_count": aging_body.get("summary", {}).get("case_count") == 1,
            "aging_overdue_count": aging_body.get("summary", {}).get(
                "overdue_case_count"
            )
            == 1,
            "escalation_status": escalation_response.status_code == 200,
            "escalation_schema": escalation_body.get(
                "case_escalations_schema_version"
            )
            == "ag_operator_review_case_escalations.v1",
            "escalation_candidate_count": escalation_body.get("summary", {}).get(
                "candidate_count"
            )
            == 1,
            "dashboard_status": dashboard_response.status_code == 200,
            "dashboard_escalation_count": (
                dashboard_body.get("operator_review_cases", {})
                .get("escalations", {})
                .get("summary", {})
                .get("candidate_count")
                == 1
            ),
            "tables_present": observations.get("tables_present")
            == {
                "ag_op_cases": True,
                "service_operational_events": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "event_rows_persisted": observations.get("event_count") == 1,
            "event_details_case_scoped": observations.get("event_details_case_count")
            == 1,
            "event_details_redacted": observations.get("raw_case_comment_leak_count")
            == 0,
        }
        cleanup = _cleanup_smoke_rows(engine, case_id, target_id, trace_id)
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
            "target_id": target_id,
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
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
        forbidden_values=(RAW_CASE_COMMENT, idempotency_key),
    )
    return evidence


def _case_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_case_sla_smoke",
            "target_id": target_id,
        },
        "operator_ref": _operator_ref(suffix),
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": target_id,
            "source_service": "nex-ag",
            "workbench_path": "/admin/v1/operator-review/workbench",
        },
        "assignment_ref": None,
        "reason_codes": ["postgres_smoke", "operator_review_case_sla_escalation"],
        "metadata": {
            "source": "postgres_smoke",
            "slice": "0689",
            "raw_case_comment_sha256_only": True,
        },
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


def _service_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
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
    raw_case_comment: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        tables = {
            table: _regclass_matches(
                connection.execute(text(f"SELECT to_regclass('public.{table}')")).scalar(),
                table,
            )
            for table in ("ag_op_cases", "service_operational_events")
        }
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*) FROM ag_op_cases
                            WHERE target_id = :target_id
                        ) AS case_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND event_type = :case_event_type
                        ) AS event_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND details->>'case_id' = :case_id
                        ) AS event_details_case_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND details::text LIKE '%' || :raw_case_comment || '%'
                        ) AS raw_case_comment_leak_count
                    """
                ),
                {
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "case_id": case_id or "",
                    "case_event_type": OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
                    "raw_case_comment": raw_case_comment,
                },
            )
            .mappings()
            .one()
        )
    return {
        "tables_present": tables,
        "case_count": int(row["case_count"]),
        "event_count": int(row["event_count"]),
        "event_details_case_count": int(row["event_details_case_count"]),
        "raw_case_comment_leak_count": int(row["raw_case_comment_leak_count"]),
    }


def _cleanup_smoke_rows(
    engine: Any,
    case_id: str | None,
    target_id: str | None,
    trace_id: str | None,
) -> dict[str, int]:
    if not case_id and not target_id and not trace_id:
        return {"cases": 0, "events": 0}
    deleted_cases = deleted_events = 0
    try:
        with engine.begin() as connection:
            params = {
                "case_id": case_id or "",
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
                                OR details->>'case_id' = :case_id
                                OR details->>'target_id' = :target_id
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
                            WHERE case_id = :case_id OR target_id = :target_id
                            """
                        ),
                        params,
                    )
                ).rowcount
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {"cases": 0, "events": 0}
    return {"cases": deleted_cases, "events": deleted_events}


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
        raise ValueError("AG case SLA/escalation smoke evidence contains raw DB URL.")
    for value in forbidden_values:
        if value and value in serialized_evidence:
            raise ValueError("AG case SLA/escalation smoke evidence contains raw secret.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_case_sla_escalation_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_case_sla_escalation_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"cases={evidence['observations']['case_count']} "
            f"events={evidence['observations']['event_count']} "
            f"deleted_cases={cleanup['cases']} "
            f"deleted_events={cleanup['events']}"
        )
    return (
        "ag_operator_review_case_sla_escalation_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review case SLA/escalation PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_case_sla_escalation_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
