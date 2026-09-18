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

from nex_ag.liveness_ack_expiry_automation import (  # noqa: E402
    ACK_EXPIRY_AUTOMATION_ENABLED_ENV,
)
from nex_ag.liveness_ack_expiry_automation_cli import (  # noqa: E402
    execute_liveness_ack_expiry_automation_cli,
)
from nex_ag.liveness_ack_expiry_automation_operations import (  # noqa: E402
    build_liveness_ack_expiry_automation_operations_projection,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateError,
    OperatorReviewLivenessAckStateStore,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
)


SCHEMA_VERSION = "ag_ack_expiry_automation_privacy_runbook.v1"
SLICE_ID = "0829"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_ack_expiry_automation_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0828_ag_ack_expiry_automation_postgres_smoke.md"
)
SOURCE_TABLE = "ag_op_review_ack_state"
EVENT_TABLE = "service_operational_events"
MAX_IDENTIFIER_LENGTH = 30
OBSERVED_AT = "2026-09-18T06:00:00Z"
ENABLED_ENV = {ACK_EXPIRY_AUTOMATION_ENABLED_ENV: "1"}
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer automation-secret-0829",
    "raw_comment": "raw-automation-comment-secret-0829",
    "raw_idempotency_key": "raw-automation-idempotency-secret-0829",
    "provider_api_key": "provider-api-key-secret-0829",
    "exception_detail": "postgresql://private-exception-detail-0829",
}
FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "exception_detail",
    "idempotency_key",
    "provider_api_key",
    "raw_comment",
    "raw_idempotency_key",
    "raw_payload",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0821", "ag_ack_expiry_automation_boundary_audit"),
        ("0822", "ag_ack_expiry_automation_policy"),
        ("0823", "ag_ack_expiry_automation_tick_plan"),
        ("0824", "ag_ack_expiry_automation_tick_execution"),
        ("0825", "ag_ack_expiry_automation_cli"),
        ("0826", "ag_ack_expiry_automation_lifecycle_events"),
        ("0827", "ag_ack_expiry_automation_operations_projection"),
        ("0828", "ag_ack_expiry_automation_postgres_smoke"),
    )
)


class _ConflictStore:
    def __init__(self, candidate: dict[str, Any]) -> None:
        self.candidate = candidate

    def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [self.candidate]

    def apply_expiry_reconciliation(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


class _BrokenStore:
    def list_expiry_candidates(self, **_kwargs: Any) -> list[dict[str, Any]]:
        raise OperatorReviewLivenessAckStateError(
            FORBIDDEN_VALUES["exception_detail"],
            error_code="ag.operator_review_liveness_ack_state_store_unavailable",
            status_code=503,
        )


def run_ag_ack_expiry_automation_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    disabled = execute_liveness_ack_expiry_automation_cli(
        OperatorReviewLivenessAckStateStore(),
        action="plan",
        environ={},
        request_id="req-disabled-0829",
        observed_at=OBSERVED_AT,
    )
    blocked_store = _store_with_expired_state("ack-blocked-0829")
    blocked = execute_liveness_ack_expiry_automation_cli(
        blocked_store,
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-blocked-0829",
        observed_at=OBSERVED_AT,
        lifecycle_emitter=emitter,
    )
    success_store = _store_with_expired_state("ack-success-0829")
    completed = execute_liveness_ack_expiry_automation_cli(
        success_store,
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-completed-0829",
        confirm_tick=True,
        observed_at="2026-09-18T06:01:00Z",
        lifecycle_emitter=emitter,
    )
    conflict = execute_liveness_ack_expiry_automation_cli(
        _ConflictStore(_expired_state("ack-conflict-0829")),
        action="run_once",
        environ=ENABLED_ENV,
        request_id="req-conflict-0829",
        confirm_tick=True,
        observed_at="2026-09-18T06:02:00Z",
        lifecycle_emitter=emitter,
    )
    failure_code = _capture_failure(emitter)
    operations = build_liveness_ack_expiry_automation_operations_projection(
        event_store,
        environ=ENABLED_ENV,
        event_limit=20,
        request_trace_id="trace-0829",
    )
    runbook = _runbook_actions()
    surfaces = {
        "disabled": _cli_surface(disabled),
        "blocked": _cli_surface(blocked),
        "completed": _cli_surface(completed),
        "conflict": _cli_surface(conflict),
        "failure": {"error_code": failure_code},
        "events": _event_surface(event_store.list_events(limit=20)),
        "operations": operations,
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
    postgres_evidence = (root / POSTGRES_EVIDENCE_PATH).read_text(encoding="utf-8")
    checks = {
        "disabled_plan_safe": (
            disabled["result_status"] == "PLANNED"
            and disabled["plan"]["plan_status"] == "DISABLED"
            and disabled["lifecycle_events"] == []
        ),
        "confirmation_guard_blocks_mutation": (
            blocked["result_status"] == "BLOCKED"
            and blocked["tick_result"]["blocked_reason"]
            == "confirm_tick_required"
            and blocked_store.get("ack-blocked-0829")["state_status"]
            == "SUPPRESSED"
        ),
        "confirmed_tick_expires_state": (
            completed["result_status"] == "EXECUTED"
            and completed["tick_result"]["applied_count"] == 1
            and success_store.get("ack-success-0829")["state_status"] == "EXPIRED"
        ),
        "cas_conflict_reported": (
            conflict["tick_result"]["tick_status"]
            == "COMPLETED_WITH_CONFLICTS"
            and conflict["tick_result"]["conflict_count"] == 1
        ),
        "store_failure_normalized": failure_code.endswith("store_unavailable"),
        "lifecycle_events_complete": len(event_store.list_events(limit=20)) == 8,
        "operations_degraded_after_failure": (
            operations["automation_status"] == "DEGRADED"
            and operations["summary"]["requires_operator_action"] is True
        ),
        "external_scheduler_guardrails": (
            operations["scheduler"]["owner"] == "external_scheduler"
            and operations["scheduler"]["continuous_loop_started"] is False
            and operations["scheduler"]["subprocess_started"] is False
        ),
        "runbook_complete": set(runbook)
        == {
            "automation_disabled",
            "confirm_tick_required",
            "database_unavailable",
            "event_source_unavailable",
            "cas_conflict",
            "zero_candidate_noop",
            "scheduler_invocation_failed",
        },
        "identifier_lengths_safe": (
            len(SOURCE_TABLE) <= MAX_IDENTIFIER_LENGTH
            and len(EVENT_TABLE) <= MAX_IDENTIFIER_LENGTH
        ),
        "postgres_live_evidence_present": (
            "ag_ack_expiry_automation_postgres_smoke=pass" in postgres_evidence
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
        else "ag_ack_expiry_automation_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces),
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _expired_state(state_id: str) -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=state_id,
        acknowledgement_key=f"nex-ag:{state_id}:stale",
        service_id="nex-ag",
        worker_id="ag-dispatch-execution-daemon",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={"operator_type": "service", "operator_id": "evidence-0829"},
        reason_codes=["privacy_runbook_0829"],
        comment=FORBIDDEN_VALUES["raw_comment"],
        idempotency_key=FORBIDDEN_VALUES["raw_idempotency_key"],
        requested_ttl_seconds=300,
        suppressed_until="2026-09-18T05:30:00Z",
        metadata={"source": "privacy_runbook", "slice": SLICE_ID},
        created_at="2026-09-18T05:00:00Z",
        updated_at="2026-09-18T05:00:00Z",
    )


def _store_with_expired_state(state_id: str) -> OperatorReviewLivenessAckStateStore:
    store = OperatorReviewLivenessAckStateStore()
    store.save(_expired_state(state_id))
    return store


def _capture_failure(emitter: OperationalEventEmitter) -> str:
    try:
        execute_liveness_ack_expiry_automation_cli(
            _BrokenStore(),
            action="run_once",
            environ=ENABLED_ENV,
            request_id="req-failed-0829",
            confirm_tick=True,
            observed_at="2026-09-18T06:03:00Z",
            lifecycle_emitter=emitter,
        )
    except OperatorReviewLivenessAckStateError as exc:
        return exc.error_code
    raise AssertionError("broken store did not fail")


def _cli_surface(result: Mapping[str, Any]) -> dict[str, Any]:
    tick = result.get("tick_result")
    tick_map = tick if isinstance(tick, Mapping) else {}
    plan = result.get("plan")
    plan_map = plan if isinstance(plan, Mapping) else {}
    return {
        "result_status": result.get("result_status"),
        "action": result.get("action"),
        "plan_status": plan_map.get("plan_status"),
        "planned_candidate_count": plan_map.get("candidate_count"),
        "tick_status": tick_map.get("tick_status"),
        "blocked_reason": tick_map.get("blocked_reason"),
        "candidate_count": tick_map.get("candidate_count"),
        "applied_count": tick_map.get("applied_count"),
        "conflict_count": tick_map.get("conflict_count"),
        "lifecycle_events": list(result.get("lifecycle_events") or []),
        "database_bound": bool(result.get("database_bound")),
    }


def _event_surface(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "event_count": len(events),
        "event_types": sorted(str(event.get("event_type") or "") for event in events),
        "details": [event.get("details", {}) for event in events],
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "automation_disabled": {
            "retryable": False,
            "action": "enable only after reviewing policy, scheduler, and test evidence",
        },
        "confirm_tick_required": {
            "retryable": True,
            "action": "repeat run-once with explicit confirm-tick after reviewing plan",
        },
        "database_unavailable": {
            "retryable": False,
            "action": "inspect nex-ag test or runtime database health and worker pool",
        },
        "event_source_unavailable": {
            "retryable": False,
            "action": "inspect service_operational_events persistence before scheduling",
        },
        "cas_conflict": {
            "retryable": True,
            "action": "allow the next bounded tick to re-read current state",
        },
        "zero_candidate_noop": {
            "retryable": False,
            "action": "treat as a successful idle tick",
        },
        "scheduler_invocation_failed": {
            "retryable": True,
            "action": "inspect exit code and safe lifecycle failure code before retry",
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
            "ag_ack_expiry_automation_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_ack_expiry_automation_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"conflict={checks.get('cas_conflict_reported')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_ack_expiry_automation_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
