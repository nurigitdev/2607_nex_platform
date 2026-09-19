#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    UrllibDispatchProviderHttpTransport,
    build_dispatch_execution_provider_config,
)
from nex_ag.operator_reviews import sha256_text  # noqa: E402
from nex_ag.recovery_notification_delivery import (  # noqa: E402
    build_recovery_notification_delivery_admission,
    build_recovery_notification_dispatch_handoff,
    build_recovery_notification_live_admission,
    persist_recovery_notification_dispatch_handoff,
    run_recovery_notification_delivery_live_once,
)
from nex_ag.recovery_notification_operations import (  # noqa: E402
    build_recovery_notification_delivery_operations_projection,
)
from nex_ag.recovery_notification_policy import (  # noqa: E402
    build_recovery_notification_plan,
)


SCHEMA_VERSION = "ag_recovery_notification_live_loopback_smoke.v1"
SMOKE_ENV = "NEX_AG_RECOVERY_NOTIFICATION_LIVE_LOOPBACK_SMOKE"
SLICE_ID = "0857"
SERVICE_ID = "nex-ag"
REFERENCE_TIME = "2026-09-19T09:00:00Z"
LOOPBACK_TOKEN = "recovery-notification-loopback-token-0857"


def run_ag_recovery_notification_live_loopback_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    server = _RecoveryNotificationLoopbackServer()
    server.start()
    try:
        evidence = _execute_loopback_smoke(server)
        _assert_evidence_redacted(evidence, server.endpoint_url)
        return evidence
    finally:
        server.stop()


def _execute_loopback_smoke(
    server: "_RecoveryNotificationLoopbackServer",
) -> dict[str, Any]:
    provider_config = build_dispatch_execution_provider_config(
        {
            "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            "NEX_AG_NOTIFICATION_WEBHOOK_URL": server.endpoint_url,
            "NEX_AG_NOTIFICATION_SERVICE_TOKEN": LOOPBACK_TOKEN,
            "NEX_AG_DISPATCH_HTTP_MAX_RETRIES": "0",
            "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS": "5",
        }
    )
    plan = build_recovery_notification_plan(
        _recovery_plan_source(),
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=REFERENCE_TIME,
    )
    case = _case_record()
    escalation = _escalation_record()
    admission = build_recovery_notification_delivery_admission(
        plan,
        case,
        escalation,
        channel_type="NOTIFICATION",
        provider_profile="notification-webhook-default",
        admitted_at=REFERENCE_TIME,
    )
    live_admission = build_recovery_notification_live_admission(
        admission,
        provider_config,
        confirm_live_delivery=True,
        admitted_at=REFERENCE_TIME,
    )
    handoff = build_recovery_notification_dispatch_handoff(
        plan,
        admission,
        escalation,
        request_id="request-0857-loopback",
        idempotency_key="idem-0857-loopback",
        created_at=REFERENCE_TIME,
        live_admission=live_admission,
    )
    store = OperatorReviewEscalationDispatchStore()
    persisted = persist_recovery_notification_dispatch_handoff(handoff, store)
    dispatch_id = persisted["dispatch_record"]["dispatch_id"]
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=store,
    )
    execution = run_recovery_notification_delivery_live_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0857-execute",
        provider_config=provider_config,
        live_http_transport=UrllibDispatchProviderHttpTransport(
            endpoint_url=server.endpoint_url,
            bearer_token=LOOPBACK_TOKEN,
        ),
        confirm_run=True,
        executed_at=REFERENCE_TIME,
    )
    final_dispatch = store.get(dispatch_id) or {}
    projection = build_recovery_notification_delivery_operations_projection(
        [final_dispatch]
    )
    loopback = server.observations()
    recent = projection.get("recent") or [{}]
    projected_execution = recent[0].get("execution") or {}
    checks = {
        "one_loopback_request_received": loopback["request_count"] == 1,
        "post_method_received": loopback["method_seen"] == "POST",
        "authorization_header_received": loopback["authorization_header_seen"]
        is True,
        "notification_category_received": loopback["provider_category"]
        == "notification",
        "safe_payload_received": loopback["safe_payload_present"] is True,
        "execution_completed": execution["execution_status"] == "COMPLETED",
        "worker_succeeded": execution["worker_run"]["succeeded_count"] == 1,
        "provider_invoked": execution["delivery"][
            "provider_invocation_performed"
        ]
        is True,
        "dispatch_succeeded": final_dispatch.get("dispatch_status") == "SUCCEEDED",
        "projection_live_http": projected_execution.get("provider_mode")
        == "live_http",
        "projection_http_202": projected_execution.get("http_status_code") == 202,
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None if all(checks.values()) else "checks_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "transport": "local_loopback_http_server",
        "delivery": {
            "channel_type": final_dispatch.get("channel_type"),
            "provider_profile": final_dispatch.get("provider_profile"),
            "dispatch_status": final_dispatch.get("dispatch_status"),
            "execution_status": execution.get("execution_status"),
            "provider_invocation_performed": execution.get("delivery", {}).get(
                "provider_invocation_performed"
            ),
        },
        "projection": {
            "delivery_status": projection.get("delivery_status"),
            "succeeded": projection.get("summary", {}).get("succeeded"),
            "provider_mode": projected_execution.get("provider_mode"),
            "http_status_code": projected_execution.get("http_status_code"),
            "provider_result_hash_present": bool(
                projected_execution.get("provider_result_hash")
            ),
            "response_body_hash_present": bool(
                projected_execution.get("response_body_hash")
            ),
        },
        "loopback": loopback,
        "checks": checks,
        "redaction": {
            "endpoint_value_included": False,
            "authorization_header_value_included": False,
            "provider_token_included": False,
            "raw_notification_payload_included": False,
            "database_url_included": False,
        },
    }


class _RecoveryNotificationLoopbackServer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ag-recovery-notification-live-loopback",
            daemon=True,
        )

    @property
    def endpoint_url(self) -> str:
        return (
            f"http://127.0.0.1:{self._server.server_address[1]}"
            "/recovery-notification"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def observations(self) -> dict[str, Any]:
        record = self.records[0] if self.records else {}
        body = record.get("body") if isinstance(record.get("body"), Mapping) else {}
        return {
            "request_count": len(self.records),
            "method_seen": record.get("method"),
            "path_hash": record.get("path_hash"),
            "authorization_header_seen": bool(
                record.get("authorization_header_seen")
            ),
            "provider_category": body.get("provider_category"),
            "safe_payload_present": isinstance(body.get("safe_payload"), Mapping),
            "request_hash_present": bool(body.get("provider_request_hash")),
        }

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        records = self.records

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                records.append(
                    {
                        "method": "POST",
                        "path_hash": sha256_text(self.path),
                        "authorization_header_seen": bool(
                            self.headers.get("Authorization")
                        ),
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"accepted":true}')

            def log_message(self, *_args: Any) -> None:
                return None

        return Handler


def _recovery_plan_source() -> dict[str, Any]:
    return {
        "projection_schema_version": "recovery-plan.v1",
        "summary": {"liveness_status": "STALE"},
        "daemon_identity": {
            "service_id": SERVICE_ID,
            "worker_id": "ag-dispatch-execution-daemon",
        },
        "recommended_actions": [{"severity": "ERROR"}],
    }


def _case_record() -> dict[str, Any]:
    return {
        "case_id": "case-0857-loopback",
        "target_service": SERVICE_ID,
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def _escalation_record() -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0857-loopback",
        "case_id": "case-0857-loopback",
        "target_service": SERVICE_ID,
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "reason_codes": ["daemon_stale"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
    }


def _assert_evidence_redacted(
    evidence: Mapping[str, Any],
    endpoint_url: str,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)
    forbidden = (
        LOOPBACK_TOKEN,
        endpoint_url,
        "/recovery-notification",
        "Authorization: Bearer",
    )
    if any(value in serialized for value in forbidden):
        raise AssertionError("recovery notification loopback evidence leaked secrets")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "UNKNOWN").lower()
    if status == "skipped":
        return (
            "ag_recovery_notification_live_loopback_smoke=skipped "
            f"reason={evidence.get('skip_reason')}"
        )
    return (
        "ag_recovery_notification_live_loopback_smoke="
        f"{status} transport={evidence.get('transport')} "
        f"requests={evidence.get('loopback', {}).get('request_count')} "
        f"dispatch={evidence.get('delivery', {}).get('dispatch_status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_recovery_notification_live_loopback_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
