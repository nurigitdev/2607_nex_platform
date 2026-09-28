#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "quality"))

from run_ae_generation_lifecycle_boundary_audit import (  # noqa: E402
    run_ae_generation_lifecycle_boundary_audit as run_boundary,
)
from run_ae_generation_lifecycle_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_generation_lifecycle_postgres_smoke as run_postgres,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s105_ae_generation_lifecycle_closure.v1"
SLICE_RANGE = "1042-1051"

REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/generation_progress.py",
    "services/nex-ae-api/nex_ae_api/generation_lifecycle.py",
    "services/nex-ae-api/nex_ae_api/generation_recovery.py",
    "services/nex-ae-api/nex_ae_api/generation_lifecycle_observability.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "contracts/schemas/service/nex_ae_api/generation_progress.v1.schema.json",
    "contracts/schemas/service/nex_ae_api/generation_recovery_plan.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/smoke/run_ae_generation_lifecycle_postgres_smoke.py",
    "scripts/smoke/run_s105_ae_generation_lifecycle_closure.py",
    "tests/test_s105_ae_generation_lifecycle_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1042", "ae_generation_lifecycle_boundary_audit"),
            ("1043", "ae_generation_progress_contract"),
            ("1044", "ae_generation_lifecycle_orchestration"),
            ("1045", "ae_generation_progress_api"),
            ("1046", "ae_generation_cancellation_race"),
            ("1047", "ae_generation_recovery_orchestration"),
            ("1048", "ae_generation_lifecycle_observability"),
            ("1049", "ae_generation_lifecycle_contract_hardening"),
            ("1050", "ae_generation_lifecycle_postgres_smoke"),
            ("1051", "s105_ae_generation_lifecycle_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "progress_projection",
        "services/nex-ae-api/nex_ae_api/generation_progress.py",
        "def build_generation_progress_projection(",
    ),
    (
        "recovery_projection",
        "services/nex-ae-api/nex_ae_api/generation_progress.py",
        "def build_generation_recovery_plan(",
    ),
    (
        "lifecycle_orchestration",
        "services/nex-ae-api/nex_ae_api/generation_lifecycle.py",
        "def orchestrate_generation_lifecycle(",
    ),
    (
        "cancellation_convergence",
        "services/nex-ae-api/nex_ae_api/generation_lifecycle.py",
        "def orchestrate_generation_cancellation(",
    ),
    (
        "retry_orchestration",
        "services/nex-ae-api/nex_ae_api/generation_recovery.py",
        "def prepare_generation_retry(",
    ),
    (
        "progress_api",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/progress"',
    ),
    (
        "recovery_api",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/recovery"',
    ),
    (
        "metadata_observability",
        "services/nex-ae-api/nex_ae_api/generation_lifecycle_observability.py",
        '"ae_generation_lifecycle_observability.v1"',
    ),
    (
        "progress_schema",
        "contracts/schemas/service/nex_ae_api/generation_progress.v1.schema.json",
        '"ae_generation_progress.v1"',
    ),
    (
        "recovery_schema",
        "contracts/schemas/service/nex_ae_api/generation_recovery_plan.v1.schema.json",
        '"ae_generation_recovery_plan.v1"',
    ),
    (
        "openapi_progress",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/progress:",
    ),
    (
        "openapi_recovery",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/recovery:",
    ),
    (
        "actual_ae_test_target",
        "scripts/smoke/run_ae_generation_lifecycle_postgres_smoke.py",
        'AE_DATABASE = "nex_ae_test"',
    ),
    (
        "actual_cx_test_target",
        "scripts/smoke/run_ae_generation_lifecycle_postgres_smoke.py",
        'CX_DATABASE = "nex_cx_test"',
    ),
    (
        "postgres_cleanup",
        "scripts/smoke/run_ae_generation_lifecycle_postgres_smoke.py",
        'checks["cleanup_complete"]',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_generation_lifecycle_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s105_ae_generation_lifecycle_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1051_s105_ae_generation_lifecycle_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("progress_projection",),
    "progress_recovery_contract": (
        "progress_projection",
        "recovery_projection",
    ),
    "lifecycle_orchestration": ("lifecycle_orchestration",),
    "owner_scoped_progress_api": ("progress_api",),
    "cancellation_race_convergence": ("cancellation_convergence",),
    "recovery_retry_orchestration": ("recovery_api", "retry_orchestration"),
    "metadata_observability": ("metadata_observability",),
    "contract_openapi": (
        "progress_schema",
        "recovery_schema",
        "openapi_progress",
        "openapi_recovery",
    ),
    "actual_postgresql": (
        "actual_ae_test_target",
        "actual_cx_test_target",
        "postgres_cleanup",
    ),
    "quality_documentation": (
        "quality_postgres",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s105_ae_generation_lifecycle_closure(
    root: Path = ROOT,
    *,
    postgres_evidence: Mapping[str, Any] | None = None,
    contract_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKEN_NAMES.items()
    }
    boundary = _safe_evidence(lambda: run_boundary(root))
    contract = (
        dict(contract_evidence)
        if contract_evidence is not None
        else _safe_evidence(lambda: _contract_evidence(root))
    )
    postgres = (
        dict(postgres_evidence)
        if postgres_evidence is not None
        else _safe_evidence(run_postgres)
    )
    boundary_summary = _mapping(boundary.get("summary"))
    boundary_decision = _mapping(boundary.get("decision"))
    postgres_checks = _mapping(postgres.get("checks"))
    identity = _mapping(postgres.get("database_identity"))
    cleanup = _mapping(postgres.get("cleanup_counts"))
    postgres_requested = os.environ.get(POSTGRES_SMOKE_ENV) == "1"
    postgres_executed = (
        postgres.get("status") == "PASS"
        and postgres.get("actual_postgres") is True
        and postgres.get("execution_state") == "EXECUTED"
        and _mapping(identity.get("ae"))
        == {"database": "nex_ae_test", "role": "nex_ae_user"}
        and _mapping(identity.get("cx"))
        == {"database": "nex_cx_test", "role": "nex_cx_user"}
        and bool(postgres_checks)
        and all(postgres_checks.values())
        and cleanup.get("ae_remaining") == 0
        and cleanup.get("cx_remaining") == 0
    )
    postgres_policy_satisfied = postgres_executed or (
        not postgres_requested and postgres.get("status") == "SKIPPED"
    )
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "boundary_plan_completed": (
            boundary_summary.get("planned_slice_count") == 10
            and boundary_summary.get("gap_count") == 8
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary.get("next_slice") == "1051"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "ownership_boundary_preserved": (
            boundary_decision.get("cx_lifecycle_owner") == "nex-cx"
            and boundary_decision.get("ae_interaction_owner") == "nex-ae-api"
        ),
        "explicit_polling_boundary_preserved": (
            boundary_decision.get("progress_model")
            == "explicit_owner_scoped_polling_snapshot"
            and boundary_decision.get("background_poller_in_scope") is False
        ),
        "race_and_recovery_boundary_preserved": (
            boundary_decision.get("terminal_state_precedence") is True
            and boundary_decision.get("cancellation_model")
            == "delegate_to_cx_then_reconcile"
            and boundary_decision.get("recovery_model")
            == "read_only_plan_then_new_child_admission"
        ),
        "privacy_boundary_preserved": (
            boundary_decision.get("raw_generation_content_in_progress") is False
            and boundary_decision.get("raw_failure_detail_in_progress") is False
        ),
        "compatibility_and_storage_preserved": (
            boundary_decision.get("synchronous_backward_compatibility") is True
            and boundary_decision.get("new_tables_expected") == 0
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "1042-1051",
                "checkpoint_gate": "1046",
                "full_gate": "1051",
            }
        ),
        "remote_provider_out_of_scope": (
            boundary_decision.get("remote_provider_required") is False
            and postgres.get("remote_provider_required", False) is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1051",
        "slice_range": SLICE_RANGE,
        "requirement": "S105",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s105_ae_generation_lifecycle_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S106"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_GENERATION_LIFECYCLE_READY"
            if status == "PASS" and postgres_executed
            else "REPOSITORY_READY_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "resolved_gap_count": int(
                boundary_summary.get("resolved_gap_count") or 0
            ),
            "contract_schema_count": int(contract.get("schema_count") or 0),
            "contract_example_count": int(contract.get("example_count") or 0),
            "contract_negative_count": int(
                contract.get("negative_example_count") or 0
            ),
            "postgres_check_count": (
                len(postgres_checks) if postgres_executed else 0
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "components": components,
        "boundary_status": boundary.get("status"),
        "contract_status": contract.get("status"),
        "postgres_status": postgres.get("status"),
        "postgres_executed": postgres_executed,
        "postgres_evidence": postgres,
        "required_files": required_files,
        "token_checks": token_checks,
        "decision": _closure_decision(),
        "next_requirement": "S106",
    }


def _contract_evidence(root: Path) -> dict[str, Any]:
    result = validate_contract_tree(root / "contracts")
    return {
        "status": "PASS" if result.ok else "FAIL",
        "schema_count": result.schema_count,
        "example_count": result.example_count,
        "negative_example_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
        "failure_count": len(result.failures),
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "ae_generation_progress_cancellation_recovery",
        "lifecycle_owner": "nex-cx",
        "interaction_owner": "nex-ae-api",
        "polling_policy": "explicit_owner_scoped_snapshot",
        "cancellation_policy": "terminal_state_wins_and_ae_reconciles",
        "recovery_policy": "read_only_plan_then_lineage_bound_child_retry",
        "content_policy": "metadata_only_progress_and_recovery",
        "postgres_smoke_targets": [
            "nex_ae_user@nex_ae_test",
            "nex_cx_user@nex_cx_test",
        ],
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S106_to_be_confirmed",
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s105_ae_generation_lifecycle_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"postgres={str(evidence.get('postgres_status') or 'not-run').lower()} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s105_ae_generation_lifecycle_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
