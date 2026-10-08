#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_ag.platform_alert_repository import SqlAlchemyPlatformAlertRepository
from nex_ag.platform_alerting import AlertRecord
from nex_ag.platform_observability_operations import (
    PLATFORM_OBSERVABILITY_ALERTS_PATH,
    PLATFORM_OBSERVABILITY_DASHBOARD_PATH,
    PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH,
    PLATFORM_OBSERVABILITY_SLO_PATH,
    PlatformObservabilityOperations,
    register_platform_observability_routes,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)
from run_s148_alert_persistence_restart import SQLITE_SCHEMA

NOW = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
TRACE_ID = "b" * 32
OPERATOR_HASH = "sha256:" + "e" * 64


def run_observability_api() -> dict[str, Any]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        for statement in SQLITE_SCHEMA.split(";"):
            if statement.strip():
                connection.execute(text(statement))
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    repository = SqlAlchemyPlatformAlertRepository(factory)
    _insert(repository, "a", "nex-cx", ("LOCAL", "EXTERNAL_WEBHOOK"))
    _insert(repository, "b", "nex-ag", ())
    events = InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_platform_observability_routes(
        app,
        operations=PlatformObservabilityOperations(
            repository, notification_mode="internet_connected"
        ),
        audit_event_store=events,
        clock=lambda: NOW,
    )
    client = TestClient(app)
    headers = _headers()
    dashboard = client.get(PLATFORM_OBSERVABILITY_DASHBOARD_PATH, headers=headers)
    slos = client.get(PLATFORM_OBSERVABILITY_SLO_PATH, headers=headers)
    alerts = client.get(PLATFORM_OBSERVABILITY_ALERTS_PATH, headers=headers)
    notifications = client.get(
        PLATFORM_OBSERVABILITY_NOTIFICATIONS_PATH, headers=headers
    )
    acknowledged = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:a/acknowledge",
        headers=headers,
        json={"operator_ref_hash": OPERATOR_HASH},
    )
    suppressed = client.post(
        PLATFORM_OBSERVABILITY_ALERTS_PATH + "/alert:b/suppress",
        headers=headers,
        json={"duration_seconds": 300, "reason_code": "MAINTENANCE_WINDOW"},
    )
    unauthorized = client.get(PLATFORM_OBSERVABILITY_DASHBOARD_PATH)
    dashboard_payload = dashboard.json()
    event_items = events.list_events(trace_id=TRACE_ID)
    serialized = json.dumps(
        {
            "dashboard": dashboard_payload,
            "alerts": alerts.json(),
            "notifications": notifications.json(),
        },
        sort_keys=True,
    ).lower()
    checks = {
        "dashboard_protected": dashboard.status_code == 200 and unauthorized.status_code == 401,
        "dashboard_trace_linked": dashboard_payload.get("request_trace_id") == TRACE_ID,
        "dashboard_degraded_honestly": dashboard_payload.get("status") == "DEGRADED",
        "external_not_activated": dashboard_payload.get("external_activation") == "EXTERNAL_NOT_ACTIVATED",
        "five_service_slos_visible": slos.status_code == 200 and len(slos.json().get("items", [])) == 5,
        "no_data_visible": {item["status"] for item in slos.json()["items"]} == {"NO_DATA"},
        "alerts_visible": alerts.status_code == 200 and len(alerts.json().get("items", [])) == 2,
        "notifications_visible": notifications.status_code == 200 and len(notifications.json().get("items", [])) == 2,
        "acknowledgement_persisted": acknowledged.status_code == 200 and acknowledged.json()["alert"]["state"] == "ACKNOWLEDGED",
        "suppression_persisted": suppressed.status_code == 200 and suppressed.json()["alert"]["state"] == "SUPPRESSED",
        "operator_actions_audited": len(event_items) == 2,
        "audit_trace_correlated": all(item.get("trace_id") == TRACE_ID for item in event_items),
        "metadata_only_projection": dashboard_payload.get("private_payload_included") is False,
        "sensitive_material_absent": not any(
            term in serialized
            for term in ("authorization", "password", "api-key", "source_text", "raw_prompt")
        ),
    }
    engine.dispose()
    passed = all(checks.values())
    return {
        "schema_version": "s148_observability_api_smoke.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "slo_count": len(slos.json().get("items", [])),
            "alert_count": len(alerts.json().get("items", [])),
            "notification_count": len(notifications.json().get("items", [])),
            "audit_event_count": len(event_items),
            "check_count": len(checks),
        },
        "external_activation": "EXTERNAL_NOT_ACTIVATED",
        "next_slice": "1480" if passed else "blocked",
    }


def _insert(
    repository: SqlAlchemyPlatformAlertRepository,
    suffix: str,
    service_id: str,
    channels: tuple[str, ...],
) -> None:
    alert = AlertRecord(
        alert_id=f"alert:{suffix}",
        dedup_key="sha256:" + suffix * 64,
        rule_id=f"rule:{suffix}",
        policy_id=f"slo:{suffix}",
        service_id=service_id,
        state="FIRING",
        severity="CRITICAL",
        reason_code="SLO_CRITICAL_BURN",
        occurrence_count=1,
        first_observed_at="2026-10-08T03:59:00Z",
        last_observed_at="2026-10-08T03:59:00Z",
        accountable_owner="platform-operations",
        runbook_ref="runbook:platform:availability",
    )
    intents = [
        {
            "channel": channel,
            "route_alias": f"route-{index}",
            "idempotency_key_hash": "sha256:" + character * 64,
            "payload_hash": "sha256:" + "f" * 64,
        }
        for index, (channel, character) in enumerate(zip(channels, ("c", "d")), start=1)
    ]
    repository.insert_alert_with_notifications(
        alert, intents, created_at="2026-10-08T03:59:00Z"
    )


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0148",
        audience="nex-ag",
        roles=["admin"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_observability_api="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"slos={summary.get('slo_count', 0)} "
        f"alerts={summary.get('alert_count', 0)} "
        f"notifications={summary.get('notification_count', 0)} "
        f"audits={summary.get('audit_event_count', 0)} "
        f"checks={summary.get('check_count', 0)}/14 "
        f"activation={result.get('external_activation', 'unknown')} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_observability_api()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
