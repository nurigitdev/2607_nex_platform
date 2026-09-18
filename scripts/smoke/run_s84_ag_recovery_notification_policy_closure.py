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
    RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV,
    build_recovery_notification_plan,
    build_recovery_notification_policy,
)
from run_ag_recovery_notification_privacy_runbook_evidence import (  # noqa: E402
    run_ag_recovery_notification_privacy_runbook_evidence as run_privacy_runbook,
)
from run_ag_recovery_notification_privacy_runbook_evidence import (  # noqa: E402
    summary_line as privacy_summary_line,
)


SCHEMA_VERSION = "s84_ag_recovery_notification_policy_closure.v1"
SLICE_RANGE = "0831-0840"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = "docs/slices/0838_ag_recovery_notification_postgres_smoke.md"
PRIVACY_RUNBOOK_DOC = "docs/slices/0839_ag_recovery_notification_privacy_runbook.md"
PREVIEW_ROUTE = (
    "GET /admin/v1/operator-review/dispatch-daemon/liveness/"
    "recovery-notification-preview"
)
SOURCE_TABLES = ("ag_op_review_ack_state", "service_operational_events")
OBSERVED_AT = "2026-09-18T10:00:00Z"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/recovery_notification_policy.py",
    "services/nex-ag/nex_ag/recovery_notification_operations.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_recovery_notification_policy_boundary_audit.py",
    "scripts/smoke/run_ag_recovery_notification_postgres_smoke.py",
    "scripts/smoke/run_ag_recovery_notification_privacy_runbook_evidence.py",
    "scripts/smoke/run_s84_ag_recovery_notification_policy_closure.py",
    "tests/test_ag_recovery_notification_policy_boundary_audit.py",
    "tests/test_nex_ag_recovery_notification_policy.py",
    "tests/test_nex_ag_recovery_notification_operations.py",
    "tests/test_nex_ag_recovery_notification_preview_api.py",
    "tests/test_nex_ag_recovery_notification_contracts.py",
    "tests/test_ag_recovery_notification_postgres_smoke.py",
    "tests/test_ag_recovery_notification_privacy_runbook_evidence.py",
    "tests/test_s84_ag_recovery_notification_policy_closure.py",
    "docs/README.md",
    *(
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
            ("0839", "ag_recovery_notification_privacy_runbook"),
            ("0840", "s84_ag_recovery_notification_policy_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_policy_boundary_audit.py",
    ),
    (
        "quality_gate_postgres",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_postgres_smoke.py",
    ),
    (
        "quality_gate_privacy",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_closure",
        QUALITY_GATE_PATH,
        "run_s84_ag_recovery_notification_policy_closure.py",
    ),
    (
        "delivery_disabled_default",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
        '"delivery_disabled_by_default": True',
    ),
    (
        "provider_invocation_forbidden",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
        '"external_provider_invocation_allowed": False',
    ),
    (
        "dispatch_persistence_forbidden",
        "services/nex-ag/nex_ag/recovery_notification_policy.py",
        '"dispatch_persistence_allowed": False',
    ),
    (
        "protected_preview_route",
        "services/nex-ag/nex_ag/operations.py",
        "getAgOperatorReviewDispatchDaemonRecoveryNotificationPreview",
    ),
    (
        "static_openapi_route",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgOperatorReviewDispatchDaemonRecoveryNotificationPreview",
    ),
    (
        "operations_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_recovery_notification",
    ),
    (
        "operations_fixture",
        "contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json",
        '"recovery_notification"',
    ),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "ag_recovery_notification_postgres_smoke=pass",
    ),
    (
        "postgres_non_skip",
        POSTGRES_SMOKE_DOC,
        "The result was not skipped",
    ),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_recovery_notification_privacy_runbook=pass",
    ),
    (
        "docs_index_0840",
        "docs/README.md",
        "0840_s84_ag_recovery_notification_policy_closure.md",
    ),
)


def run_s84_ag_recovery_notification_policy_closure(
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
        "default_policy_enabled": runtime["default_policy"]["enabled"] is True,
        "delivery_disabled_by_default": runtime["default_policy"][
            "delivery_enabled"
        ]
        is False,
        "preview_plan_ready": runtime["preview_plan_status"] == "PREVIEW_ONLY",
        "delivery_ready_but_unsent": (
            runtime["delivery_ready_plan_status"] == "READY"
            and runtime["delivery_performed"] is False
            and runtime["provider_invocation_performed"] is False
        ),
        "suppression_verified": runtime["suppressed_plan_status"] == "SUPPRESSED",
        "operations_projection_ready": runtime["operations_status"] == "READY",
        "source_unavailable_safe": runtime["unavailable_status"]
        == "SOURCE_UNAVAILABLE",
        "postgres_smoke_used_test_db": postgres["uses_test_db"],
        "postgres_smoke_passed": postgres["summary_pass"],
        "postgres_smoke_not_skipped": postgres["not_skipped"],
        "postgres_no_dispatch_or_event": postgres["side_effect_free"],
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
        else "s84_ag_recovery_notification_policy_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "ag_recovery_notification_policy_preview_only",
        "source_tables": list(SOURCE_TABLES),
        "new_tables": [],
        "new_indexes": [],
        "protected_routes": [PREVIEW_ROUTE],
        "external_delivery_implemented": False,
        "closure_surfaces": [
            "boundary_audit",
            "policy_configuration",
            "eligibility_evaluation",
            "redacted_notification_plan",
            "protected_preview_api",
            "operations_projection",
            "dashboard_openapi_schema_contracts",
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
        "summary_pass": "ag_recovery_notification_postgres_smoke=pass" in content,
        "not_skipped": "The result was not skipped" in content,
        "migration_verified": "Current migrations ran" in content,
        "suppression_verified": "plan=SUPPRESSED" in content,
        "side_effect_free": "dispatches=0 events=0" in content,
        "cleanup_verified": "cleaned=1" in content,
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
                "ag_recovery_notification_privacy_runbook=fail "
                "failure=privacy_runbook_execution_failed"
            ),
            "checks": {
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "provider_invocation_absent": False,
                "runbook_complete": False,
            },
        }
    selected_checks = {
        key: bool(result.get("checks", {}).get(key))
        for key in (
            "forbidden_values_absent",
            "forbidden_keys_absent",
            "provider_invocation_absent",
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
    default_policy = build_recovery_notification_policy({})
    recovery_plan = _recovery_plan()
    preview = build_recovery_notification_plan(
        recovery_plan,
        policy=default_policy,
        evaluated_at=OBSERVED_AT,
    )
    delivery_ready = build_recovery_notification_plan(
        recovery_plan,
        environ={RECOVERY_NOTIFICATION_DELIVERY_ENABLED_ENV: "1"},
        evaluated_at=OBSERVED_AT,
    )
    suppressed = build_recovery_notification_plan(
        _recovery_plan(effective_state="SUPPRESSED"),
        evaluated_at=OBSERVED_AT,
    )
    operations = build_recovery_notification_operations_projection(recovery_plan)
    unavailable = build_recovery_notification_operations_projection(None)
    return {
        "default_policy": default_policy,
        "preview_plan_status": preview["plan_status"],
        "delivery_ready_plan_status": delivery_ready["plan_status"],
        "delivery_performed": delivery_ready["delivery"]["performed"],
        "provider_invocation_performed": delivery_ready["delivery"][
            "provider_invocation_performed"
        ],
        "suppressed_plan_status": suppressed["plan_status"],
        "operations_status": operations["projection_status"],
        "unavailable_status": unavailable["notification_status"],
        "new_tables_required": operations["new_tables_required"],
    }


def _recovery_plan(*, effective_state: str | None = None) -> dict[str, Any]:
    return {
        "projection_schema_version": "ag_recovery_notification_closure_source.v1",
        "projection_status": "READY",
        "summary": {"liveness_status": "MISSING"},
        "recommended_actions": [
            {"action_id": "inspect-daemon", "severity": "ERROR"}
        ],
        "acknowledgement_state_overlay": {
            "effective_state_status": effective_state
        },
        "daemon_identity": {
            "service_id": "nex-ag",
            "worker_id": "ag-dispatch-execution-daemon",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = evidence.get("summary", {})
        return (
            "s84_ag_recovery_notification_policy_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    checks = evidence.get("checks", {})
    runtime = evidence.get("runtime", {})
    return (
        "s84_ag_recovery_notification_policy_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"postgres={checks.get('postgres_smoke_passed')} "
        f"privacy={checks.get('privacy_runbook_passed')} "
        f"delivery={runtime.get('delivery_performed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s84_ag_recovery_notification_policy_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
