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
from run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence import (  # noqa: E402
    run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence as run_privacy_runbook,
)
from run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence import (  # noqa: E402
    summary_line as privacy_summary_line,
)


SCHEMA_VERSION = "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.v1"
SLICE_RANGE = "0811-0820"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = (
    "docs/slices/0818_ag_dispatch_liveness_ack_expiry_postgres_smoke.md"
)
PRIVACY_RUNBOOK_DOC = (
    "docs/slices/0819_ag_dispatch_liveness_ack_expiry_privacy_runbook.md"
)
TABLE_NAME = AG_OPERATOR_REVIEW_LIVENESS_ACK_STATE_TABLE
INDEX_NAME = "idx_ag_ack_state_expiry"
MAX_IDENTIFIER_LENGTH = 30
PROTECTED_ROUTE = (
    "POST /admin/v1/operator-review/dispatch-daemon/liveness/"
    "ack-states/reconcile-expired"
)

REQUIRED_FILES = (
    "database/nex-ag/migrations/0802_ag_liveness_ack_state.sql",
    "database/nex-ag/migrations/0813_ag_ack_expiry_index.sql",
    "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
    "services/nex-ag/nex_ag/liveness_ack_expiry_reconciliation.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.py",
    "scripts/smoke/run_ag_dispatch_liveness_ack_expiry_postgres_smoke.py",
    "scripts/smoke/run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py",
    "scripts/smoke/run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py",
    "tests/test_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.py",
    "tests/test_nex_ag_operator_review_liveness_ack_expiry.py",
    "tests/test_nex_ag_liveness_ack_expiry_reconciliation.py",
    "tests/test_nex_ag_liveness_ack_expiry_api.py",
    "tests/test_nex_ag_liveness_ack_expiry_operations_overlay.py",
    "tests/test_nex_ag_liveness_ack_expiry_contracts.py",
    "tests/test_ag_dispatch_liveness_ack_expiry_postgres_smoke.py",
    "tests/test_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py",
    "tests/test_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0811", "ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit"),
            ("0812", "ag_dispatch_liveness_ack_expiry_reconciliation_contract"),
            ("0813", "ag_dispatch_liveness_ack_expiry_persistence_adapter"),
            ("0814", "ag_dispatch_liveness_ack_expiry_reconciliation_worker"),
            ("0815", "ag_dispatch_liveness_ack_expiry_reconciliation_api_audit"),
            ("0816", "ag_dispatch_liveness_ack_expiry_operations_overlay"),
            ("0817", "ag_dispatch_liveness_ack_expiry_contract_hardening"),
            ("0818", "ag_dispatch_liveness_ack_expiry_postgres_smoke"),
            ("0819", "ag_dispatch_liveness_ack_expiry_privacy_runbook"),
            ("0820", "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_gate_boundary",
        QUALITY_GATE_PATH,
        "run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit.py",
    ),
    (
        "quality_gate_postgres",
        QUALITY_GATE_PATH,
        "run_ag_dispatch_liveness_ack_expiry_postgres_smoke.py",
    ),
    (
        "quality_gate_privacy",
        QUALITY_GATE_PATH,
        "run_ag_dispatch_liveness_ack_expiry_privacy_runbook_evidence.py",
    ),
    (
        "quality_gate_closure",
        QUALITY_GATE_PATH,
        "run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.py",
    ),
    (
        "candidate_query",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def list_expiry_candidates",
    ),
    (
        "cas_update",
        "services/nex-ag/nex_ag/operator_review_liveness_ack.py",
        "def apply_expiry_reconciliation",
    ),
    (
        "one_cycle_worker",
        "services/nex-ag/nex_ag/liveness_ack_expiry_reconciliation.py",
        "def run_operator_review_liveness_ack_expiry_reconciliation",
    ),
    (
        "protected_route",
        "services/nex-ag/nex_ag/operations.py",
        "ack-states/reconcile-expired",
    ),
    (
        "static_openapi_operation",
        "contracts/openapi/nex-ag.openapi.yaml",
        "postAgOperatorReviewDispatchDaemonLivenessAckExpiryReconcile",
    ),
    (
        "operations_overlay_schema",
        "contracts/schemas/service/nex_ag/operations_projection.v1.schema.json",
        "dashboard_operator_review_liveness_ack_expiry_reconciliation_overlay",
    ),
    (
        "expiry_index",
        "database/nex-ag/migrations/0813_ag_ack_expiry_index.sql",
        "idx_ag_ack_state_expiry",
    ),
    ("postgres_test_db", POSTGRES_SMOKE_DOC, "nex_ag_test"),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "Real PostgreSQL result: `PASS`",
    ),
    (
        "postgres_migration",
        POSTGRES_SMOKE_DOC,
        "0813_ag_ack_expiry_index",
    ),
    (
        "postgres_cleanup",
        POSTGRES_SMOKE_DOC,
        "zero remaining rows",
    ),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "privacy_runbook=pass",
    ),
    (
        "docs_index_0820",
        "docs/README.md",
        "0820_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure.md",
    ),
)


def run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    postgres = _postgres_smoke_doc_evidence(root)
    privacy = _privacy_evidence(root)
    identifiers = _identifier_evidence()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "identifier_lengths_safe": identifiers["within_limit"],
        "postgres_smoke_doc_present": postgres["doc_present"],
        "postgres_smoke_used_test_db": postgres["uses_test_db"],
        "postgres_smoke_passed": postgres["summary_pass"],
        "postgres_migration_verified": postgres["migration_verified"],
        "postgres_cleanup_verified": postgres["cleanup_verified"],
        "privacy_runbook_passed": privacy["status"] == "PASS",
        "privacy_checks_passed": all(privacy["checks"].values()),
        "conflict_guard_verified": bool(
            privacy["checks"].get("cas_conflict_reported")
        ),
        "idempotent_rerun_verified": bool(
            privacy["checks"].get("idempotent_rerun_empty")
        ),
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "ag_owned_dispatch_liveness_ack_expiry_reconciliation",
        "source_tables": [TABLE_NAME],
        "new_tables": [],
        "new_indexes": [INDEX_NAME],
        "protected_routes": [PROTECTED_ROUTE],
        "closure_surfaces": [
            "boundary_audit",
            "pure_transition_contract",
            "persistent_candidate_and_cas_adapter",
            "bounded_one_cycle_worker",
            "protected_api_and_audit",
            "dashboard_and_issue_overlay",
            "openapi_and_schema_hardening",
            "test_db_postgres_smoke",
            "privacy_concurrency_runbook",
        ],
        "postgres_smoke": postgres,
        "privacy_runbook": privacy,
        "identifiers": identifiers,
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
        "uses_test_db": "nex_ag_test" in content,
        "summary_pass": "Real PostgreSQL result: `PASS`" in content,
        "migration_verified": "0813_ag_ack_expiry_index" in content,
        "index_verified": INDEX_NAME in content,
        "idempotent_rerun_verified": "zero candidates" in content,
        "stale_cas_verified": "stale CAS" in content,
        "cleanup_verified": "zero remaining rows" in content,
    }


def _privacy_evidence(root: Path) -> dict[str, Any]:
    try:
        result = run_privacy_runbook(root)
    except Exception as exc:  # pragma: no cover - exercised by direct tests
        return {
            "status": "FAIL",
            "failure_code": "privacy_runbook_execution_failed",
            "detail": str(exc),
            "summary_line": (
                "ag_dispatch_liveness_ack_expiry_privacy_runbook=fail "
                "failure=privacy_runbook_execution_failed"
            ),
            "checks": {
                "cas_conflict_reported": False,
                "idempotent_rerun_empty": False,
                "forbidden_values_absent": False,
                "forbidden_keys_absent": False,
                "runbook_complete": False,
            },
        }
    selected_checks = {
        key: bool(result.get("checks", {}).get(key))
        for key in (
            "cas_conflict_reported",
            "idempotent_rerun_empty",
            "forbidden_values_absent",
            "forbidden_keys_absent",
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


def _identifier_evidence() -> dict[str, Any]:
    identifiers = {"table": TABLE_NAME, "index": INDEX_NAME}
    lengths = {name: len(value) for name, value in identifiers.items()}
    return {
        "identifiers": identifiers,
        "lengths": lengths,
        "max_length": MAX_IDENTIFIER_LENGTH,
        "within_limit": all(
            length <= MAX_IDENTIFIER_LENGTH for length in lengths.values()
        ),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = evidence.get("summary", {})
        return (
            "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    checks = evidence.get("checks", {})
    return (
        "s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"table={TABLE_NAME} index={INDEX_NAME} "
        f"postgres={checks.get('postgres_smoke_passed')} "
        f"privacy={checks.get('privacy_runbook_passed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s82_ag_dispatch_liveness_ack_expiry_reconciliation_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
