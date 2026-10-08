#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_ag.platform_alert_repository import SqlAlchemyPlatformAlertRepository
from nex_ag.platform_alerting import AlertRoutingPolicy, AlertRule, apply_slo_evaluation, route_alert

SQLITE_SCHEMA = """
CREATE TABLE ag_alerts (
    alert_id TEXT PRIMARY KEY, dedup_key TEXT NOT NULL UNIQUE,
    rule_id TEXT NOT NULL, policy_id TEXT NOT NULL, service_id TEXT NOT NULL,
    alert_state TEXT NOT NULL, severity TEXT NOT NULL, reason_code TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL, state_revision INTEGER NOT NULL,
    first_observed_at TEXT NOT NULL, last_observed_at TEXT NOT NULL,
    accountable_owner TEXT NOT NULL, runbook_ref TEXT NOT NULL,
    suppression_until TEXT, acknowledged_by_hash TEXT
);
CREATE TABLE ag_notify_outbox (
    notify_id TEXT PRIMARY KEY, alert_id TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL UNIQUE, channel TEXT NOT NULL,
    route_alias TEXT NOT NULL, payload_hash TEXT NOT NULL,
    delivery_state TEXT NOT NULL, attempt_count INTEGER NOT NULL,
    next_attempt_at TEXT, lease_owner TEXT, lease_expires_at TEXT,
    last_error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE TABLE ag_notify_attempts (
    attempt_id TEXT PRIMARY KEY, notify_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL, outcome TEXT NOT NULL,
    response_code INTEGER, receipt_digest TEXT, error_code TEXT,
    attempted_at TEXT NOT NULL, UNIQUE (notify_id, attempt_number)
);
"""
DIGEST = "sha256:" + "d" * 64


def run_alert_persistence_restart() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-s148-") as directory:
        path = Path(directory) / "alerts.db"
        engine = create_engine(f"sqlite+pysqlite:///{path}")
        with engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        repository = _repository(engine)
        rule = AlertRule(
            rule_id="rule:nex-cx:index-freshness",
            policy_id="slo:nex-cx:index-freshness",
            service_id="nex-cx",
            minimum_consecutive_failures=1,
            grouping_window_seconds=300,
        )
        evaluation = {
            "policy_id": rule.policy_id,
            "service_id": rule.service_id,
            "status": "BREACHED",
            "reason_code": "SLO_CRITICAL_BURN",
            "accountable_owner": "content",
            "runbook_ref": "runbook:nex-cx:index-freshness",
        }
        alert = apply_slo_evaluation(rule, evaluation, evaluated_at="2026-10-08T01:00:00Z")
        assert alert is not None
        routing = route_alert(
            alert,
            AlertRoutingPolicy(
                "private_network", "test", "ag-local", "incident-private"
            ),
        )
        _, notifications = repository.insert_alert_with_notifications(
            alert, routing["intents"], created_at="2026-10-08T01:00:00Z"
        )
        claimed = repository.claim_notifications(
            worker_id="worker:s148", claimed_at="2026-10-08T01:00:01Z", lease_seconds=30
        )
        delivered, _ = repository.record_attempt(
            notify_id=claimed[1].notify_id,
            worker_id="worker:s148",
            outcome="DELIVERED",
            attempted_at="2026-10-08T01:00:05Z",
            response_code=202,
            receipt_digest=DIGEST,
        )
        engine.dispose()

        restarted_engine = create_engine(f"sqlite+pysqlite:///{path}")
        restarted = _repository(restarted_engine)
        recovered_alert = restarted.get_alert(alert.alert_id)
        before_expiry = restarted.claim_notifications(
            worker_id="worker:restart",
            claimed_at="2026-10-08T01:00:20Z",
            lease_seconds=30,
        )
        recovered_claim = restarted.claim_notifications(
            worker_id="worker:restart",
            claimed_at="2026-10-08T01:00:31Z",
            lease_seconds=30,
        )
        retry, _ = restarted.record_attempt(
            notify_id=recovered_claim[0].notify_id,
            worker_id="worker:restart",
            outcome="RETRY_WAIT",
            attempted_at="2026-10-08T01:00:32Z",
            response_code=503,
            error_code="INCIDENT_PROVIDER_UNAVAILABLE",
            next_attempt_at="2026-10-08T01:01:00Z",
        )
        before_retry = restarted.claim_notifications(
            worker_id="worker:retry", claimed_at="2026-10-08T01:00:59Z", lease_seconds=30
        )
        retry_claim = restarted.claim_notifications(
            worker_id="worker:retry", claimed_at="2026-10-08T01:01:00Z", lease_seconds=30
        )
        retried, _ = restarted.record_attempt(
            notify_id=retry_claim[0].notify_id,
            worker_id="worker:retry",
            outcome="DELIVERED",
            attempted_at="2026-10-08T01:01:01Z",
            response_code=202,
            receipt_digest=DIGEST,
        )
        resolved = apply_slo_evaluation(
            rule,
            {**evaluation, "status": "HEALTHY", "reason_code": "SLO_OBJECTIVE_MET"},
            previous=alert,
            evaluated_at="2026-10-08T01:01:02Z",
        )
        assert resolved is not None
        restarted.update_alert(resolved, expected_state_revision=1)
        final_alert = restarted.get_alert(alert.alert_id)
        attempts = {
            item.notify_id: restarted.list_attempts(item.notify_id) for item in notifications
        }
        migration = (
            ROOT
            / "database"
            / "nex-ag"
            / "migrations"
            / "1477_ag_platform_alert_persistence.sql"
        ).read_text(encoding="utf-8")
        with restarted_engine.begin() as connection:
            deleted_attempts = connection.execute(text("DELETE FROM ag_notify_attempts")).rowcount
            deleted_outbox = connection.execute(text("DELETE FROM ag_notify_outbox")).rowcount
            deleted_alerts = connection.execute(text("DELETE FROM ag_alerts")).rowcount
            residue = sum(
                connection.execute(text(f"SELECT COUNT(*) FROM {table}" )).scalar_one()
                for table in ("ag_alerts", "ag_notify_outbox", "ag_notify_attempts")
            )
        restarted_engine.dispose()

    checks = {
        "migration_defines_concise_tables": all(
            table in migration for table in ("ag_alerts", "ag_notify_outbox", "ag_notify_attempts")
        ) and all(len(table) <= 30 for table in ("ag_alerts", "ag_notify_outbox", "ag_notify_attempts")),
        "migration_has_claim_index": "ix_ag_notify_claim" in migration,
        "alert_and_intents_persisted": recovered_alert is not None and len(notifications) == 2,
        "initial_claim_bounded": len(claimed) == 2,
        "one_notification_delivered": delivered.delivery_state == "DELIVERED",
        "active_lease_not_stolen": before_expiry == [],
        "expired_lease_recovered": len(recovered_claim) == 1,
        "retry_wait_recorded": retry.delivery_state == "RETRY_WAIT",
        "retry_schedule_respected": before_retry == [] and len(retry_claim) == 1,
        "retry_eventually_delivered": retried.delivery_state == "DELIVERED",
        "append_only_attempts_recovered": sorted(len(items) for items in attempts.values()) == [1, 2],
        "alert_revision_recovered": final_alert is not None and final_alert.state == "RESOLVED" and final_alert.state_revision == 2,
        "cleanup_exact": (deleted_attempts, deleted_outbox, deleted_alerts) == (3, 2, 1),
        "cleanup_zero_residue": residue == 0,
    }
    passed = all(checks.values())
    return {
        "schema_version": "s148_alert_persistence_restart.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "alert_count": 1,
            "notification_count": len(notifications),
            "attempt_count": sum(len(items) for items in attempts.values()),
            "recovered_lease_count": len(recovered_claim),
            "cleanup_residue": int(residue),
            "check_count": len(checks),
        },
        "next_slice": "1478" if passed else "blocked",
    }


def _repository(engine) -> SqlAlchemyPlatformAlertRepository:
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    return SqlAlchemyPlatformAlertRepository(factory)


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_alert_persistence_restart="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"alerts={summary.get('alert_count', 0)} "
        f"notifications={summary.get('notification_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"recovered={summary.get('recovered_lease_count', 0)} "
        f"cleanup={summary.get('cleanup_residue', -1)} "
        f"checks={summary.get('check_count', 0)}/14 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_alert_persistence_restart()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
