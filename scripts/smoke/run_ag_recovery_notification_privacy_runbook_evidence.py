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

from nex_ag.recovery_notification_operations import (  # noqa: E402
    build_recovery_notification_operations_projection,
)
from nex_ag.recovery_notification_policy import (  # noqa: E402
    RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV,
    RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV,
    RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV,
    RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV,
    build_recovery_notification_plan,
)


SCHEMA_VERSION = "ag_recovery_notification_privacy_runbook.v1"
SLICE_ID = "0839"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_recovery_notification_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0838_ag_recovery_notification_postgres_smoke.md"
)
OBSERVED_AT = "2026-09-18T09:00:00Z"
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer recovery-notification-secret-0839",
    "raw_comment": "raw-recovery-comment-secret-0839",
    "raw_idempotency_key": "raw-recovery-idempotency-secret-0839",
    "provider_api_key": "provider-api-key-secret-0839",
    "provider_endpoint": "https://private-provider.example/notify/0839",
    "provider_payload": "raw-provider-payload-secret-0839",
}
FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_comment",
    "raw_idempotency_key",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0831", "ag_recovery_notification_policy_boundary_audit"),
        ("0832", "ag_recovery_notification_policy_configuration"),
        ("0833", "ag_recovery_notification_eligibility"),
        ("0834", "ag_recovery_notification_redacted_plan"),
        ("0835", "ag_recovery_notification_preview_api"),
        ("0836", "ag_recovery_notification_operations_projection"),
        ("0837", "ag_recovery_notification_dashboard_contract_integration"),
        ("0838", "ag_recovery_notification_postgres_smoke"),
    )
)


def run_ag_recovery_notification_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    scenarios = {
        "policy_disabled": _notification_plan(
            _recovery_plan(),
            environ={RECOVERY_NOTIFICATION_POLICY_ENABLED_ENV: "0"},
        ),
        "eligible_preview": _notification_plan(_recovery_plan()),
        "delivery_ready_unsent": _notification_plan(
            _recovery_plan(),
            environ={RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "1"},
        ),
        "acknowledged": _notification_plan(
            _recovery_plan(effective_state="ACKNOWLEDGED")
        ),
        "active_suppression": _notification_plan(
            _recovery_plan(effective_state="SUPPRESSED")
        ),
        "critical_bypass": _notification_plan(
            _recovery_plan(
                severity="CRITICAL",
                effective_state="SUPPRESSED",
            ),
            environ={RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION_ENV: "1"},
        ),
        "below_threshold": _notification_plan(
            _recovery_plan(severity="INFO"),
            environ={RECOVERY_NOTIFICATION_MIN_SEVERITY_ENV: "ERROR"},
        ),
    }
    unavailable = build_recovery_notification_operations_projection(
        None,
        environ={},
        request_trace_id="trace-0839",
    )
    runbook = _runbook_actions()
    surfaces = {
        "scenarios": {
            name: _plan_surface(plan) for name, plan in scenarios.items()
        },
        "source_unavailable": {
            "projection_status": unavailable["projection_status"],
            "notification_status": unavailable["notification_status"],
            "error_code": unavailable["source_statuses"]["nex-ag"][
                "error_code"
            ],
            "provider_invocation_performed": unavailable["summary"][
                "provider_invocation_performed"
            ],
        },
        "runbook": runbook,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True)
    forbidden_value_labels = _forbidden_value_labels(serialized)
    forbidden_key_paths = _forbidden_key_paths(surfaces)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    postgres_evidence = (root / POSTGRES_EVIDENCE_PATH).read_text(
        encoding="utf-8"
    )
    checks = {
        "policy_disabled_not_required": scenarios["policy_disabled"][
            "plan_status"
        ]
        == "NOT_REQUIRED",
        "eligible_preview_safe": (
            scenarios["eligible_preview"]["plan_status"] == "PREVIEW_ONLY"
            and scenarios["eligible_preview"]["decision"]["eligible"] is True
        ),
        "delivery_ready_remains_unsent": (
            scenarios["delivery_ready_unsent"]["plan_status"] == "READY"
            and scenarios["delivery_ready_unsent"]["delivery"]["performed"]
            is False
            and scenarios["delivery_ready_unsent"]["delivery"][
                "provider_invocation_performed"
            ]
            is False
        ),
        "acknowledgement_suppresses_repeat": scenarios["acknowledged"][
            "decision"
        ]["reason_codes"]
        == ["acknowledged_repeat"],
        "active_suppression_blocks_notification": scenarios[
            "active_suppression"
        ]["plan_status"]
        == "SUPPRESSED",
        "critical_bypass_is_eligible": scenarios["critical_bypass"][
            "decision"
        ]["reason_codes"]
        == ["critical_bypass_suppression"],
        "below_threshold_not_required": scenarios["below_threshold"][
            "plan_status"
        ]
        == "NOT_REQUIRED",
        "source_unavailable_degrades_safely": (
            unavailable["projection_status"] == "DEGRADED"
            and unavailable["notification_status"] == "SOURCE_UNAVAILABLE"
            and unavailable["preview"] is None
        ),
        "provider_invocation_absent": all(
            plan["delivery"]["provider_invocation_performed"] is False
            for plan in scenarios.values()
        ),
        "runbook_complete": set(runbook)
        == {
            "policy_disabled",
            "below_minimum_severity",
            "acknowledged_repeat",
            "active_suppression",
            "critical_bypass",
            "source_unavailable",
            "delivery_ready",
        },
        "postgres_live_evidence_present": (
            "ag_recovery_notification_postgres_smoke=pass" in postgres_evidence
            and "The result was not skipped" in postgres_evidence
        ),
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_recovery_notification_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces["scenarios"]) + 1,
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _recovery_plan(
    *,
    severity: str = "ERROR",
    effective_state: str | None = None,
) -> dict[str, Any]:
    return {
        "projection_schema_version": "ag_recovery_privacy_source.v1",
        "summary": {"liveness_status": "MISSING"},
        "recommended_actions": [
            {
                "action_id": "inspect-daemon",
                "severity": severity,
                "raw_comment": FORBIDDEN_VALUES["raw_comment"],
                "provider_payload": FORBIDDEN_VALUES["provider_payload"],
            }
        ],
        "acknowledgement_state_overlay": {
            "effective_state_status": effective_state,
            "idempotency_key": FORBIDDEN_VALUES["raw_idempotency_key"],
        },
        "daemon_identity": {
            "service_id": "nex-ag",
            "worker_id": "ag-dispatch-execution-daemon",
        },
        "authorization": FORBIDDEN_VALUES["authorization"],
        "database_url": FORBIDDEN_VALUES["database_url"],
        "provider_api_key": FORBIDDEN_VALUES["provider_api_key"],
        "provider_endpoint": FORBIDDEN_VALUES["provider_endpoint"],
    }


def _notification_plan(
    recovery_plan: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return build_recovery_notification_plan(
        recovery_plan,
        environ={} if environ is None else environ,
        evaluated_at=OBSERVED_AT,
        request_trace_id="trace-0839",
    )


def _plan_surface(plan: Mapping[str, Any]) -> dict[str, Any]:
    decision = plan.get("decision")
    delivery = plan.get("delivery")
    safe_payload = plan.get("safe_payload")
    return {
        "plan_status": plan.get("plan_status"),
        "decision": dict(decision) if isinstance(decision, Mapping) else {},
        "delivery": dict(delivery) if isinstance(delivery, Mapping) else {},
        "safe_payload": (
            dict(safe_payload) if isinstance(safe_payload, Mapping) else {}
        ),
        "redaction": dict(plan.get("redaction") or {}),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "policy_disabled": {
            "retryable": False,
            "action": "review policy ownership before enabling notifications",
        },
        "below_minimum_severity": {
            "retryable": False,
            "action": "treat as an intentional policy threshold decision",
        },
        "acknowledged_repeat": {
            "retryable": True,
            "action": "re-evaluate after the configured repeat window",
        },
        "active_suppression": {
            "retryable": True,
            "action": "wait for expiry or clear suppression after operator review",
        },
        "critical_bypass": {
            "retryable": False,
            "action": "review the critical signal immediately",
        },
        "source_unavailable": {
            "retryable": True,
            "action": "restore liveness and acknowledgement read models",
        },
        "delivery_ready": {
            "retryable": False,
            "action": "preview only; external delivery remains a later boundary",
        },
    }


def _forbidden_value_labels(serialized: str) -> list[str]:
    return sorted(
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    )


def _forbidden_key_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _assert_no_forbidden_values(serialized: str) -> None:
    labels = _forbidden_value_labels(serialized)
    if labels:
        raise ValueError(f"privacy evidence contains forbidden values: {labels}")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_recovery_notification_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_recovery_notification_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"suppression={checks.get('active_suppression_blocks_notification')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_recovery_notification_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
