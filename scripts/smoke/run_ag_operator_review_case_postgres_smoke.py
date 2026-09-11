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
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_case_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_CASE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_ACTION_COMMENT = "AG case smoke raw action comment must stay out of evidence."


def run_ag_operator_review_case_postgres_smoke(
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
    request_id = f"ag-op-case-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    target_id = f"ag-op-case-smoke-target-{suffix}"
    create_idempotency_key = f"ag-op-case-create-idem-{suffix}"
    action_idempotency_key = f"ag-op-case-action-idem-{suffix}"
    case_id: str | None = None
    action_id: str | None = None
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        event_store = InMemoryOperationalEventStore()
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
        replay_response = client.post(
            "/admin/v1/operator-review/cases",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=create_idempotency_key,
            ),
            json=_case_payload(suffix=suffix, target_id=target_id),
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
        detail_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        query = (
            "target_service=nex-ag"
            "&target_kind=operator_review_case_smoke"
            f"&target_id={target_id}"
            "&case_status=ASSIGNED"
            "&case_priority=URGENT"
        )
        list_response = client.get(
            f"/admin/v1/operator-review/cases?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        rollup_response = client.get(
            f"/admin/v1/operator-review/cases/rollups?{query}",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        dashboard_response = client.get(
            "/admin/v1/operations/dashboard?service_id=nex-ag&recent_limit=10",
            headers=_service_headers(request_id=request_id, trace_id=trace_id),
        )
        observations = _db_observations(engine, target_id)
        detail_body = detail_response.json()
        list_body = list_response.json()
        rollup_body = rollup_response.json()
        dashboard_body = dashboard_response.json()
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "case_create_status": create_response.status_code == 201,
            "case_create_replay_status": replay_response.status_code == 200,
            "case_action_status": action_response.status_code == 201,
            "case_detail_status": detail_response.status_code == 200,
            "case_detail_assigned": detail_body.get("case_status") == "ASSIGNED",
            "case_list_status": list_response.status_code == 200,
            "case_list_filtered_count": list_body.get("summary", {}).get("count") == 1,
            "case_rollup_status": rollup_response.status_code == 200,
            "case_rollup_attention": _first_attention_status(rollup_body) == "BLOCKED",
            "dashboard_status": dashboard_response.status_code == 200,
            "dashboard_case_visible": _contains_attention_target(
                dashboard_body.get("operator_review_cases", {}),
                target_id,
            ),
            "table_present": observations.get("table_present") is True,
            "table_rows": observations.get("case_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns") == {
                "operator_ref": "jsonb",
                "source_ref": "jsonb",
                "assignment_ref": "jsonb",
                "reason_codes": "jsonb",
                "metadata": "jsonb",
            },
            "assigned_case_persisted": observations.get("assigned_case_count") == 1,
            "urgent_case_persisted": observations.get("urgent_case_count") == 1,
            "last_action_persisted": observations.get("last_action_assign_count") == 1,
            "assignee_persisted": observations.get("assignee_count") == 1,
            "audit_events_recorded": event_store.summary()["total"] == 2,
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
            "cleanup": _cleanup_case_rows(engine, case_id, target_id),
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_case_rows(engine, case_id, target_id)
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
            "target_kind": "operator_review_case_smoke",
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
        },
        "reason_codes": ["postgres_smoke", "operator_review_case"],
        "metadata": {"source": "postgres_smoke"},
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
        "reason_codes": ["operator_review_case_postgres_smoke"],
        "action_comment": RAW_ACTION_COMMENT,
        "metadata": {"source": "postgres_smoke"},
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


def _db_observations(engine: Any, target_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        table = connection.execute(
            text("SELECT to_regclass('public.ag_op_cases')")
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
                            SELECT pg_typeof(operator_ref)::text
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS operator_ref_type,
                        (
                            SELECT pg_typeof(source_ref)::text
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS source_ref_type,
                        (
                            SELECT pg_typeof(assignment_ref)::text
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS assignment_ref_type,
                        (
                            SELECT pg_typeof(reason_codes)::text
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS reason_codes_type,
                        (
                            SELECT pg_typeof(metadata)::text
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                            LIMIT 1
                        ) AS metadata_type,
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                                AND case_status = 'ASSIGNED'
                        ) AS assigned_case_count,
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                                AND case_priority = 'URGENT'
                        ) AS urgent_case_count,
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                                AND metadata->>'last_action_type' = 'ASSIGN'
                        ) AS last_action_assign_count,
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE target_id = :target_id
                                AND assignee_id IS NOT NULL
                        ) AS assignee_count
                    """
                ),
                {"target_id": target_id},
            )
            .mappings()
            .one()
        )
    return {
        "table_present": _regclass_matches(table, "ag_op_cases"),
        "case_count": int(row["case_count"]),
        "jsonb_columns": {
            "operator_ref": row["operator_ref_type"],
            "source_ref": row["source_ref_type"],
            "assignment_ref": row["assignment_ref_type"],
            "reason_codes": row["reason_codes_type"],
            "metadata": row["metadata_type"],
        },
        "assigned_case_count": int(row["assigned_case_count"]),
        "urgent_case_count": int(row["urgent_case_count"]),
        "last_action_assign_count": int(row["last_action_assign_count"]),
        "assignee_count": int(row["assignee_count"]),
    }


def _first_attention_status(rollup_body: Mapping[str, Any]) -> str | None:
    attention = rollup_body.get("attention")
    if not isinstance(attention, Mapping):
        return None
    items = attention.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    return first.get("attention_status") if isinstance(first, Mapping) else None


def _contains_attention_target(section: object, target_id: str) -> bool:
    if not isinstance(section, Mapping):
        return False
    attention = section.get("attention")
    if isinstance(attention, list):
        items = attention
    elif isinstance(attention, Mapping):
        items = attention.get("items")
    else:
        return False
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, Mapping):
            continue
        target_ref = item.get("target_ref")
        if isinstance(target_ref, Mapping) and target_ref.get("target_id") == target_id:
            return True
    return False


def _regclass_matches(value: object, table_name: str) -> bool:
    if value is None:
        return False
    return str(value).split(".")[-1] == table_name


def _cleanup_case_rows(
    engine: Any,
    case_id: str | None,
    target_id: str | None,
) -> dict[str, int]:
    if not case_id and not target_id:
        return {"cases": 0}
    try:
        with engine.begin() as connection:
            if case_id and target_id:
                result = connection.execute(
                    text(
                        """
                        DELETE FROM ag_op_cases
                        WHERE case_id = :case_id OR target_id = :target_id
                        """
                    ),
                    {"case_id": case_id, "target_id": target_id},
                )
            elif case_id:
                result = connection.execute(
                    text("DELETE FROM ag_op_cases WHERE case_id = :case_id"),
                    {"case_id": case_id},
                )
            else:
                result = connection.execute(
                    text("DELETE FROM ag_op_cases WHERE target_id = :target_id"),
                    {"target_id": target_id},
                )
    except (AttributeError, SQLAlchemyError):
        return {"cases": 0}
    return {"cases": int(result.rowcount or 0)}


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
        raise ValueError("AG case smoke evidence contains raw DB URL.")
    if raw_action_comment and raw_action_comment in serialized_evidence:
        raise ValueError("AG case smoke evidence contains raw action comment.")
    for idempotency_key in idempotency_keys:
        if idempotency_key and idempotency_key in serialized_evidence:
            raise ValueError("AG case smoke evidence contains raw idempotency key.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_operator_review_case_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_case_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"cases={evidence['observations']['case_count']} "
            f"assigned={evidence['observations']['assigned_case_count']} "
            f"deleted_cases={cleanup['cases']}"
        )
    return (
        "ag_operator_review_case_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG operator review case/action PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_case_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
