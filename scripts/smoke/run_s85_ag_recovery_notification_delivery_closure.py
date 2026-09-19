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
from run_ag_recovery_notification_delivery_privacy_runbook_evidence import (  # noqa: E402
    run_ag_recovery_notification_delivery_privacy_runbook_evidence as run_privacy_runbook,
)
from run_ag_recovery_notification_delivery_privacy_runbook_evidence import (  # noqa: E402
    summary_line as privacy_summary_line,
)


SCHEMA_VERSION = "s85_ag_recovery_notification_delivery_closure.v1"
SLICE_RANGE = "0841-0850"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = (
    "docs/slices/0848_ag_recovery_notification_delivery_postgres_smoke.md"
)
PRIVACY_RUNBOOK_DOC = (
    "docs/slices/0849_ag_recovery_notification_delivery_privacy_runbook.md"
)
DELIVERY_ROUTE = (
    "/admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-deliveries"
)
SOURCE_TABLE = "ag_op_esc_dispatches"
OBSERVED_AT = "2026-09-19T07:00:00Z"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/recovery_notification_delivery.py",
    "services/nex-ag/nex_ag/recovery_notification_operations.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/recovery_notification_delivery.v1.schema.json",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_recovery_notification_delivery.mock_success.json",
    "contracts/tests/negative/operations/ag_recovery_notification_delivery.raw_payload_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_recovery_notification_delivery_boundary_audit.py",
    "scripts/smoke/run_ag_recovery_notification_delivery_postgres_smoke.py",
    "scripts/smoke/run_ag_recovery_notification_delivery_privacy_runbook_evidence.py",
    "scripts/smoke/run_s85_ag_recovery_notification_delivery_closure.py",
    "tests/test_ag_recovery_notification_delivery_boundary_audit.py",
    "tests/test_nex_ag_recovery_notification_delivery_admission.py",
    "tests/test_nex_ag_recovery_notification_dispatch_handoff.py",
    "tests/test_nex_ag_recovery_notification_delivery_api.py",
    "tests/test_nex_ag_recovery_notification_operations.py",
    "tests/test_nex_ag_recovery_notification_contracts.py",
    "tests/test_nex_ag_recovery_notification_delivery_execution.py",
    "tests/test_ag_recovery_notification_delivery_postgres_smoke.py",
    "tests/test_ag_recovery_notification_delivery_privacy_runbook_evidence.py",
    "tests/test_s85_ag_recovery_notification_delivery_closure.py",
    "docs/README.md",
    *(
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
            ("0849", "ag_recovery_notification_delivery_privacy_runbook"),
            ("0850", "s85_ag_recovery_notification_delivery_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "approved_option_a",
        "docs/slices/0841_ag_recovery_notification_delivery_boundary_audit.md",
        "reuse_existing_dispatch_outbox_with_explicit_case_escalation_context",
    ),
    (
        "quality_gate_boundary",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_delivery_boundary_audit.py",
    ),
    (
        "quality_gate_postgres",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_delivery_postgres_smoke.py",
    ),
    (
        "quality_gate_privacy",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_delivery_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_closure",
        QUALITY_GATE_PATH,
        "run_s85_ag_recovery_notification_delivery_closure.py",
    ),
    (
        "explicit_context_admission",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "build_recovery_notification_delivery_admission",
    ),
    (
        "existing_worker_reuse",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "run_dispatch_execution_worker_once",
    ),
    (
        "private_signature_redaction",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "_without_private_request_signatures",
    ),
    (
        "protected_delivery_post",
        "services/nex-ag/nex_ag/operations.py",
        "postAgOperatorReviewDispatchDaemonRecoveryNotificationDelivery",
    ),
    (
        "protected_delivery_get",
        "services/nex-ag/nex_ag/operations.py",
        "listAgOperatorReviewDispatchDaemonRecoveryNotificationDeliveries",
    ),
    (
        "openapi_delivery_post",
        "contracts/openapi/nex-ag.openapi.yaml",
        "postAgOperatorReviewDispatchDaemonRecoveryNotificationDelivery",
    ),
    (
        "delivery_contract",
        "contracts/schemas/service/nex_ag/recovery_notification_delivery.v1.schema.json",
        "ag_recovery_notification_delivery_operations_projection.v1",
    ),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "ag_recovery_notification_delivery_postgres_smoke=pass",
    ),
    (
        "postgres_cleanup",
        POSTGRES_SMOKE_DOC,
        "cleaned=True",
    ),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_recovery_notification_delivery_privacy_runbook=pass",
    ),
    (
        "docs_index_0850",
        "docs/README.md",
        "0850_s85_ag_recovery_notification_delivery_closure.md",
    ),
)


def run_s85_ag_recovery_notification_delivery_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    postgres = _postgres_smoke_doc_evidence(root)
    privacy = _privacy_evidence(root)
    runtime = _runtime_evidence()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "explicit_context_verified": runtime["admission_status"] == "ADMITTED",
        "existing_outbox_reused": runtime["source_table"] == SOURCE_TABLE,
        "created_and_replayed": (
            runtime["created_idempotency_status"] == "NEW"
            and runtime["replayed_idempotency_status"] == "REPLAYED"
        ),
        "private_signature_preserved_only_internally": (
            runtime["internal_request_signature_persisted"] is True
            and runtime["public_request_signature_exposed"] is False
        ),
        "targeted_mock_execution_completed": (
            runtime["execution_status"] == "COMPLETED"
            and runtime["external_network_allowed"] is False
        ),
        "completed_delivery_is_noop": runtime["repeat_execution_status"]
        == "NOOP",
        "operations_projection_ready": (
            runtime["projection_status"] == "READY"
            and runtime["delivery_status"] == "ACTIVE"
            and runtime["succeeded_count"] == 1
        ),
        "postgres_smoke_used_test_db": postgres["uses_test_db"],
        "postgres_smoke_passed": postgres["summary_pass"],
        "postgres_cleanup_verified": postgres["cleanup_verified"],
        "privacy_runbook_passed": privacy["status"] == "PASS",
        "privacy_checks_passed": all(privacy["checks"].values()),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s85_ag_recovery_notification_delivery_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": (
            "explicit_case_escalation_existing_outbox_mock_delivery"
        ),
        "source_tables": [SOURCE_TABLE],
        "new_tables": [],
        "new_indexes": [],
        "protected_routes": [
            f"GET {DELIVERY_ROUTE}",
            f"POST {DELIVERY_ROUTE}",
        ],
        "mock_delivery_implemented": True,
        "external_live_delivery_implemented": False,
        "closure_surfaces": [
            "boundary_decision_option_a",
            "explicit_context_admission",
            "existing_dispatch_handoff",
            "protected_idempotent_api",
            "operations_read_model",
            "openapi_json_schema_contracts",
            "targeted_bounded_mock_execution",
            "test_db_postgres_smoke",
            "privacy_operator_runbook",
        ],
        "runtime": runtime,
        "postgres_smoke": postgres,
        "privacy_runbook": privacy,
        "required_files": required_files,
        "token_checks": token_checks,
        "checks": checks,
        "summary": {
            "required_file_count": len(required_files),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "token_check_count": len(token_checks),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
    }


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        path = root / relative_path
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in content,
            }
        )
    return results


def _postgres_smoke_doc_evidence(root: Path) -> dict[str, Any]:
    path = root / POSTGRES_SMOKE_DOC
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "doc": POSTGRES_SMOKE_DOC,
        "doc_present": path.is_file(),
        "uses_test_db": "database=nex_ag_test" in content,
        "summary_pass": (
            "ag_recovery_notification_delivery_postgres_smoke=pass" in content
        ),
        "migration_verified": "runs current `nex-ag` migrations" in content,
        "dispatch_succeeded": "succeeded=1" in content,
        "metadata_verified": "metadata=1" in content,
        "cleanup_verified": "cleaned=True" in content,
        "remaining_rows_zero": "dispatch rows is `0`" in content,
    }


def _privacy_evidence(root: Path) -> dict[str, Any]:
    try:
        result = run_privacy_runbook(root)
    except Exception as exc:  # pragma: no cover - exercised by direct tests
        return {
            "status": "FAIL",
            "failure_code": "privacy_runbook_execution_failed",
            "error_type": type(exc).__name__,
            "summary_line": (
                "ag_recovery_notification_delivery_privacy_runbook=fail "
                "failure=privacy_runbook_execution_failed"
            ),
            "checks": {
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "internal_idempotency_signature_preserved": False,
                "runbook_complete": False,
            },
        }
    selected_checks = {
        key: bool(result.get("checks", {}).get(key))
        for key in (
            "forbidden_values_absent",
            "forbidden_keys_absent",
            "internal_idempotency_signature_preserved",
            "runbook_complete",
        )
    }
    return {
        "status": result.get("status"),
        "failure_code": result.get("failure_code"),
        "summary_line": privacy_summary_line(result),
        "surface_count": result.get("surface_count", 0),
        "checks": selected_checks,
    }


def _runtime_evidence() -> dict[str, Any]:
    case = _case_record()
    escalation = _escalation_record()
    plan = _notification_plan()
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
        request_id="request-0850",
        idempotency_key="idem-0850",
        created_at=OBSERVED_AT,
    )
    store = OperatorReviewEscalationDispatchStore()
    created = persist_recovery_notification_dispatch_handoff(handoff, store)
    replayed = persist_recovery_notification_dispatch_handoff(handoff, store)
    dispatch_id = str(created["dispatch_record"]["dispatch_id"])
    persisted = store.get(dispatch_id) or {}
    internal_delivery = _mapping(_mapping(persisted.get("metadata")).get(
        "recovery_notification_delivery"
    ))
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=OperatorReviewEscalationStore(),
        dispatch_store=store,
    )
    execution = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0850-execute",
        confirm_run=True,
        executed_at=OBSERVED_AT,
    )
    repeated = run_recovery_notification_delivery_mock_once(
        service,
        dispatch_id=dispatch_id,
        request_id="request-0850-noop",
        confirm_run=True,
        executed_at="2026-09-19T07:01:00Z",
    )
    projection = build_recovery_notification_delivery_operations_projection(
        store.list_dispatches()
    )
    return {
        "admission_status": admission["admission_status"],
        "handoff_status": handoff["handoff_status"],
        "source_table": SOURCE_TABLE,
        "created_idempotency_status": created["idempotency_status"],
        "replayed_idempotency_status": replayed["idempotency_status"],
        "internal_request_signature_persisted": (
            "request_signature" in internal_delivery
        ),
        "public_request_signature_exposed": (
            "request_signature" in json.dumps(created)
            or "request_signature" in json.dumps(replayed)
        ),
        "execution_status": execution["execution_status"],
        "external_network_allowed": execution["guardrails"][
            "external_network_allowed"
        ],
        "repeat_execution_status": repeated["execution_status"],
        "projection_status": projection["projection_status"],
        "delivery_status": projection["delivery_status"],
        "succeeded_count": projection["summary"]["succeeded"],
        "new_tables_required": projection["new_tables_required"],
    }


def _notification_plan() -> dict[str, Any]:
    return build_recovery_notification_plan(
        {
            "projection_schema_version": "recovery-plan.v1",
            "summary": {"liveness_status": "STALE"},
            "daemon_identity": {
                "service_id": "nex-ag",
                "worker_id": "ag-dispatch-execution-daemon",
            },
            "recommended_actions": [{"severity": "ERROR"}],
        },
        environ={"NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED": "1"},
        evaluated_at=OBSERVED_AT,
    )


def _case_record() -> dict[str, Any]:
    return {
        "case_id": "case-0850",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
    }


def _escalation_record() -> dict[str, Any]:
    return {
        "escalation_id": "escalation-0850",
        "candidate_id": "candidate-0850",
        "case_id": "case-0850",
        "target_service": "nex-ag",
        "target_kind": "dispatch_daemon",
        "target_id": "ag-dispatch-execution-daemon",
        "escalation_status": "ACTIVE",
        "escalation_level": "ATTENTION",
        "sla_state": "WARNING",
        "reason_codes": ["daemon_stale"],
        "runbook_ids": ["ag.dispatch_daemon.recover.v1"],
        "recommended_actions": ["inspect_dispatch_daemon"],
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = _mapping(evidence.get("summary"))
        return (
            "s85_ag_recovery_notification_delivery_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    checks = _mapping(evidence.get("checks"))
    runtime = _mapping(evidence.get("runtime"))
    return (
        "s85_ag_recovery_notification_delivery_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"postgres={checks.get('postgres_smoke_passed')} "
        f"privacy={checks.get('privacy_runbook_passed')} "
        f"mock_delivery={runtime.get('execution_status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s85_ag_recovery_notification_delivery_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
