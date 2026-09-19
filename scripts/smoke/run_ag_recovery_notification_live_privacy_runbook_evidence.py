#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


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
    MockDispatchProviderHttpTransport,
    build_dispatch_execution_provider_config,
)
from nex_ag.recovery_notification_delivery import (  # noqa: E402
    RecoveryNotificationDeliveryError,
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


SCHEMA_VERSION = "ag_recovery_notification_live_privacy_runbook.v1"
SLICE_ID = "0859"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_recovery_notification_live_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0858_ag_recovery_notification_live_postgres_smoke.md"
)
OBSERVED_AT = "2026-09-19T11:00:00Z"
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "endpoint_url": "http://127.0.0.1:18559/private-recovery-notification",
    "endpoint_path": "/private-recovery-notification",
    "provider_token": "private-recovery-live-provider-token-0859",
    "raw_idempotency_key": "private-recovery-live-idempotency-0859",
    "raw_notification_payload": "private-recovery-live-payload-0859",
}
FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "endpoint_url",
    "idempotency_key",
    "provider_token",
    "raw_notification_payload",
    "request_signature",
    "secret",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0851", "ag_recovery_notification_live_delivery_boundary_audit"),
        ("0852", "ag_recovery_notification_live_delivery_admission"),
        ("0853", "ag_recovery_notification_live_dispatch_handoff"),
        ("0854", "ag_recovery_notification_live_delivery_api"),
        ("0855", "ag_recovery_notification_live_execution"),
        ("0856", "ag_recovery_notification_live_contract_hardening"),
        ("0857", "ag_recovery_notification_live_loopback_smoke"),
        ("0858", "ag_recovery_notification_live_postgres_smoke"),
    )
)


def run_ag_recovery_notification_live_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    disabled = _capture_error(
        lambda: build_recovery_notification_live_admission(
            _base_delivery_admission("disabled"),
            _disabled_provider_config(),
            confirm_live_delivery=True,
            admitted_at=OBSERVED_AT,
        )
    )
    unconfirmed_admission = _capture_error(
        lambda: build_recovery_notification_live_admission(
            _base_delivery_admission("unconfirmed-admission"),
            _live_provider_config(),
            admitted_at=OBSERVED_AT,
        )
    )
    blocked_service, blocked_store, blocked_id = _live_delivery("blocked")
    unconfirmed_execution = run_recovery_notification_delivery_live_once(
        blocked_service,
        dispatch_id=blocked_id,
        request_id="request-0859-blocked",
        provider_config=_live_provider_config(),
        executed_at=OBSERVED_AT,
    )
    missing_transport = _capture_error(
        lambda: run_recovery_notification_delivery_live_once(
            blocked_service,
            dispatch_id=blocked_id,
            request_id="request-0859-no-transport",
            provider_config=_live_provider_config(),
            confirm_run=True,
            executed_at=OBSERVED_AT,
        )
    )
    retry_service, retry_store, retry_id = _live_delivery("retry")
    retry_execution = run_recovery_notification_delivery_live_once(
        retry_service,
        dispatch_id=retry_id,
        request_id="request-0859-retry",
        provider_config=_live_provider_config(),
        live_http_transport=MockDispatchProviderHttpTransport((503, 503, 503)),
        confirm_run=True,
        executed_at=OBSERVED_AT,
    )
    success_service, success_store, success_id = _live_delivery("success")
    success_execution = run_recovery_notification_delivery_live_once(
        success_service,
        dispatch_id=success_id,
        request_id="request-0859-success",
        provider_config=_live_provider_config(),
        live_http_transport=MockDispatchProviderHttpTransport((202,)),
        confirm_run=True,
        executed_at=OBSERVED_AT,
    )
    completed_noop = run_recovery_notification_delivery_live_once(
        success_service,
        dispatch_id=success_id,
        request_id="request-0859-noop",
        provider_config=_live_provider_config(),
        live_http_transport=MockDispatchProviderHttpTransport((202,)),
        confirm_run=True,
        executed_at="2026-09-19T11:01:00Z",
    )
    projection = build_recovery_notification_delivery_operations_projection(
        success_store.list_dispatches(),
        request_trace_id="trace-0859",
    )
    runbook = _runbook_actions()
    surfaces = {
        "provider_disabled": disabled,
        "admission_confirmation_missing": unconfirmed_admission,
        "execution_confirmation_missing": _execution_surface(
            unconfirmed_execution
        ),
        "transport_missing": missing_transport,
        "retry_wait": _execution_surface(retry_execution),
        "success": _execution_surface(success_execution),
        "completed_noop": _execution_surface(completed_noop),
        "delivery_projection": projection,
        "persisted_states": {
            "blocked": _dispatch_status(blocked_store, blocked_id),
            "retry": _dispatch_status(retry_store, retry_id),
            "success": _dispatch_status(success_store, success_id),
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
        "provider_default_disabled": disabled.get("error_code")
        == "ag.recovery_notification_live_provider_not_enabled",
        "admission_confirmation_required": unconfirmed_admission.get("error_code")
        == "ag.recovery_notification_live_confirmation_required",
        "execution_confirmation_required": (
            unconfirmed_execution.get("execution_status") == "BLOCKED"
            and unconfirmed_execution.get("delivery", {}).get(
                "provider_invocation_performed"
            )
            is False
            and _dispatch_status(blocked_store, blocked_id) == "PENDING"
        ),
        "transport_injection_required": missing_transport.get("error_code")
        == "ag.recovery_notification_live_execution_transport_required",
        "retry_wait_is_persisted": (
            retry_execution.get("execution_status") == "COMPLETED"
            and retry_execution.get("worker_run", {}).get("retry_wait_count") == 1
            and _dispatch_status(retry_store, retry_id) == "RETRY_WAIT"
        ),
        "success_and_terminal_noop": (
            success_execution.get("execution_status") == "COMPLETED"
            and _dispatch_status(success_store, success_id) == "SUCCEEDED"
            and completed_noop.get("execution_status") == "NOOP"
        ),
        "projection_is_redacted": (
            projection.get("summary", {}).get("succeeded") == 1
            and projection.get("redaction", {}).get(
                "request_signatures_included"
            )
            is False
        ),
        "runbook_complete": set(runbook)
        == {
            "default_disabled",
            "admission_confirmation",
            "execution_confirmation",
            "transport_injection",
            "endpoint_readiness",
            "retry_wait",
            "completed_noop",
            "real_endpoint_deferred",
            "postgres_cleanup",
        },
        "postgres_loopback_evidence_present": (
            "ag_recovery_notification_live_postgres_smoke=pass"
            in postgres_evidence
            and "cleaned=True" in postgres_evidence
        ),
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    passed = all(checks.values())
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_recovery_notification_live_privacy_runbook_failed",
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


def _live_delivery(
    suffix: str,
) -> tuple[
    OperatorReviewCaseService,
    OperatorReviewEscalationDispatchStore,
    str,
]:
    admission = _base_delivery_admission(suffix)
    live_admission = build_recovery_notification_live_admission(
        admission,
        _live_provider_config(),
        confirm_live_delivery=True,
        admitted_at=OBSERVED_AT,
    )
    escalation = _escalation_record(suffix)
    handoff = build_recovery_notification_dispatch_handoff(
        _notification_plan(suffix),
        admission,
        escalation,
        request_id=f"request-0859-{suffix}",
        idempotency_key=(
            f"{FORBIDDEN_VALUES['raw_idempotency_key']}-{suffix}"
        ),
        created_at=OBSERVED_AT,
        live_admission=live_admission,
    )
    store = OperatorReviewEscalationDispatchStore()
    persisted = persist_recovery_notification_dispatch_handoff(handoff, store)
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=store,
    )
    return service, store, str(persisted["dispatch_record"]["dispatch_id"])


def _base_delivery_admission(suffix: str) -> dict[str, Any]:
    plan = _notification_plan(suffix)
    return build_recovery_notification_delivery_admission(
        plan,
        _case_record(suffix),
        _escalation_record(suffix),
        channel_type="NOTIFICATION",
        provider_profile="notification-webhook-default",
        admitted_at=OBSERVED_AT,
    )


def _notification_plan(suffix: str) -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": "nex-ag",
                "worker_id": f"ag-dispatch-execution-daemon-{suffix}",
            },
            "recommended_actions": [
                {
                    "severity": "ERROR",
                    "raw_notification_payload": FORBIDDEN_VALUES[
                        "raw_notification_payload"
                    ],
                }
            ],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=OBSERVED_AT,
    )


def _case_record(suffix: str) -> dict[str, Any]:
    return {
        "case_id": f"case-0859-{suffix}",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": f"ag-dispatch-execution-daemon-{suffix}",
    }


def _escalation_record(suffix: str) -> dict[str, Any]:
    return {
        "escalation_id": f"escalation-0859-{suffix}",
        "case_id": f"case-0859-{suffix}",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": f"ag-dispatch-execution-daemon-{suffix}",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "reason_codes": ["daemon_stale"],
        "recommended_actions": ["inspect_dispatch_daemon"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
    }


def _live_provider_config() -> dict[str, Any]:
    return build_dispatch_execution_provider_config(
        {
            "NEX_AG_DISPATCH_EXECUTION_PROVIDER_MODE": "live_http",
            "NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE": "1",
            "NEX_AG_NOTIFICATION_WEBHOOK_URL": FORBIDDEN_VALUES["endpoint_url"],
            "NEX_AG_NOTIFICATION_SERVICE_TOKEN": FORBIDDEN_VALUES[
                "provider_token"
            ],
            "NEX_AG_DISPATCH_HTTP_MAX_RETRIES": "0",
        }
    )


def _disabled_provider_config() -> dict[str, Any]:
    return build_dispatch_execution_provider_config({})


def _capture_error(call: Callable[[], object]) -> dict[str, Any]:
    try:
        call()
    except RecoveryNotificationDeliveryError as exc:
        return {
            "status": "BLOCKED",
            "status_code": exc.status_code,
            "error_code": exc.error_code,
            "retryable": exc.status_code >= 500,
        }
    return {"status": "UNEXPECTED_SUCCESS"}


def _execution_surface(value: Mapping[str, Any]) -> dict[str, Any]:
    worker = _mapping(value.get("worker_run"))
    delivery = _mapping(value.get("delivery"))
    return {
        "execution_status": value.get("execution_status"),
        "blocked_reason": worker.get("blocked_reason"),
        "candidate_count": worker.get("candidate_count"),
        "succeeded_count": worker.get("succeeded_count"),
        "retry_wait_count": worker.get("retry_wait_count"),
        "provider_invocation_performed": delivery.get(
            "provider_invocation_performed"
        ),
    }


def _dispatch_status(
    store: OperatorReviewEscalationDispatchStore,
    dispatch_id: str,
) -> str | None:
    return _mapping(store.get(dispatch_id)).get("dispatch_status")


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "default_disabled": {
            "retryable": True,
            "action": "keep live mode disabled until an approved window",
        },
        "admission_confirmation": {
            "retryable": True,
            "action": "obtain explicit live-delivery admission confirmation",
        },
        "execution_confirmation": {
            "retryable": True,
            "action": "confirm the selected dispatch immediately before execution",
        },
        "transport_injection": {
            "retryable": True,
            "action": "inject the approved HTTP transport at the execution boundary",
        },
        "endpoint_readiness": {
            "retryable": True,
            "action": "verify configured endpoint and compatible provider profile",
        },
        "retry_wait": {
            "retryable": True,
            "action": "wait for next_attempt_at and preserve bounded retry policy",
        },
        "completed_noop": {
            "retryable": False,
            "action": "treat a succeeded dispatch as terminal",
        },
        "real_endpoint_deferred": {
            "retryable": False,
            "action": "use loopback smoke until a real endpoint is approved",
        },
        "postgres_cleanup": {
            "retryable": True,
            "action": "verify zero owned rows before rerunning PostgreSQL smoke",
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
            "ag_recovery_notification_live_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_recovery_notification_live_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"failures={checks.get('transport_injection_required')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_recovery_notification_live_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
