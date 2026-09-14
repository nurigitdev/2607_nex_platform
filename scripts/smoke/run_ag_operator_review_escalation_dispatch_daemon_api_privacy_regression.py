#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewEscalationDispatchStore,
    build_operator_review_escalation_dispatch_record,
    build_operator_review_escalation_record,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.v1"
)
SLICE_ID = "0755"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_dispatch_daemon_api_privacy"
TARGET_ID = "operator-review-escalation-dispatch-daemon-api-privacy-0755"
CASE_ID = "case-operator-review-escalation-dispatch-daemon-api-privacy-0755"
TRACE_ID = "b75fb07dbf804a79abe872584f630755"
REQUEST_ID = "ag-dispatch-daemon-api-privacy-0755"
REFERENCE_TIME = "2026-09-14T14:55:00Z"

RAW_PROVIDER_PAYLOAD = "RAW_PROVIDER_PAYLOAD_0755_SHOULD_NOT_LEAK"
RAW_ACTION_COMMENT = "RAW_ACTION_SECRET_0755_SHOULD_NOT_LEAK"
RAW_SAFE_BODY = "RAW_SAFE_BODY_0755_SHOULD_NOT_LEAK"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1/nex_ag_test"
STORAGE_PATH = "/data/nex-platform/ag/private/dispatch-daemon-api-0755.json"
PROVIDER_API_KEY = "provider-key-0755"
DISPATCH_IDEMPOTENCY_KEY = "dispatch-idem-0755-secret"
CONTROL_IDEMPOTENCY_KEY = "control-idem-0755-secret"
AUTHORIZATION_VALUE = "Bearer route-secret-0755"

FORBIDDEN_VALUES = {
    "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
    "raw_action_comment": RAW_ACTION_COMMENT,
    "raw_safe_body": RAW_SAFE_BODY,
    "database_url": DATABASE_URL,
    "storage_path": STORAGE_PATH,
    "provider_api_key": PROVIDER_API_KEY,
    "dispatch_idempotency_key": DISPATCH_IDEMPOTENCY_KEY,
    "control_idempotency_key": CONTROL_IDEMPOTENCY_KEY,
    "authorization": AUTHORIZATION_VALUE,
    "database_password": "nuri1004",
}

FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_provider_payload",
    "secret",
    "storage_path",
    "storage_uri",
}


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression() -> (
    dict[str, Any]
):
    dispatch_store = OperatorReviewEscalationDispatchStore()
    dispatch = _seed_dispatch(dispatch_store)
    client = _build_client(dispatch_store)
    surfaces = [
        _get_tick_plan_surface(client),
        _post_tick_plan_surface(client),
        _post_tick_once_surface(client),
    ]
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    surface_map = {surface.name: surface.payload for surface in surfaces}
    checks = {
        "all_routes_successful": all(surface.status_code == 200 for surface in surfaces),
        "get_tick_plan_ready": (
            surface_map["get_tick_plan"].get("summary", {}).get("candidate_count")
            == 1
        ),
        "post_tick_plan_forced_safe_action": (
            surface_map["post_tick_plan"].get("control_request", {}).get("action")
            == "tick_plan"
            and surface_map["post_tick_plan"].get("route", {}).get("mutation") is False
        ),
        "tick_once_mutated": (
            surface_map["post_tick_once"].get("summary", {}).get(
                "mutation_performed"
            )
            is True
            and dispatch_store.get(dispatch["dispatch_id"])["dispatch_status"]
            == "SUCCEEDED"
        ),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "raw_fields_absent": all(
            not _contains_forbidden_keys(surface.payload, FORBIDDEN_KEYS)
            for surface in surfaces
        ),
        "redaction_flags_safe": all(
            _redaction_flags_safe(surface.payload) for surface in surfaces
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_daemon_api_privacy_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "surface_count": len(surfaces),
        "surfaces": [
            {
                "name": item["name"],
                "status_code": item["status_code"],
                "payload_bytes": item["payload_bytes"],
                "leak_labels": item["leak_labels"],
                "forbidden_key_paths": item["forbidden_key_paths"],
            }
            for item in surface_checks
        ],
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _seed_dispatch(
    dispatch_store: OperatorReviewEscalationDispatchStore,
) -> dict[str, Any]:
    escalation = build_operator_review_escalation_record(
        {
            "candidate_id": f"{CASE_ID}:privacy",
            "case_id": CASE_ID,
            "target_ref": {
                "target_service": TARGET_SERVICE,
                "target_kind": TARGET_KIND,
                "target_id": TARGET_ID,
            },
            "assignment_ref": {
                "assignee_type": None,
                "assignee_id": None,
                "tenant_id": "privacy-tenant",
            },
            "escalation_level": "BLOCKED",
            "sla_state": "OVERDUE",
            "escalation_reasons": ["dispatch_daemon_api_privacy"],
            "runbook_ids": ["ag.dispatch_daemon_api.privacy.v1"],
            "recommended_operator_actions": ["execute_pending_dispatch"],
        },
        {"action_comment": RAW_ACTION_COMMENT},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="escalation-idem-0755-secret",
        created_at=REFERENCE_TIME,
    )
    dispatch = build_operator_review_escalation_dispatch_record(
        escalation,
        {
            "dispatch_status": "PENDING",
            "dispatch_intent": "NOTIFY_OPERATOR",
            "channel_type": "MOCK",
            "provider_profile": "mock-privacy-provider",
            "safe_subject": "Safe dispatch daemon API privacy subject",
            "safe_body": RAW_SAFE_BODY,
            "provider_payload_fingerprint": RAW_PROVIDER_PAYLOAD,
            "reason_codes": ["dispatch_daemon_api_privacy"],
            "last_error": RAW_ACTION_COMMENT,
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=DISPATCH_IDEMPOTENCY_KEY,
        created_at=REFERENCE_TIME,
    )
    dispatch_store.save(dispatch)
    return dispatch


def _build_client(dispatch_store: OperatorReviewEscalationDispatchStore) -> TestClient:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(
        app,
        operator_review_escalation_dispatch_store=dispatch_store,
    )
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _sensitive_control_payload(*, confirm_tick: bool, dry_run: bool) -> dict[str, Any]:
    return {
        "action": "tick_once",
        "enabled": True,
        "confirm_tick": confirm_tick,
        "dry_run": dry_run,
        "batch_limit": 1,
        "provider_mode": "mock_first_only",
        "operator_ref": {
            "operator_type": "employee",
            "operator_id": "employee-0755",
            "authorization": AUTHORIZATION_VALUE,
            "secret": PROVIDER_API_KEY,
        },
        "reason_codes": ["dispatch_daemon_api_privacy"],
        "authorization": AUTHORIZATION_VALUE,
        "database_url": DATABASE_URL,
        "idempotency_key": CONTROL_IDEMPOTENCY_KEY,
        "provider_api_key": PROVIDER_API_KEY,
        "provider_payload": {"raw": RAW_PROVIDER_PAYLOAD},
        "raw_action_comment": RAW_ACTION_COMMENT,
        "storage_path": STORAGE_PATH,
    }


def _get_tick_plan_surface(client: TestClient) -> SurfacePayload:
    response = client.get(
        "/admin/v1/operator-review/dispatch-daemon/tick-plan",
        params={
            "enabled": "true",
            "dry_run": "false",
            "batch_limit": 1,
            "provider_mode": "mock_first_only",
        },
        headers=_auth_headers(),
    )
    return SurfacePayload("get_tick_plan", response.status_code, response.json())


def _post_tick_plan_surface(client: TestClient) -> SurfacePayload:
    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/tick-plan",
        json=_sensitive_control_payload(confirm_tick=True, dry_run=False),
        headers=_auth_headers(),
    )
    return SurfacePayload("post_tick_plan", response.status_code, response.json())


def _post_tick_once_surface(client: TestClient) -> SurfacePayload:
    response = client.post(
        "/admin/v1/operator-review/dispatch-daemon/tick-once",
        json=_sensitive_control_payload(confirm_tick=True, dry_run=False),
        headers=_auth_headers(),
    )
    return SurfacePayload("post_tick_once", response.status_code, response.json())


def _surface_privacy_check(surface: SurfacePayload) -> dict[str, Any]:
    serialized = json.dumps(surface.payload, ensure_ascii=False, sort_keys=True)
    return {
        "name": surface.name,
        "status_code": surface.status_code,
        "payload_bytes": len(serialized.encode("utf-8")),
        "leak_labels": [
            label for label, value in FORBIDDEN_VALUES.items() if value in serialized
        ],
        "forbidden_key_paths": _forbidden_key_paths(surface.payload, FORBIDDEN_KEYS),
    }


def _forbidden_key_paths(payload: Any, forbidden_keys: set[str]) -> list[str]:
    paths: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text in forbidden_keys:
                    paths.append(child_path)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "")
    return paths


def _contains_forbidden_keys(payload: Any, forbidden_keys: set[str]) -> bool:
    return bool(_forbidden_key_paths(payload, forbidden_keys))


def _redaction_flags_safe(payload: Any) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    unsafe_markers = (
        '"database_urls_included": true',
        '"idempotency_keys_included": true',
        '"provider_payloads_included": true',
        '"provider_secrets_included": true',
        '"raw_action_comment_included": true',
        '"raw_provider_payload_included": true',
        '"storage_paths_included": true',
        '"tokens_included": true',
    )
    return not any(marker in serialized for marker in unsafe_markers)


def _assert_no_forbidden_values(serialized: str) -> None:
    leaks = [label for label, value in FORBIDDEN_VALUES.items() if value in serialized]
    if leaks:
        raise ValueError(
            "Dispatch daemon API privacy regression leaked forbidden values: "
            + ", ".join(sorted(leaks))
        )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_api_privacy_regression="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_api_privacy_regression=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"forbidden_absent={checks.get('no_forbidden_values')} "
        f"raw_fields_absent={checks.get('raw_fields_absent')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
