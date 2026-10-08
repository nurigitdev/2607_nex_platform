#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))
sys.path.insert(0, str(ROOT / "scripts" / "db"))

from nex_ag.platform_alert_repository import SqlAlchemyPlatformAlertRepository
from nex_ag.platform_alerting import AlertRecord
from nex_ag.platform_notification_delivery import (
    LocalNotificationTransport,
    NotificationDeliveryPolicy,
    ScriptedMockNotificationTransport,
    execute_notification_batch,
)
from nex_ag.platform_observability_operations import (
    PLATFORM_OBSERVABILITY_ALERTS_PATH,
    PLATFORM_OBSERVABILITY_DASHBOARD_PATH,
    PlatformObservabilityOperations,
    register_platform_observability_routes,
)
from nex_runtime import (
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "s148_observability_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OBSERVABILITY_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TRACE_ID = "c" * 32
OPERATOR_HASH = "sha256:" + "e" * 64


def run_observability_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV)
    if not database_url:
        return _failure("DATABASE_URL_MISSING", f"{DATABASE_ENV} is required.")
    try:
        migration = run_service_migrations(
            SERVICE_ID, database_url=database_url, profile=PROFILE
        )
    except MigrationError as exc:
        return _failure("MIGRATION_FAILED", str(exc))

    suffix = uuid4().hex[:16]
    alert_ids = (f"alert:s148-{suffix}-a", f"alert:s148-{suffix}-b")
    engine = build_engine(database_url)
    try:
        if _database_name(engine) != "nex_ag_test":
            engine.dispose()
            return _failure("TEST_DATABASE_REQUIRED", "protected smoke requires nex_ag_test")
        repository = SqlAlchemyPlatformAlertRepository(build_session_factory(engine))
        first_alert = _alert(alert_ids[0], suffix + "a", "nex-cx")
        second_alert = _alert(alert_ids[1], suffix + "b", "nex-ag")
        repository.insert_alert_with_notifications(
            first_alert,
            [
                _intent("LOCAL", suffix + "c", "ag-local"),
                _intent("EXTERNAL_WEBHOOK", suffix + "d", "incident-external"),
            ],
            created_at="2026-10-08T05:00:00Z",
        )
        repository.insert_alert_with_notifications(
            second_alert, [], created_at="2026-10-08T05:00:00Z"
        )
        first_delivery = execute_notification_batch(
            repository,
            worker_id=f"worker:s148-{suffix}",
            attempted_at="2026-10-08T05:00:01Z",
            policy=NotificationDeliveryPolicy(
                "internet_connected", retry_base_seconds=10, retry_max_seconds=30
            ),
            transports={
                "LOCAL": LocalNotificationTransport(),
                "EXTERNAL_WEBHOOK": ScriptedMockNotificationTransport((503,)),
            },
        )
    except (SQLAlchemyError, ValueError, RuntimeError) as exc:
        engine.dispose()
        _cleanup(database_url, alert_ids)
        return _failure("INITIAL_EXECUTION_FAILED", _safe_detail(exc))
    engine.dispose()

    restarted_engine = build_engine(database_url)
    try:
        restarted = SqlAlchemyPlatformAlertRepository(
            build_session_factory(restarted_engine)
        )
        recovered = restarted.get_alert(first_alert.alert_id)
        retry_delivery = execute_notification_batch(
            restarted,
            worker_id=f"worker:s148-restart-{suffix}",
            attempted_at="2026-10-08T05:00:11Z",
            policy=NotificationDeliveryPolicy(
                "internet_connected", retry_base_seconds=10, retry_max_seconds=30
            ),
            transports={
                "EXTERNAL_WEBHOOK": ScriptedMockNotificationTransport((202,))
            },
        )
        app = build_service_app(SERVICE_SPECS["nex-ag"])
        register_platform_observability_routes(
            app,
            operations=PlatformObservabilityOperations(
                restarted, notification_mode="internet_connected"
            ),
            clock=lambda: _fixed_time(),
        )
        client = TestClient(app)
        headers = _headers()
        dashboard = client.get(PLATFORM_OBSERVABILITY_DASHBOARD_PATH, headers=headers)
        acknowledged = client.post(
            PLATFORM_OBSERVABILITY_ALERTS_PATH + f"/{first_alert.alert_id}/acknowledge",
            headers=headers,
            json={"operator_ref_hash": OPERATOR_HASH},
        )
        suppressed = client.post(
            PLATFORM_OBSERVABILITY_ALERTS_PATH + f"/{second_alert.alert_id}/suppress",
            headers=headers,
            json={"duration_seconds": 300, "reason_code": "SMOKE_MAINTENANCE"},
        )
        observations = _db_observations(restarted_engine, alert_ids)
        checks = {
            "actual_postgresql_backend": _is_postgresql(restarted_engine),
            "test_database_selected": _database_name(restarted_engine) == "nex_ag_test",
            "migration_recorded": observations["migration_recorded"],
            "concise_tables_present": observations["table_count"] == 3,
            "claim_index_present": observations["claim_index_present"],
            "two_alerts_persisted": observations["alert_count"] == 2,
            "two_notifications_persisted": observations["notification_count"] == 2,
            "first_batch_local_delivered": any(
                item["acceptance_status"] == "LOCAL_DELIVERED"
                for item in first_delivery["results"]
            ),
            "first_batch_retry_wait": any(
                item["delivery_state"] == "RETRY_WAIT"
                for item in first_delivery["results"]
            ),
            "restart_recovered_alert": recovered is not None,
            "retry_mock_accepted_honestly": retry_delivery["results"][0]["acceptance_status"] == "MOCK_ACCEPTED"
            and retry_delivery["results"][0]["delivery_state"] == "BLOCKED",
            "attempt_history_persisted": observations["attempt_count"] == 3,
            "dashboard_read_from_postgres": dashboard.status_code == 200
            and dashboard.json()["summary"]["active_alert_count"] == 2,
            "acknowledgement_persisted": acknowledged.status_code == 200
            and acknowledged.json()["alert"]["state"] == "ACKNOWLEDGED",
            "suppression_persisted": suppressed.status_code == 200
            and suppressed.json()["alert"]["state"] == "SUPPRESSED",
            "external_not_activated": dashboard.json().get("external_activation") == "EXTERNAL_NOT_ACTIVATED",
        }
        cleanup = _cleanup_engine(restarted_engine, alert_ids)
        checks["cleanup_exact"] = cleanup["deleted_alerts"] == 2
        checks["cleanup_zero_residue"] = cleanup["residue"] == 0
        passed = all(checks.values())
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "CHECKS_FAILED",
            "service": SERVICE_ID,
            "profile": PROFILE,
            "database": {"backend": "postgresql", "database": "nex_ag_test"},
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            "checks": checks,
            "observations": observations,
            "cleanup": cleanup,
            "external_activation": "EXTERNAL_NOT_ACTIVATED",
            "next_slice": "1481" if passed else "blocked",
        }
    except (SQLAlchemyError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        evidence = _failure("RESTART_OR_API_FAILED", _safe_detail(exc))
    finally:
        _cleanup_engine(restarted_engine, alert_ids)
        restarted_engine.dispose()
    assert_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _alert(alert_id: str, digest_seed: str, service_id: str) -> AlertRecord:
    return AlertRecord(
        alert_id=alert_id,
        dedup_key=_digest(digest_seed),
        rule_id=f"rule:s148-{digest_seed}",
        policy_id=f"slo:s148-{digest_seed}",
        service_id=service_id,
        state="FIRING",
        severity="CRITICAL",
        reason_code="SLO_CRITICAL_BURN",
        occurrence_count=1,
        first_observed_at="2026-10-08T05:00:00Z",
        last_observed_at="2026-10-08T05:00:00Z",
        accountable_owner="platform-operations",
        runbook_ref="runbook:platform:availability",
    )


def _intent(channel: str, seed: str, route_alias: str) -> dict[str, str]:
    return {
        "channel": channel,
        "route_alias": route_alias,
        "idempotency_key_hash": _digest(seed),
        "payload_hash": _digest(seed + "payload"),
    }


def _digest(seed: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _db_observations(engine: Any, alert_ids: tuple[str, str]) -> dict[str, Any]:
    with engine.connect() as connection:
        table_count = connection.execute(
            text(
                "SELECT count(*) FROM unnest(ARRAY["
                "to_regclass('public.ag_alerts'), "
                "to_regclass('public.ag_notify_outbox'), "
                "to_regclass('public.ag_notify_attempts')]) AS table_ref "
                "WHERE table_ref IS NOT NULL"
            )
        ).scalar_one()
        migration_recorded = connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM schema_migrations "
                "WHERE version = '1477_ag_platform_alert_persistence')"
            )
        ).scalar_one()
        claim_index_present = connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname = 'ix_ag_notify_claim')"
            )
        ).scalar_one()
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ag_alerts WHERE alert_id IN (:a, :b)) AS alerts, "
                "(SELECT count(*) FROM ag_notify_outbox WHERE alert_id IN (:a, :b)) AS notifications, "
                "(SELECT count(*) FROM ag_notify_attempts t JOIN ag_notify_outbox o "
                "ON o.notify_id = t.notify_id WHERE o.alert_id IN (:a, :b)) AS attempts"
            ),
            {"a": alert_ids[0], "b": alert_ids[1]},
        ).mappings().one()
    return {
        "table_count": int(table_count),
        "migration_recorded": bool(migration_recorded),
        "claim_index_present": bool(claim_index_present),
        "alert_count": int(counts["alerts"]),
        "notification_count": int(counts["notifications"]),
        "attempt_count": int(counts["attempts"]),
    }


def _database_name(engine: Any) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT current_database()" )).scalar_one())


def _is_postgresql(engine: Any) -> bool:
    return engine.dialect.name == "postgresql"


def _cleanup(database_url: str, alert_ids: tuple[str, str]) -> None:
    engine = build_engine(database_url)
    try:
        _cleanup_engine(engine, alert_ids)
    finally:
        engine.dispose()


def _cleanup_engine(engine: Any, alert_ids: tuple[str, str]) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            deleted = connection.execute(
                text("DELETE FROM ag_alerts WHERE alert_id IN (:a, :b)"),
                {"a": alert_ids[0], "b": alert_ids[1]},
            ).rowcount
            residue = connection.execute(
                text("SELECT count(*) FROM ag_alerts WHERE alert_id IN (:a, :b)"),
                {"a": alert_ids[0], "b": alert_ids[1]},
            ).scalar_one()
        return {"deleted_alerts": int(deleted or 0), "residue": int(residue)}
    except SQLAlchemyError:
        return {"deleted_alerts": 0, "residue": -1}


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-s148",
        audience="nex-ag",
        roles=["admin"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _fixed_time():
    from datetime import UTC, datetime

    return datetime(2026, 10, 8, 5, 1, tzinfo=UTC)


def _safe_detail(exc: Exception) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "PostgreSQL observability operation failed."
    return str(exc)


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "next_slice": "blocked",
    }


def assert_evidence_redacted(serialized: str, environ: Mapping[str, str]) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized:
        raise ValueError("S148 PostgreSQL evidence contains a raw database URL.")
    if any(value in serialized for key, value in environ.items() if "PASSWORD" in key and value):
        raise ValueError("S148 PostgreSQL evidence contains a password.")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL")
    if status == "SKIPPED":
        return f"s148_observability_postgres=skipped reason={SMOKE_ENV}"
    if status != "PASS":
        return f"s148_observability_postgres=fail reason={evidence.get('failure_code')}"
    observations = dict(evidence.get("observations") or {})
    cleanup = dict(evidence.get("cleanup") or {})
    return (
        "s148_observability_postgres=pass "
        "database=nex_ag_test backend=postgresql "
        f"alerts={observations.get('alert_count', 0)} "
        f"notifications={observations.get('notification_count', 0)} "
        f"attempts={observations.get('attempt_count', 0)} "
        f"cleanup={cleanup.get('residue', -1)} "
        f"checks={sum(bool(value) for value in evidence.get('checks', {}).values())}/18 "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_observability_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
