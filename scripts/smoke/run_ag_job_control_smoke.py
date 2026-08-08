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
    "services/nex-oa",
    "services/nex-ag",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ag.job_control import AgJobControlError  # noqa: E402
from nex_ag.operations import register_job_operation_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    AG_JOB_CONTROL_EVENT_SUCCEEDED,
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    JobRetryPolicy,
    SERVICE_JOB_CONTROL_SCHEMA_VERSION,
    SERVICE_SPECS,
    build_common_job,
    build_service_app,
    build_subject_ref,
    issue_mock_service_token,
    register_service_job_control_routes,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SCHEMA_VERSION = "ag_job_control_smoke.v1"


class LocalAgJobControlClient:
    def __init__(self, service_clients: dict[str, TestClient]) -> None:
        self._service_clients = service_clients

    def get_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            service_id,
            f"/internal/v1/jobs/{job_id}",
            request_id=request_id,
            trace_id=trace_id,
        )

    def cancel_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{job_id}/cancel",
            request_id=request_id,
            trace_id=trace_id,
            payload=_compact_payload({"observed_at": observed_at}),
        )

    def retry_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        error_code: str | None = None,
        detail: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{job_id}/retry",
            request_id=request_id,
            trace_id=trace_id,
            payload=_compact_payload(
                {
                    "error_code": error_code,
                    "detail": detail,
                    "observed_at": observed_at,
                }
            ),
        )

    def replay_job(
        self,
        service_id: str,
        job_id: str,
        *,
        request_id: str,
        trace_id: str,
        replay_job_id: str,
        idempotency_key: str,
        requested_by: str,
        reason: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            service_id,
            f"/internal/v1/jobs/{job_id}/replay",
            request_id=request_id,
            trace_id=trace_id,
            payload=_compact_payload(
                {
                    "replay_job_id": replay_job_id,
                    "idempotency_key": idempotency_key,
                    "requested_by": requested_by,
                    "reason": reason,
                    "observed_at": observed_at,
                }
            ),
        )

    def _request(
        self,
        method: str,
        service_id: str,
        path: str,
        *,
        request_id: str,
        trace_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._service_clients.get(service_id)
        if client is None:
            raise AgJobControlError(
                status_code=404,
                error_code="ag.job_control_service_not_configured",
                detail=f"AG has no local smoke client configured for service: {service_id}",
                retryable=False,
            )
        response = client.request(
            method,
            path,
            json=payload,
            headers=_service_headers(service_id, request_id=request_id, trace_id=trace_id),
        )
        body = response.json()
        if response.status_code >= 400:
            raise AgJobControlError(
                status_code=response.status_code,
                error_code=str(body.get("error_code", "ag.job_control_request_failed")),
                detail=str(body.get("detail", "Job control request failed.")),
                retryable=bool(body.get("retryable", False)),
            )
        return body


def run_ag_job_control_smoke() -> dict[str, Any]:
    cx_queue = _build_cx_queue()
    service_client = _build_cx_service_client(cx_queue)
    audit_store = InMemoryOperationalEventStore()
    ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_job_operation_routes(
        ag_app,
        job_control_client=LocalAgJobControlClient({"nex-cx": service_client}),
        audit_event_store=audit_store,
    )
    ag_client = TestClient(ag_app)

    cancel = _post_json(
        ag_client,
        "/admin/v1/operations/jobs/nex-cx/smoke-job-cancel/cancel",
        {"observed_at": "2026-08-05T00:00:10Z"},
    )
    retry = _post_json(
        ag_client,
        "/admin/v1/operations/jobs/nex-cx/smoke-job-retry/retry",
        {
            "error_code": "operator.retry",
            "detail": "Operator requested retry.",
            "observed_at": "2026-08-05T00:00:11Z",
        },
    )
    replay = _post_json(
        ag_client,
        "/admin/v1/operations/jobs/nex-cx/smoke-job-replay/replay",
        {
            "replay_job_id": "smoke-job-replay-001",
            "idempotency_key": "smoke-idem-replay-001",
            "requested_by": "operator-smoke",
            "reason": "operator smoke replay",
            "observed_at": "2026-08-05T00:00:14Z",
        },
    )
    audit_events = audit_store.list_events(service_id="nex-ag", limit=10)
    checks = _checks(
        cancel=cancel,
        retry=retry,
        replay=replay,
        cancel_job=cx_queue.get_job("smoke-job-cancel"),
        retry_job=cx_queue.get_job("smoke-job-retry"),
        replay_source_job=cx_queue.get_job("smoke-job-replay"),
        replay_job=cx_queue.get_job("smoke-job-replay-001"),
        audit_events=audit_events,
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "trace_id": TRACE_ID,
        "actions": ["cancel", "retry", "replay"],
        "projection_versions": {
            "cancel": cancel.get("projection_schema_version"),
            "retry": retry.get("projection_schema_version"),
            "replay": replay.get("projection_schema_version"),
            "service_response": replay.get("service_response", {}).get(
                "job_control_schema_version"
            ),
        },
        "job_statuses": {
            "cancel": (cx_queue.get_job("smoke-job-cancel") or {}).get("status"),
            "retry": (cx_queue.get_job("smoke-job-retry") or {}).get("status"),
            "replay_source": (cx_queue.get_job("smoke-job-replay") or {}).get("status"),
            "replay": (cx_queue.get_job("smoke-job-replay-001") or {}).get("status"),
        },
        "audit_event_count": len(audit_events),
        "checks": checks,
    }


def _build_cx_queue() -> InMemoryJobQueue:
    queue = InMemoryJobQueue()
    queue.enqueue(
        _sample_job(
            job_id="smoke-job-cancel",
            idempotency_key="smoke-idem-cancel",
        )
    )
    queue.enqueue(
        _sample_job(
            job_id="smoke-job-retry",
            idempotency_key="smoke-idem-retry",
            max_attempts=2,
        )
    )
    replay_source_job = _sample_job(
        job_id="smoke-job-replay",
        idempotency_key="smoke-idem-replay-source",
        max_attempts=1,
    )
    replay_source_job["payload"] = {"source_file_id": "source-smoke-001"}
    queue.enqueue(replay_source_job)
    queue.start_job("smoke-job-retry", updated_at="2026-08-05T00:00:09Z")
    queue.start_job("smoke-job-replay", updated_at="2026-08-05T00:00:12Z")
    queue.retry_job(
        "smoke-job-replay",
        error={
            "error_code": "cx.parser.failed",
            "detail": "Private parser details stay service-local.",
        },
        failed_at="2026-08-05T00:00:13Z",
    )
    return queue


def _build_cx_service_client(queue: InMemoryJobQueue) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_service_job_control_routes(
        app,
        service_id="nex-cx",
        job_queue=queue,
        retry_policy=JobRetryPolicy(initial_delay_seconds=5, max_delay_seconds=10),
    )
    return TestClient(app)


def _sample_job(**overrides: Any) -> dict[str, Any]:
    return build_common_job(
        job_id=overrides.pop("job_id", "smoke-job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop(
            "subject_ref",
            build_subject_ref("cx.document", "doc-smoke-001"),
        ),
        idempotency_key=overrides.pop("idempotency_key", "smoke-idem-001"),
        created_at=overrides.pop("created_at", "2026-08-05T00:00:00Z"),
        max_attempts=overrides.pop("max_attempts", 2),
        links=overrides.pop("links", {"document": "/api/v1/documents/doc-smoke-001"}),
        **overrides,
    )


def _post_json(
    client: TestClient,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(path, json=payload, headers=_ag_headers())
    response.raise_for_status()
    return response.json()


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
    }


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _checks(
    *,
    cancel: dict[str, Any],
    retry: dict[str, Any],
    replay: dict[str, Any],
    cancel_job: dict[str, Any] | None,
    retry_job: dict[str, Any] | None,
    replay_source_job: dict[str, Any] | None,
    replay_job: dict[str, Any] | None,
    audit_events: list[dict[str, Any]],
) -> dict[str, bool]:
    return {
        "cancel_dispatch_projection": (
            cancel["projection_schema_version"] == "ag_job_control_dispatch.v1"
            and cancel["summary"]["action"] == "cancel"
            and cancel["summary"]["job_status"] == "CANCELLED"
        ),
        "retry_dispatch_projection": (
            retry["projection_schema_version"] == "ag_job_control_dispatch.v1"
            and retry["service_response"]["job_control_schema_version"]
            == SERVICE_JOB_CONTROL_SCHEMA_VERSION
            and retry["summary"]["action"] == "retry"
            and retry["summary"]["job_status"] == "QUEUED"
        ),
        "replay_dispatch_projection": (
            replay["projection_schema_version"] == "ag_job_control_dispatch.v1"
            and replay["service_response"]["job_control_schema_version"]
            == SERVICE_JOB_CONTROL_SCHEMA_VERSION
            and replay["summary"]["action"] == "replay"
            and replay["summary"]["job_status"] == "QUEUED"
            and replay["service_response"]["replay"]["source_job"]["dead_lettered"] is True
            and replay["service_response"]["replay"]["replay_job_id"]
            == "smoke-job-replay-001"
        ),
        "service_queue_mutated": (
            cancel_job is not None
            and cancel_job["status"] == "CANCELLED"
            and retry_job is not None
            and retry_job["status"] == "QUEUED"
            and retry_job["available_at"] == "2026-08-05T00:00:16Z"
            and replay_source_job is not None
            and replay_source_job["status"] == "FAILED"
            and replay_source_job["error"]["dead_lettered"] is True
            and replay_job is not None
            and replay_job["status"] == "QUEUED"
            and replay_job["replay_lineage"]["source_job_id"] == "smoke-job-replay"
        ),
        "audit_events_recorded": (
            len(audit_events) == 3
            and {event["event_type"] for event in audit_events}
            == {AG_JOB_CONTROL_EVENT_SUCCEEDED}
            and {event["details"]["action"] for event in audit_events}
            == {"cancel", "retry", "replay"}
        ),
        "operator_projection_redacted": "payload" not in json.dumps(
            {"cancel": cancel, "retry": retry, "replay": replay},
            ensure_ascii=False,
        )
        and "source-smoke-001" not in json.dumps(replay, ensure_ascii=False),
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_job_control_smoke=pass "
            f"actions={len(evidence['actions'])} "
            f"audit_events={evidence['audit_event_count']} "
            f"cancel_status={evidence['job_statuses']['cancel']} "
            f"retry_status={evidence['job_statuses']['retry']} "
            f"replay_status={evidence['job_statuses']['replay']}"
        )
    return "ag_job_control_smoke=fail"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run mock-first AG job control smoke.")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_job_control_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
