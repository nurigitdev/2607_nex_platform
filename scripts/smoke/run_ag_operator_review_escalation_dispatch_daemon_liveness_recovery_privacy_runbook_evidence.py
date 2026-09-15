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


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import (  # noqa: E402
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event_details,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan,
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
    "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook.v1"
)
SLICE_ID = "0798"
SERVICE_ID = "nex-ag"
TRACE_ID = "a7980d5da7984b41a7980d5da7984b41"
REQUEST_ID = "ag-dispatch-daemon-liveness-recovery-privacy-runbook-0798"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
MAX_TABLE_NAME_LENGTH = 30
FUTURE_ACK_STATE_TABLE = "ag_op_review_ack_state"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
    "privacy_runbook_evidence.py"
)
RECOVERY_PLAN_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
)
PROCESS_CONTROL_ROUTE = "/admin/v1/operator-review/dispatch-daemon/process-controls"

FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer recovery-secret-0798",
    "provider_api_key": "provider-api-key-0798",
    "raw_operator_comment": "raw-operator-comment-0798",
    "raw_provider_payload": "raw-provider-payload-0798",
    "raw_request_payload": "raw-recovery-request-0798",
    "storage_path": "/data/nex-platform/ag/private/recovery-0798.json",
    "idempotency_key": "recovery-idempotency-key-0798",
}

FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_operator_comment",
    "raw_provider_payload",
    "raw_request_payload",
    "secret",
    "storage_path",
    "storage_uri",
}

REQUIRED_DOCS = (
    "docs/slices/0791_ag_escalation_dispatch_daemon_liveness_recovery_boundary_audit.md",
    "docs/slices/0792_ag_escalation_dispatch_daemon_liveness_recovery_plan_contract.md",
    "docs/slices/0793_ag_escalation_dispatch_daemon_liveness_recovery_plan_route.md",
    "docs/slices/0794_ag_escalation_dispatch_daemon_liveness_recovery_audit_event.md",
    "docs/slices/0795_ag_escalation_dispatch_daemon_liveness_recovery_dashboard.md",
    "docs/slices/0796_ag_escalation_dispatch_daemon_liveness_ack_suppression_policy.md",
    "docs/slices/0797_ag_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.md",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    stale_store = _heartbeat_store_with_status("STALE")
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
        dispatches = dashboard["operator_review_escalation_dispatches"]
        process_section = dispatches.get("daemon_process")
        stale_recovery = (
            build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
                stale_liveness,
                process_section=process_section,
                request_trace_id=TRACE_ID,
            )
        )
        missing_recovery = (
            build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
                missing_liveness,
                process_section=process_section,
                request_trace_id=TRACE_ID,
            )
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

    dashboard_recovery = dispatches["daemon_recovery"]
    audit_details = (
        build_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event_details(
            http_method="GET",
            route_path=RECOVERY_PLAN_ROUTE,
            recovery_plan=stale_recovery,
        )
    )
    persistence_decision = _ack_suppression_persistence_decision(
        stale_recovery,
        missing_recovery,
    )
    runbook_matrix = _runbook_matrix(
        stale_recovery=stale_recovery,
        missing_recovery=missing_recovery,
        stale_issue=stale_issue,
        missing_issue=missing_issue,
    )
    route_evidence = _recovery_route_evidence()
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    surfaces = {
        "stale_recovery": stale_recovery,
        "missing_recovery": missing_recovery,
        "dashboard_recovery": dashboard_recovery,
        "audit_details": audit_details,
        "stale_issue_candidate": _issue_candidate_summary(stale_issue),
        "missing_issue_candidate": _issue_candidate_summary(missing_issue),
        "runbook_matrix": runbook_matrix,
        "persistence_decision": persistence_decision,
    }
    serialized_surfaces = json.dumps(
        surfaces,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    forbidden_key_paths = _forbidden_key_paths(surfaces, FORBIDDEN_KEYS)
    forbidden_value_labels = _forbidden_value_labels(serialized_surfaces)
    checks = {
        "stale_recovery_actionable": stale_recovery.get("projection_status")
        == "ACTION_RECOMMENDED"
        and stale_recovery.get("summary", {}).get("liveness_status") == "STALE",
        "missing_recovery_actionable": missing_recovery.get("projection_status")
        == "ACTION_RECOMMENDED"
        and missing_recovery.get("summary", {}).get("liveness_status") == "MISSING",
        "dashboard_recovery_actionable": dashboard_recovery.get(
            "recovery_plan_status"
        )
        == "ACTION_RECOMMENDED",
        "audit_details_safe": audit_details.get("recovery_status") == "PLANNED"
        and audit_details.get("raw_request_payload_included") is False
        and audit_details.get("raw_provider_payload_included") is False
        and audit_details.get("sensitive_values_included") is False,
        "runbook_ids_ready": _expected_runbooks_ready(runbook_matrix),
        "operator_actions_ready": _expected_operator_actions_ready(runbook_matrix),
        "ack_policy_actions_ready": {
            "acknowledge_once",
            "suppress_for_ttl",
        }.issubset(set(runbook_matrix["ack_supported_actions"])),
        "issue_candidate_ack_policy_ready": (
            _issue_ack_policy(stale_issue).get("policy_status") == "ACTIONABLE"
            and _issue_ack_policy(missing_issue).get("policy_status") == "ACTIONABLE"
        ),
        "persistence_deferred": (
            persistence_decision["current_state_persisted"] is False
            and persistence_decision["new_table_in_slice_0798"] is False
        ),
        "future_table_name_within_limit": persistence_decision[
            "future_table_name_within_limit"
        ]
        is True,
        "runtime_recovery_route_ready": route_evidence["runtime_ready"],
        "recovery_route_parameters_ready": route_evidence["parameters_ready"],
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "redaction_flags_safe": _redaction_flags_safe(surfaces),
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else (
            "ag_operator_review_escalation_dispatch_daemon_"
            "liveness_recovery_privacy_runbook_failed"
        ),
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": {
            "stale_recovery": stale_recovery.get("summary", {}),
            "missing_recovery": missing_recovery.get("summary", {}),
            "dashboard_recovery": dashboard_recovery.get("summary", {}),
            "audit_details": {
                "recovery_status": audit_details.get("recovery_status"),
                "projection_status": audit_details.get("projection_status"),
                "source_event_table": audit_details.get("source_event_table"),
            },
            "stale_issue_candidate": _issue_candidate_summary(stale_issue),
            "missing_issue_candidate": _issue_candidate_summary(missing_issue),
            "runbook_matrix": runbook_matrix,
            "persistence_decision": persistence_decision,
        },
        "route": route_evidence,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _heartbeat_store_with_status(liveness_status: str) -> InMemoryWorkerHeartbeatStore:
    store = InMemoryWorkerHeartbeatStore()
    offset_seconds = (
        STALE_AFTER_SECONDS + 30 if liveness_status == "STALE" else 5
    )
    last_seen_at = datetime.now(UTC) - timedelta(seconds=offset_seconds)
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
                "source": "recovery_privacy_runbook_evidence",
                "slice": SLICE_ID,
                "request_id": REQUEST_ID,
                "secret_included": False,
            },
        )
    )
    return store


def _ack_suppression_persistence_decision(
    stale_recovery: Mapping[str, Any],
    missing_recovery: Mapping[str, Any],
) -> dict[str, Any]:
    policy_statuses = sorted(
        {
            str(policy.get("policy_status"))
            for policy in (
                stale_recovery.get("acknowledgement_suppression_policy", {}),
                missing_recovery.get("acknowledgement_suppression_policy", {}),
            )
            if isinstance(policy, Mapping) and policy.get("policy_status")
        }
    )
    return {
        "decision": "DEFER_PERSISTENCE_UNTIL_OPERATOR_ACTION_STATE_SLICE",
        "current_state_persisted": False,
        "new_table_in_slice_0798": False,
        "future_table_candidate": FUTURE_ACK_STATE_TABLE,
        "future_table_name_length": len(FUTURE_ACK_STATE_TABLE),
        "future_table_name_max_length": MAX_TABLE_NAME_LENGTH,
        "future_table_name_within_limit": (
            len(FUTURE_ACK_STATE_TABLE) <= MAX_TABLE_NAME_LENGTH
        ),
        "future_owner_service": SERVICE_ID,
        "future_primary_key": [
            "service_id",
            "worker_id",
            "liveness_status",
            "acknowledgement_key",
        ],
        "future_index_candidates": [
            "service_id",
            "worker_id",
            "expires_at",
            "operator_subject_id",
        ],
        "required_before_persistence": [
            "operator_subject_resolution",
            "reason_code_normalization",
            "ttl_expiry_semantics",
            "audit_event_correlation",
        ],
        "policy_statuses": policy_statuses,
    }


def _runbook_matrix(
    *,
    stale_recovery: Mapping[str, Any],
    missing_recovery: Mapping[str, Any],
    stale_issue: Mapping[str, Any] | None,
    missing_issue: Mapping[str, Any] | None,
) -> dict[str, Any]:
    recovery_actions = [
        action
        for recovery in (stale_recovery, missing_recovery)
        for action in recovery.get("recommended_actions", [])
        if isinstance(action, Mapping)
    ]
    issue_signals = [
        signal
        for signal in (_issue_signal(stale_issue), _issue_signal(missing_issue))
        if signal
    ]
    policies = [
        policy
        for policy in (
            stale_recovery.get("acknowledgement_suppression_policy", {}),
            missing_recovery.get("acknowledgement_suppression_policy", {}),
            _issue_ack_policy(stale_issue),
            _issue_ack_policy(missing_issue),
        )
        if isinstance(policy, Mapping)
    ]
    return {
        "runbook_ids": sorted(
            {
                str(runbook_id)
                for action in recovery_actions
                for runbook_id in action.get("runbook_ids", [])
            }
            | {
                str(runbook_id)
                for signal in issue_signals
                for runbook_id in signal.get("runbook_ids", [])
            }
        ),
        "recommended_operator_actions": sorted(
            {
                str(action.get("action_id"))
                for action in recovery_actions
                if action.get("action_id")
            }
            | {
                str(operator_action)
                for signal in issue_signals
                for operator_action in signal.get(
                    "recommended_operator_actions",
                    [],
                )
            }
        ),
        "ack_supported_actions": sorted(
            {
                str(action)
                for policy in policies
                for action in policy.get("supported_actions", [])
            }
        ),
        "recovery_plan_path": RECOVERY_PLAN_ROUTE,
        "process_control_path": PROCESS_CONTROL_ROUTE,
        "manual_process_mutation_required": False,
        "redaction": {
            "raw_provider_payload_included": False,
            "raw_request_payload_included": False,
            "raw_operator_comment_included": False,
            "provider_secrets_included": False,
            "database_urls_included": False,
            "tokens_included": False,
            "idempotency_keys_included": False,
        },
    }


def _expected_runbooks_ready(runbook_matrix: Mapping[str, Any]) -> bool:
    return {
        "ag.operator_review_dispatch_daemon_liveness.stale_heartbeat.v1",
        "ag.operator_review_dispatch_daemon_liveness.missing_heartbeat.v1",
    }.issubset(set(runbook_matrix.get("runbook_ids", [])))


def _expected_operator_actions_ready(runbook_matrix: Mapping[str, Any]) -> bool:
    return {
        "inspect_stale_dispatch_daemon_heartbeat",
        "start_or_inspect_dispatch_daemon_process",
    }.issubset(set(runbook_matrix.get("recommended_operator_actions", [])))


def _recovery_route_evidence() -> dict[str, Any]:
    runtime_paths = _runtime_openapi_paths()
    operation = runtime_paths.get(RECOVERY_PLAN_ROUTE, {}).get("get", {})
    parameter_names = {
        item.get("name")
        for item in operation.get("parameters", [])
        if isinstance(item, Mapping)
    }
    expected_operation_id = "getAgOperatorReviewDispatchDaemonLivenessRecoveryPlan"
    return {
        "path": RECOVERY_PLAN_ROUTE,
        "method": "GET",
        "operation_id": expected_operation_id,
        "runtime_operation_id": operation.get("operationId"),
        "runtime_ready": operation.get("operationId") == expected_operation_id,
        "parameters_ready": {"worker_id", "stale_after_seconds"}.issubset(
            parameter_names
        ),
        "parameters": sorted(name for name in parameter_names if name),
        "static_openapi_hardening_deferred_to_slice_0799": True,
    }


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


def _issue_ack_policy(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    signal = _issue_signal(candidate)
    policy = signal.get("acknowledgement_suppression_policy")
    return dict(policy) if isinstance(policy, Mapping) else {}


def _issue_candidate_summary(
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    signal = _issue_signal(candidate)
    policy = _issue_ack_policy(candidate)
    return {
        "rule_id": candidate.get("rule_id"),
        "severity": candidate.get("severity"),
        "signal_status": signal.get("status"),
        "runbook_ids": sorted(signal.get("runbook_ids", [])),
        "recommended_operator_actions": sorted(
            signal.get("recommended_operator_actions", [])
        ),
        "ack_policy_status": policy.get("policy_status"),
        "ack_policy_new_tables_required": policy.get("new_tables_required"),
    }


def _redaction_flags_safe(surface: object) -> bool:
    unsafe_flags = {
        "raw_request_payload_included",
        "raw_provider_payload_included",
        "raw_provider_error_included",
        "raw_action_comment_included",
        "raw_operator_comment_included",
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
            "Dispatch daemon liveness recovery privacy/runbook evidence leaked "
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
            "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
            f"privacy_runbook=fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    persistence = evidence.get("surfaces", {}).get("persistence_decision", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_recovery_"
        "privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"runbooks={checks.get('runbook_ids_ready')} "
        f"ack_state={persistence.get('future_table_candidate')} "
        f"persisted_now={persistence.get('current_state_persisted')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_privacy_runbook_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
