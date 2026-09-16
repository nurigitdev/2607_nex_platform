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
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan,
    register_unified_operation_routes,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV,
    DISPATCH_EXECUTION_DAEMON_ENABLED_ENV,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
    OperatorReviewLivenessAckStateStore,
    apply_operator_review_liveness_ack_state_transition,
    build_operator_review_liveness_ack_state_list_response,
)
from nex_runtime import (  # noqa: E402
    InMemoryWorkerHeartbeatStore,
    SERVICE_SPECS,
    build_service_app,
    build_worker_heartbeat,
)


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook.v1"
)
SLICE_ID = "0809"
SERVICE_ID = "nex-ag"
TRACE_ID = "a8090d5da8094b41a8090d5da8094b41"
REQUEST_ID = "ag-dispatch-daemon-liveness-ack-state-privacy-runbook-0809"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
MAX_TABLE_NAME_LENGTH = 30
OPENAPI_PATH = "contracts/openapi/nex-ag.openapi.yaml"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = (
    "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
    "privacy_runbook_evidence.py"
)
ACK_STATE_ACTION_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state"
)
ACK_STATE_LIST_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/ack-states"
)
ACK_STATE_DETAIL_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/ack-states/{ack_state_id}"
)
RECOVERY_PLAN_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan"
)

FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "authorization": "Bearer ack-state-secret-0809",
    "provider_api_key": "provider-api-key-0809",
    "raw_idempotency_key": "ack-state-idempotency-secret-0809",
    "raw_operator_comment": "raw-operator-comment-secret-0809",
    "raw_provider_payload": "raw-provider-payload-0809",
    "raw_request_payload": "raw-ack-state-request-0809",
    "storage_path": "/data/nex-platform/ag/private/ack-state-0809.json",
}

FORBIDDEN_KEYS = {
    "authorization",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_idempotency_key",
    "raw_operator_comment",
    "raw_provider_payload",
    "raw_request_payload",
    "secret",
    "storage_path",
    "storage_uri",
}

REQUIRED_DOCS = (
    "docs/slices/0801_ag_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.md",
    "docs/slices/0802_ag_dispatch_liveness_ack_state_persistence_foundation.md",
    "docs/slices/0803_ag_dispatch_liveness_ack_state_machine.md",
    "docs/slices/0804_ag_dispatch_liveness_ack_state_protected_action_api.md",
    "docs/slices/0805_ag_dispatch_liveness_ack_state_read_model_routes.md",
    "docs/slices/0806_ag_dispatch_liveness_ack_state_dashboard_issue_overlay.md",
    "docs/slices/0807_ag_dispatch_liveness_ack_state_openapi_hardening.md",
    "docs/slices/0808_ag_dispatch_liveness_ack_state_postgres_smoke.md",
)


def run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    heartbeat_store = _stale_heartbeat_store()
    ack_state_store = OperatorReviewLivenessAckStateStore()
    checked_at = datetime.now(UTC).replace(microsecond=0)
    with _temporary_environ(
        {
            DISPATCH_EXECUTION_DAEMON_ENABLED_ENV: "1",
            DISPATCH_EXECUTION_DAEMON_DRY_RUN_ENV: "1",
        }
    ):
        liveness_projection = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=_to_zulu(checked_at),
                request_trace_id=TRACE_ID,
            )
        )
        suppress_mutation = apply_operator_review_liveness_ack_state_transition(
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            liveness_status="STALE",
            action="suppress_for_ttl",
            operator_ref={
                "operator_type": "service",
                "operator_id": "privacy-runbook-0809",
                "tenant_id": "nex-platform",
            },
            reason_codes=["privacy_runbook_0809"],
            comment="S81 acknowledgement state privacy runbook evidence.",
            idempotency_key=FORBIDDEN_VALUES["raw_idempotency_key"],
            requested_ttl_seconds=300,
            observed_at=checked_at,
            metadata={
                "source": "privacy_runbook_evidence",
                "slice": SLICE_ID,
                "request_id": REQUEST_ID,
                "secret_included": False,
            },
        )
        saved_state = ack_state_store.save(suppress_mutation["state"])
        clear_mutation = apply_operator_review_liveness_ack_state_transition(
            saved_state,
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            liveness_status="STALE",
            action="clear",
            operator_ref={
                "operator_type": "service",
                "operator_id": "privacy-runbook-0809",
                "tenant_id": "nex-platform",
            },
            reason_codes=["privacy_runbook_0809_clear"],
            comment="S81 acknowledgement state privacy clear evidence.",
            idempotency_key=f"clear-{FORBIDDEN_VALUES['raw_idempotency_key']}",
            observed_at=checked_at + timedelta(seconds=1),
            metadata={
                "source": "privacy_runbook_evidence",
                "slice": SLICE_ID,
                "request_id": REQUEST_ID,
                "secret_included": False,
            },
        )
        list_response = build_operator_review_liveness_ack_state_list_response(
            [saved_state],
            checked_at=checked_at,
        )
        recovery_plan = build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
            liveness_projection,
            process_section={
                "process_control_path": (
                    "/admin/v1/operator-review/dispatch-daemon/process-controls"
                )
            },
            ack_state_store=ack_state_store,
            checked_at=_to_zulu(checked_at),
            request_trace_id=TRACE_ID,
        )

    overlay = recovery_plan.get("acknowledgement_state_overlay", {})
    route_evidence = _ack_state_route_evidence(root)
    migration_evidence = _migration_evidence(root)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in (
        root / QUALITY_GATE_PATH
    ).read_text(encoding="utf-8")
    surfaces = {
        "liveness_summary": liveness_projection.get("summary", {}),
        "suppress_mutation": _mutation_surface(suppress_mutation),
        "clear_mutation": _mutation_surface(clear_mutation),
        "list_response": _list_surface(list_response),
        "recovery_overlay": _overlay_surface(overlay),
        "migration": migration_evidence,
        "route": route_evidence,
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
        "liveness_stale_ready": liveness_projection.get("projection_status")
        == "READY"
        and liveness_projection.get("summary", {}).get("liveness_status") == "STALE",
        "suppression_guardrails_safe": _mutation_guardrails_safe(suppress_mutation),
        "clear_guardrails_safe": _mutation_guardrails_safe(clear_mutation),
        "state_redaction_ready": (
            saved_state.get("comment_hash") is not None
            and saved_state.get("idempotency_key_hash") is not None
            and saved_state.get("comment_preview")
            == "S81 acknowledgement state privacy runbook evidence."
        ),
        "list_redaction_ready": (
            list_response.get("source_table")
            == AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE
            and list_response.get("redaction", {}).get("raw_comment_included")
            is False
            and list_response.get("redaction", {}).get(
                "raw_idempotency_key_included"
            )
            is False
        ),
        "overlay_reads_persisted_state": (
            isinstance(overlay, Mapping)
            and overlay.get("overlay_status") == "STATE_PRESENT"
            and overlay.get("source_projection_suppressed") is False
            and overlay.get("issue_candidate_suppressed") is False
        ),
        "route_static_ready": route_evidence["static_ready"],
        "route_runtime_ready": route_evidence["runtime_ready"],
        "route_parameters_ready": route_evidence["parameters_ready"],
        "migration_table_name_within_limit": migration_evidence[
            "table_name_within_limit"
        ],
        "migration_redaction_columns_ready": migration_evidence[
            "redaction_columns_ready"
        ],
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
            "liveness_ack_state_privacy_runbook_failed"
        ),
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "trace_id": TRACE_ID,
        "surface_count": len(surfaces),
        "surfaces": surfaces,
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


def _mutation_surface(mutation: Mapping[str, Any]) -> dict[str, Any]:
    transition = mutation.get("transition")
    state = mutation.get("state")
    transition_map = transition if isinstance(transition, Mapping) else {}
    state_map = state if isinstance(state, Mapping) else {}
    guardrails = transition_map.get("guardrails")
    guardrails_map = guardrails if isinstance(guardrails, Mapping) else {}
    return {
        "mutation_status": mutation.get("mutation_status"),
        "ack_state_id": state_map.get("ack_state_id"),
        "action": transition_map.get("action"),
        "target_state_status": transition_map.get("target_state_status"),
        "stored_state_status": state_map.get("state_status"),
        "comment_hash_present": bool(state_map.get("comment_hash")),
        "comment_preview_present": bool(state_map.get("comment_preview")),
        "idempotency_key_hash_present": bool(state_map.get("idempotency_key_hash")),
        "guardrails": {
            "source_liveness_projection_suppressed": guardrails_map.get(
                "source_liveness_projection_suppressed"
            ),
            "raw_comment_stored": guardrails_map.get("raw_comment_stored"),
            "raw_idempotency_key_stored": guardrails_map.get(
                "raw_idempotency_key_stored"
            ),
            "process_control_invoked": guardrails_map.get("process_control_invoked"),
        },
    }


def _list_surface(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "projection_status": response.get("projection_status"),
        "state_count": response.get("state_count"),
        "source_table": response.get("source_table"),
        "redaction": dict(response.get("redaction", {})),
    }


def _overlay_surface(overlay: object) -> dict[str, Any]:
    if not isinstance(overlay, Mapping):
        return {"present": False}
    effective = overlay.get("effective_status")
    effective_map = effective if isinstance(effective, Mapping) else {}
    return {
        "present": True,
        "overlay_status": overlay.get("overlay_status"),
        "state_present": overlay.get("state_present"),
        "source_table": overlay.get("source_table"),
        "ack_state_id": overlay.get("ack_state_id"),
        "state_status": overlay.get("state_status"),
        "effective_state_status": effective_map.get("effective_state_status"),
        "source_projection_suppressed": overlay.get("source_projection_suppressed"),
        "issue_candidate_suppressed": overlay.get("issue_candidate_suppressed"),
        "redaction": dict(overlay.get("redaction", {})),
    }


def _mutation_guardrails_safe(mutation: Mapping[str, Any]) -> bool:
    transition = mutation.get("transition")
    transition_map = transition if isinstance(transition, Mapping) else {}
    guardrails = transition_map.get("guardrails")
    guardrails_map = guardrails if isinstance(guardrails, Mapping) else {}
    return (
        guardrails_map.get("source_liveness_projection_suppressed") is False
        and guardrails_map.get("raw_comment_stored") is False
        and guardrails_map.get("raw_idempotency_key_stored") is False
        and guardrails_map.get("process_control_invoked") is False
    )


def _ack_state_route_evidence(root: Path) -> dict[str, Any]:
    static_paths = _load_static_openapi_paths(root)
    runtime_paths = _runtime_openapi_paths()
    routes = {
        "action": {
            "path": ACK_STATE_ACTION_ROUTE,
            "method": "post",
            "operation_id": "postAgOperatorReviewDispatchDaemonLivenessAckState",
            "required_parameters": {"worker_id", "stale_after_seconds"},
        },
        "list": {
            "path": ACK_STATE_LIST_ROUTE,
            "method": "get",
            "operation_id": "listAgOperatorReviewDispatchDaemonLivenessAckStates",
            "required_parameters": {"service_id", "worker_id", "limit"},
        },
        "detail": {
            "path": ACK_STATE_DETAIL_ROUTE,
            "method": "get",
            "operation_id": "getAgOperatorReviewDispatchDaemonLivenessAckState",
            "required_parameters": {"ack_state_id", "observed_at"},
        },
    }
    route_results: dict[str, dict[str, Any]] = {}
    for name, spec in routes.items():
        static_operation = static_paths.get(spec["path"], {}).get(spec["method"], {})
        runtime_operation = runtime_paths.get(spec["path"], {}).get(spec["method"], {})
        static_parameter_names = _parameter_names(static_operation)
        runtime_parameter_names = _parameter_names(runtime_operation)
        route_results[name] = {
            "path": spec["path"],
            "method": spec["method"].upper(),
            "operation_id": spec["operation_id"],
            "static_operation_id": static_operation.get("operationId"),
            "runtime_operation_id": runtime_operation.get("operationId"),
            "static_ready": static_operation.get("operationId")
            == spec["operation_id"],
            "runtime_ready": runtime_operation.get("operationId")
            == spec["operation_id"],
            "parameters_ready": spec["required_parameters"].issubset(
                static_parameter_names | runtime_parameter_names
            ),
            "static_parameters": sorted(static_parameter_names),
            "runtime_parameters": sorted(runtime_parameter_names),
        }
    return {
        "routes": route_results,
        "static_ready": all(item["static_ready"] for item in route_results.values()),
        "runtime_ready": all(
            item["runtime_ready"] for item in route_results.values()
        ),
        "parameters_ready": all(
            item["parameters_ready"] for item in route_results.values()
        ),
    }


def _parameter_names(operation: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("name"))
        for item in operation.get("parameters", [])
        if isinstance(item, Mapping) and item.get("name")
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


def _migration_evidence(root: Path) -> dict[str, Any]:
    migration_path = root / "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql"
    migration = migration_path.read_text(encoding="utf-8")
    return {
        "path": str(migration_path.relative_to(root)),
        "source_table": AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
        "table_name_length": len(AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE),
        "table_name_max_length": MAX_TABLE_NAME_LENGTH,
        "table_name_within_limit": (
            len(AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE)
            <= MAX_TABLE_NAME_LENGTH
        ),
        "table_created": (
            "CREATE TABLE IF NOT EXISTS ag_op_review_ack_state" in migration
        ),
        "redaction_columns_ready": all(
            token in migration
            for token in (
                "comment_hash",
                "comment_preview",
                "idempotency_key_hash",
                "operator_ref JSONB",
                "metadata JSONB",
            )
        ),
        "indexes_ready": all(
            token in migration
            for token in (
                "uq_ag_ack_state_key",
                "idx_ag_ack_state_status_time",
                "idx_ag_ack_state_worker_time",
            )
        ),
    }


def _redaction_flags_safe(surface: object) -> bool:
    unsafe_flags = {
        "raw_request_payload_included",
        "raw_provider_payload_included",
        "raw_provider_error_included",
        "raw_action_comment_included",
        "raw_idempotency_key_included",
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
            "Dispatch daemon liveness acknowledgement state privacy/runbook "
            f"evidence leaked {len(leaks)} forbidden value(s)."
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
            "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
            f"privacy_runbook=fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = evidence.get("checks", {})
    migration = evidence.get("surfaces", {}).get("migration", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
        "privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"routes={checks.get('route_runtime_ready')} "
        f"table={migration.get('source_table')} "
        f"redaction={checks.get('state_redaction_ready')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
