#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import (  # noqa: E402
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
    register_unified_operation_routes,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_runtime import (  # noqa: E402
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_service_app,
    build_worker_heartbeat,
)


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook.v1"
)
SLICE_ID = "0789"
SERVICE_ID = "nex-ag"
TRACE_ID = "a7890d5da7894b41a7890d5da7894b41"
REQUEST_ID = "ag-dispatch-daemon-liveness-privacy-runbook-0789"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_"
    "runbook_evidence.py"
)
LIVENESS_ROUTE = "/admin/v1/operator-review/dispatch-daemon/liveness"
PROCESS_CONTROL_ROUTE = "/admin/v1/operator-review/dispatch-daemon/process-controls"

FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer liveness-secret-0789",
    "provider_api_key": "provider-api-key-0789",
    "raw_provider_payload": "raw-provider-payload-0789",
    "raw_request_payload": "raw-liveness-request-0789",
    "storage_path": "/data/nex-platform/ag/private/liveness-0789.json",
    "idempotency_key": "liveness-idempotency-key-0789",
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
    "ag.operator_review_dispatch_daemon_liveness.stale_heartbeat.v1",
    "ag.operator_review_dispatch_daemon_liveness.missing_heartbeat.v1",
}
EXPECTED_OPERATOR_ACTIONS = {
    "inspect_stale_dispatch_daemon_heartbeat",
    "start_or_inspect_dispatch_daemon_process",
}

REQUIRED_DOCS = (
    "docs/slices/0781_ag_escalation_dispatch_daemon_liveness_boundary_audit.md",
    "docs/slices/0782_ag_escalation_dispatch_daemon_heartbeat_contract.md",
    "docs/slices/0783_ag_escalation_dispatch_daemon_heartbeat_emission.md",
    "docs/slices/0784_ag_escalation_dispatch_daemon_liveness_read_model.md",
    "docs/slices/0785_ag_escalation_dispatch_daemon_liveness_route.md",
    "docs/slices/0786_ag_escalation_dispatch_daemon_liveness_dashboard.md",
    "docs/slices/0787_ag_escalation_dispatch_daemon_liveness_issue_candidate.md",
    "docs/slices/0788_ag_escalation_dispatch_daemon_liveness_postgres_smoke.md",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    stale_store = _stale_heartbeat_store()
    missing_store = InMemoryWorkerHeartbeatStore()
    with _temporary_environ(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
        }
    ):
        stale_liveness = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: stale_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                request_trace_id=TRACE_ID,
            )
        )
        missing_liveness = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: missing_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                request_trace_id=TRACE_ID,
            )
        )
        dashboard = build_operations_dashboard_snapshot_projection(
            worker_heartbeat_stores={SERVICE_ID: stale_store},
            service_id=SERVICE_ID,
            recent_limit=5,
            request_trace_id=TRACE_ID,
        )
        stale_issue = _liveness_issue_candidate(
            build_operations_issue_candidate_projection(
                worker_heartbeat_stores={SERVICE_ID: stale_store},
                service_id=SERVICE_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                request_trace_id=TRACE_ID,
            )
        )
        missing_issue = _liveness_issue_candidate(
            build_operations_issue_candidate_projection(
                worker_heartbeat_stores={SERVICE_ID: missing_store},
                service_id=SERVICE_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                request_trace_id=TRACE_ID,
            )
        )

    dashboard_liveness = dashboard["operator_review_escalation_dispatches"][
        "daemon_liveness"
    ]
    runbook_matrix = _runbook_matrix(stale_issue, missing_issue)
    surfaces = {
        "stale_liveness": stale_liveness,
        "missing_liveness": missing_liveness,
        "dashboard_liveness": dashboard_liveness,
        "stale_issue_candidate": stale_issue,
        "missing_issue_candidate": missing_issue,
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
    route_evidence = _liveness_route_evidence(root)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    checks = {
        "stale_liveness_ready": stale_liveness.get("projection_status") == "READY"
        and stale_liveness.get("summary", {}).get("liveness_status") == "STALE",
        "missing_liveness_ready": missing_liveness.get("projection_status")
        == "READY"
        and missing_liveness.get("summary", {}).get("liveness_status") == "MISSING",
        "dashboard_liveness_ready": dashboard_liveness.get("projection_status")
        == "READY"
        and dashboard_liveness.get("summary", {}).get("liveness_status") == "STALE",
        "stale_issue_candidate_ready": _issue_signal_status(stale_issue) == "STALE",
        "missing_issue_candidate_ready": _issue_signal_status(missing_issue)
        == "MISSING",
        "runbook_ids_ready": EXPECTED_RUNBOOK_IDS.issubset(
            set(runbook_matrix["runbook_ids"])
        ),
        "operator_actions_ready": EXPECTED_OPERATOR_ACTIONS.issubset(
            set(runbook_matrix["recommended_operator_actions"])
        ),
        "runbook_paths_ready": _runbook_paths_ready(runbook_matrix),
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "redaction_flags_safe": _redaction_flags_safe(surfaces),
        "static_liveness_route_ready": route_evidence["static_ready"],
        "runtime_liveness_route_ready": route_evidence["runtime_ready"],
        "liveness_route_parameters_ready": route_evidence["parameters_ready"],
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": {
            "stale_liveness": stale_liveness.get("summary", {}),
            "missing_liveness": missing_liveness.get("summary", {}),
            "dashboard_liveness": dashboard_liveness.get("summary", {}),
            "stale_issue_candidate": _issue_candidate_summary(stale_issue),
            "missing_issue_candidate": _issue_candidate_summary(missing_issue),
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


def _stale_heartbeat_store() -> InMemoryWorkerHeartbeatStore:
    store = InMemoryWorkerHeartbeatStore()
    last_seen_at = datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS + 30)
    started_at = last_seen_at - timedelta(seconds=15)
    store.upsert_heartbeat(
        build_worker_heartbeat(
            service_id=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
            worker_id=WORKER_ID,
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            status="IDLE",
            trace_id=TRACE_ID,
            started_at=_to_zulu(started_at),
            last_seen_at=_to_zulu(last_seen_at),
            metadata={
                "source": "privacy_runbook_evidence",
                "slice": SLICE_ID,
                "request_id": REQUEST_ID,
                "secret_included": False,
            },
        )
    )
    return store


def _runbook_matrix(
    stale_issue: Mapping[str, Any] | None,
    missing_issue: Mapping[str, Any] | None,
) -> dict[str, Any]:
    signals = [
        signal
        for signal in (
            _issue_signal(stale_issue),
            _issue_signal(missing_issue),
        )
        if signal
    ]
    return {
        "runbook_ids": sorted(
            {
                runbook_id
                for signal in signals
                for runbook_id in signal.get("runbook_ids", [])
            }
        ),
        "recommended_operator_actions": sorted(
            {
                action
                for signal in signals
                for action in signal.get("recommended_operator_actions", [])
            }
        ),
        "liveness_path": LIVENESS_ROUTE,
        "process_control_path": PROCESS_CONTROL_ROUTE,
        "diagnostic_sources": [
            "service_worker_heartbeats",
            "operations_dashboard.daemon_liveness",
            "operations_issue_candidates",
        ],
        "manual_process_mutation_required": False,
        "redaction": {
            "raw_provider_payload_included": False,
            "raw_request_payload_included": False,
            "provider_secrets_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
        },
    }


def _liveness_route_evidence(root: Path) -> dict[str, Any]:
    static_paths = _load_static_openapi_paths(root)
    runtime_paths = _runtime_openapi_paths()
    static_operation = static_paths.get(LIVENESS_ROUTE, {}).get("get", {})
    runtime_operation = runtime_paths.get(LIVENESS_ROUTE, {}).get("get", {})
    expected_operation_id = "getAgOperatorReviewDispatchDaemonLiveness"
    parameter_names = {
        item.get("name")
        for item in static_operation.get("parameters", [])
        if isinstance(item, Mapping)
    }
    return {
        "path": LIVENESS_ROUTE,
        "method": "GET",
        "operation_id": expected_operation_id,
        "static_operation_id": static_operation.get("operationId"),
        "runtime_operation_id": runtime_operation.get("operationId"),
        "static_ready": static_operation.get("operationId") == expected_operation_id,
        "runtime_ready": runtime_operation.get("operationId") == expected_operation_id,
        "parameters_ready": {"worker_id", "stale_after_seconds"}.issubset(
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
        worker_heartbeat_stores={SERVICE_ID: InMemoryWorkerHeartbeatStore()},
    )
    return app.openapi()["paths"]


def _liveness_issue_candidate(
    issue_projection: Mapping[str, Any],
) -> dict[str, Any] | None:
    candidates = issue_projection.get("issue_candidates", [])
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if (
            isinstance(candidate, Mapping)
            and candidate.get("rule_id")
            == "operator_review_dispatch_daemon_liveness_attention_required.v1"
        ):
            return dict(candidate)
    return None


def _issue_signal(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    signal = candidate.get("signal", {}) if isinstance(candidate, Mapping) else {}
    return dict(signal) if isinstance(signal, Mapping) else {}


def _issue_signal_status(candidate: Mapping[str, Any] | None) -> str | None:
    return _issue_signal(candidate).get("status")


def _issue_candidate_summary(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    signal = _issue_signal(candidate)
    return {
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "signal_status": signal.get("status"),
        "runbook_ids": sorted(signal.get("runbook_ids", [])),
        "recommended_operator_actions": sorted(
            signal.get("recommended_operator_actions", [])
        ),
    }


def _runbook_paths_ready(runbook_matrix: Mapping[str, Any]) -> bool:
    return (
        runbook_matrix.get("liveness_path") == LIVENESS_ROUTE
        and runbook_matrix.get("process_control_path") == PROCESS_CONTROL_ROUTE
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
            "Dispatch daemon liveness privacy/runbook evidence leaked "
            f"{len(leaks)} forbidden value(s)."
        )


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


@contextmanager
def _temporary_environ(updates: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook="
            f"fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"runbooks={checks.get('runbook_ids_ready')} "
        f"route={checks.get('runtime_liveness_route_ready')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
