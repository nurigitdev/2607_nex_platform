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

from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
)
from run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence import (  # noqa: E402
    summary_line as privacy_summary_line,
)
from run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence import (  # noqa: E402
    run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence as run_privacy_runbook,
)


SCHEMA_VERSION = (
    "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.v1"
)
MAX_TABLE_NAME_LENGTH = 30
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = "docs/slices/0808_ag_dispatch_liveness_ack_state_postgres_smoke.md"

ACK_STATE_ACTION_ROUTE = (
    "POST /admin/v1/operator-review/dispatch-daemon/liveness/ack-state"
)
ACK_STATE_LIST_ROUTE = (
    "GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states"
)
ACK_STATE_DETAIL_ROUTE = (
    "GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states/{ack_state_id}"
)

REQUIRED_FILES = (
    "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
    "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py",
    "scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py",
    "scripts/smoke/run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py",
    "tests/test_nex_ag_operator_review_liveness_ack.py",
    "tests/test_nex_ag_operator_review_liveness_ack_api.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py",
    "tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py",
    "tests/test_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.py",
    "tests/test_contract_validation.py",
    "tests/test_nex_ag_operations.py",
    "docs/README.md",
    "docs/slices/0801_ag_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.md",
    "docs/slices/0802_ag_dispatch_liveness_ack_state_persistence_foundation.md",
    "docs/slices/0803_ag_dispatch_liveness_ack_state_machine.md",
    "docs/slices/0804_ag_dispatch_liveness_ack_state_protected_action_api.md",
    "docs/slices/0805_ag_dispatch_liveness_ack_state_read_model_routes.md",
    "docs/slices/0806_ag_dispatch_liveness_ack_state_dashboard_issue_overlay.md",
    "docs/slices/0807_ag_dispatch_liveness_ack_state_openapi_hardening.md",
    POSTGRES_SMOKE_DOC,
    "docs/slices/0809_ag_dispatch_liveness_ack_state_privacy_runbook.md",
    "docs/slices/0810_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.md",
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary_audit",
        QUALITY_GATE_PATH,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_state_boundary_audit.py",
    ),
    (
        "quality_gate_postgres_smoke",
        QUALITY_GATE_PATH,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py",
    ),
    (
        "quality_gate_privacy_runbook",
        QUALITY_GATE_PATH,
        "run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_s81_closure",
        QUALITY_GATE_PATH,
        "run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.py",
    ),
    (
        "short_table_name_constant",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        'AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE = "ag_op_review_ack_state"',
    ),
    (
        "persistent_store_adapter",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "class SqlAlchemyOperatorReviewLivenessAckStateStore",
    ),
    (
        "state_transition_builder",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def build_operator_review_liveness_ack_state_transition",
    ),
    (
        "state_transition_applier",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def apply_operator_review_liveness_ack_state_transition",
    ),
    (
        "read_model_response",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def build_operator_review_liveness_ack_state_list_response",
    ),
    (
        "recovery_overlay_builder",
        "services/nex-ag/nex_ag/operations.py",
        "acknowledgement_state_overlay",
    ),
    (
        "action_route_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-state",
    ),
    (
        "list_route_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "/admin/v1/operator-review/dispatch-daemon/liveness/ack-states",
    ),
    (
        "detail_route_runtime",
        "services/nex-ag/nex_ag/operations.py",
        "ack-states/{ack_state_id}",
    ),
    (
        "action_route_openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "postAgOperatorReviewDispatchDaemonLivenessAckState",
    ),
    (
        "list_route_openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "listAgOperatorReviewDispatchDaemonLivenessAckStates",
    ),
    (
        "detail_route_openapi",
        "contracts/openapi/nex-ag.openapi.yaml",
        "getAgOperatorReviewDispatchDaemonLivenessAckState",
    ),
    (
        "migration_table",
        "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
        "CREATE TABLE IF NOT EXISTS ag_op_review_ack_state",
    ),
    (
        "migration_redaction_hash",
        "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
        "idempotency_key_hash",
    ),
    (
        "migration_indexes",
        "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
        "idx_ag_ack_state_worker_time",
    ),
    (
        "postgres_smoke_actual_test_db",
        POSTGRES_SMOKE_DOC,
        "nex_ag_test",
    ),
    (
        "postgres_smoke_summary",
        POSTGRES_SMOKE_DOC,
        "liveness_ack_state_postgres_smoke=pass",
    ),
    (
        "privacy_runbook_summary",
        "docs/slices/0809_ag_dispatch_liveness_ack_state_privacy_runbook.md",
        "liveness_ack_state_privacy_runbook=pass",
    ),
    (
        "docs_index_slice_0809",
        "docs/README.md",
        "0809_ag_dispatch_liveness_ack_state_privacy_runbook.md",
    ),
    (
        "docs_index_slice_0810",
        "docs/README.md",
        "0810_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure.md",
    ),
)


def run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_file_results = _required_file_results(root)
    token_results = _token_results(root)
    privacy_evidence = _privacy_evidence(root)
    postgres_evidence = _postgres_smoke_doc_evidence(root)
    table_evidence = _table_name_evidence()
    checks = {
        "required_files_present": all(
            item["present"] for item in required_file_results
        ),
        "required_tokens_present": all(item["present"] for item in token_results),
        "table_name_within_limit": table_evidence["within_limit"],
        "postgres_smoke_doc_present": postgres_evidence["doc_present"],
        "postgres_smoke_used_test_db": postgres_evidence["uses_test_db"],
        "postgres_smoke_summary_pass": postgres_evidence["summary_pass"],
        "privacy_runbook_passed": privacy_evidence["status"] == "PASS",
        "privacy_route_checks_passed": all(
            privacy_evidence["route_checks"].values()
        ),
        "privacy_redaction_checks_passed": all(
            privacy_evidence["redaction_checks"].values()
        ),
        "runtime_overlay_reads_persisted_state": (
            privacy_evidence["runtime_overlay"].get("overlay_status")
            == "STATE_PRESENT"
            and privacy_evidence["runtime_overlay"].get(
                "source_projection_suppressed"
            )
            is False
            and privacy_evidence["runtime_overlay"].get(
                "issue_candidate_suppressed"
            )
            is False
        ),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else (
            "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
            "closure_failed"
        ),
        "slice_range": "0801-0810",
        "boundary": (
            "ag_owned_operator_review_escalation_dispatch_daemon_liveness_"
            "acknowledgement_suppression_state"
        ),
        "source_tables": ["service_worker_heartbeats"],
        "new_tables": [AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE],
        "protected_routes": [
            ACK_STATE_ACTION_ROUTE,
            ACK_STATE_LIST_ROUTE,
            ACK_STATE_DETAIL_ROUTE,
        ],
        "closure_surfaces": [
            "boundary_audit",
            "persistence_foundation",
            "state_machine",
            "protected_action_api",
            "persisted_read_model_routes",
            "dashboard_issue_and_recovery_overlay",
            "openapi_contract_hardening",
            "test_db_postgres_smoke_evidence",
            "privacy_runbook_evidence",
        ],
        "postgres_smoke": postgres_evidence,
        "privacy_runbook": privacy_evidence,
        "table": table_evidence,
        "required_files": required_file_results,
        "token_checks": token_results,
        "checks": checks,
        "summary": {
            "required_file_count": len(required_file_results),
            "missing_file_count": sum(
                1 for item in required_file_results if not item["present"]
            ),
            "token_check_count": len(token_results),
            "missing_token_count": sum(
                1 for item in token_results if not item["present"]
            ),
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
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in text,
            }
        )
    return results


def _privacy_evidence(root: Path) -> dict[str, Any]:
    try:
        result = run_privacy_runbook(root)
    except Exception as exc:  # pragma: no cover - exercised by direct tests
        return {
            "status": "FAIL",
            "failure_code": "privacy_runbook_execution_failed",
            "detail": str(exc),
            "summary_line": (
                "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
                "privacy_runbook=fail failure=privacy_runbook_execution_failed"
            ),
            "surface_count": 0,
            "route_checks": {
                "route_static_ready": False,
                "route_runtime_ready": False,
                "route_parameters_ready": False,
            },
            "redaction_checks": {
                "state_redaction_ready": False,
                "list_redaction_ready": False,
                "redaction_flags_safe": False,
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
            },
            "runtime_overlay": {},
        }
    checks = result.get("checks", {})
    surfaces = result.get("surfaces", {})
    return {
        "status": result.get("status"),
        "failure_code": result.get("failure_code"),
        "summary_line": privacy_summary_line(result),
        "surface_count": result.get("surface_count", 0),
        "route_checks": {
            "route_static_ready": bool(checks.get("route_static_ready")),
            "route_runtime_ready": bool(checks.get("route_runtime_ready")),
            "route_parameters_ready": bool(checks.get("route_parameters_ready")),
        },
        "redaction_checks": {
            "state_redaction_ready": bool(checks.get("state_redaction_ready")),
            "list_redaction_ready": bool(checks.get("list_redaction_ready")),
            "redaction_flags_safe": bool(checks.get("redaction_flags_safe")),
            "forbidden_values_absent": bool(checks.get("forbidden_values_absent")),
            "forbidden_keys_absent": bool(checks.get("forbidden_keys_absent")),
        },
        "runtime_overlay": dict(surfaces.get("recovery_overlay", {})),
    }


def _postgres_smoke_doc_evidence(root: Path) -> dict[str, Any]:
    path = root / POSTGRES_SMOKE_DOC
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "doc": POSTGRES_SMOKE_DOC,
        "doc_present": path.is_file(),
        "uses_test_db": "nex_ag_test" in text,
        "summary_pass": "liveness_ack_state_postgres_smoke=pass" in text,
        "redacted_database_url": "<redacted>" in text or "NEX_AG_TEST_DATABASE_URL"
        in text,
    }


def _table_name_evidence() -> dict[str, Any]:
    return {
        "name": AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE,
        "length": len(AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE),
        "max_length": MAX_TABLE_NAME_LENGTH,
        "within_limit": (
            len(AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE)
            <= MAX_TABLE_NAME_LENGTH
        ),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "PASS":
        return (
            "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
            "closure=pass "
            f"slice_range={evidence.get('slice_range')} "
            f"table={evidence.get('table', {}).get('name')} "
            f"routes={len(evidence.get('protected_routes', []))} "
            f"privacy={evidence.get('checks', {}).get('privacy_runbook_passed')} "
            f"postgres_smoke={evidence.get('checks', {}).get('postgres_smoke_summary_pass')}"
        )
    return (
        "s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
        f"closure=fail reason={evidence.get('failure_code') or 'unknown'} "
        f"missing_files={evidence.get('summary', {}).get('missing_file_count')} "
        f"missing_tokens={evidence.get('summary', {}).get('missing_token_count')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = (
        run_s81_operator_review_escalation_dispatch_daemon_liveness_ack_state_closure()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
