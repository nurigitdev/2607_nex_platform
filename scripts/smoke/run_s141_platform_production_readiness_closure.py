#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any

from run_platform_nonproduction_path_inventory import (
    run_platform_nonproduction_path_inventory,
)
from run_platform_operational_incompleteness_register import (
    run_platform_operational_incompleteness_register,
)
from run_platform_production_configuration_audit import (
    run_platform_production_configuration_audit,
)
from run_platform_production_deferral_inventory import (
    run_platform_production_deferral_inventory,
)
from run_platform_production_evidence_decision_contract import (
    run_platform_production_evidence_decision_contract,
)
from run_platform_production_readiness_boundary import (
    run_platform_production_readiness_boundary,
)
from run_platform_production_responsibility_matrix import (
    run_platform_production_responsibility_matrix,
)
from run_platform_production_transition_dependency_plan import (
    run_platform_production_transition_dependency_plan,
)
from run_platform_runtime_deployment_coupling_audit import (
    run_platform_runtime_deployment_coupling_audit,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s141_platform_production_readiness_closure.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
CANONICAL_PATH = "docs/49_platform_production_readiness_reaudit.md"
RUNBOOK_PATH = "docs/runbooks/platform_production_readiness_reaudit.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s141_platform_production_readiness_closure.py"
EvidenceRunner = Callable[[Path], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, str, EvidenceRunner], ...] = (
    (
        "boundary",
        "run_platform_production_readiness_boundary.py",
        run_platform_production_readiness_boundary,
    ),
    (
        "deferrals",
        "run_platform_production_deferral_inventory.py",
        run_platform_production_deferral_inventory,
    ),
    (
        "nonproduction_paths",
        "run_platform_nonproduction_path_inventory.py",
        run_platform_nonproduction_path_inventory,
    ),
    (
        "configuration",
        "run_platform_production_configuration_audit.py",
        run_platform_production_configuration_audit,
    ),
    (
        "coupling",
        "run_platform_runtime_deployment_coupling_audit.py",
        run_platform_runtime_deployment_coupling_audit,
    ),
    (
        "responsibility",
        "run_platform_production_responsibility_matrix.py",
        run_platform_production_responsibility_matrix,
    ),
    (
        "operations",
        "run_platform_operational_incompleteness_register.py",
        run_platform_operational_incompleteness_register,
    ),
    (
        "transition",
        "run_platform_production_transition_dependency_plan.py",
        run_platform_production_transition_dependency_plan,
    ),
    (
        "evidence_contract",
        "run_platform_production_evidence_decision_contract.py",
        run_platform_production_evidence_decision_contract,
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1402", "platform_production_readiness_boundary"),
        ("1403", "platform_production_deferral_inventory"),
        ("1404", "platform_nonproduction_path_inventory"),
        ("1405", "platform_production_configuration_audit"),
        ("1406", "platform_runtime_deployment_coupling_audit"),
        ("1407", "platform_production_responsibility_matrix"),
        ("1408", "platform_operational_incompleteness_register"),
        ("1409", "platform_production_transition_dependency_plan"),
        ("1410", "platform_production_evidence_decision_contract"),
        ("1411", "s141_platform_production_readiness_closure"),
    )
)


def run_s141_platform_production_readiness_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (*SLICE_DOCUMENTS, PLAN_PATH, CANONICAL_PATH, RUNBOOK_PATH)
    document_presence = {path: (root / path).is_file() for path in required_documents}
    evidence = _run_evidence(root) if all(document_presence.values()) else {}
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)

    boundary = _mapping(evidence.get("boundary"))
    deferrals = _mapping(evidence.get("deferrals"))
    paths = _mapping(evidence.get("nonproduction_paths"))
    configuration = _mapping(evidence.get("configuration"))
    coupling = _mapping(evidence.get("coupling"))
    responsibility = _mapping(evidence.get("responsibility"))
    operations = _mapping(evidence.get("operations"))
    transition = _mapping(evidence.get("transition"))
    evidence_contract = _mapping(evidence.get("evidence_contract"))

    boundary_summary = _mapping(boundary.get("summary"))
    deferral_summary = _mapping(deferrals.get("summary"))
    path_summary = _mapping(paths.get("summary"))
    config_summary = _mapping(configuration.get("summary"))
    coupling_summary = _mapping(coupling.get("summary"))
    responsibility_summary = _mapping(responsibility.get("summary"))
    operations_summary = _mapping(operations.get("summary"))
    transition_summary = _mapping(transition.get("summary"))
    contract_summary = _mapping(evidence_contract.get("summary"))

    checks = {
        "all_nine_audits_passed": len(evidence) == 9
        and all(item.get("status") == "PASS" for item in evidence.values()),
        "all_slice_canonical_runbook_documents_present": all(
            document_presence.values()
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER)
        == 1,
        "plan_marks_s141_complete": all(
            token in plan
            for token in (
                "S141 is complete; production deployment remains unapproved",
                "S142 is the active",
                "Completion signal: Met.",
            )
        ),
        "canonical_decision_and_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S141 complete through Slice 1411.",
                "Production deployment remains unapproved.",
                "No production resource was contacted by S141.",
                "S140 release-candidate closure is the rollback baseline.",
                "## S142 Handoff",
                "Completion signal: Met.",
            )
        ),
        "boundary_inventory_exact": boundary_summary.get("deferral_count") == 9
        and boundary_summary.get("audit_count") == 9,
        "nine_deferrals_remain_open": deferral_summary
        == {
            "runtime_deferral_count": 9,
            "registered_deferral_count": 9,
            "documented_deferral_count": 9,
            "owner_count": 6,
            "target_requirement_count": 7,
            "open_deferral_count": 9,
        },
        "nine_nonproduction_paths_forbidden": path_summary
        == {
            "path_count": 9,
            "evidence_anchor_count": 15,
            "path_class_count": 5,
            "production_forbidden_count": 9,
            "transition_requirement_count": 6,
        },
        "production_configuration_gap_baseline_exact": config_summary
        == {
            "required_environment_count": 25,
            "database_environment_count": 5,
            "service_endpoint_count": 6,
            "signed_trust_environment_count": 8,
            "live_provider_environment_count": 6,
            "config_gap_count": 10,
        },
        "runtime_coupling_baseline_exact": coupling_summary
        == {
            "http_client_anchor_count": 11,
            "logical_api_edge_count": 7,
            "cross_service_import_count": 0,
            "non_mo_provider_reference_count": 0,
            "legacy_database_adapter_count": 4,
            "loopback_occurrence_count": 45,
            "loopback_file_count": 25,
            "source_process_count": 13,
            "coupling_record_count": 6,
        },
        "production_responsibility_baseline_exact": (
            responsibility_summary.get("control_count") == 9
            and responsibility_summary.get("owner_count") == 6
            and responsibility_summary.get("database_owner_count") == 5
        ),
        "operational_gaps_remain_open": (
            operations_summary.get("gap_count") == 12
            and operations_summary.get("p0_count") == 8
            and operations_summary.get("p1_count") == 4
            and operations_summary.get("domain_count") == 5
            and operations_summary.get("open_count") == 12
        ),
        "transition_dependency_order_exact": (
            transition_summary.get("requirement_count") == 9
            and transition_summary.get("wave_count") == 6
            and transition_summary.get("parallel_wave_requirement_count") == 4
            and transition_summary.get("dependency_edge_count") == 16
            and transition_summary.get("external_capability_count") == 11
        ),
        "evidence_decision_contract_exact": (
            contract_summary.get("evidence_field_count") == 20
            and contract_summary.get("forbidden_category_count") == 13
            and contract_summary.get("freshness_class_count") == 4
            and contract_summary.get("rollback_field_count") == 9
            and contract_summary.get("decision_gate_count") == 10
            and contract_summary.get("decision_state_count") == 2
        ),
        "no_production_execution_claimed": (
            _mapping(boundary.get("decision")).get(
                "production_deployment_approved"
            )
            is False
            and _mapping(configuration.get("decision")).get(
                "production_admission_complete"
            )
            is False
            and _mapping(operations.get("decision")).get(
                "production_admission_blocked"
            )
            is True
            and _mapping(transition.get("decision")).get(
                "production_deployment_performed"
            )
            is False
            and _mapping(evidence_contract.get("decision")).get(
                "production_deployment_performed"
            )
            is False
        ),
        "runbook_reproduces_all_audits_and_full_gate": all(
            script_name in runbook for _, script_name, _ in EVIDENCE_RUNNERS
        )
        and CLOSURE_RUNNER in runbook
        and "scripts/quality/run_quality_gate.sh" in runbook,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1411",
        "slice_range": "1402-1411",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s141_platform_production_readiness_closure_failed",
        "closure_readiness": "READY_FOR_S142" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "required_documents": document_presence,
        "summary": {
            "audit_count": len(evidence),
            "passed_audit_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "deferral_count": int(deferral_summary.get("open_deferral_count") or 0),
            "nonproduction_path_count": int(path_summary.get("path_count") or 0),
            "configuration_gap_count": int(config_summary.get("config_gap_count") or 0),
            "operational_gap_count": int(operations_summary.get("gap_count") or 0),
            "transition_requirement_count": int(
                transition_summary.get("requirement_count") or 0
            ),
            "evidence_field_count": int(
                contract_summary.get("evidence_field_count") or 0
            ),
        },
        "decision": {
            "production_deployment_approved": False,
            "production_resources_contacted": False,
            "s140_release_candidate_retained": True,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S142" if passed else "blocked",
            "next_requirement_scope": (
                "reproducible_deployment_packaging_and_environment_topology"
                if passed
                else "blocked"
            ),
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner(root) for name, _, runner in EVIDENCE_RUNNERS}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s141_platform_production_readiness_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s141_platform_production_readiness_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"deferrals={summary.get('deferral_count', 0)} "
        f"paths={summary.get('nonproduction_path_count', 0)} "
        f"config_gaps={summary.get('configuration_gap_count', 0)} "
        f"operations={summary.get('operational_gap_count', 0)} "
        f"requirements={summary.get('transition_requirement_count', 0)} "
        f"fields={summary.get('evidence_field_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s141_platform_production_readiness_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
