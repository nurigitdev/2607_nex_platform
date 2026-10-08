#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_ag.platform_alert_repository import SqlAlchemyPlatformAlertRepository
from nex_ag.platform_alerting import AlertRecord, AlertRoutingPolicy, route_alert
from nex_ag.platform_notification_delivery import (
    LocalNotificationTransport,
    NotificationDeliveryPolicy,
    ScriptedMockNotificationTransport,
    execute_notification_batch,
)
from run_s148_alert_persistence_restart import SQLITE_SCHEMA


def run_mock_notification_delivery() -> dict[str, Any]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    repository = SqlAlchemyPlatformAlertRepository(factory)

    local = _insert(repository, "a", "local_only", None, "2026-10-08T02:00:00Z")
    local_run = execute_notification_batch(
        repository,
        worker_id="worker:s148-local",
        attempted_at="2026-10-08T02:00:01Z",
        policy=NotificationDeliveryPolicy("local_only"),
        transports={"LOCAL": LocalNotificationTransport()},
    )

    private = _insert(
        repository, "b", "private_network", "incident-private", "2026-10-08T02:01:00Z"
    )
    private_run = execute_notification_batch(
        repository,
        worker_id="worker:s148-private",
        attempted_at="2026-10-08T02:01:01Z",
        policy=NotificationDeliveryPolicy("private_network"),
        transports={
            "LOCAL": LocalNotificationTransport(),
            "INTERNAL_WEBHOOK": ScriptedMockNotificationTransport((202,)),
        },
    )

    internet = _insert(
        repository, "c", "internet_connected", "incident-external", "2026-10-08T02:02:00Z"
    )
    internet_transport = ScriptedMockNotificationTransport((503, 202))
    internet_policy = NotificationDeliveryPolicy(
        "internet_connected", retry_base_seconds=10, retry_max_seconds=30
    )
    internet_first = execute_notification_batch(
        repository,
        worker_id="worker:s148-internet",
        attempted_at="2026-10-08T02:02:01Z",
        policy=internet_policy,
        transports={
            "LOCAL": LocalNotificationTransport(),
            "EXTERNAL_WEBHOOK": internet_transport,
        },
    )
    internet_second = execute_notification_batch(
        repository,
        worker_id="worker:s148-internet",
        attempted_at="2026-10-08T02:02:11Z",
        policy=internet_policy,
        transports={"EXTERNAL_WEBHOOK": internet_transport},
    )

    all_notifications = repository.list_notifications(limit=20)
    attempts = {
        item.notify_id: repository.list_attempts(item.notify_id)
        for item in all_notifications
    }
    all_results = (
        local_run["results"]
        + private_run["results"]
        + internet_first["results"]
        + internet_second["results"]
    )
    local_results = [item for item in all_results if item["channel"] == "LOCAL"]
    mock_results = [item for item in all_results if item["acceptance_status"] == "MOCK_ACCEPTED"]
    checks = {
        "local_mode_one_intent": len(local) == 1,
        "private_mode_two_intents": len(private) == 2,
        "internet_mode_two_intents": len(internet) == 2,
        "local_delivery_real": len(local_results) == 3
        and all(item["delivery_state"] == "DELIVERED" for item in local_results),
        "private_mock_accepted": any(
            item["channel"] == "INTERNAL_WEBHOOK" for item in mock_results
        ),
        "internet_retry_scheduled": any(
            item["channel"] == "EXTERNAL_WEBHOOK"
            and item["delivery_state"] == "RETRY_WAIT"
            for item in internet_first["results"]
        ),
        "internet_mock_accepted_after_retry": any(
            item["acceptance_status"] == "MOCK_ACCEPTED"
            for item in internet_second["results"]
        ),
        "mock_not_live_delivery": all(
            item["delivery_state"] == "BLOCKED"
            and item["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
            for item in mock_results
        ),
        "all_receipts_hashed": all(
            item["receipt_digest"] is not None
            and item["receipt_digest"].startswith("sha256:")
            for item in all_results
        ),
        "attempt_history_complete": sum(len(items) for items in attempts.values()) == 6,
        "internet_has_two_attempts": sorted(len(items) for items in attempts.values()) == [1, 1, 1, 1, 2],
        "terminal_state_counts": _state_counts(all_notifications)
        == {"BLOCKED": 2, "DELIVERED": 3},
        "no_private_payload": all(item["private_payload_included"] is False for item in all_results),
        "no_endpoint_material": not any(
            forbidden in json.dumps(all_results, sort_keys=True).lower()
            for forbidden in ("http://", "https://", "authorization", "api-key")
        ),
        "mock_only_external": all(
            item["external_activation"] == "EXTERNAL_NOT_ACTIVATED"
            for item in mock_results
        ),
    }
    engine.dispose()
    passed = all(checks.values())
    return {
        "schema_version": "s148_mock_notification_delivery.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "notification_count": len(all_notifications),
            "attempt_count": sum(len(items) for items in attempts.values()),
            "mock_accepted_count": len(mock_results),
            "local_delivered_count": len(local_results),
            "check_count": len(checks),
        },
        "external_activation": "EXTERNAL_NOT_ACTIVATED",
        "next_slice": "1479" if passed else "blocked",
    }


def _insert(
    repository: SqlAlchemyPlatformAlertRepository,
    suffix: str,
    mode: str,
    external_alias: str | None,
    created_at: str,
) -> list[Any]:
    alert = AlertRecord(
        alert_id=f"alert:{suffix}",
        dedup_key="sha256:" + suffix * 64,
        rule_id=f"rule:{suffix}",
        policy_id=f"slo:{suffix}",
        service_id="nex-ag",
        state="FIRING",
        severity="CRITICAL",
        reason_code="SLO_CRITICAL_BURN",
        occurrence_count=1,
        first_observed_at=created_at,
        last_observed_at=created_at,
        accountable_owner="platform-operations",
        runbook_ref="runbook:nex-ag:availability",
    )
    decision = route_alert(
        alert,
        AlertRoutingPolicy(mode, "test", "ag-local", external_alias),
    )
    return repository.insert_alert_with_notifications(
        alert, decision["intents"], created_at=created_at
    )[1]


def _state_counts(notifications: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in notifications:
        counts[item.delivery_state] = counts.get(item.delivery_state, 0) + 1
    return counts


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_mock_notification_delivery="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"notifications={summary.get('notification_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"local={summary.get('local_delivered_count', 0)} "
        f"mock={summary.get('mock_accepted_count', 0)} "
        f"checks={summary.get('check_count', 0)}/15 "
        f"activation={result.get('external_activation', 'unknown')} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_mock_notification_delivery()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
