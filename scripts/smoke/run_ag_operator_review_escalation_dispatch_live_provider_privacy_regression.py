#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import build_operations_dashboard_snapshot_projection  # noqa: E402
from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewEscalationDispatchStore,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    MockDispatchProviderHttpTransport,
    build_dispatch_execution_provider_config,
    build_dispatch_execution_result_metadata,
    build_external_incident_dispatch_provider_request,
    build_notification_dispatch_provider_request,
    execute_dispatch_provider_http_request,
    execute_dispatch_with_provider_router,
    record_dispatch_execution_result_metadata,
)
from nex_ag.operator_reviews import sha256_text  # noqa: E402


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_live_provider_privacy_regression.v1"
)
SLICE_ID = "0728"
SERVICE_ID = "nex-ag"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
REFERENCE_TIME = "2026-09-13T13:00:00Z"

RAW_NOTIFICATION_PAYLOAD = "RAW_NOTIFICATION_PAYLOAD_0728_SHOULD_NOT_LEAK"
RAW_EXTERNAL_INCIDENT_PAYLOAD = "RAW_EXTERNAL_INCIDENT_0728_SHOULD_NOT_LEAK"
RAW_PROVIDER_PAYLOAD = "RAW_PROVIDER_PAYLOAD_0728_SHOULD_NOT_LEAK"
RAW_PROVIDER_RESPONSE = "RAW_PROVIDER_RESPONSE_0728_SHOULD_NOT_LEAK"
NOTIFICATION_WEBHOOK_URL = "https://notify.invalid/hook/secret-0728"
NOTIFICATION_SERVICE_TOKEN = "notify-token-0728"
EXTERNAL_INCIDENT_BASE_URL = "https://incident.invalid/api/private-0728"
EXTERNAL_INCIDENT_TOKEN = "incident-token-0728"
PROVIDER_API_KEY = "provider-api-key-0728"
AUTHORIZATION_HEADER = "Bearer live-provider-secret-0728"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret-0728@127.0.0.1/nex_ag_test"
IDEMPOTENCY_KEY = "idempotency-key-0728-secret"
STORAGE_PATH = "/data/nex-platform/ag/provider-privacy-0728.json"
SAFE_BODY = "Safe bounded provider privacy regression body."

PROTECTED_ENV_KEYS = (
    "NEX_AG_DATABASE_URL",
    "NEX_AG_TEST_DATABASE_URL",
    "NEX_AG_NOTIFICATION_WEBHOOK_URL",
    "NEX_AG_NOTIFICATION_SERVICE_TOKEN",
    "NEX_AG_EXTERNAL_INCIDENT_BASE_URL",
    "NEX_AG_EXTERNAL_INCIDENT_TOKEN",
)

FORBIDDEN_VALUES = {
    "raw_notification_payload": RAW_NOTIFICATION_PAYLOAD,
    "raw_external_incident_payload": RAW_EXTERNAL_INCIDENT_PAYLOAD,
    "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
    "raw_provider_response": RAW_PROVIDER_RESPONSE,
    "notification_webhook_url": NOTIFICATION_WEBHOOK_URL,
    "notification_service_token": NOTIFICATION_SERVICE_TOKEN,
    "external_incident_base_url": EXTERNAL_INCIDENT_BASE_URL,
    "external_incident_token": EXTERNAL_INCIDENT_TOKEN,
    "provider_api_key": PROVIDER_API_KEY,
    "authorization_header": AUTHORIZATION_HEADER,
    "database_url": DATABASE_URL,
    "idempotency_key": IDEMPOTENCY_KEY,
    "storage_path": STORAGE_PATH,
}

FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "database_url",
    "external_incident_payload",
    "idempotency_key",
    "notification_payload",
    "provider_api_key",
    "provider_payload",
    "raw_external_incident_payload",
    "raw_notification_payload",
    "raw_provider_error",
    "raw_provider_payload",
    "secret",
    "service_token",
    "storage_path",
    "storage_uri",
    "webhook_url",
}

SENSITIVE_REDACTION_FLAGS = {
    "database_urls_included",
    "external_incident_payload_included",
    "idempotency_keys_included",
    "notification_payload_included",
    "provider_payloads_included",
    "provider_secrets_included",
    "raw_external_incident_payload_included",
    "raw_notification_payload_included",
    "raw_provider_error_included",
    "raw_provider_payload_included",
    "storage_paths_included",
    "tokens_included",
}


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    payload: dict[str, Any]


def run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    config = build_dispatch_execution_provider_config(_provider_env(env))
    notification_dispatch = _provider_dispatch(
        dispatch_id="dispatch-0728-notification",
        channel_type="EMAIL",
        dispatch_intent="NOTIFY_OWNER",
        provider_profile="email-notification-default",
    )
    incident_dispatch = _provider_dispatch(
        dispatch_id="dispatch-0728-incident",
        channel_type="INCIDENT",
        dispatch_intent="OPEN_INCIDENT",
        provider_profile="external-incident-default",
    )
    notification_request = build_notification_dispatch_provider_request(
        notification_dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at=REFERENCE_TIME,
    )
    incident_request = build_external_incident_dispatch_provider_request(
        incident_dispatch,
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at=REFERENCE_TIME,
    )
    notification_result = execute_dispatch_with_provider_router(
        notification_dispatch,
        provider_mode="mock_http",
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        notification_status_code=202,
        executed_at=REFERENCE_TIME,
    )
    incident_result = execute_dispatch_with_provider_router(
        incident_dispatch,
        provider_mode="mock_http",
        provider_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        external_incident_status_code=503,
        executed_at=REFERENCE_TIME,
    )
    http_result = execute_dispatch_provider_http_request(
        notification_request,
        transport=MockDispatchProviderHttpTransport(status_codes=(429, 202)),
        provider_config=config,
        executed_at=REFERENCE_TIME,
    )
    metadata = build_dispatch_execution_result_metadata(
        notification_result,
        run_id="provider-privacy-run-0728",
        worker_id="ag-dispatch-provider-privacy-worker",
    )
    dashboard = _dashboard_surface(
        notification_dispatch,
        incident_dispatch,
        notification_result,
        incident_result,
    )
    surfaces = [
        SurfacePayload("provider_config", config),
        SurfacePayload("notification_request", notification_request),
        SurfacePayload("incident_request", incident_request),
        SurfacePayload("notification_result", notification_result),
        SurfacePayload("incident_result", incident_result),
        SurfacePayload("http_client_result", http_result),
        SurfacePayload("result_metadata", metadata),
        SurfacePayload("operations_dashboard_dispatches", dashboard),
    ]
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    checks = {
        "all_surfaces_redacted": all(item["redacted"] for item in surface_checks),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "no_forbidden_keys": all(not item["forbidden_key_paths"] for item in surface_checks),
        "redaction_flags_safe": all(not item["unsafe_flag_paths"] for item in surface_checks),
        "provider_config_safe": surface_checks[0]["redacted"],
        "provider_requests_safe": surface_checks[1]["redacted"]
        and surface_checks[2]["redacted"],
        "provider_results_safe": surface_checks[3]["redacted"]
        and surface_checks[4]["redacted"]
        and surface_checks[5]["redacted"],
        "dashboard_surface_safe": surface_checks[7]["redacted"],
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_live_provider_privacy_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "surface_count": len(surfaces),
        "surfaces": surface_checks,
        "checks": checks,
        "protected_env": {
            key: bool((env or {}).get(key)) for key in PROTECTED_ENV_KEYS
        },
        "redaction_policy": {
            "raw_provider_payload_storage_allowed": False,
            "provider_tokens_in_evidence_allowed": False,
            "endpoint_paths_in_evidence_allowed": False,
            "idempotency_keys_in_evidence_allowed": False,
            "database_urls_in_evidence_allowed": False,
        },
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env or {})
    return evidence


def _provider_env(env: Mapping[str, str] | None) -> dict[str, str]:
    return {
        "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "mock_http",
        "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "0",
        "NEX_AG_NOTIFICATION_WEBHOOK_URL": NOTIFICATION_WEBHOOK_URL,
        "NEX_AG_NOTIFICATION_SERVICE_TOKEN": NOTIFICATION_SERVICE_TOKEN,
        "NEX_AG_EXTERNAL_INCIDENT_BASE_URL": EXTERNAL_INCIDENT_BASE_URL,
        "NEX_AG_EXTERNAL_INCIDENT_TOKEN": EXTERNAL_INCIDENT_TOKEN,
        **dict(env or {}),
    }


def _provider_dispatch(
    *,
    dispatch_id: str,
    channel_type: str,
    dispatch_intent: str,
    provider_profile: str,
) -> dict[str, Any]:
    return {
        "dispatch_id": dispatch_id,
        "escalation_id": "escalation-0728",
        "case_id": "case-0728",
        "target_service": "nex-ag",
        "target_kind": "operator_review_dispatch_privacy",
        "target_id": "target-0728-sensitive-id",
        "provider_ref": {
            "provider_type": "mock",
            "provider_id": "provider-0728",
        },
        "channel_type": channel_type,
        "dispatch_intent": dispatch_intent,
        "provider_profile": provider_profile,
        "dispatch_status": "PENDING",
        "reason_codes": ["sla_warning"],
        "safe_subject": "Provider privacy regression",
        "safe_body_hash": sha256_text(SAFE_BODY),
        "safe_body_preview": SAFE_BODY,
        "provider_payload_hash": sha256_text(RAW_PROVIDER_PAYLOAD),
        "attempt_count": 0,
        "metadata": {},
    }


def _dashboard_surface(
    notification_dispatch: Mapping[str, Any],
    incident_dispatch: Mapping[str, Any],
    notification_result: Mapping[str, Any],
    incident_result: Mapping[str, Any],
) -> dict[str, Any]:
    dispatch_store = OperatorReviewEscalationDispatchStore()
    dispatch_store.save(
        record_dispatch_execution_result_metadata(
            {**notification_dispatch, "dispatch_status": "SUCCEEDED"},
            notification_result,
            run_id="provider-privacy-run-0728",
            worker_id="ag-dispatch-provider-privacy-worker",
        )
    )
    dispatch_store.save(
        record_dispatch_execution_result_metadata(
            {**incident_dispatch, "dispatch_status": "RETRY_WAIT"},
            incident_result,
            run_id="provider-privacy-run-0728",
            worker_id="ag-dispatch-provider-privacy-worker",
        )
    )
    projection = build_operations_dashboard_snapshot_projection(
        operator_review_escalation_dispatch_store=dispatch_store,
        service_id="nex-ag",
        recent_limit=5,
        request_trace_id=TRACE_ID,
    )
    return projection["operator_review_escalation_dispatches"]


def _surface_privacy_check(surface: SurfacePayload) -> dict[str, Any]:
    serialized = json.dumps(surface.payload, ensure_ascii=False, sort_keys=True)
    leak_labels = [
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    ]
    forbidden_key_paths = _forbidden_key_paths(surface.payload, FORBIDDEN_KEYS)
    unsafe_flag_paths = _unsafe_redaction_flag_paths(surface.payload)
    return {
        "name": surface.name,
        "payload_bytes": len(serialized.encode("utf-8")),
        "leak_labels": leak_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "unsafe_flag_paths": unsafe_flag_paths,
        "redacted": not leak_labels and not forbidden_key_paths and not unsafe_flag_paths,
    }


def _forbidden_key_paths(
    payload: Any,
    forbidden_keys: set[str],
    prefix: str = "",
) -> list[str]:
    if isinstance(payload, Mapping):
        paths: list[str] = []
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in forbidden_keys:
                paths.append(path)
            paths.extend(_forbidden_key_paths(value, forbidden_keys, path))
        return paths
    if isinstance(payload, list):
        paths = []
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_forbidden_key_paths(value, forbidden_keys, path))
        return paths
    return []


def _unsafe_redaction_flag_paths(payload: Any, prefix: str = "") -> list[str]:
    if isinstance(payload, Mapping):
        paths: list[str] = []
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in SENSITIVE_REDACTION_FLAGS and value is True:
                paths.append(path)
            paths.extend(_unsafe_redaction_flag_paths(value, path))
        return paths
    if isinstance(payload, list):
        paths = []
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_unsafe_redaction_flag_paths(value, path))
        return paths
    return []


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized:
            raise ValueError(f"Protected environment value leaked: {key}")
    for label, value in FORBIDDEN_VALUES.items():
        if value in serialized:
            raise ValueError(f"Sensitive value leaked: {label}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "ag_operator_review_escalation_dispatch_live_provider_privacy="
            f"{str(evidence.get('status') or 'FAIL').lower()} "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_live_provider_privacy=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"values={checks.get('no_forbidden_values')} "
        f"keys={checks.get('no_forbidden_keys')} "
        f"flags={checks.get('redaction_flags_safe')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    evidence = run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    if evidence["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
