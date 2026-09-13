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
    OperatorReviewCaseService,
    SqlAlchemyOperatorReviewCaseStore,
    SqlAlchemyOperatorReviewEscalationDispatchStore,
    SqlAlchemyOperatorReviewEscalationStore,
    build_operator_review_case_record,
    build_operator_review_escalation_record,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_RESULT_STORAGE,
    run_dispatch_execution_worker_once,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_execution_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_EXECUTION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_dispatch_execution_postgres_smoke"
TRACE_ID = "60c1719e2d44424ab30302fc0719a719"
REFERENCE_TIME = "2026-09-13T12:19:00Z"
RAW_PROVIDER_PAYLOAD = "S72 raw provider payload must not persist."
RAW_PROVIDER_ERROR = "S72 raw provider error must not persist."
RAW_ACTION_COMMENT = "S72 raw dispatch execution action comment must not persist."


def run_ag_operator_review_escalation_dispatch_execution_postgres_smoke(
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
    request_id = f"ag-dispatch-exec-smoke-{suffix}"
    target_id = f"ag-dispatch-exec-smoke-target-{suffix}"
    case_id = f"ag-dispatch-exec-smoke-case-{suffix}"
    case_idempotency_key = f"ag-dispatch-exec-case-idem-{suffix}"
    escalation_idempotency_key = f"ag-dispatch-exec-escalation-idem-{suffix}"
    dispatch_idempotency_key = f"ag-dispatch-exec-create-idem-{suffix}"
    worker_id = f"ag-dispatch-exec-worker-{suffix}"
    escalation_id: str | None = None
    dispatch_id: str | None = None
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        escalation_store = SqlAlchemyOperatorReviewEscalationStore(session_factory)
        dispatch_store = SqlAlchemyOperatorReviewEscalationDispatchStore(
            session_factory
        )
        event_store = SqlAlchemyOperationalEventStore(session_factory)
        service = OperatorReviewCaseService(
            case_store,
            escalation_store=escalation_store,
            dispatch_store=dispatch_store,
        )

        case_store.save(
            build_operator_review_case_record(
                _case_payload(suffix=suffix, case_id=case_id, target_id=target_id),
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=case_idempotency_key,
                created_at=REFERENCE_TIME,
            )
        )
        escalation = build_operator_review_escalation_record(
            _escalation_candidate(
                suffix=suffix,
                case_id=case_id,
                target_id=target_id,
            ),
            {
                "operator_ref": _operator_ref(suffix),
                "action_comment": "Seed S72 PostgreSQL execution smoke safely.",
                "metadata": {"source": "postgres_smoke", "slice": "0719"},
            },
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=escalation_idempotency_key,
            created_at=REFERENCE_TIME,
        )
        escalation_id = escalation["escalation_id"]
        escalation_store.save(escalation)

        create_plan = service.create_escalation_dispatch(
            escalation_id,
            _dispatch_payload(suffix=suffix),
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=dispatch_idempotency_key,
        )
        dispatch_id = _created_dispatch_id(create_plan)
        worker_run = run_dispatch_execution_worker_once(
            service,
            request_id=request_id,
            trace_id=TRACE_ID,
            worker_id=worker_id,
            batch_limit=1,
            confirm_run=True,
            executed_at=REFERENCE_TIME,
        )
        final_dispatch = dispatch_store.get(dispatch_id) or {}

        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_unified_operation_routes(
            app,
            event_store=event_store,
            operator_review_case_store=case_store,
            operator_review_escalation_store=escalation_store,
            operator_review_escalation_dispatch_store=dispatch_store,
        )
        client = TestClient(app)
        dashboard_response = client.get(
            "/admin/v1/operations/dashboard"
            f"?service_id={TARGET_SERVICE}&recent_limit=5",
            headers=_service_headers(request_id=request_id, trace_id=TRACE_ID),
        )
        dashboard_body = dashboard_response.json()
        dispatch_dashboard = dashboard_body.get(
            "operator_review_escalation_dispatches", {}
        )
        dashboard_recent_item = _dashboard_dispatch_item(
            dispatch_dashboard,
            dispatch_id=dispatch_id,
        )
        worker_item = _worker_item(worker_run, dispatch_id=dispatch_id)
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=TRACE_ID,
            case_id=case_id,
            escalation_id=escalation_id,
            dispatch_id=dispatch_id,
            dispatch_idempotency_key=dispatch_idempotency_key,
        )

        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "create_schema": create_plan.get("dispatch_plan_schema_version")
            == "ag_operator_review_escalation_dispatch_plan.v1",
            "create_new": create_plan.get("idempotency_status") == "NEW",
            "created_pending": (
                create_plan.get("dispatch_record", {}).get("dispatch_status")
                == "PENDING"
            ),
            "worker_completed": worker_run.get("run_status") == "COMPLETED",
            "worker_processed_dispatch": bool(worker_item),
            "worker_result_metadata_persisted": (
                worker_item.get("result_metadata_persisted") is True
                if isinstance(worker_item, Mapping)
                else False
            ),
            "worker_succeeded": (
                worker_item.get("final_status") == "SUCCEEDED"
                if isinstance(worker_item, Mapping)
                else False
            ),
            "final_dispatch_succeeded": (
                final_dispatch.get("dispatch_status") == "SUCCEEDED"
            ),
            "last_execution_result_recorded": (
                final_dispatch.get("metadata", {}).get(
                    "last_execution_result_recorded"
                )
                is True
            ),
            "last_execution_result_succeeded": (
                final_dispatch.get("metadata", {})
                .get("last_execution_result", {})
                .get("execution_status")
                == "SUCCEEDED"
            ),
            "last_execution_result_storage_safe": (
                final_dispatch.get("metadata", {})
                .get("last_execution_result", {})
                .get("result_storage")
                == DISPATCH_EXECUTION_RESULT_STORAGE
            ),
            "dashboard_status": dashboard_response.status_code == 200,
            "dashboard_execution_count": (
                dispatch_dashboard.get("execution_summary", {}).get("recorded_count")
                >= 1
            ),
            "dashboard_execution_succeeded": (
                dispatch_dashboard.get("execution_summary", {}).get("succeeded_count")
                >= 1
            ),
            "dashboard_recent_execution_result": (
                isinstance(dashboard_recent_item, Mapping)
                and dashboard_recent_item.get("execution_result", {}).get(
                    "execution_status"
                )
                == "SUCCEEDED"
            ),
            "tables_present": observations.get("tables_present")
            == {
                "ag_op_cases": True,
                "ag_op_escalations": True,
                "ag_op_esc_dispatches": True,
                "service_operational_events": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "escalation_row_persisted": observations.get("escalation_count") == 1,
            "dispatch_row_persisted": observations.get("dispatch_count") == 1,
            "succeeded_row_persisted": observations.get("succeeded_count") == 1,
            "execution_metadata_persisted": (
                observations.get("execution_metadata_count") == 1
            ),
            "last_action_succeeded": observations.get("last_action_succeed_count")
            == 1,
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
            "idempotency_values_redacted": observations.get("idempotency_leak_count")
            == 0,
        }
        cleanup = _cleanup_smoke_rows(
            engine,
            case_id,
            escalation_id,
            dispatch_id,
            target_id,
            TRACE_ID,
        )
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
            "case_id": case_id,
            "escalation_id": escalation_id,
            "dispatch_id": dispatch_id,
            "target_id": target_id,
            "worker_run": {
                "run_id": worker_run.get("run_id"),
                "run_status": worker_run.get("run_status"),
                "candidate_count": worker_run.get("candidate_count"),
                "processed_count": worker_run.get("processed_count"),
                "succeeded_count": worker_run.get("succeeded_count"),
                "failed_count": worker_run.get("failed_count"),
                "retry_wait_count": worker_run.get("retry_wait_count"),
                "dry_run": worker_run.get("dry_run"),
            },
            "observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_smoke_rows(
                engine,
                case_id,
                escalation_id,
                dispatch_id,
                target_id,
                TRACE_ID,
            )
            engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        forbidden_values=(
            RAW_PROVIDER_PAYLOAD,
            RAW_PROVIDER_ERROR,
            RAW_ACTION_COMMENT,
            case_idempotency_key,
            escalation_idempotency_key,
            dispatch_idempotency_key,
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
            "workbench_path": "/admin/v1/operator-review/dispatches",
        },
        "assignment_ref": None,
        "reason_codes": ["postgres_smoke", "operator_review_dispatch_execution"],
        "metadata": {"source": "postgres_smoke", "slice": "0719"},
    }


def _escalation_candidate(
    *,
    suffix: str,
    case_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "candidate_id": f"{case_id}:dispatch-execution:ready",
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
        "escalation_reasons": ["postgres_smoke", "dispatch_execution_ready"],
        "runbook_ids": ["ag.operator_review_escalation_dispatch_execution.smoke.v1"],
        "recommended_operator_actions": ["execute_pending_escalation_dispatch"],
        "metadata": {"suffix": suffix},
    }


def _dispatch_payload(*, suffix: str) -> dict[str, Any]:
    return {
        "dispatch_intent": "NOTIFY_OPERATOR",
        "channel_type": "MOCK",
        "provider_profile": "mock-default",
        "provider_ref": {
            "provider_type": "mock",
            "provider_id": "mock-escalation-dispatch-execution",
            "external_ref": f"mock-execution-{suffix}",
        },
        "safe_subject": "S72 dispatch execution PostgreSQL smoke",
        "safe_body": (
            "S72 dispatch execution PostgreSQL smoke uses only safe refs, "
            "hashes, and bounded previews."
        ),
        "reason_codes": ["postgres_smoke_dispatch_execution"],
        "metadata": {"source": "postgres_smoke", "slice": "0719"},
    }


def _operator_ref(suffix: str) -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": f"smoke-operator-{suffix}",
        "tenant_id": "smoke-tenant",
    }


def _service_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f0719a0ba902b7-01",
    }


def _created_dispatch_id(response: Mapping[str, Any]) -> str:
    record = response.get("dispatch_record")
    if not isinstance(record, Mapping):
        return ""
    return str(record.get("dispatch_id") or "")


def _worker_item(
    worker_run: Mapping[str, Any],
    *,
    dispatch_id: str | None,
) -> Mapping[str, Any]:
    for item in worker_run.get("items", []):
        if isinstance(item, Mapping) and item.get("dispatch_id") == dispatch_id:
            return item
    return {}


def _dashboard_dispatch_item(
    dispatch_dashboard: Mapping[str, Any],
    *,
    dispatch_id: str | None,
) -> Mapping[str, Any]:
    for item in dispatch_dashboard.get("recent", []):
        if isinstance(item, Mapping) and item.get("dispatch_id") == dispatch_id:
            return item
    return {}


def _db_observations(
    engine: Any,
    *,
    target_id: str,
    trace_id: str,
    case_id: str | None,
    escalation_id: str | None,
    dispatch_id: str | None,
    dispatch_idempotency_key: str,
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
                "ag_op_esc_dispatches",
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
                            WHERE escalation_id = :escalation_id
                                AND target_id = :target_id
                        ) AS escalation_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                AND target_id = :target_id
                        ) AS dispatch_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                AND dispatch_status = 'SUCCEEDED'
                                AND attempt_count = 1
                        ) AS succeeded_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                AND metadata->>'last_execution_result_recorded'
                                    = 'true'
                                AND metadata->'last_execution_result'
                                    ->>'execution_status' = 'SUCCEEDED'
                                AND metadata->'last_execution_result'
                                    ->>'result_storage' = :result_storage
                        ) AS execution_metadata_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                AND metadata->'last_action'->>'action_type'
                                    = 'SUCCEED'
                        ) AS last_action_succeed_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                AND (
                                    metadata::text LIKE '%' || :raw_provider_payload || '%'
                                    OR metadata::text LIKE '%' || :raw_provider_error || '%'
                                    OR metadata::text LIKE '%' || :raw_action_comment || '%'
                                    OR provider_ref::text LIKE '%' || :raw_provider_payload || '%'
                                    OR provider_payload_hash = :raw_provider_payload
                                    OR idempotency_key_hash = :dispatch_idempotency_key
                                )
                        ) AS row_secret_leak_count,
                        (
                            SELECT count(*) FROM service_operational_events
                            WHERE service_id = 'nex-ag'
                                AND trace_id = :trace_id
                                AND (
                                    details::text LIKE '%' || :raw_provider_payload || '%'
                                    OR details::text LIKE '%' || :raw_provider_error || '%'
                                    OR details::text LIKE '%' || :raw_action_comment || '%'
                                    OR details::text LIKE '%' || :dispatch_idempotency_key || '%'
                                )
                        ) AS event_secret_leak_count
                    """
                ),
                {
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "case_id": case_id or "",
                    "escalation_id": escalation_id or "",
                    "dispatch_id": dispatch_id or "",
                    "dispatch_idempotency_key": dispatch_idempotency_key,
                    "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
                    "raw_provider_error": RAW_PROVIDER_ERROR,
                    "raw_action_comment": RAW_ACTION_COMMENT,
                    "result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
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
        "dispatch_count": int(row["dispatch_count"]),
        "succeeded_count": int(row["succeeded_count"]),
        "execution_metadata_count": int(row["execution_metadata_count"]),
        "last_action_succeed_count": int(row["last_action_succeed_count"]),
        "raw_value_leak_count": row_secret_leak_count + event_secret_leak_count,
        "idempotency_leak_count": row_secret_leak_count + event_secret_leak_count,
    }


def _cleanup_smoke_rows(
    engine: Any,
    case_id: str | None,
    escalation_id: str | None,
    dispatch_id: str | None,
    target_id: str | None,
    trace_id: str | None,
) -> dict[str, int]:
    if not case_id and not escalation_id and not dispatch_id and not target_id and not trace_id:
        return {"cases": 0, "escalations": 0, "dispatches": 0, "events": 0}
    deleted_cases = deleted_escalations = deleted_dispatches = deleted_events = 0
    try:
        with engine.begin() as connection:
            params = {
                "case_id": case_id or "",
                "escalation_id": escalation_id or "",
                "dispatch_id": dispatch_id or "",
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
                                OR details->>'dispatch_id' = :dispatch_id
                                OR details->>'escalation_id' = :escalation_id
                                OR details->>'target_id' = :target_id
                            """
                        ),
                        params,
                    )
                ).rowcount
                or 0
            )
            deleted_dispatches = int(
                (
                    connection.execute(
                        text(
                            """
                            DELETE FROM ag_op_esc_dispatches
                            WHERE dispatch_id = :dispatch_id
                                OR escalation_id = :escalation_id
                                OR target_id = :target_id
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
        return {"cases": 0, "escalations": 0, "dispatches": 0, "events": 0}
    return {
        "cases": deleted_cases,
        "escalations": deleted_escalations,
        "dispatches": deleted_dispatches,
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
        raise ValueError("AG dispatch execution smoke evidence contains raw DB URL.")
    for value in forbidden_values:
        if value and value in serialized_evidence:
            raise ValueError(
                "AG dispatch execution smoke evidence contains raw secret."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_escalation_dispatch_execution_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_escalation_dispatch_execution_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"dispatches={evidence['observations']['dispatch_count']} "
            f"succeeded={evidence['observations']['succeeded_count']} "
            f"metadata={evidence['observations']['execution_metadata_count']} "
            f"deleted_dispatches={cleanup['dispatches']} "
            f"deleted_events={cleanup['events']}"
        )
    return (
        "ag_operator_review_escalation_dispatch_execution_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AG escalation dispatch execution PostgreSQL smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_escalation_dispatch_execution_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
