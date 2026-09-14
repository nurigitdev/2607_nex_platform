#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operations import (  # noqa: E402
    build_operations_dashboard_snapshot_projection,
    build_operator_review_escalation_dispatch_daemon_runtime_projection,
)
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
    UrllibDispatchProviderHttpTransport,
    build_dispatch_execution_daemon_control_admission,
    build_dispatch_execution_daemon_control_request,
    build_dispatch_execution_daemon_policy,
    build_dispatch_execution_daemon_tick_event,
    build_dispatch_execution_daemon_tick_log_entry,
    build_dispatch_execution_provider_config,
    run_dispatch_execution_daemon_tick_once,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke import (  # noqa: E402
    _LiveHttpPostgresLoopbackServer,
)
from run_ag_operator_review_escalation_dispatch_provider_postgres_smoke import (  # noqa: E402
    RAW_ACTION_COMMENT,
    RAW_PROVIDER_PAYLOAD,
    RAW_PROVIDER_RESPONSE,
    _case_payload,
    _cleanup_smoke_rows,
    _db_observations,
    _dispatch_payload,
    _escalation_candidate,
    _operator_ref,
    assert_smoke_evidence_redacted,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_daemon_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TRACE_ID = "c7de88d87d2044dc831f51975466a748"
REFERENCE_TIME = "2026-09-14T13:48:00Z"
LOOPBACK_TOKEN = "dispatch-daemon-postgres-loopback-token-0748"


def run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke(
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

    server = _LiveHttpPostgresLoopbackServer()
    server.start()
    suffix = uuid4().hex[:12]
    request_id = f"ag-dispatch-daemon-smoke-{suffix}"
    worker_id = f"ag-dispatch-daemon-worker-{suffix}"
    target_id = f"ag-dispatch-daemon-target-{suffix}"
    case_id = f"ag-dispatch-daemon-case-{suffix}"
    case_idempotency_key = f"ag-dispatch-daemon-case-idem-{suffix}"
    escalation_idempotency_key = f"ag-dispatch-daemon-escalation-idem-{suffix}"
    email_idempotency_key = f"ag-dispatch-daemon-email-idem-{suffix}"
    incident_idempotency_key = f"ag-dispatch-daemon-incident-idem-{suffix}"
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
                "action_comment": "Seed S75 dispatch daemon PostgreSQL smoke safely.",
                "metadata": {"source": "postgres_smoke", "slice": "0748"},
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
                "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
                "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
                "NEX_AG_NOTIFICATION_WEBHOOK_URL": server.endpoint_url,
                "NEX_AG_NOTIFICATION_SERVICE_TOKEN": LOOPBACK_TOKEN,
                "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": server.endpoint_url,
                "NEX_AG_EXTERNAL_INCIDENT_TOKEN": LOOPBACK_TOKEN,
                "NEX_AG_DISPATCH_HTTP_MAX_RETRIES": "0",
                "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS": "5",
            }
        )
        policy = build_dispatch_execution_daemon_policy(
            {
                "NEX_AG_DISPATCH_DAEMON_ENABLED": "1",
                "NEX_AG_DISPATCH_DAEMON_DRY_RUN": "0",
                "NEX_AG_DISPATCH_DAEMON_BATCH_LIMIT": "5",
                "NEX_AG_DISPATCH_DAEMON_CYCLE_LIMIT": "1",
                "NEX_AG_DISPATCH_DAEMON_PROVIDER_MODE": "live_http",
                "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            },
            provider_config=provider_config,
        )
        control_request = build_dispatch_execution_daemon_control_request(
            {
                "action": "tick_once",
                "confirm_tick": True,
                "dry_run": False,
                "batch_limit": 5,
                "provider_mode": "live_http",
                "operator_ref": _operator_ref(suffix),
                "reason_codes": ["postgres_smoke_dispatch_daemon"],
            },
            request_id=request_id,
            trace_id=TRACE_ID,
            requested_at=REFERENCE_TIME,
        )
        control_admission = build_dispatch_execution_daemon_control_admission(
            control_request,
            policy=policy,
        )
        tick_result = run_dispatch_execution_daemon_tick_once(
            service,
            request_id=request_id,
            trace_id=TRACE_ID,
            worker_id=worker_id,
            policy=policy,
            provider_config=provider_config,
            live_http_transport=UrllibDispatchProviderHttpTransport(
                endpoint_url=server.endpoint_url,
                bearer_token=LOOPBACK_TOKEN,
            ),
            confirm_tick=True,
            executed_at=REFERENCE_TIME,
        )
        final_dispatches = [
            dispatch_store.get(dispatch_id) or {} for dispatch_id in dispatch_ids
        ]
        dashboard = build_operations_dashboard_snapshot_projection(
            operator_review_escalation_dispatch_store=dispatch_store,
            service_id=SERVICE_ID,
            recent_limit=10,
            request_trace_id=TRACE_ID,
        )
        dispatch_dashboard = dashboard.get("operator_review_escalation_dispatches", {})
        runtime_projection = (
            build_operator_review_escalation_dispatch_daemon_runtime_projection(
                [tick_result],
                policy=policy,
                checked_at=REFERENCE_TIME,
            )
        )
        tick_event = build_dispatch_execution_daemon_tick_event(tick_result)
        tick_log = build_dispatch_execution_daemon_tick_log_entry(tick_result)
        observations = _db_observations(
            engine,
            target_id=target_id,
            trace_id=TRACE_ID,
            case_id=case_id,
            escalation_id=escalation_id,
            dispatch_ids=dispatch_ids,
            idempotency_keys=(email_idempotency_key, incident_idempotency_key),
        )
        loopback = server.observations()
        worker_run = tick_result.get("worker_run") or {}
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "control_admitted": control_admission.get("admission_status")
            == "ACCEPTED",
            "tick_completed": tick_result.get("tick_status") == "COMPLETED",
            "worker_completed": worker_run.get("run_status") == "COMPLETED",
            "worker_processed_two": worker_run.get("processed_count") == 2,
            "worker_succeeded_two": worker_run.get("succeeded_count") == 2,
            "loopback_received_two_requests": loopback["request_count"] == 2,
            "loopback_categories": loopback["by_provider_category"]
            == {"external_incident": 1, "notification": 1},
            "final_dispatches_succeeded": all(
                dispatch.get("dispatch_status") == "SUCCEEDED"
                for dispatch in final_dispatches
            ),
            "runtime_projection_ready": (
                runtime_projection.get("summary", {}).get("tick_count") == 1
                and runtime_projection.get("summary", {}).get(
                    "processed_count_total"
                )
                == 2
            ),
            "tick_event_info": tick_event.get("severity") == "INFO",
            "tick_log_info": tick_log.get("severity") == "INFO",
            "dashboard_http_statuses": (
                dispatch_dashboard.get("execution_summary", {}).get(
                    "by_http_status_code"
                )
                == {"201": 1, "202": 1}
            ),
            "dispatch_rows_persisted": observations.get("dispatch_count") == 2,
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
            "dispatch_ids": dispatch_ids,
            "control": {
                "admission_status": control_admission.get("admission_status"),
                "action": control_admission.get("action"),
                "dry_run": control_admission.get("dry_run"),
            },
            "tick": {
                "tick_id": tick_result.get("tick_id"),
                "tick_status": tick_result.get("tick_status"),
                "processed_count": tick_result.get("processed_count"),
                "succeeded_count": tick_result.get("succeeded_count"),
                "effective_provider_mode": tick_result.get("effective_provider_mode"),
            },
            "runtime_summary": runtime_projection.get("summary"),
            "event": {
                "event_type": tick_event.get("event_type"),
                "severity": tick_event.get("severity"),
            },
            "log": {
                "severity": tick_log.get("severity"),
                "message": tick_log.get("message"),
            },
            "loopback": loopback,
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
        server.stop()
    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        forbidden_values=(
            LOOPBACK_TOKEN,
            RAW_PROVIDER_PAYLOAD,
            RAW_PROVIDER_RESPONSE,
            RAW_ACTION_COMMENT,
            email_idempotency_key,
            incident_idempotency_key,
            server.endpoint_url,
        ),
    )
    return evidence


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
            "ag_operator_review_escalation_dispatch_daemon_postgres_smoke="
            f"skipped reason={evidence.get('skip_reason')}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    observations = evidence.get("observations", {})
    loopback = evidence.get("loopback", {})
    cleanup = evidence.get("cleanup", {})
    runtime_summary = evidence.get("runtime_summary", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_postgres_smoke=pass "
        f"requests={loopback.get('request_count')} "
        f"ticks={runtime_summary.get('tick_count')} "
        f"dispatches={observations.get('dispatch_count')} "
        f"metadata={observations.get('provider_metadata_count')} "
        f"deleted_dispatches={cleanup.get('dispatches')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
