#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import (  # noqa: E402
    OperationsQueryError,
    build_operation_query_options,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_control_history_projection,
    emit_operator_review_escalation_dispatch_daemon_control_audit_event,
    register_unified_operation_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
)


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook.v1"
)
SLICE_ID = "0769"
SERVICE_ID = "nex-ag"
TRACE_ID = "a7690d5da7694b41a7690d5da7694b41"
REQUEST_ID = "ag-dispatch-daemon-operations-privacy-runbook-0769"
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_"
    "runbook_evidence.py"
)
CONTROLS_ROUTE = "/admin/v1/operator-review/dispatch-daemon/controls"
TICK_PLAN_ROUTE = "/admin/v1/operator-review/dispatch-daemon/tick-plan"
TICK_ONCE_ROUTE = "/admin/v1/operator-review/dispatch-daemon/tick-once"

FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer operations-secret-0769",
    "provider_api_key": "provider-api-key-0769",
    "raw_provider_payload": "raw-provider-payload-0769",
    "raw_request_payload": "raw-control-request-0769",
    "storage_path": "/data/nex-platform/ag/private/operations-0769.json",
    "idempotency_key": "control-idempotency-key-0769",
}

FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_provider_payload",
    "raw_request_payload",
    "secret",
    "storage_path",
    "storage_uri",
}

EXPECTED_RUNBOOK_IDS = {
    "ag.operator_review_dispatch_daemon_control.failed_triage.v1",
    "ag.operator_review_dispatch_daemon_control.rejected_request_review.v1",
}
EXPECTED_OPERATOR_ACTIONS = {
    "inspect_failed_dispatch_daemon_control",
    "review_rejected_dispatch_daemon_control_request",
}

REQUIRED_DOCS = (
    "docs/slices/0761_ag_escalation_dispatch_daemon_operations_boundary_audit.md",
    "docs/slices/0762_ag_escalation_dispatch_daemon_control_audit_events.md",
    "docs/slices/0763_ag_escalation_dispatch_daemon_control_history_read_model.md",
    "docs/slices/0764_ag_escalation_dispatch_daemon_control_history_route.md",
    "docs/slices/0765_ag_escalation_dispatch_daemon_dashboard_integration.md",
    "docs/slices/0766_ag_escalation_dispatch_daemon_issue_candidate_integration.md",
    "docs/slices/0767_ag_escalation_dispatch_daemon_contract_openapi_hardening.md",
    "docs/slices/0768_ag_escalation_dispatch_daemon_operations_postgres_smoke.md",
)


def run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    event_store = _seed_event_store()
    query_options = build_operation_query_options(limit=50, sort="desc")
    history = (
        build_operator_review_escalation_dispatch_daemon_control_history_projection(
            event_store,
            trace_id=TRACE_ID,
            limit=50,
            query_options=query_options,
            request_trace_id=TRACE_ID,
        )
    )
    dashboard = build_operations_dashboard_snapshot_projection(
        event_store=event_store,
        service_id=SERVICE_ID,
        recent_limit=50,
        query_options=query_options,
        request_trace_id=TRACE_ID,
    )
    daemon_controls = dashboard["operator_review_escalation_dispatches"][
        "daemon_controls"
    ]
    issue_projection = build_operations_issue_candidate_projection(
        event_store=event_store,
        service_id=SERVICE_ID,
        recent_limit=50,
        query_options=query_options,
        request_trace_id=TRACE_ID,
    )
    issue_candidate = _dispatch_daemon_issue_candidate(issue_projection)
    surfaces = {
        "control_history": history,
        "dashboard_daemon_controls": daemon_controls,
        "issue_candidate": issue_candidate,
    }
    serialized_surfaces = json.dumps(
        surfaces,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    forbidden_key_paths = _forbidden_key_paths(surfaces, FORBIDDEN_KEYS)
    forbidden_value_labels = _forbidden_value_labels(serialized_surfaces)
    route_evidence = _controls_route_evidence(root)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    signal = (
        issue_candidate.get("signal", {})
        if isinstance(issue_candidate, Mapping)
        else {}
    )
    checks = {
        "history_ready": history.get("projection_status") == "READY",
        "history_trace_scoped": history.get("filters", {}).get("trace_id")
        == TRACE_ID,
        "history_has_three_controls": history.get("summary", {}).get(
            "control_count"
        )
        == 3,
        "dashboard_controls_ready": daemon_controls.get("projection_status")
        == "READY",
        "dashboard_failed_rejected_visible": (
            daemon_controls.get("summary", {}).get("failed_count") == 1
            and daemon_controls.get("summary", {}).get("rejected_count") == 1
        ),
        "issue_candidate_ready": issue_candidate is not None,
        "issue_candidate_runbooks_ready": EXPECTED_RUNBOOK_IDS.issubset(
            set(signal.get("runbook_ids", [])) if isinstance(signal, Mapping) else set()
        ),
        "issue_candidate_operator_actions_ready": EXPECTED_OPERATOR_ACTIONS.issubset(
            set(signal.get("recommended_operator_actions", []))
            if isinstance(signal, Mapping)
            else set()
        ),
        "runbook_paths_ready": _runbook_paths_ready(daemon_controls, signal),
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "redaction_flags_safe": _redaction_flags_safe(history)
        and _redaction_flags_safe(daemon_controls),
        "static_controls_route_ready": route_evidence["static_ready"],
        "runtime_controls_route_ready": route_evidence["runtime_ready"],
        "controls_route_filters_ready": route_evidence["filters_ready"],
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": {
            "control_history": history.get("summary", {}),
            "dashboard_daemon_controls": daemon_controls.get("summary", {}),
            "issue_candidate": _issue_candidate_summary(issue_candidate),
        },
        "route": route_evidence,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _seed_event_store() -> InMemoryOperationalEventStore:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    results = [
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_plan",
            http_method="GET",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            projection=_tick_plan_projection(),
        ),
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_once",
            http_method="POST",
            request_id=f"{REQUEST_ID}-rejected",
            trace_id=TRACE_ID,
            error=OperationsQueryError(
                error_code=(
                    "ag.operator_review_escalation_dispatch_daemon_control_denied"
                ),
                detail="Synthetic rejected control for S77 privacy/runbook evidence.",
                status_code=409,
            ),
        ),
        emit_operator_review_escalation_dispatch_daemon_control_audit_event(
            emitter,
            action="tick_once",
            http_method="POST",
            request_id=f"{REQUEST_ID}-failed",
            trace_id=TRACE_ID,
            error=OperationsQueryError(
                error_code=(
                    "ag.operator_review_escalation_dispatch_daemon_dispatch_source_"
                    "unavailable"
                ),
                detail="Synthetic failed control for S77 privacy/runbook evidence.",
                status_code=503,
            ),
        ),
    ]
    if not all(result.ok for result in results):
        raise ValueError("failed to seed dispatch daemon control events")
    return event_store


def _tick_plan_projection() -> dict[str, Any]:
    return {
        "projection_schema_version": (
            "ag_operator_review_escalation_dispatch_daemon_tick_plan_api.v1"
        ),
        "summary": {
            "plan_status": "READY",
            "candidate_count": 1,
            "processed_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "retry_wait_count": 0,
            "skipped_count": 0,
            "mutation_performed": False,
        },
        "route": {
            "method": "GET",
            "path": TICK_PLAN_ROUTE,
            "mutation": False,
            "requires_confirm_tick": False,
        },
        "control_request": {
            "confirm_tick": False,
            "dry_run": True,
            "authorization": FORBIDDEN_VALUES["authorization"],
            "database_url": FORBIDDEN_VALUES["database_url"],
            "idempotency_key": FORBIDDEN_VALUES["idempotency_key"],
            "provider_api_key": FORBIDDEN_VALUES["provider_api_key"],
            "provider_payload": {"raw": FORBIDDEN_VALUES["raw_provider_payload"]},
            "raw_request_payload": FORBIDDEN_VALUES["raw_request_payload"],
            "storage_path": FORBIDDEN_VALUES["storage_path"],
        },
        "control_admission": {
            "admission_status": "ACCEPTED",
            "rejection_reason": None,
        },
        "policy": {
            "enabled": True,
            "batch_limit": 1,
            "effective_provider_mode": "mock_first_only",
        },
    }


def _controls_route_evidence(root: Path) -> dict[str, Any]:
    static_paths = _load_static_openapi_paths(root)
    runtime_paths = _runtime_openapi_paths()
    static_operation = static_paths.get(CONTROLS_ROUTE, {}).get("get", {})
    runtime_operation = runtime_paths.get(CONTROLS_ROUTE, {}).get("get", {})
    expected_operation_id = "listAgOperatorReviewDispatchDaemonControls"
    parameter_names = {
        item.get("name")
        for item in static_operation.get("parameters", [])
        if isinstance(item, Mapping)
    }
    return {
        "path": CONTROLS_ROUTE,
        "method": "GET",
        "operation_id": expected_operation_id,
        "static_operation_id": static_operation.get("operationId"),
        "runtime_operation_id": runtime_operation.get("operationId"),
        "static_ready": static_operation.get("operationId") == expected_operation_id,
        "runtime_ready": runtime_operation.get("operationId") == expected_operation_id,
        "filters_ready": {"action", "control_status", "trace_id"}.issubset(
            parameter_names
        ),
        "parameters": sorted(name for name in parameter_names if name),
    }


def _load_static_openapi_paths(root: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
    return payload["paths"]


def _runtime_openapi_paths() -> Mapping[str, Any]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(
        app,
        event_store=InMemoryOperationalEventStore(),
    )
    return app.openapi()["paths"]


def _dispatch_daemon_issue_candidate(
    issue_projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    for candidate in issue_projection.get("issue_candidates", []):
        if (
            isinstance(candidate, Mapping)
            and candidate.get("rule_id")
            == "operator_review_dispatch_daemon_control_attention_required.v1"
        ):
            return dict(candidate)
    return None


def _issue_candidate_summary(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    signal = candidate.get("signal", {})
    return {
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "runbook_ids": (
            sorted(signal.get("runbook_ids", []))
            if isinstance(signal, Mapping)
            else []
        ),
        "recommended_operator_actions": (
            sorted(signal.get("recommended_operator_actions", []))
            if isinstance(signal, Mapping)
            else []
        ),
    }


def _runbook_paths_ready(
    daemon_controls: Mapping[str, Any],
    signal: Mapping[str, Any] | object,
) -> bool:
    if not isinstance(signal, Mapping):
        return False
    return (
        daemon_controls.get("control_history_path") == CONTROLS_ROUTE
        and daemon_controls.get("tick_plan_path") == TICK_PLAN_ROUTE
        and daemon_controls.get("tick_once_path") == TICK_ONCE_ROUTE
        and signal.get("control_history_path") == CONTROLS_ROUTE
        and signal.get("tick_plan_path") == TICK_PLAN_ROUTE
        and signal.get("tick_once_path") == TICK_ONCE_ROUTE
    )


def _redaction_flags_safe(surface: object) -> bool:
    unsafe_flags = {
        "raw_request_payload_included",
        "raw_provider_payload_included",
        "sensitive_values_included",
    }
    if isinstance(surface, Mapping):
        return all(
            not (key in unsafe_flags and value is True)
            and _redaction_flags_safe(value)
            for key, value in surface.items()
        )
    if isinstance(surface, list):
        return all(_redaction_flags_safe(item) for item in surface)
    return True


def _forbidden_key_paths(value: object, forbidden_keys: set[str]) -> list[str]:
    paths: list[str] = []

    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text in forbidden_keys:
                    paths.append(child_path)
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return sorted(paths)


def _forbidden_value_labels(serialized: str) -> list[str]:
    return sorted(
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    )


def _assert_no_forbidden_values(serialized: str) -> None:
    leaks = _forbidden_value_labels(serialized)
    if leaks:
        raise ValueError(
            "Dispatch daemon operations privacy/runbook evidence leaked "
            f"{len(leaks)} forbidden value(s)."
        )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"runbooks={checks.get('issue_candidate_runbooks_ready')} "
        f"route={checks.get('runtime_controls_route_ready')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
