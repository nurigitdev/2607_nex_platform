#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-ag",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ag.operations import (  # noqa: E402
    AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
    AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
    register_service_log_routes,
)
from nex_ag.service_log_retention import AgServiceLogRetentionError  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION,
    SERVICE_SPECS,
    build_service_app,
    build_service_log_entry,
    issue_mock_service_token,
    register_service_log_retention_routes,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SCHEMA_VERSION = "ag_service_log_retention_smoke.v1"


class LocalAgServiceLogRetentionClient:
    def __init__(self, service_clients: dict[str, TestClient]) -> None:
        self._service_clients = service_clients
        self.calls: list[dict[str, Any]] = []

    def purge_logs(
        self,
        service_id: str,
        *,
        request_id: str,
        trace_id: str,
        retention_cutoff: str,
        retention_days: int | None = None,
        checked_at: str | None = None,
        dry_run: bool = True,
        delete_enabled: bool = False,
        max_delete_count: int | None = None,
        requested_by: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "service_id": service_id,
                "dry_run": dry_run,
                "delete_enabled": delete_enabled,
                "max_delete_count": max_delete_count,
            }
        )
        return self._request(
            service_id,
            payload=_compact_payload(
                {
                    "retention_cutoff": retention_cutoff,
                    "retention_days": retention_days,
                    "checked_at": checked_at,
                    "dry_run": dry_run,
                    "delete_enabled": delete_enabled,
                    "max_delete_count": max_delete_count,
                    "requested_by": requested_by,
                    "idempotency_key": idempotency_key,
                }
            ),
            request_id=request_id,
            trace_id=trace_id,
        )

    def _request(
        self,
        service_id: str,
        *,
        payload: dict[str, Any],
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        client = self._service_clients.get(service_id)
        if client is None:
            raise AgServiceLogRetentionError(
                status_code=404,
                error_code="ag.service_log_retention_service_not_configured",
                detail=(
                    "AG has no local smoke client configured for service: "
                    f"{service_id}"
                ),
                retryable=False,
            )
        response = client.post(
            "/internal/v1/service-logs/retention/purge",
            json=payload,
            headers=_service_headers(
                service_id,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        body = response.json()
        if response.status_code >= 400:
            raise AgServiceLogRetentionError(
                status_code=response.status_code,
                error_code=str(
                    body.get(
                        "error_code",
                        "ag.service_log_retention_request_failed",
                    )
                ),
                detail=str(body.get("detail", "Service log retention request failed.")),
                retryable=bool(body.get("retryable", False)),
            )
        return body


def run_ag_service_log_retention_smoke() -> dict[str, Any]:
    store = _build_cx_log_store()
    service_client = _build_cx_service_client(store)
    local_client = LocalAgServiceLogRetentionClient({"nex-cx": service_client})
    audit_store = InMemoryOperationalEventStore()
    ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_service_log_routes(
        ag_app,
        retention_control_client=local_client,
        audit_event_store=audit_store,
    )
    ag_client = TestClient(ag_app)

    dry_run = _post_json(
        ag_client,
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        {
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "checked_at": "2026-08-05T00:00:00Z",
            "retention_days": 30,
            "max_delete_count": 1,
            "idempotency_key": "smoke-retention-dry-run",
        },
    )
    blocked = _post_json(
        ag_client,
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        {
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "checked_at": "2026-08-05T00:00:00Z",
            "dry_run": False,
            "idempotency_key": "smoke-retention-blocked",
        },
    )
    execute = _post_json(
        ag_client,
        "/admin/v1/operations/logs/retention/nex-cx/purge",
        {
            "retention_cutoff": "2026-07-06T00:00:00Z",
            "checked_at": "2026-08-05T00:00:00Z",
            "dry_run": False,
            "delete_enabled": True,
            "max_delete_count": 1,
            "requested_by": {
                "actor_type": "service",
                "actor_id": "nex-ag",
                "service_id": "nex-ag",
            },
            "idempotency_key": "smoke-retention-execute",
        },
    )
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    checks = _checks(
        dry_run=dry_run,
        blocked=blocked,
        execute=execute,
        old_deleted=store.get_log("smoke-log-old-001") is None,
        old_remaining=store.get_log("smoke-log-old-002") is not None,
        fresh_remaining=store.get_log("smoke-log-fresh") is not None,
        audit_events=audit_events,
        local_calls=local_client.calls,
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "trace_id": TRACE_ID,
        "actions": ["dry_run", "blocked", "execute"],
        "projection_versions": {
            "dry_run": dry_run.get("projection_schema_version"),
            "execute": execute.get("projection_schema_version"),
            "service_response": execute.get("service_response", {}).get(
                "retention_execution_schema_version"
            ),
        },
        "http_statuses": {
            "dry_run": dry_run["_http_status"],
            "blocked": blocked["_http_status"],
            "execute": execute["_http_status"],
        },
        "counts": {
            "candidate_count": execute.get("summary", {}).get("candidate_count"),
            "deleted_count": execute.get("summary", {}).get("deleted_count"),
            "audit_events": len(audit_events),
            "service_calls": len(local_client.calls),
        },
        "checks": checks,
    }


def _checks(
    *,
    dry_run: dict[str, Any],
    blocked: dict[str, Any],
    execute: dict[str, Any],
    old_deleted: bool,
    old_remaining: bool,
    fresh_remaining: bool,
    audit_events: list[dict[str, Any]],
    local_calls: list[dict[str, Any]],
) -> dict[str, bool]:
    return {
        "dry_run_dispatch_succeeded": (
            dry_run["_http_status"] == 200
            and dry_run["projection_schema_version"]
            == "ag_service_log_retention_dispatch.v1"
            and dry_run["summary"]["deleted_count"] == 0
        ),
        "blocked_before_service_call": (
            blocked["_http_status"] == 409
            and blocked["error_code"]
            == "ag.service_log_retention_delete_not_enabled"
            and len(local_calls) == 2
        ),
        "execute_dispatch_deleted_one": (
            execute["_http_status"] == 200
            and execute["summary"]["deleted_count"] == 1
            and execute["service_response"]["retention_execution_schema_version"]
            == SERVICE_LOG_RETENTION_EXECUTION_SCHEMA_VERSION
        ),
        "store_state_guarded": old_deleted and old_remaining and fresh_remaining,
        "audit_events_recorded": (
            len(audit_events) == 3
            and [event["event_type"] for event in audit_events]
            == [
                AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
                AG_SERVICE_LOG_RETENTION_EVENT_FAILED,
                AG_SERVICE_LOG_RETENTION_EVENT_SUCCEEDED,
            ]
        ),
        "private_values_redacted": "Bearer private" not in json.dumps(
            {"dry_run": dry_run, "blocked": blocked, "execute": execute},
            ensure_ascii=False,
        ),
    }


def _build_cx_log_store() -> InMemoryServiceLogStore:
    store = InMemoryServiceLogStore()
    for log_id, observed_at in (
        ("smoke-log-old-001", "2026-06-01T00:00:00Z"),
        ("smoke-log-old-002", "2026-06-02T00:00:00Z"),
        ("smoke-log-fresh", "2026-08-04T00:00:00Z"),
    ):
        store.append(
            build_service_log_entry(
                log_id=log_id,
                service_id="nex-cx",
                severity="ERROR" if "old" in log_id else "INFO",
                logger_name="nex_cx.retention_smoke",
                message="Retention smoke structured service log.",
                trace_id=TRACE_ID,
                request_id=REQUEST_ID,
                job_id="smoke-retention-job",
                subject_ref={"type": "cx.document", "id": log_id},
                attributes={"authorization": "Bearer private", "log_id": log_id},
                observed_at=observed_at,
            )
        )
    return store


def _build_cx_service_client(store: InMemoryServiceLogStore) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_service_log_retention_routes(app, service_id="nex-cx", store=store)
    return TestClient(app)


def _post_json(
    client: TestClient,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(path, json=payload, headers=_ag_headers())
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def _ag_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _service_headers(
    service_id: str,
    *,
    request_id: str,
    trace_id: str,
) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience=service_id)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": "nex-ag",
    }


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def summary_line(evidence: dict[str, Any]) -> str:
    status = str(evidence.get("status", "FAIL")).lower()
    if status != "pass":
        return "ag_service_log_retention_smoke=fail"
    counts = evidence["counts"]
    statuses = evidence["http_statuses"]
    return (
        "ag_service_log_retention_smoke=pass "
        f"actions={len(evidence['actions'])} "
        f"audit_events={counts['audit_events']} "
        f"dry_run_status={statuses['dry_run']} "
        f"blocked_status={statuses['blocked']} "
        f"execute_deleted={counts['deleted_count']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_service_log_retention_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
