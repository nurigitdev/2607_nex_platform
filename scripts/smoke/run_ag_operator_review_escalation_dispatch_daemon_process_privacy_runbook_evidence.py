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
    build_operations_dashboard_snapshot_projection,
    build_operator_review_escalation_dispatch_daemon_process_control_api_projection,
    register_unified_operation_routes,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    build_dispatch_execution_daemon_process_metadata,
    build_dispatch_execution_daemon_process_runtime_state,
    emit_dispatch_execution_daemon_lifecycle_event,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
)


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook.v1"
)
SLICE_ID = "0779"
SERVICE_ID = "nex-ag"
TRACE_ID = "a7790d5da7794b41a7790d5da7794b41"
REQUEST_ID = "ag-dispatch-daemon-process-privacy-runbook-0779"
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_operator_review_escalation_dispatch_daemon_process_privacy_"
    "runbook_evidence.py"
)
PROCESS_CONTROL_ROUTE = "/admin/v1/operator-review/dispatch-daemon/process-controls"
CONTROL_HISTORY_ROUTE = "/admin/v1/operator-review/dispatch-daemon/controls"
TICK_PLAN_ROUTE = "/admin/v1/operator-review/dispatch-daemon/tick-plan"
TICK_ONCE_ROUTE = "/admin/v1/operator-review/dispatch-daemon/tick-once"

FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer process-secret-0779",
    "provider_api_key": "provider-api-key-0779",
    "raw_provider_payload": "raw-provider-payload-0779",
    "raw_request_payload": "raw-process-control-request-0779",
    "storage_path": "/data/nex-platform/ag/private/process-0779.json",
    "idempotency_key": "process-control-idempotency-key-0779",
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
    "ag.operator_review_dispatch_daemon_process.lifecycle_triage.v1",
    "ag.operator_review_dispatch_daemon_process.control_review.v1",
}
EXPECTED_OPERATOR_ACTIONS = {
    "inspect_dispatch_daemon_process_lifecycle",
    "review_dispatch_daemon_process_control_request",
}

REQUIRED_DOCS = (
    "docs/slices/0771_ag_escalation_dispatch_daemon_process_boundary_audit.md",
    "docs/slices/0772_ag_escalation_dispatch_daemon_runtime_loop_policy.md",
    "docs/slices/0773_ag_escalation_dispatch_daemon_process_metadata_contract.md",
    "docs/slices/0774_ag_escalation_dispatch_daemon_executable_cli.md",
    "docs/slices/0775_ag_escalation_dispatch_daemon_lifecycle_event_persistence.md",
    "docs/slices/0776_ag_escalation_dispatch_daemon_process_control_api.md",
    "docs/slices/0777_ag_escalation_dispatch_daemon_process_dashboard.md",
    "docs/slices/0778_ag_escalation_dispatch_daemon_process_postgres_smoke.md",
)


def run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    event_store = _seed_process_event_store()
    dashboard = build_operations_dashboard_snapshot_projection(
        event_store=event_store,
        service_id=SERVICE_ID,
        recent_limit=20,
        request_trace_id=TRACE_ID,
    )
    daemon_process = dashboard["operator_review_escalation_dispatches"][
        "daemon_process"
    ]
    process_control = (
        build_operator_review_escalation_dispatch_daemon_process_control_api_projection(
            payload={
                "action": "start_process",
                "enabled": True,
                "dry_run": False,
                "confirm_process": True,
                "operator_ref": {
                    "operator_type": "user",
                    "operator_id": "employee-0779",
                    "authorization": FORBIDDEN_VALUES["authorization"],
                    "secret": "hidden-process-secret",
                },
                "reason_codes": ["operator_start"],
                "database_url": FORBIDDEN_VALUES["database_url"],
                "raw_request_payload": FORBIDDEN_VALUES["raw_request_payload"],
                "provider_api_key": FORBIDDEN_VALUES["provider_api_key"],
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    )
    lifecycle_surface = _lifecycle_surface(event_store)
    runbook_matrix = _runbook_matrix(daemon_process, process_control)
    surfaces = {
        "dashboard_daemon_process": daemon_process,
        "process_control": process_control,
        "lifecycle_events": lifecycle_surface,
        "runbook_matrix": runbook_matrix,
    }
    serialized_surfaces = json.dumps(
        surfaces,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    forbidden_key_paths = _forbidden_key_paths(surfaces, FORBIDDEN_KEYS)
    forbidden_value_labels = _forbidden_value_labels(serialized_surfaces)
    route_evidence = _process_control_route_evidence(root)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    checks = {
        "dashboard_process_ready": daemon_process.get("projection_status") == "READY",
        "process_control_ready": process_control.get("projection_status") == "READY",
        "process_control_contract_only": (
            process_control.get("route", {}).get("protected") is True
            and process_control.get("route", {}).get("mutation") is False
            and process_control.get("summary", {}).get("subprocess_mutation_performed")
            is False
        ),
        "lifecycle_events_ready": lifecycle_surface["event_count"] == 3
        and lifecycle_surface["blocked_count"] == 1,
        "runbook_ids_ready": EXPECTED_RUNBOOK_IDS.issubset(
            set(runbook_matrix["runbook_ids"])
        ),
        "operator_actions_ready": EXPECTED_OPERATOR_ACTIONS.issubset(
            set(runbook_matrix["recommended_operator_actions"])
        ),
        "runbook_paths_ready": _runbook_paths_ready(
            daemon_process,
            process_control,
            runbook_matrix,
        ),
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "redaction_flags_safe": _redaction_flags_safe(surfaces),
        "static_process_control_route_ready": route_evidence["static_ready"],
        "runtime_process_control_route_ready": route_evidence["runtime_ready"],
        "process_control_request_body_ready": route_evidence["request_body_ready"],
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": {
            "dashboard_daemon_process": daemon_process.get("summary", {}),
            "process_control": process_control.get("summary", {}),
            "lifecycle_events": lifecycle_surface,
            "runbook_matrix": runbook_matrix,
        },
        "route": route_evidence,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _seed_process_event_store() -> InMemoryOperationalEventStore:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    metadata = build_dispatch_execution_daemon_process_metadata(
        process_run_id="process-run-0779",
        worker_id="worker-0779",
        started_at="2026-09-15T14:00:00Z",
    )
    blocked_loop = {
        "loop_status": "BLOCKED",
        "stop_reason": "confirm_tick_required",
        "worker_id": "worker-0779",
        "cycle_count": 0,
        "cycle_limit": 1,
        "summary": {
            "processed_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "retry_wait_count": 0,
        },
        "new_tables_required": False,
    }
    blocked_state = build_dispatch_execution_daemon_process_runtime_state(
        metadata,
        loop_result=blocked_loop,
        observed_at="2026-09-15T14:00:03Z",
    )
    results = [
        emit_dispatch_execution_daemon_lifecycle_event(
            emitter,
            process_metadata=metadata,
            event_name="started",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            occurred_at="2026-09-15T14:00:01Z",
        ),
        emit_dispatch_execution_daemon_lifecycle_event(
            emitter,
            process_metadata=metadata,
            event_name="completed",
            runtime_state=build_dispatch_execution_daemon_process_runtime_state(
                metadata,
                observed_at="2026-09-15T14:00:02Z",
            ),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            occurred_at="2026-09-15T14:00:02Z",
        ),
        emit_dispatch_execution_daemon_lifecycle_event(
            emitter,
            process_metadata=metadata,
            event_name="completed",
            loop_result=blocked_loop,
            runtime_state=blocked_state,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            occurred_at="2026-09-15T14:00:03Z",
        ),
    ]
    if not all(result.ok for result in results):
        raise ValueError("failed to seed dispatch daemon process lifecycle events")
    return event_store


def _lifecycle_surface(event_store: InMemoryOperationalEventStore) -> dict[str, Any]:
    events = event_store.list_events(
        service_id=SERVICE_ID,
        trace_id=TRACE_ID,
        limit=20,
    )
    event_types = [str(event.get("event_type")) for event in events]
    return {
        "event_count": len(events),
        "blocked_count": sum(1 for event_type in event_types if event_type.endswith(".blocked")),
        "event_types": sorted(event_types),
        "event_ids": sorted(str(event.get("event_id")) for event in events),
        "redaction": {
            "raw_provider_payload_included": False,
            "raw_request_payload_included": False,
            "provider_secrets_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
        },
    }


def _runbook_matrix(
    daemon_process: Mapping[str, Any],
    process_control: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "runbook_ids": sorted(EXPECTED_RUNBOOK_IDS),
        "recommended_operator_actions": sorted(EXPECTED_OPERATOR_ACTIONS),
        "process_control_path": process_control.get("route", {}).get("path"),
        "dashboard_process_control_path": daemon_process.get("process_control_path"),
        "control_history_path": CONTROL_HISTORY_ROUTE,
        "tick_plan_path": TICK_PLAN_ROUTE,
        "tick_once_path": TICK_ONCE_ROUTE,
        "diagnostic_sources": [
            "service_operational_events",
            "service_worker_heartbeats",
            "ag_op_esc_dispatches",
        ],
        "manual_subprocess_mutation_required": False,
        "redaction": {
            "raw_provider_payload_included": False,
            "raw_request_payload_included": False,
            "provider_secrets_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
        },
    }


def _process_control_route_evidence(root: Path) -> dict[str, Any]:
    static_paths = _load_static_openapi_paths(root)
    runtime_paths = _runtime_openapi_paths()
    static_operation = static_paths.get(PROCESS_CONTROL_ROUTE, {}).get("post", {})
    runtime_operation = runtime_paths.get(PROCESS_CONTROL_ROUTE, {}).get("post", {})
    expected_operation_id = "postAgOperatorReviewDispatchDaemonProcessControl"
    return {
        "path": PROCESS_CONTROL_ROUTE,
        "method": "POST",
        "operation_id": expected_operation_id,
        "static_operation_id": static_operation.get("operationId"),
        "runtime_operation_id": runtime_operation.get("operationId"),
        "static_ready": static_operation.get("operationId") == expected_operation_id,
        "runtime_ready": runtime_operation.get("operationId") == expected_operation_id,
        "request_body_ready": "requestBody" in static_operation,
        "response_codes": sorted(static_operation.get("responses", {}).keys()),
    }


def _load_static_openapi_paths(root: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load((root / OPENAPI_PATH).read_text(encoding="utf-8"))
    return payload["paths"]


def _runtime_openapi_paths() -> Mapping[str, Any]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_unified_operation_routes(app)
    return app.openapi()["paths"]


def _runbook_paths_ready(
    daemon_process: Mapping[str, Any],
    process_control: Mapping[str, Any],
    runbook_matrix: Mapping[str, Any],
) -> bool:
    return (
        daemon_process.get("process_control_path") == PROCESS_CONTROL_ROUTE
        and process_control.get("route", {}).get("path") == PROCESS_CONTROL_ROUTE
        and runbook_matrix.get("process_control_path") == PROCESS_CONTROL_ROUTE
        and runbook_matrix.get("dashboard_process_control_path")
        == PROCESS_CONTROL_ROUTE
        and runbook_matrix.get("control_history_path") == CONTROL_HISTORY_ROUTE
        and runbook_matrix.get("tick_plan_path") == TICK_PLAN_ROUTE
        and runbook_matrix.get("tick_once_path") == TICK_ONCE_ROUTE
    )


def _redaction_flags_safe(surface: object) -> bool:
    unsafe_flags = {
        "raw_request_payload_included",
        "raw_provider_payload_included",
        "raw_provider_error_included",
        "raw_action_comment_included",
        "raw_source_text_included",
        "provider_secrets_included",
        "database_urls_included",
        "tokens_included",
        "idempotency_keys_included",
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
            "Dispatch daemon process privacy/runbook evidence leaked "
            f"{len(leaks)} forbidden value(s)."
        )


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"runbooks={checks.get('runbook_ids_ready')} "
        f"route={checks.get('runtime_process_control_route_ready')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
