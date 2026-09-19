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

from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    SqlAlchemyOperatorReviewCaseStore,
    SqlAlchemyOperatorReviewEscalationDispatchStore,
    SqlAlchemyOperatorReviewEscalationStore,
    build_operator_review_case_record,
    build_operator_review_escalation_record,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_ag.recovery_notification_delivery import (  # noqa: E402
    RecoveryNotificationDeliveryError,
    build_recovery_notification_delivery_admission,
    build_recovery_notification_dispatch_handoff,
    persist_recovery_notification_dispatch_handoff,
    run_recovery_notification_delivery_mock_once,
)
from nex_ag.recovery_notification_policy import (  # noqa: E402
    build_recovery_notification_plan,
)
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_recovery_notification_delivery_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
REFERENCE_TIME = "2026-09-19T05:00:00Z"
RAW_IDEMPOTENCY_KEY = "private-recovery-delivery-idempotency-0848"
RAW_PROVIDER_TOKEN = "private-recovery-delivery-provider-token-0848"


def run_ag_recovery_notification_delivery_postgres_smoke(
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

    suffix = uuid4().hex[:12]
    context = {
        "case_id": f"ag-recovery-delivery-smoke-case-{suffix}",
        "target_id": f"ag-recovery-delivery-smoke-target-{suffix}",
        "request_id": f"ag-recovery-delivery-smoke-request-{suffix}",
        "trace_id": uuid4().hex,
        "worker_id": f"ag-recovery-delivery-smoke-worker-{suffix}",
        "case_idempotency_key": f"ag-recovery-delivery-case-{suffix}",
        "escalation_idempotency_key": f"ag-recovery-delivery-escalation-{suffix}",
        "dispatch_idempotency_key": (
            f"{RAW_IDEMPOTENCY_KEY}-{suffix}"
        ),
    }
    engine: Any | None = None
    cleanup_done = False
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
        evidence = _execute_smoke(
            engine,
            service,
            case_store=case_store,
            escalation_store=escalation_store,
            dispatch_store=dispatch_store,
            migration=migration,
            database_url=database_url,
            context=context,
        )
        cleanup = _cleanup_owned_rows(engine, context=evidence["owned_context"])
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_rows_deleted"] = (
            cleanup["dispatches"] == 1
            and cleanup["escalations"] == 1
            and cleanup["cases"] == 1
            and cleanup["remaining_rows"] == 0
        )
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        OperatorReviewNoteError,
        RecoveryNotificationDeliveryError,
        SQLAlchemyError,
        RuntimeError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None and not cleanup_done:
            _cleanup_owned_rows(engine, context=context)
        if engine is not None:
            engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_smoke(
    engine: Any,
    service: Any,
    *,
    case_store: Any,
    escalation_store: Any,
    dispatch_store: Any,
    migration: Any,
    database_url: str,
    context: dict[str, str],
) -> dict[str, Any]:
    case_record = build_operator_review_case_record(
        _case_payload(context),
        request_id=context["request_id"],
        trace_id=context["trace_id"],
        idempotency_key=context["case_idempotency_key"],
        created_at=REFERENCE_TIME,
    )
    case_store.save(case_record)
    escalation = build_operator_review_escalation_record(
        _escalation_candidate(context),
        {
            "operator_ref": _operator_ref(context),
            "metadata": {"source": "postgres_smoke", "slice": "0848"},
        },
        request_id=context["request_id"],
        trace_id=context["trace_id"],
        idempotency_key=context["escalation_idempotency_key"],
        created_at=REFERENCE_TIME,
    )
    escalation_store.save(escalation)
    context["escalation_id"] = escalation["escalation_id"]

    plan = _ready_notification_plan(context)
    admission = build_recovery_notification_delivery_admission(
        plan,
        case_record,
        escalation,
        channel_type="MOCK",
        provider_profile="mock-default",
        admitted_at=REFERENCE_TIME,
    )
    handoff = build_recovery_notification_dispatch_handoff(
        plan,
        admission,
        escalation,
        request_id=context["request_id"],
        trace_id=context["trace_id"],
        idempotency_key=context["dispatch_idempotency_key"],
        created_at=REFERENCE_TIME,
    )
    mutation = persist_recovery_notification_dispatch_handoff(
        handoff,
        dispatch_store,
    )
    context["dispatch_id"] = mutation["dispatch_record"]["dispatch_id"]
    before = _database_observation(engine, context=context)
    execution = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=context["dispatch_id"],
        request_id=context["request_id"],
        trace_id=context["trace_id"],
        worker_id=context["worker_id"],
        confirm_run=True,
        executed_at=REFERENCE_TIME,
    )
    final_dispatch = dispatch_store.get(context["dispatch_id"]) or {}
    after = _database_observation(engine, context=context)
    worker_run = _mapping(execution.get("worker_run"))
    marker = _mapping(final_dispatch.get("metadata")).get(
        "recovery_notification_delivery"
    )
    checks = {
        "migration_ran": migration.service_id == SERVICE_ID,
        "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
        "test_database_selected": _engine_database(engine) == "nex_ag_test",
        "tables_present": all(before["tables_present"].values()),
        "case_and_escalation_persisted": (
            before["case_count"] == 1 and before["escalation_count"] == 1
        ),
        "delivery_dispatch_persisted_pending": (
            before["dispatch_count"] == 1
            and before["pending_count"] == 1
            and before["delivery_marker_count"] == 1
        ),
        "targeted_mock_execution_completed": (
            execution.get("execution_status") == "COMPLETED"
            and worker_run.get("candidate_count") == 1
            and worker_run.get("succeeded_count") == 1
        ),
        "dispatch_succeeded": (
            final_dispatch.get("dispatch_status") == "SUCCEEDED"
            and after["succeeded_count"] == 1
        ),
        "delivery_marker_preserved": (
            isinstance(marker, Mapping)
            and marker.get("notification_plan_id")
            == mutation.get("notification_plan_id")
            and after["delivery_marker_count"] == 1
        ),
        "safe_execution_metadata_persisted": (
            after["execution_metadata_count"] == 1
            and _mapping(final_dispatch.get("metadata"))
            .get("last_execution_result", {})
            .get("execution_status")
            == "SUCCEEDED"
        ),
        "provider_network_not_used": (
            execution.get("guardrails", {}).get("external_network_allowed")
            is False
        ),
        "raw_values_not_persisted": after["raw_value_leak_count"] == 0,
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
        "owned_context": {
            "case_id": context["case_id"],
            "escalation_id": context["escalation_id"],
            "dispatch_id": context["dispatch_id"],
            "target_id": context["target_id"],
            "trace_id": context["trace_id"],
        },
        "execution": {
            "execution_status": execution.get("execution_status"),
            "run_status": worker_run.get("run_status"),
            "candidate_count": worker_run.get("candidate_count"),
            "processed_count": worker_run.get("processed_count"),
            "succeeded_count": worker_run.get("succeeded_count"),
            "provider_mode": execution.get("guardrails", {}).get(
                "provider_mode"
            ),
            "external_network_allowed": execution.get("guardrails", {}).get(
                "external_network_allowed"
            ),
        },
        "before": before,
        "after": after,
        "checks": checks,
    }


def _case_payload(context: Mapping[str, str]) -> dict[str, Any]:
    return {
        "case_id": context["case_id"],
        "target_ref": {
            "target_service": SERVICE_ID,
            "target_kind": "dispatch_daemon",
            "target_id": context["target_id"],
        },
        "operator_ref": _operator_ref(context),
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_issue_candidate",
            "source_id": context["target_id"],
            "source_service": SERVICE_ID,
            "workbench_path": "/admin/v1/operator-review/dispatches",
        },
        "assignment_ref": None,
        "reason_codes": ["postgres_smoke", "recovery_notification_delivery"],
        "metadata": {"source": "postgres_smoke", "slice": "0848"},
    }


def _escalation_candidate(context: Mapping[str, str]) -> dict[str, Any]:
    return {
        "candidate_id": f"{context['case_id']}:recovery-delivery:ready",
        "case_id": context["case_id"],
        "target_ref": {
            "target_service": SERVICE_ID,
            "target_kind": "dispatch_daemon",
            "target_id": context["target_id"],
        },
        "assignment_ref": {
            "assignee_type": None,
            "assignee_id": None,
            "tenant_id": "smoke-tenant",
        },
        "escalation_level": "BLOCKED",
        "sla_state": "OVERDUE",
        "escalation_reasons": ["postgres_smoke", "delivery_ready"],
        "runbook_ids": ["ag.recovery_notification_delivery.smoke.v1"],
        "recommended_operator_actions": ["execute_mock_delivery"],
        "metadata": {"source": "postgres_smoke", "slice": "0848"},
    }


def _operator_ref(context: Mapping[str, str]) -> dict[str, str]:
    return {
        "operator_type": "service",
        "operator_id": context["worker_id"],
        "tenant_id": "smoke-tenant",
    }


def _ready_notification_plan(context: Mapping[str, str]) -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": SERVICE_ID,
                "worker_id": context["worker_id"],
            },
            "recommended_actions": [{"severity": "ERROR"}],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=REFERENCE_TIME,
    )


def _database_observation(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, Any]:
    with engine.connect() as connection:
        tables = {
            table_name: _regclass_matches(
                connection.execute(
                    text(f"SELECT to_regclass('public.{table_name}')")
                ).scalar(),
                table_name,
            )
            for table_name in (
                "ag_op_cases",
                "ag_op_escalations",
                "ag_op_esc_dispatches",
            )
        }
        row = connection.execute(
            text(
                """
                SELECT current_database() AS database_name,
                       (SELECT count(*) FROM ag_op_cases
                        WHERE case_id = :case_id) AS case_count,
                       (SELECT count(*) FROM ag_op_escalations
                        WHERE escalation_id = :escalation_id) AS escalation_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id) AS dispatch_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id
                          AND dispatch_status = 'PENDING') AS pending_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id
                          AND dispatch_status = 'SUCCEEDED'
                          AND attempt_count = 1) AS succeeded_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id
                          AND metadata ? 'recovery_notification_delivery')
                          AS delivery_marker_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id
                          AND metadata->>'last_execution_result_recorded' = 'true'
                          AND metadata->'last_execution_result'
                              ->>'execution_status' = 'SUCCEEDED')
                          AS execution_metadata_count,
                       (SELECT count(*) FROM ag_op_esc_dispatches
                        WHERE dispatch_id = :dispatch_id
                          AND (metadata::text LIKE '%' || :raw_token || '%'
                            OR metadata::text LIKE '%' || :raw_idempotency || '%'
                            OR provider_ref::text LIKE '%' || :raw_token || '%'))
                          AS raw_value_leak_count
                """
            ),
            {
                **context,
                "raw_token": RAW_PROVIDER_TOKEN,
                "raw_idempotency": RAW_IDEMPOTENCY_KEY,
            },
        ).mappings().one()
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "tables_present": tables,
        "case_count": int(row.get("case_count") or 0),
        "escalation_count": int(row.get("escalation_count") or 0),
        "dispatch_count": int(row.get("dispatch_count") or 0),
        "pending_count": int(row.get("pending_count") or 0),
        "succeeded_count": int(row.get("succeeded_count") or 0),
        "delivery_marker_count": int(row.get("delivery_marker_count") or 0),
        "execution_metadata_count": int(
            row.get("execution_metadata_count") or 0
        ),
        "raw_value_leak_count": int(row.get("raw_value_leak_count") or 0),
    }


def _cleanup_owned_rows(
    engine: Any,
    *,
    context: Mapping[str, str],
) -> dict[str, int]:
    params = {
        "case_id": context.get("case_id", ""),
        "escalation_id": context.get("escalation_id", ""),
        "dispatch_id": context.get("dispatch_id", ""),
        "target_id": context.get("target_id", ""),
    }
    try:
        with engine.begin() as connection:
            dispatches = int(
                connection.execute(
                    text(
                        "DELETE FROM ag_op_esc_dispatches "
                        "WHERE dispatch_id = :dispatch_id OR target_id = :target_id"
                    ),
                    params,
                ).rowcount
                or 0
            )
            escalations = int(
                connection.execute(
                    text(
                        "DELETE FROM ag_op_escalations "
                        "WHERE escalation_id = :escalation_id "
                        "OR target_id = :target_id"
                    ),
                    params,
                ).rowcount
                or 0
            )
            cases = int(
                connection.execute(
                    text(
                        "DELETE FROM ag_op_cases "
                        "WHERE case_id = :case_id OR target_id = :target_id"
                    ),
                    params,
                ).rowcount
                or 0
            )
            remaining = int(
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM ag_op_esc_dispatches "
                        " WHERE dispatch_id = :dispatch_id) + "
                        "(SELECT count(*) FROM ag_op_escalations "
                        " WHERE escalation_id = :escalation_id) + "
                        "(SELECT count(*) FROM ag_op_cases "
                        " WHERE case_id = :case_id)"
                    ),
                    params,
                ).scalar()
                or 0
            )
    except (AttributeError, SQLAlchemyError):
        return {
            "cases": 0,
            "escalations": 0,
            "dispatches": 0,
            "remaining_rows": -1,
        }
    return {
        "cases": cases,
        "escalations": escalations,
        "dispatches": dispatches,
        "remaining_rows": remaining,
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
    forbidden = (
        env.get(DATABASE_ENV, ""),
        RAW_IDEMPOTENCY_KEY,
        RAW_PROVIDER_TOKEN,
    )
    if any(value and value in serialized_evidence for value in forbidden):
        raise ValueError("recovery delivery smoke evidence contains a secret")


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
            "ag_recovery_notification_delivery_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_recovery_notification_delivery_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    after = _mapping(evidence.get("after"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_recovery_notification_delivery_postgres_smoke=pass "
        f"database={after.get('database')} "
        f"backend={after.get('backend')} "
        f"dispatches={after.get('dispatch_count')} "
        f"succeeded={after.get('succeeded_count')} "
        f"metadata={after.get('execution_metadata_count')} "
        f"cleaned={cleanup.get('remaining_rows') == 0}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env.local")
    args = parser.parse_args(argv)
    load_env_file(ROOT / args.env_file)
    evidence = run_ag_recovery_notification_delivery_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence))
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
