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

from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    build_dispatch_execution_provider_config,
    build_dispatch_live_http_transport,
    build_dispatch_live_http_transport_request_plan,
    build_external_incident_dispatch_provider_request,
    execute_dispatch_with_live_http_transport,
)
from nex_ag.operator_reviews import sha256_text  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_incident_loopback_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_INCIDENT_LOOPBACK_SMOKE"
SERVICE_ID = "nex-ag"
SLICE_ID = "0736"
TRACE_ID = "8a840033f3c14e438cf97f877248c99a"
REQUEST_ID = "ag-dispatch-incident-loopback-0736"
REFERENCE_TIME = "2026-09-14T10:36:00Z"
LOOPBACK_TOKEN = "incident-loopback-token-0736"
SAFE_BODY = "Safe incident loopback dispatch body."
TARGET_ID = "incident-target-0736-sensitive"


def run_ag_operator_review_escalation_dispatch_incident_loopback_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    server = _LoopbackIncidentServer()
    server.start()
    try:
        endpoint_url = server.endpoint_url
        provider_config = build_dispatch_execution_provider_config(
            {
                "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
                "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
                "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": endpoint_url,
                "NEX_AG_EXTERNAL_INCIDENT_TOKEN": LOOPBACK_TOKEN,
                "NEX_AG_DISPATCH_HTTP_MAX_RETRIES": "0",
                "NEX_AG_DISPATCH_HTTP_TIMEOUT_SECONDS": "5",
            }
        )
        dispatch = _incident_dispatch()
        provider_request = build_external_incident_dispatch_provider_request(
            dispatch,
            provider_config=provider_config,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            requested_at=REFERENCE_TIME,
        )
        request_plan = build_dispatch_live_http_transport_request_plan(
            provider_request,
            endpoint_url=endpoint_url,
            attempt_number=1,
            bearer_token_configured=True,
        )
        result = execute_dispatch_with_live_http_transport(
            dispatch,
            transport=build_dispatch_live_http_transport(
                provider_request,
                endpoint_url=endpoint_url,
                bearer_token=LOOPBACK_TOKEN,
            ),
            provider_config=provider_config,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            executed_at=REFERENCE_TIME,
        )
        observations = _observations(server.records, provider_request)
        checks = {
            "loopback_received_one_request": observations["request_count"] == 1,
            "loopback_used_post": observations["method_seen"] == "POST",
            "authorization_header_seen": observations["authorization_header_seen"]
            is True,
            "request_hash_matched": observations["body_request_hash_matches"] is True,
            "body_category_incident": (
                observations["body_provider_category"] == "external_incident"
            ),
            "target_id_hashed": observations["target_id_hashed"] is True,
            "safe_payload_hash_matched": (
                observations["incident_payload_hash_matches"] is True
            ),
            "result_succeeded": result.get("execution_status") == "SUCCEEDED",
            "result_status_code_created": result.get("http_status_code") == 201,
            "request_plan_redacted": request_plan.get("endpoint_hint")
            == _loopback_endpoint_hint(server.port),
        }
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "failure_code": None if all(checks.values()) else "checks_failed",
            "slice": SLICE_ID,
            "service": SERVICE_ID,
            "transport": "local_loopback_http_server",
            "provider_category": "external_incident",
            "request_plan": request_plan,
            "result": {
                "execution_status": result.get("execution_status"),
                "provider_mode": result.get("provider_mode"),
                "provider_category": result.get("provider_category"),
                "provider_profile": result.get("provider_profile"),
                "http_status_code": result.get("http_status_code"),
                "attempt_count": result.get("attempt_count"),
                "response_body_hash": result.get("response_body_hash"),
                "provider_result_hash": result.get("provider_result_hash"),
            },
            "observations": observations,
            "checks": checks,
        }
        _assert_evidence_redacted(evidence, server.port)
        return evidence
    finally:
        server.stop()


class _LoopbackIncidentServer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ag-incident-loopback-smoke",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def endpoint_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/dispatch/incident"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

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
                        "content_type": self.headers.get("Content-Type"),
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"created":true}')

            def log_message(self, *_: Any) -> None:
                return None

        return Handler


def _incident_dispatch() -> dict[str, Any]:
    return {
        "dispatch_id": "dispatch-0736-incident-loopback",
        "escalation_id": "escalation-0736-loopback",
        "case_id": "case-0736-loopback",
        "dispatch_status": "PENDING",
        "dispatch_intent": "OPEN_INCIDENT",
        "channel_type": "INCIDENT",
        "provider_profile": "external-incident-default",
        "provider_ref": {"provider_id": "incident-loopback-provider"},
        "target_service": "nex-ag",
        "target_kind": "operator_review_case",
        "target_id": TARGET_ID,
        "safe_subject": "S74 incident loopback",
        "safe_body_preview": SAFE_BODY,
        "safe_body_hash": sha256_text(SAFE_BODY),
        "provider_payload_hash": sha256_text("incident-loopback-provider-payload"),
        "reason_codes": ["s74_loopback_smoke"],
    }


def _observations(
    records: list[dict[str, Any]],
    provider_request: Mapping[str, Any],
) -> dict[str, Any]:
    record = records[0] if records else {}
    body = record.get("body") if isinstance(record.get("body"), Mapping) else {}
    incident_payload = (
        body.get("incident_payload") if isinstance(body, Mapping) else {}
    )
    target_ref = (
        incident_payload.get("target_ref")
        if isinstance(incident_payload, Mapping)
        else {}
    )
    return {
        "request_count": len(records),
        "method_seen": record.get("method"),
        "path_hash": record.get("path_hash"),
        "authorization_header_seen": bool(record.get("authorization_header_seen")),
        "content_type_seen": record.get("content_type"),
        "body_schema_version": body.get("transport_envelope_schema_version"),
        "body_provider_category": body.get("provider_category"),
        "body_request_hash_matches": body.get("provider_request_hash")
        == provider_request.get("provider_request_hash"),
        "incident_payload_hash_matches": isinstance(incident_payload, Mapping)
        and incident_payload.get("safe_body_hash")
        == sha256_text(SAFE_BODY),
        "target_id_hashed": isinstance(target_ref, Mapping)
        and target_ref.get("target_id_hash") == sha256_text(TARGET_ID),
    }


def _loopback_endpoint_hint(port: int) -> str:
    return f"http://127.0.0.1:{port}/<redacted>"


def _assert_evidence_redacted(evidence: Mapping[str, Any], port: int) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)
    forbidden_values = (
        LOOPBACK_TOKEN,
        TARGET_ID,
        f"http://127.0.0.1:{port}/dispatch/incident",
        "/dispatch/incident",
    )
    leaks = [value for value in forbidden_values if value in serialized]
    if leaks:
        raise AssertionError("incident loopback smoke evidence leaked sensitive values")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "UNKNOWN").lower()
    if status == "skipped":
        return (
            "ag_operator_review_escalation_dispatch_incident_loopback_smoke="
            f"skipped reason={evidence.get('skip_reason')}"
        )
    observations = evidence.get("observations") or {}
    result = evidence.get("result") or {}
    return (
        "ag_operator_review_escalation_dispatch_incident_loopback_smoke="
        f"{status} transport={evidence.get('transport')} "
        f"requests={observations.get('request_count')} "
        f"status_code={result.get('http_status_code')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_incident_loopback_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
