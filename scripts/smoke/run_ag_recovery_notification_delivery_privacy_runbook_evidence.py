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

from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
)
from nex_ag.recovery_notification_delivery import (  # noqa: E402
    build_recovery_notification_delivery_admission,
    build_recovery_notification_dispatch_handoff,
    persist_recovery_notification_dispatch_handoff,
    run_recovery_notification_delivery_mock_once,
)
from nex_ag.recovery_notification_operations import (  # noqa: E402
    build_recovery_notification_delivery_operations_projection,
)
from nex_ag.recovery_notification_policy import (  # noqa: E402
    build_recovery_notification_plan,
)


SCHEMA_VERSION = "ag_recovery_notification_delivery_privacy_runbook.v1"
SLICE_ID = "0849"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_recovery_notification_delivery_privacy_runbook_evidence.py"
)
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0848_ag_recovery_notification_delivery_postgres_smoke.md"
)
OBSERVED_AT = "2026-09-19T06:00:00Z"
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer recovery-delivery-secret-0849",
    "raw_comment": "raw-recovery-delivery-comment-secret-0849",
    "raw_idempotency_key": "raw-recovery-delivery-idempotency-secret-0849",
    "provider_token": "provider-token-secret-0849",
    "raw_provider_payload": "raw-provider-payload-secret-0849",
}
FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_token",
    "raw_comment",
    "raw_notification_payload",
    "raw_provider_payload",
    "request_signature",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0841", "ag_recovery_notification_delivery_boundary_audit"),
        ("0842", "ag_recovery_notification_delivery_admission"),
        ("0843", "ag_recovery_notification_dispatch_handoff"),
        ("0844", "ag_recovery_notification_delivery_api"),
        ("0845", "ag_recovery_notification_delivery_operations"),
        ("0846", "ag_recovery_notification_delivery_contract_hardening"),
        ("0847", "ag_recovery_notification_delivery_mock_execution"),
        ("0848", "ag_recovery_notification_delivery_postgres_smoke"),
    )
)


def run_ag_recovery_notification_delivery_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _notification_plan()
    case = _case_record()
    escalation = _escalation_record()
    admission = build_recovery_notification_delivery_admission(
        plan,
        case,
        escalation,
        admitted_at=OBSERVED_AT,
    )
    handoff = build_recovery_notification_dispatch_handoff(
        plan,
        admission,
        escalation,
        request_id="request-0849",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        idempotency_key=FORBIDDEN_VALUES["raw_idempotency_key"],
        created_at=OBSERVED_AT,
    )
    dispatch_store = OperatorReviewEscalationDispatchStore()
    created = persist_recovery_notification_dispatch_handoff(
        handoff,
        dispatch_store,
    )
    replayed = persist_recovery_notification_dispatch_handoff(
        handoff,
        dispatch_store,
    )
    dispatch_id = str(created["dispatch_record"]["dispatch_id"])
    persisted = dispatch_store.get(dispatch_id) or {}
    internal_delivery = _mapping(_mapping(persisted.get("metadata")).get(
        "recovery_notification_delivery"
    ))
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=dispatch_store,
    )
    blocked = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0849-blocked",
        executed_at=OBSERVED_AT,
    )
    executed = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0849-executed",
        confirm_run=True,
        executed_at=OBSERVED_AT,
    )
    noop = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0849-noop",
        confirm_run=True,
        executed_at="2026-09-19T06:01:00Z",
    )
    projection = build_recovery_notification_delivery_operations_projection(
        dispatch_store.list_dispatches(),
        request_trace_id="trace-0849",
    )
    unavailable = build_recovery_notification_delivery_operations_projection(
        None,
        error_code="ag.recovery_notification_delivery_store_unavailable",
    )
    live_admission = build_recovery_notification_delivery_admission(
        plan,
        case,
        escalation,
        channel_type="NOTIFICATION",
        admitted_at=OBSERVED_AT,
    )
    live_handoff = build_recovery_notification_dispatch_handoff(
        plan,
        live_admission,
        escalation,
        request_id="request-0849-live",
        created_at=OBSERVED_AT,
    )
    runbook = _runbook_actions()
    surfaces = {
        "created": created,
        "replayed": replayed,
        "confirmation_blocked": blocked,
        "mock_executed": executed,
        "completed_noop": noop,
        "delivery_projection": projection,
        "source_unavailable": unavailable,
        "live_channel_handoff": _handoff_surface(live_handoff),
        "internal_persistence": {
            "request_signature_persisted": (
                "request_signature" in internal_delivery
            ),
            "request_signature_exposed": False,
            "source_table": "ag_op_esc_dispatches",
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
        "created_response_redacted": (
            created["idempotency_status"] == "NEW"
            and "request_signature" not in json.dumps(created)
        ),
        "replay_response_redacted": (
            replayed["idempotency_status"] == "REPLAYED"
            and "request_signature" not in json.dumps(replayed)
        ),
        "internal_idempotency_signature_preserved": (
            "request_signature" in internal_delivery
        ),
        "confirmation_required": blocked["execution_status"] == "BLOCKED",
        "mock_execution_completed": (
            executed["execution_status"] == "COMPLETED"
            and executed["guardrails"]["external_network_allowed"] is False
        ),
        "completed_retry_is_noop": noop["execution_status"] == "NOOP",
        "read_model_redacted": (
            projection["delivery_status"] == "ACTIVE"
            and projection["summary"]["succeeded"] == 1
            and projection["redaction"]["request_signatures_included"] is False
        ),
        "source_unavailable_degrades": (
            unavailable["projection_status"] == "DEGRADED"
            and unavailable["delivery_status"] == "SOURCE_UNAVAILABLE"
        ),
        "live_channel_remains_blocked": (
            live_handoff["handoff_status"] == "BLOCKED"
            and live_handoff["blocking_reasons"] == ["live_channel_deferred"]
        ),
        "runbook_complete": set(runbook)
        == {
            "confirmation_required",
            "non_delivery_marker",
            "live_channel_blocked",
            "idempotency_conflict",
            "provider_retry_wait",
            "completed_noop",
            "source_unavailable",
            "postgres_failure_cleanup",
        },
        "postgres_live_evidence_present": (
            "ag_recovery_notification_delivery_postgres_smoke=pass"
            in postgres_evidence
            and "cleaned=True" in postgres_evidence
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
        else "ag_recovery_notification_delivery_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces) - 1,
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _notification_plan() -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": "nex-ag",
                "worker_id": "ag-dispatch-execution-daemon",
            },
            "recommended_actions": [
                {
                    "severity": "ERROR",
                    "raw_comment": FORBIDDEN_VALUES["raw_comment"],
                    "raw_provider_payload": FORBIDDEN_VALUES[
                        "raw_provider_payload"
                    ],
                }
            ],
            "authorization": FORBIDDEN_VALUES["authorization"],
            "database_url": FORBIDDEN_VALUES["database_url"],
            "provider_token": FORBIDDEN_VALUES["provider_token"],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=OBSERVED_AT,
        request_trace_id="trace-0849",
    )


def _case_record() -> dict[str, Any]:
    return {
        "case_id": "case-0849",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "metadata": {"raw_comment": FORBIDDEN_VALUES["raw_comment"]},
    }


def _escalation_record() -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0849",
        "candidate_id": "candidate-0849",
        "case_id": "case-0849",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_stale"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "metadata": {
            "provider_token": FORBIDDEN_VALUES["provider_token"],
        },
    }


def _handoff_surface(handoff: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dispatch_handoff_schema_version": handoff.get(
            "dispatch_handoff_schema_version"
        ),
        "handoff_status": handoff.get("handoff_status"),
        "blocking_reasons": list(handoff.get("blocking_reasons") or []),
        "guardrails": dict(handoff.get("guardrails") or {}),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "confirmation_required": {
            "retryable": True,
            "action": "repeat with explicit operator-approved confirmation",
        },
        "non_delivery_marker": {
            "retryable": False,
            "action": "reject the record and inspect its creation path",
        },
        "live_channel_blocked": {
            "retryable": False,
            "action": "keep MOCK mode until a live-provider boundary is approved",
        },
        "idempotency_conflict": {
            "retryable": False,
            "action": "use a new key only after comparing safe request context",
        },
        "provider_retry_wait": {
            "retryable": True,
            "action": "wait for next_attempt_at and retain bounded retry policy",
        },
        "completed_noop": {
            "retryable": False,
            "action": "treat the completed dispatch as terminal",
        },
        "source_unavailable": {
            "retryable": True,
            "action": "restore the AG dispatch store before retrying",
        },
        "postgres_failure_cleanup": {
            "retryable": True,
            "action": "verify cleanup and migrations before rerunning smoke",
        },
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
            "ag_recovery_notification_delivery_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_recovery_notification_delivery_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"signature={checks.get('internal_idempotency_signature_preserved')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_recovery_notification_delivery_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
