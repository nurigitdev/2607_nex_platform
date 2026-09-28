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

from run_ae_citation_repair_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_ae_citation_repair_postgres_smoke as run_postgres,
)
from run_ae_citation_repair_workflow_boundary_audit import (  # noqa: E402
    run_ae_citation_repair_workflow_boundary_audit as run_boundary,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s106_ae_citation_repair_workflow_closure.v1"
SLICE_RANGE = "1052-1061"

REQUIRED_FILES = (
    "services/nex-cx/nex_cx/citation_repair.py",
    "services/nex-cx/nex_cx/generation_persistence.py",
    "services/nex-ae-api/nex_ae_api/citation_quality_workflow.py",
    "services/nex-ae-api/nex_ae_api/citation_quality_observability.py",
    "services/nex-ae-api/nex_ae_api/chat.py",
    "services/nex-ae-api/nex_ae_api/repaired_responses.py",
    "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
    "contracts/schemas/service/nex_ae_api/citation_quality_workflow.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/smoke/run_ae_citation_repair_postgres_smoke.py",
    "scripts/smoke/run_s106_ae_citation_repair_workflow_closure.py",
    "tests/test_s106_ae_citation_repair_workflow_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1052", "ae_citation_repair_workflow_boundary_audit"),
            ("1053", "cx_citation_repair_metadata_persistence"),
            ("1054", "ae_citation_quality_workflow_projection"),
            ("1055", "ae_citation_quality_api"),
            ("1056", "ae_repaired_response_owner_scope_hardening"),
            ("1057", "ae_async_citation_workflow_integration"),
            ("1058", "ae_citation_repair_workflow_observability"),
            ("1059", "ae_citation_repair_contract_hardening"),
            ("1060", "ae_citation_repair_postgres_smoke"),
            ("1061", "s106_ae_citation_repair_workflow_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "cx_bounded_repair",
        "services/nex-cx/nex_cx/citation_repair.py",
        "def generate_with_bounded_citation_repair(",
    ),
    (
        "cx_repair_persistence",
        "services/nex-cx/nex_cx/generation_persistence.py",
        "validate_citation_repair_projection(repair)",
    ),
    (
        "ae_workflow_projection",
        "services/nex-ae-api/nex_ae_api/citation_quality_workflow.py",
        "def build_citation_quality_workflow(",
    ),
    (
        "ae_workflow_validation",
        "services/nex-ae-api/nex_ae_api/citation_quality_workflow.py",
        "def validate_citation_quality_workflow(",
    ),
    (
        "owner_quality_api",
        "services/nex-ae-api/nex_ae_api/chat.py",
        '"/api/v1/chat/interactions/{interaction_id}/citation-quality"',
    ),
    (
        "durable_workflow",
        "services/nex-ae-api/nex_ae_api/chat.py",
        'refreshed_generation["citation_workflow"]',
    ),
    (
        "repaired_handoff_owner_scope",
        "services/nex-ae-api/nex_ae_api/repaired_responses.py",
        "get_for_owner(",
    ),
    (
        "repaired_decision_owner_scope",
        "services/nex-ae-api/nex_ae_api/repaired_response_decisions.py",
        "get_for_owner(",
    ),
    (
        "metadata_observability",
        "services/nex-ae-api/nex_ae_api/citation_quality_observability.py",
        'AE_CITATION_QUALITY_WORKFLOW_EVENT = "ae.citation_quality.workflow_observed"',
    ),
    (
        "workflow_schema",
        "contracts/schemas/service/nex_ae_api/citation_quality_workflow.v1.schema.json",
        '"ae_citation_quality_workflow.v1"',
    ),
    (
        "workflow_openapi",
        "contracts/openapi/nex-ae-api.openapi.yaml",
        "/api/v1/chat/interactions/{interaction_id}/citation-quality:",
    ),
    (
        "actual_ae_test_target",
        "scripts/smoke/run_ae_citation_repair_postgres_smoke.py",
        'AE_DATABASE = "nex_ae_test"',
    ),
    (
        "actual_cx_test_target",
        "scripts/smoke/run_ae_citation_repair_postgres_smoke.py",
        'CX_DATABASE = "nex_cx_test"',
    ),
    (
        "postgres_cleanup",
        "scripts/smoke/run_ae_citation_repair_postgres_smoke.py",
        'checks["cleanup_complete"]',
    ),
    (
        "quality_postgres",
        "scripts/quality/run_quality_gate.sh",
        "run_ae_citation_repair_postgres_smoke.py",
    ),
    (
        "quality_closure",
        "scripts/quality/run_quality_gate.sh",
        "run_s106_ae_citation_repair_workflow_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1061_s106_ae_citation_repair_workflow_closure.md",
    ),
)

COMPONENT_TOKEN_NAMES = {
    "boundary_audit": ("cx_bounded_repair",),
    "cx_repair_persistence": ("cx_repair_persistence",),
    "ae_workflow_projection": (
        "ae_workflow_projection",
        "ae_workflow_validation",
    ),
    "owner_scoped_quality_api": ("owner_quality_api",),
    "repaired_response_owner_scope": (
        "repaired_handoff_owner_scope",
        "repaired_decision_owner_scope",
    ),
    "durable_async_integration": ("durable_workflow",),
    "metadata_observability": ("metadata_observability",),
    "contract_openapi": ("workflow_schema", "workflow_openapi"),
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


def run_s106_ae_citation_repair_workflow_closure(
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
        and postgres.get("provider_call_count") == 2
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
            and boundary.get("next_slice") == "1061"
        ),
        "all_components_closed": all(components.values()),
        "contract_tree_valid": contract.get("status") == "PASS",
        "postgres_policy_satisfied": postgres_policy_satisfied,
        "ownership_boundary_preserved": (
            boundary_decision.get("cx_generation_quality_owner") == "nex-cx"
            and boundary_decision.get("ae_workflow_projection_owner")
            == "nex-ae-api"
            and boundary_decision.get("ag_operator_remediation_owner") == "nex-ag"
        ),
        "repair_modes_remain_distinct": (
            boundary_decision.get("repair_modes_must_remain_distinct") is True
            and boundary_decision.get("bounded_repair_model")
            == "one_inline_attempt_same_retrieval_package"
            and boundary_decision.get("operator_repair_model")
            == "separate_ag_cx_remediation_lineage"
        ),
        "owner_scope_preserved": (
            boundary_decision.get("owner_scope")
            == "tenant_and_owner_user_exact_match"
        ),
        "privacy_boundary_preserved": all(
            boundary_decision.get(field) is False
            for field in (
                "raw_generation_content_in_workflow",
                "raw_invalid_output_in_workflow",
                "raw_evidence_text_in_workflow",
            )
        ),
        "compatibility_and_storage_preserved": (
            boundary_decision.get("existing_handoff_tables_reused") is True
            and boundary_decision.get("new_tables_expected") == 0
        ),
        "tiered_quality_cadence_preserved": (
            boundary_decision.get("quality_cadence")
            == {
                "slice_gate": "1052-1061",
                "checkpoint_gate": "1056",
                "full_gate": "1061",
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
        "slice": "1061",
        "slice_range": SLICE_RANGE,
        "requirement": "S106",
        "status": status,
        "failure_code": (
            None
            if status == "PASS"
            else "s106_ae_citation_repair_workflow_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_S107"
            if status == "PASS" and postgres_executed
            else "READY_WITH_PROTECTED_POSTGRES_PENDING"
            if status == "PASS"
            else "BLOCKED"
        ),
        "feature_readiness": (
            "AE_CITATION_REPAIR_WORKFLOW_READY"
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
        "next_requirement": "S107",
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
        "feature_scope": "ae_citation_quality_and_repair_workflow",
        "generation_quality_owner": "nex-cx",
        "owner_workflow_projection_owner": "nex-ae-api",
        "operator_remediation_owner": "nex-ag",
        "bounded_repair_policy": "one_inline_attempt_same_retrieval_package",
        "operator_repair_policy": "separate_remediation_lineage",
        "content_policy": "privacy_safe_metadata_only_workflow",
        "postgres_smoke_targets": [
            "nex_ae_user@nex_ae_test",
            "nex_cx_user@nex_cx_test",
        ],
        "remote_provider_required": False,
        "new_tables_added": [],
        "next_requirement_scope": "S107_to_be_confirmed",
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
        "s106_ae_citation_repair_workflow_closure="
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
    evidence = run_s106_ae_citation_repair_workflow_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
