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
    "ag_operator_review_escalation_dispatch_daemon_api_admission_guard.v1"
)
SLICE_ID = "0759"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_dispatch_daemon_api_admission_guard"
TARGET_ID = "operator-review-escalation-dispatch-daemon-api-admission-0759"
CASE_ID = "case-operator-review-escalation-dispatch-daemon-api-admission-0759"
TRACE_ID = "a95e0ea5c5744c9c98f3ba7f5fd25759"
REQUEST_ID = "ag-dispatch-daemon-api-admission-0759"
REFERENCE_TIME = "2026-09-14T15:05:00Z"

SENSITIVE_VALUES = {
    "authorization": "Bearer admission-secret-0759",
    "database_password": "nuri1004",
    "database_url": "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1/nex_ag_test",
    "provider_api_key": "provider-key-0759",
    "provider_payload": "RAW_PROVIDER_PAYLOAD_0759_SHOULD_NOT_LEAK",
    "raw_action_comment": "RAW_ACTION_SECRET_0759_SHOULD_NOT_LEAK",
    "storage_path": "/data/nex-platform/ag/private/dispatch-daemon-api-0759.json",
}


@dataclass(frozen=True)
class AdmissionScenario:
    name: str
    method: str
    path: str
    include_auth: bool
    params: Mapping[str, Any] | None
    payload_name: str | None
    expected_status_code: int
    expected_error_code: str | None
    expected_mutation: bool


SCENARIOS = (
    AdmissionScenario(
        name="tick_plan_missing_auth",
        method="GET",
        path="/admin/v1/operator-review/dispatch-daemon/tick-plan",
        include_auth=False,
        params={
            "enabled": "true",
            "dry_run": "false",
            "batch_limit": 1,
            "provider_mode": "mock_first_only",
        },
        payload_name=None,
        expected_status_code=401,
        expected_error_code="AUTHORIZATION_HEADER_MISSING",
        expected_mutation=False,
    ),
    AdmissionScenario(
        name="tick_plan_unsupported_provider",
        method="GET",
        path="/admin/v1/operator-review/dispatch-daemon/tick-plan",
        include_auth=True,
        params={"provider_mode": "unsupported"},
        payload_name=None,
        expected_status_code=422,
        expected_error_code=(
            "ag.operator_review_escalation_dispatch_execution_provider_mode_"
            "unsupported"
        ),
        expected_mutation=False,
    ),
    AdmissionScenario(
        name="tick_once_missing_confirm",
        method="POST",
        path="/admin/v1/operator-review/dispatch-daemon/tick-once",
        include_auth=True,
        params=None,
        payload_name="missing_confirm",
        expected_status_code=409,
        expected_error_code=(
            "ag.operator_review_escalation_dispatch_daemon_control_"
            "confirm_tick_required"
        ),
        expected_mutation=False,
    ),
    AdmissionScenario(
        name="tick_once_disabled",
        method="POST",
        path="/admin/v1/operator-review/dispatch-daemon/tick-once",
        include_auth=True,
        params=None,
        payload_name="disabled",
        expected_status_code=409,
        expected_error_code=(
            "ag.operator_review_escalation_dispatch_daemon_control_daemon_disabled"
        ),
        expected_mutation=False,
    ),
    AdmissionScenario(
        name="tick_once_dry_run",
        method="POST",
        path="/admin/v1/operator-review/dispatch-daemon/tick-once",
        include_auth=True,
        params=None,
        payload_name="dry_run",
        expected_status_code=200,
        expected_error_code=None,
        expected_mutation=False,
    ),
    AdmissionScenario(
        name="tick_once_confirmed",
        method="POST",
        path="/admin/v1/operator-review/dispatch-daemon/tick-once",
        include_auth=True,
        params=None,
        payload_name="confirmed",
        expected_status_code=200,
        expected_error_code=None,
        expected_mutation=True,
    ),
)


def run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence() -> (
    dict[str, Any]
):
    scenarios = [_run_scenario(scenario) for scenario in SCENARIOS]
    mutating_success_names = [
        item["name"] for item in scenarios if item["mutation_observed"]
    ]
    checks = {
        "expected_status_codes": all(item["status_code_ok"] for item in scenarios),
        "expected_error_codes": all(item["error_code_ok"] for item in scenarios),
        "rejections_return_problem_json": all(
            item["problem_shape_ok"]
            for item in scenarios
            if item["expected_status_code"] >= 400
        ),
        "accepted_routes_report_admission": all(
            item["admission_status"] == "ACCEPTED"
            for item in scenarios
            if item["expected_status_code"] == 200
        ),
        "mutation_expectations_met": all(item["mutation_ok"] for item in scenarios),
        "mutation_only_after_confirmed_tick": mutating_success_names
        == ["tick_once_confirmed"],
        "sensitive_values_absent": all(
            not item["forbidden_labels"] for item in scenarios
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "admission_schema_version": SCHEMA_VERSION,
        "status": status,
        "failure_code": None
        if status == "PASS"
        else "ag_operator_review_escalation_dispatch_daemon_api_admission_guard_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "scenario_count": len(scenarios),
        "accepted_count": sum(1 for item in scenarios if item["status_code"] == 200),
        "rejected_count": sum(1 for item in scenarios if item["status_code"] >= 400),
        "mutating_success_names": mutating_success_names,
        "scenarios": scenarios,
        "checks": checks,
    }


def _run_scenario(scenario: AdmissionScenario) -> dict[str, Any]:
    dispatch_store = OperatorReviewEscalationDispatchStore()
    dispatch = _seed_dispatch(dispatch_store)
    client = _build_client(dispatch_store)
    headers = _auth_headers() if scenario.include_auth else {}
    response = client.request(
        scenario.method,
        scenario.path,
        params=dict(scenario.params or {}),
        json=_control_payload(scenario.payload_name)
        if scenario.payload_name is not None
        else None,
        headers=headers,
    )
    payload = response.json()
    before_status = dispatch["dispatch_status"]
    after_status = dispatch_store.get(dispatch["dispatch_id"])["dispatch_status"]
    mutation_observed = after_status != before_status
    error_code = payload.get("error_code")
    forbidden_labels = _forbidden_labels(payload)
    expected_error_code = scenario.expected_error_code
    return {
        "name": scenario.name,
        "method": scenario.method,
        "path": scenario.path,
        "expected_status_code": scenario.expected_status_code,
        "status_code": response.status_code,
        "status_code_ok": response.status_code == scenario.expected_status_code,
        "expected_error_code": expected_error_code,
        "error_code": error_code,
        "error_code_ok": error_code == expected_error_code,
        "expected_mutation": scenario.expected_mutation,
        "mutation_observed": mutation_observed,
        "mutation_ok": mutation_observed == scenario.expected_mutation,
        "before_dispatch_status": before_status,
        "after_dispatch_status": after_status,
        "admission_status": payload.get("control_admission", {}).get(
            "admission_status"
        ),
        "summary_mutation_performed": payload.get("summary", {}).get(
            "mutation_performed"
        ),
        "problem_shape_ok": _problem_shape_ok(payload)
        if scenario.expected_status_code >= 400
        else None,
        "forbidden_labels": forbidden_labels,
        "response_bytes": len(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ),
    }


def _seed_dispatch(
    dispatch_store: OperatorReviewEscalationDispatchStore,
) -> dict[str, Any]:
    escalation = build_operator_review_escalation_record(
        {
            "candidate_id": f"{CASE_ID}:admission",
            "case_id": CASE_ID,
            "target_ref": {
                "target_service": TARGET_SERVICE,
                "target_kind": TARGET_KIND,
                "target_id": TARGET_ID,
            },
            "assignment_ref": {
                "assignee_type": None,
                "assignee_id": None,
                "tenant_id": "admission-tenant",
            },
            "escalation_level": "BLOCKED",
            "sla_state": "OVERDUE",
            "escalation_reasons": ["dispatch_daemon_api_admission_guard"],
            "runbook_ids": ["ag.dispatch_daemon_api.admission_guard.v1"],
            "recommended_operator_actions": ["execute_pending_dispatch"],
        },
        {"action_comment": SENSITIVE_VALUES["raw_action_comment"]},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="escalation-idem-0759-secret",
        created_at=REFERENCE_TIME,
    )
    dispatch = build_operator_review_escalation_dispatch_record(
        escalation,
        {
            "dispatch_status": "PENDING",
            "dispatch_intent": "NOTIFY_OPERATOR",
            "channel_type": "MOCK",
            "provider_profile": "mock-admission-provider",
            "safe_subject": "Safe dispatch daemon API admission subject",
            "safe_body": "Safe dispatch daemon API admission body.",
            "provider_payload_fingerprint": SENSITIVE_VALUES["provider_payload"],
            "reason_codes": ["dispatch_daemon_api_admission_guard"],
            "last_error": SENSITIVE_VALUES["raw_action_comment"],
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key="dispatch-idem-0759-secret",
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


def _control_payload(payload_name: str) -> dict[str, Any]:
    payloads = {
        "missing_confirm": {
            "enabled": True,
            "confirm_tick": False,
            "dry_run": False,
        },
        "disabled": {
            "enabled": False,
            "confirm_tick": True,
            "dry_run": False,
        },
        "dry_run": {
            "enabled": True,
            "confirm_tick": True,
            "dry_run": True,
        },
        "confirmed": {
            "enabled": True,
            "confirm_tick": True,
            "dry_run": False,
        },
    }
    payload = {
        "action": "tick_once",
        "batch_limit": 1,
        "provider_mode": "mock_first_only",
        "operator_ref": {
            "operator_type": "employee",
            "operator_id": "employee-0759",
            "authorization": SENSITIVE_VALUES["authorization"],
            "secret": SENSITIVE_VALUES["provider_api_key"],
        },
        "authorization": SENSITIVE_VALUES["authorization"],
        "database_url": SENSITIVE_VALUES["database_url"],
        "provider_api_key": SENSITIVE_VALUES["provider_api_key"],
        "provider_payload": {"raw": SENSITIVE_VALUES["provider_payload"]},
        "raw_action_comment": SENSITIVE_VALUES["raw_action_comment"],
        "storage_path": SENSITIVE_VALUES["storage_path"],
        "reason_codes": ["dispatch_daemon_api_admission_guard"],
    }
    payload.update(payloads[payload_name])
    return payload


def _problem_shape_ok(payload: Mapping[str, Any]) -> bool:
    return all(
        isinstance(payload.get(key), str) and bool(payload.get(key))
        for key in ("error_code", "title", "detail")
    )


def _forbidden_labels(payload: Any) -> list[str]:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return [
        label
        for label, value in SENSITIVE_VALUES.items()
        if value and str(value) in serialized
    ]


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_api_admission_guard=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_api_admission_guard=pass "
        f"scenarios={evidence.get('scenario_count')} "
        f"rejected={evidence.get('rejected_count')} "
        f"mutation_only_confirmed={checks.get('mutation_only_after_confirmed_tick')} "
        f"sensitive_absent={checks.get('sensitive_values_absent')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
