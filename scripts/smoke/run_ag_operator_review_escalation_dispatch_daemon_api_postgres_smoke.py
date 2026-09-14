#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
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
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_ag_operator_review_escalation_dispatch_execution_postgres_smoke import (  # noqa: E402
    RAW_ACTION_COMMENT,
    RAW_PROVIDER_ERROR,
    RAW_PROVIDER_PAYLOAD,
    _case_payload,
    _cleanup_smoke_rows,
    _db_observations,
    _dispatch_payload,
    _operator_ref,
    _service_headers,
    assert_smoke_evidence_redacted,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_API_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_dispatch_daemon_api_postgres_smoke"
TRACE_ID = "75a4913f56d84b2cba16b044359a0754"


def run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke(
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
        return _failure("migration_failed", str(exc))

    suffix = uuid4().hex[:12]
    reference_time = _utc_now()
    request_id = f"ag-dispatch-daemon-api-smoke-{suffix}"
    target_id = f"ag-dispatch-daemon-api-target-{suffix}"
    case_id = f"ag-dispatch-daemon-api-case-{suffix}"
    case_idempotency_key = f"ag-dispatch-daemon-api-case-idem-{suffix}"
    escalation_idempotency_key = f"ag-dispatch-daemon-api-escalation-idem-{suffix}"
    dispatch_idempotency_key = f"ag-dispatch-daemon-api-dispatch-idem-{suffix}"
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
        service = OperatorReviewCaseService(
            case_store,
            escalation_store=escalation_store,
            dispatch_store=dispatch_store,
        )
        _cleanup_smoke_rows(
            engine,
            case_id=case_id,
            escalation_id=None,
            dispatch_id=None,
            target_id=target_id,
            trace_id=TRACE_ID,
        )
        case_store.save(
            build_operator_review_case_record(
                _case_payload(suffix=suffix, case_id=case_id, target_id=target_id),
                request_id=request_id,
                trace_id=TRACE_ID,
                idempotency_key=case_idempotency_key,
                created_at=reference_time,
            )
        )
        escalation = build_operator_review_escalation_record(
            _escalation_candidate(suffix=suffix, case_id=case_id, target_id=target_id),
            {
                "operator_ref": _operator_ref(suffix),
                "action_comment": "Seed S76 dispatch daemon API smoke safely.",
                "metadata": {"source": "postgres_smoke", "slice": "0754"},
            },
            request_id=request_id,
            trace_id=TRACE_ID,
            idempotency_key=escalation_idempotency_key,
            created_at=reference_time,
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
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_unified_operation_routes(
            app,
            operator_review_case_store=case_store,
            operator_review_escalation_store=escalation_store,
            operator_review_escalation_dispatch_store=dispatch_store,
        )
        client = TestClient(app)
        headers = _service_headers(request_id=request_id, trace_id=TRACE_ID)
        tick_plan_response = client.get(
            "/admin/v1/operator-review/dispatch-daemon/tick-plan",
            params={
                "enabled": "true",
                "dry_run": "false",
                "batch_limit": 1,
                "provider_mode": "mock_first_only",
            },
            headers=headers,
        )
        tick_once_response = client.post(
            "/admin/v1/operator-review/dispatch-daemon/tick-once",
            json={
                "enabled": True,
                "confirm_tick": True,
                "dry_run": False,
                "batch_limit": 1,
                "provider_mode": "mock_first_only",
                "operator_ref": _operator_ref(suffix),
                "reason_codes": ["postgres_smoke_dispatch_daemon_api"],
            },
            headers=headers,
        )
        tick_plan_body = tick_plan_response.json()
        tick_once_body = tick_once_response.json()
        final_dispatch = dispatch_store.get(dispatch_id) or {}
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
            "create_new": create_plan.get("idempotency_status") == "NEW",
            "created_pending": (
                create_plan.get("dispatch_record", {}).get("dispatch_status")
                == "PENDING"
            ),
            "tick_plan_http_ok": tick_plan_response.status_code == 200,
            "tick_plan_ready": tick_plan_body.get("summary", {}).get("plan_status")
            == "READY",
            "tick_plan_contains_dispatch": dispatch_id
            in tick_plan_body.get("plan", {}).get("candidate_dispatch_ids", []),
            "tick_once_http_ok": tick_once_response.status_code == 200,
            "tick_once_completed": tick_once_body.get("summary", {}).get("tick_status")
            == "COMPLETED",
            "tick_once_mutated": tick_once_body.get("summary", {}).get(
                "mutation_performed"
            )
            is True,
            "tick_once_processed_one": tick_once_body.get("summary", {}).get(
                "processed_count"
            )
            == 1,
            "final_dispatch_succeeded": (
                final_dispatch.get("dispatch_status") == "SUCCEEDED"
            ),
            "last_execution_result_recorded": (
                final_dispatch.get("metadata", {}).get(
                    "last_execution_result_recorded"
                )
                is True
            ),
            "dispatch_rows_persisted": observations.get("dispatch_count") == 1,
            "execution_metadata_persisted": observations.get(
                "execution_metadata_count"
            )
            == 1,
            "raw_values_redacted": observations.get("raw_value_leak_count") == 0,
            "idempotency_values_redacted": observations.get("idempotency_leak_count")
            == 0,
        }
        cleanup = _cleanup_smoke_rows(
            engine,
            case_id=case_id,
            escalation_id=escalation_id,
            dispatch_id=dispatch_id,
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
            "target_id": target_id,
            "dispatch_id": dispatch_id,
            "api": {
                "tick_plan_status_code": tick_plan_response.status_code,
                "tick_once_status_code": tick_once_response.status_code,
                "tick_plan_schema": tick_plan_body.get("projection_schema_version"),
                "tick_once_schema": tick_once_body.get("projection_schema_version"),
                "tick_once_route_mutation": tick_once_body.get("route", {}).get(
                    "mutation"
                ),
            },
            "tick_plan_summary": tick_plan_body.get("summary", {}),
            "tick_once_summary": tick_once_body.get("summary", {}),
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
                dispatch_id=dispatch_id,
                target_id=target_id,
                trace_id=TRACE_ID,
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


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _created_dispatch_id(response: Mapping[str, Any]) -> str:
    record = response.get("dispatch_record")
    if not isinstance(record, Mapping):
        return ""
    return str(record.get("dispatch_id") or "")


def _escalation_candidate(
    *,
    suffix: str,
    case_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "candidate_id": f"{case_id}:api-smoke",
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
        "escalation_reasons": ["postgres_smoke", "dispatch_daemon_api_ready"],
        "runbook_ids": ["ag.operator_review_escalation_dispatch_daemon_api.smoke.v1"],
        "recommended_operator_actions": ["execute_pending_escalation_dispatch"],
        "metadata": {"suffix": suffix, "slice": "0754"},
    }


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
            "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke="
            f"skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    cleanup = evidence.get("cleanup", {})
    observations = evidence.get("observations", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"tick_once={evidence.get('tick_once_summary', {}).get('tick_status')} "
        f"dispatches={observations.get('dispatch_count')} "
        f"metadata={observations.get('execution_metadata_count')} "
        f"deleted_dispatches={cleanup.get('dispatches')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
