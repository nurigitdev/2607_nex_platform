#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
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

from nex_ag.operations import build_operations_dashboard_snapshot_projection  # noqa: E402
from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    SqlAlchemyOperatorReviewCaseStore,
    SqlAlchemyOperatorReviewEscalationDispatchStore,
    SqlAlchemyOperatorReviewEscalationStore,
    build_operator_review_case_record,
    build_operator_review_escalation_dispatch_record,
    build_operator_review_escalation_record,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_RESULT_STORAGE,
    build_dispatch_execution_provider_config,
    run_dispatch_execution_worker_once,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_provider_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_PROVIDER_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TARGET_SERVICE = "nex-ag"
TARGET_KIND = "operator_review_escalation_dispatch_provider_postgres_smoke"
TRACE_ID = "60c1729e2d44424ab30302fc0729a729"
REFERENCE_TIME = "2026-09-13T12:29:00Z"
RAW_PROVIDER_PAYLOAD = "S73 raw provider payload must not persist."
RAW_PROVIDER_RESPONSE = "S73 raw provider response must not persist."
RAW_ACTION_COMMENT = "S73 raw provider action comment must not persist."


def run_ag_operator_review_escalation_dispatch_provider_postgres_smoke(
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
    request_id = f"ag-dispatch-provider-smoke-{suffix}"
    worker_id = f"ag-dispatch-provider-worker-{suffix}"
    target_id = f"ag-dispatch-provider-target-{suffix}"
    case_id = f"ag-dispatch-provider-case-{suffix}"
    case_idempotency_key = f"ag-dispatch-provider-case-idem-{suffix}"
    escalation_idempotency_key = f"ag-dispatch-provider-escalation-idem-{suffix}"
    email_idempotency_key = f"ag-dispatch-provider-email-idem-{suffix}"
    incident_idempotency_key = f"ag-dispatch-provider-incident-idem-{suffix}"
    escalation_id: str | None = None
    dispatch_ids: list[str] = []
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        escalation_store = SqlAlchemyOperatorReviewEscalationStore(session_factory)
        dispatch_store = SqlAlchemyOperatorReviewEscalationDispatchStore(
            session_factory
        )
        service = OperatorReviewCaseService(
            case_store,
            escalation_store=escalation_store,
            dispatch_store=dispatch_store,
        )
        case_store.save(
            build_operator_review_case_record(
                _case_payload(case_id=case_id, target_id=target_id),
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=case_idempotency_key,
                created_at=REFERENCE_TIME,
            )
        )
        escalation = build_operator_review_escalation_record(
            _escalation_candidate(case_id=case_id, target_id=target_id),
            {
                "operator_ref": _operator_ref(suffix),
                "action_comment": "Seed S73 provider PostgreSQL smoke safely.",
                "metadata": {"source": "postgres_smoke", "slice": "0729"},
            },
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=escalation_idempotency_key,
            created_at=REFERENCE_TIME,
        )
        escalation_id = escalation["escalation_id"]
        escalation_store.save(escalation)
        email_dispatch = build_operator_review_escalation_dispatch_record(
            escalation,
            _dispatch_payload(
                channel_type="EMAIL",
                dispatch_intent="NOTIFY_OWNER",
                provider_profile="email-notification-default",
                provider_id=f"email-provider-{suffix}",
            ),
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=email_idempotency_key,
            created_at=REFERENCE_TIME,
        )
        incident_dispatch = build_operator_review_escalation_dispatch_record(
            escalation,
            _dispatch_payload(
                channel_type="INCIDENT",
                dispatch_intent="OPEN_INCIDENT",
                provider_profile="external-incident-default",
                provider_id=f"incident-provider-{suffix}",
            ),
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=incident_idempotency_key,
            created_at=REFERENCE_TIME,
        )
        dispatch_store.save(email_dispatch)
        dispatch_store.save(incident_dispatch)
        dispatch_ids = [
            str(email_dispatch["dispatch_id"]),
            str(incident_dispatch["dispatch_id"]),
        ]
        provider_config = build_dispatch_execution_provider_config(
            {
                "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "mock_http",
                "NEX_AG_NOTIFICATION_WEBHOOK_URL": "https://notify.invalid/<smoke>",
                "NEX_AG_NOTIFICATION_SERVICE_TOKEN": "notification-token-smoke",
                "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": "https://incident.invalid/<smoke>",
                "NEX_AG_EXTERNAL_INCIDENT_TOKEN": "incident-token-smoke",
            }
        )
        worker_run = run_dispatch_execution_worker_once(
            service,
            request_id=request_id,
            trace_id=TRACE_ID,
            worker_id=worker_id,
            batch_limit=5,
            provider_mode="mock_http",
            provider_config=provider_config,
            notification_status_code=202,
            external_incident_status_code=201,
            confirm_run=True,
            executed_at=REFERENCE_TIME,
        )
        final_dispatches = [
            dispatch_store.get(dispatch_id) or {} for dispatch_id in dispatch_ids
        ]
        projection = build_operations_dashboard_snapshot_projection(
            operator_review_escalation_dispatch_store=dispatch_store,
            service_id=TARGET_SERVICE,
            recent_limit=10,
            request_trace_id=TRACE_ID,
        )
        dispatch_dashboard = projection.get("operator_review_escalation_dispatches", {})
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=TRACE_ID,
            case_id=case_id,
            escalation_id=escalation_id,
            dispatch_ids=dispatch_ids,
            idempotency_keys=(email_idempotency_key, incident_idempotency_key),
        )
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "worker_completed": worker_run.get("run_status") == "COMPLETED",
            "worker_processed_two": worker_run.get("processed_count") == 2,
            "worker_succeeded_two": worker_run.get("succeeded_count") == 2,
            "metadata_persisted_two": all(
                item.get("result_metadata_persisted") is True
                for item in worker_run.get("items", [])
            )
            and len(worker_run.get("items", [])) == 2,
            "final_dispatches_succeeded": all(
                dispatch.get("dispatch_status") == "SUCCEEDED"
                for dispatch in final_dispatches
            ),
            "provider_categories_persisted": {
                dispatch.get("metadata", {})
                .get("last_execution_result", {})
                .get("provider_category")
                for dispatch in final_dispatches
            }
            == {"notification", "external_incident"},
            "http_statuses_persisted": {
                dispatch.get("metadata", {})
                .get("last_execution_result", {})
                .get("http_status_code")
                for dispatch in final_dispatches
            }
            == {202, 201},
            "dashboard_execution_count": (
                dispatch_dashboard.get("execution_summary", {}).get("recorded_count")
                >= 2
            ),
            "dashboard_provider_categories": (
                dispatch_dashboard.get("execution_summary", {}).get(
                    "by_provider_category"
                )
                == {"external_incident": 1, "notification": 1}
            ),
            "dashboard_http_statuses": (
                dispatch_dashboard.get("execution_summary", {}).get(
                    "by_http_status_code"
                )
                == {"201": 1, "202": 1}
            ),
            "tables_present": observations.get("tables_present")
            == {
                "ag_op_cases": True,
                "ag_op_escalations": True,
                "ag_op_esc_dispatches": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "escalation_row_persisted": observations.get("escalation_count") == 1,
            "dispatch_rows_persisted": observations.get("dispatch_count") == 2,
            "succeeded_rows_persisted": observations.get("succeeded_count") == 2,
            "provider_metadata_persisted": observations.get("provider_metadata_count")
            == 2,
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
            "idempotency_values_redacted": observations.get("idempotency_leak_count")
            == 0,
        }
        cleanup = _cleanup_smoke_rows(
            engine,
            case_id=case_id,
            escalation_id=escalation_id,
            dispatch_ids=dispatch_ids,
            target_id=target_id,
            trace_id=TRACE_ID,
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
            "dispatch_ids": dispatch_ids,
            "target_id": target_id,
            "worker_run": {
                "run_id": worker_run.get("run_id"),
                "run_status": worker_run.get("run_status"),
                "candidate_count": worker_run.get("candidate_count"),
                "processed_count": worker_run.get("processed_count"),
                "succeeded_count": worker_run.get("succeeded_count"),
                "failed_count": worker_run.get("failed_count"),
                "retry_wait_count": worker_run.get("retry_wait_count"),
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
                case_id=case_id,
                escalation_id=escalation_id,
                dispatch_ids=dispatch_ids,
                target_id=target_id,
                trace_id=TRACE_ID,
            )
            engine.dispose()
    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        forbidden_values=(
            RAW_PROVIDER_PAYLOAD,
            RAW_PROVIDER_RESPONSE,
            RAW_ACTION_COMMENT,
            email_idempotency_key,
            incident_idempotency_key,
        ),
    )
    return evidence


def _case_payload(*, case_id: str, target_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "target_ref": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": target_id,
        },
        "operator_ref": _operator_ref("case"),
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": target_id,
            "source_service": SERVICE_ID,
        },
        "assignment_ref": None,
        "reason_codes": ["postgres_smoke", "dispatch_provider"],
        "metadata": {"source": "postgres_smoke", "slice": "0729"},
    }


def _escalation_candidate(*, case_id: str, target_id: str) -> dict[str, Any]:
    return {
        "candidate_id": f"{case_id}:dispatch-provider:ready",
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
        "escalation_reasons": ["postgres_smoke", "dispatch_provider_ready"],
        "runbook_ids": ["ag.operator_review_escalation_dispatch_provider.smoke.v1"],
        "recommended_operator_actions": ["execute_pending_escalation_dispatch"],
        "metadata": {"source": "postgres_smoke", "slice": "0729"},
    }


def _dispatch_payload(
    *,
    channel_type: str,
    dispatch_intent: str,
    provider_profile: str,
    provider_id: str,
) -> dict[str, Any]:
    return {
        "dispatch_intent": dispatch_intent,
        "channel_type": channel_type,
        "provider_profile": provider_profile,
        "provider_ref": {
            "provider_type": "mock_http",
            "provider_id": provider_id,
        },
        "safe_subject": "S73 dispatch provider PostgreSQL smoke",
        "safe_body": (
            "S73 dispatch provider PostgreSQL smoke uses safe provider hashes "
            "and diagnostics only."
        ),
        "provider_payload_fingerprint": RAW_PROVIDER_PAYLOAD,
        "reason_codes": ["postgres_smoke_dispatch_provider"],
        "metadata": {"source": "postgres_smoke", "slice": "0729"},
    }


def _operator_ref(suffix: str) -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": f"smoke-operator-{suffix}",
        "tenant_id": "smoke-tenant",
    }


def _db_observations(
    engine: Any,
    *,
    target_id: str,
    trace_id: str,
    case_id: str | None,
    escalation_id: str | None,
    dispatch_ids: list[str],
    idempotency_keys: tuple[str, str],
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
                            WHERE dispatch_id = ANY(:dispatch_ids)
                                AND target_id = :target_id
                        ) AS dispatch_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = ANY(:dispatch_ids)
                                AND dispatch_status = 'SUCCEEDED'
                                AND attempt_count = 1
                        ) AS succeeded_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = ANY(:dispatch_ids)
                                AND metadata->>'last_execution_result_recorded'
                                    = 'true'
                                AND metadata->'last_execution_result'
                                    ->>'result_storage' = :result_storage
                                AND metadata->'last_execution_result'
                                    ->>'provider_category'
                                    IN ('notification', 'external_incident')
                                AND metadata->'last_execution_result'
                                    ->>'http_status_code' IN ('201', '202')
                        ) AS provider_metadata_count,
                        (
                            SELECT count(*) FROM ag_op_esc_dispatches
                            WHERE dispatch_id = ANY(:dispatch_ids)
                                AND (
                                    metadata::text LIKE '%' || :raw_provider_payload || '%'
                                    OR metadata::text LIKE '%' || :raw_provider_response || '%'
                                    OR metadata::text LIKE '%' || :raw_action_comment || '%'
                                    OR provider_ref::text LIKE '%' || :raw_provider_payload || '%'
                                    OR provider_payload_hash = :raw_provider_payload
                                )
                        ) AS row_secret_leak_count
                    """
                ),
                {
                    "target_id": target_id,
                    "trace_id": trace_id,
                    "case_id": case_id or "",
                    "escalation_id": escalation_id or "",
                    "dispatch_ids": dispatch_ids,
                    "result_storage": DISPATCH_EXECUTION_RESULT_STORAGE,
                    "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
                    "raw_provider_response": RAW_PROVIDER_RESPONSE,
                    "raw_action_comment": RAW_ACTION_COMMENT,
                },
            )
            .mappings()
            .one()
        )
        row_secret_leak_count = int(row["row_secret_leak_count"])
        idempotency_leak_count = sum(
            1
            for key in idempotency_keys
            if _idempotency_key_leaked(connection, dispatch_ids, key)
        )
        return {
            "tables_present": tables,
            "case_count": int(row["case_count"]),
            "escalation_count": int(row["escalation_count"]),
            "dispatch_count": int(row["dispatch_count"]),
            "succeeded_count": int(row["succeeded_count"]),
            "provider_metadata_count": int(row["provider_metadata_count"]),
            "raw_value_leak_count": row_secret_leak_count,
            "idempotency_leak_count": idempotency_leak_count,
        }


def _idempotency_key_leaked(
    connection: Any,
    dispatch_ids: list[str],
    idempotency_key: str,
) -> bool:
    row = (
        connection.execute(
            text(
                """
                SELECT count(*) AS leak_count
                FROM ag_op_esc_dispatches
                WHERE dispatch_id = ANY(:dispatch_ids)
                    AND metadata::text LIKE '%' || :idempotency_key || '%'
                """
            ),
            {"dispatch_ids": dispatch_ids, "idempotency_key": idempotency_key},
        )
        .mappings()
        .one()
    )
    return int(row["leak_count"]) > 0


def _cleanup_smoke_rows(
    engine: Any,
    *,
    case_id: str | None,
    escalation_id: str | None,
    dispatch_ids: list[str],
    target_id: str,
    trace_id: str,
) -> dict[str, int]:
    if not case_id and not escalation_id and not dispatch_ids:
        return {"cases": 0, "escalations": 0, "dispatches": 0}
    with engine.begin() as connection:
        dispatch_count = connection.execute(
            text(
                """
                DELETE FROM ag_op_esc_dispatches
                WHERE dispatch_id = ANY(:dispatch_ids)
                    OR target_id = :target_id
                    OR trace_id = :trace_id
                """
            ),
            {"dispatch_ids": dispatch_ids, "target_id": target_id, "trace_id": trace_id},
        ).rowcount
        escalation_count = connection.execute(
            text(
                """
                DELETE FROM ag_op_escalations
                WHERE escalation_id = :escalation_id
                    OR case_id = :case_id
                    OR target_id = :target_id
                    OR trace_id = :trace_id
                """
            ),
            {
                "escalation_id": escalation_id or "",
                "case_id": case_id or "",
                "target_id": target_id,
                "trace_id": trace_id,
            },
        ).rowcount
        case_count = connection.execute(
            text(
                """
                DELETE FROM ag_op_cases
                WHERE case_id = :case_id
                    OR target_id = :target_id
                    OR trace_id = :trace_id
                """
            ),
            {"case_id": case_id or "", "target_id": target_id, "trace_id": trace_id},
        ).rowcount
    return {
        "cases": int(case_count or 0),
        "escalations": int(escalation_count or 0),
        "dispatches": int(dispatch_count or 0),
    }


def _regclass_matches(value: Any, table: str) -> bool:
    return str(value or "") in {table, f"public.{table}"}


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized: str,
    env: Mapping[str, str],
    *,
    forbidden_values: tuple[str, ...],
) -> None:
    database_url = env.get(DATABASE_ENV)
    if database_url and database_url in serialized:
        raise ValueError(f"{DATABASE_ENV} leaked in smoke evidence.")
    for value in forbidden_values:
        if value and value in serialized:
            raise ValueError("Sensitive dispatch provider smoke value leaked.")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return (
            "ag_operator_review_escalation_dispatch_provider_postgres_smoke=skipped "
            f"reason={evidence.get('skip_reason')}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_provider_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    cleanup = evidence.get("cleanup", {})
    return (
        "ag_operator_review_escalation_dispatch_provider_postgres_smoke=pass "
        f"dispatches={observations.get('dispatch_count')} "
        f"succeeded={observations.get('succeeded_count')} "
        f"metadata={observations.get('provider_metadata_count')} "
        f"deleted_dispatches={cleanup.get('dispatches')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    load_env_file(Path(args.env_file))
    evidence = run_ag_operator_review_escalation_dispatch_provider_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    if evidence["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
