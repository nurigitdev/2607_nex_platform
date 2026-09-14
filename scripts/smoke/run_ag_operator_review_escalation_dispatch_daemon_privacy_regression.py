#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import (  # noqa: E402
    build_operator_review_escalation_dispatch_daemon_runtime_projection,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    build_dispatch_execution_daemon_control_admission,
    build_dispatch_execution_daemon_control_request,
    build_dispatch_execution_daemon_policy,
    build_dispatch_execution_daemon_tick_event,
    build_dispatch_execution_daemon_tick_log_entry,
    build_dispatch_execution_daemon_tick_plan,
)
from nex_ag.operator_reviews import sha256_text  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_daemon_privacy_regression.v1"
SERVICE_ID = "nex-ag"
TRACE_ID = "f844ad11606f4d4b9a694720e0e06a1a"
REQUEST_ID = "ag-dispatch-daemon-privacy-0749"
REFERENCE_TIME = "2026-09-14T13:49:00Z"
FORBIDDEN_VALUES = (
    "nuri1004",
    "Bearer daemon-secret",
    "/data/nex-platform/ag/dispatch-daemon",
    "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test",
    "provider-raw-secret-0749",
)


def run_ag_operator_review_escalation_dispatch_daemon_privacy_regression() -> dict[
    str,
    Any,
]:
    service = _PrivacyDispatchService()
    policy = build_dispatch_execution_daemon_policy(
        {
            "NEX_AG_DISPATCH_DAEMON_ENABLED": "1",
            "NEX_AG_DISPATCH_DAEMON_DRY_RUN": "0",
            "NEX_AG_DISPATCH_DAEMON_BATCH_LIMIT": "5",
            "NEX_AG_DISPATCH_DAEMON_PROVIDER_MODE": "mock_http",
        }
    )
    control_request = build_dispatch_execution_daemon_control_request(
        {
            "action": "tick_once",
            "confirm_tick": True,
            "dry_run": False,
            "batch_limit": 5,
            "operator_ref": {
                "operator_type": "user",
                "operator_id": "employee-0749",
                "authorization": FORBIDDEN_VALUES[1],
            },
            "reason_codes": ["privacy_regression"],
            "provider_payload": {"raw": FORBIDDEN_VALUES[4]},
            "database_url": FORBIDDEN_VALUES[3],
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        requested_at=REFERENCE_TIME,
    )
    control_admission = build_dispatch_execution_daemon_control_admission(
        control_request,
        policy=policy,
    )
    tick_plan = build_dispatch_execution_daemon_tick_plan(
        service,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        policy=policy,
        planned_at=REFERENCE_TIME,
    )
    tick_result = {
        "tick_id": "tick-0749-privacy",
        "tick_status": "COMPLETED",
        "blocked_reason": None,
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
        "worker_id": "ag-dispatch-execution-daemon",
        "executed_at": REFERENCE_TIME,
        "dry_run": False,
        "plan": tick_plan,
        "candidate_count": 1,
        "processed_count": 1,
        "succeeded_count": 1,
        "failed_count": 0,
        "retry_wait_count": 0,
        "skipped_count": 0,
        "effective_provider_mode": "mock_http",
        "new_tables_required": False,
        "worker_run": {
            "items": [
                {
                    "dispatch_id": "dispatch-0749-privacy",
                    "provider_payload": FORBIDDEN_VALUES[4],
                    "storage_path": FORBIDDEN_VALUES[2],
                }
            ]
        },
    }
    event = build_dispatch_execution_daemon_tick_event(tick_result)
    log_entry = build_dispatch_execution_daemon_tick_log_entry(tick_result)
    runtime_projection = (
        build_operator_review_escalation_dispatch_daemon_runtime_projection(
            [tick_result],
            policy={**policy, "database_url": FORBIDDEN_VALUES[3]},
            checked_at=REFERENCE_TIME,
        )
    )
    surfaces = {
        "policy": policy,
        "control_request": control_request,
        "control_admission": control_admission,
        "tick_plan": tick_plan,
        "event": event,
        "log_entry": log_entry,
        "runtime_projection": runtime_projection,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True, default=str)
    checks = {
        "control_admitted": control_admission.get("admission_status") == "ACCEPTED",
        "tick_plan_ready": tick_plan.get("plan_status") == "READY",
        "event_info": event.get("severity") == "INFO",
        "log_info": log_entry.get("severity") == "INFO",
        "runtime_ready": runtime_projection.get("projection_status") == "READY",
        "worker_run_not_projected": '"provider_payload":' not in serialized,
        "forbidden_values_absent": _forbidden_values_absent(serialized),
        "database_urls_redacted": "postgresql+psycopg://" not in serialized,
        "storage_paths_redacted": "/data/nex-platform" not in serialized,
    }
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None if all(checks.values()) else "checks_failed",
        "service": SERVICE_ID,
        "request_id": REQUEST_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": sorted(surfaces),
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


class _PrivacyDispatchService:
    def list_escalation_dispatches(self, **kwargs: Any) -> dict[str, Any]:
        status = kwargs.get("dispatch_status")
        if status != "PENDING":
            return {"items": []}
        return {
            "items": [
                {
                    "dispatch_id": "dispatch-0749-privacy",
                    "case_id": "case-0749-privacy",
                    "escalation_id": "escalation-0749-privacy",
                    "dispatch_status": "PENDING",
                    "dispatch_intent": "NOTIFY_OWNER",
                    "channel_type": "EMAIL",
                    "provider_profile": "email-notification-default",
                    "attempt_count": 0,
                    "safe_body_hash": sha256_text(FORBIDDEN_VALUES[4]),
                    "metadata": {
                        "database_url": FORBIDDEN_VALUES[3],
                        "storage_path": FORBIDDEN_VALUES[2],
                    },
                }
            ]
        }


def _forbidden_values_absent(serialized: str) -> bool:
    return all(value not in serialized for value in FORBIDDEN_VALUES)


def _assert_no_forbidden_values(serialized: str) -> None:
    leaks = [value for value in FORBIDDEN_VALUES if value in serialized]
    if leaks:
        raise ValueError(f"Dispatch daemon privacy regression leaked {len(leaks)} value(s).")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_privacy_regression=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_privacy_regression=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"forbidden_absent={checks.get('forbidden_values_absent')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_daemon_privacy_regression()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
