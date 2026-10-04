#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from run_platform_ae_artifact_ag_audit_path_audit import (
    run_platform_ae_artifact_ag_audit_path_audit,
)
from run_platform_ae_cx_integration_path_audit import (
    run_platform_ae_cx_integration_path_audit,
)
from run_platform_contract_trace_privacy_e2e_gap_audit import (
    run_platform_contract_trace_privacy_e2e_gap_audit,
)
from run_platform_cx_mo_provider_path_audit import (
    run_platform_cx_mo_provider_path_audit,
)
from run_platform_oa_ae_trust_path_audit import (
    run_platform_oa_ae_trust_path_audit,
)
from run_platform_persistence_worker_process_audit import (
    run_platform_persistence_worker_process_audit,
)
from run_platform_route_client_topology_inventory import (
    run_platform_route_client_topology_inventory,
)
from run_platform_runtime_profile_residue_audit import (
    run_platform_runtime_profile_residue_audit,
)
from run_platform_vertical_spine_reaudit_boundary import (
    run_platform_vertical_spine_reaudit_boundary,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s131_platform_vertical_spine_reaudit_closure.v1"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s131_platform_vertical_spine_reaudit_closure.py"
AuditRunner = Callable[[Path], dict[str, Any]]
AUDIT_RUNNERS: tuple[tuple[str, AuditRunner], ...] = (
    ("boundary", run_platform_vertical_spine_reaudit_boundary),
    ("topology", run_platform_route_client_topology_inventory),
    ("profiles", run_platform_runtime_profile_residue_audit),
    ("oa_ae_trust", run_platform_oa_ae_trust_path_audit),
    ("ae_cx", run_platform_ae_cx_integration_path_audit),
    ("cx_mo", run_platform_cx_mo_provider_path_audit),
    ("ae_ag", run_platform_ae_artifact_ag_audit_path_audit),
    ("persistence_process", run_platform_persistence_worker_process_audit),
    ("contract_trace_privacy_e2e", run_platform_contract_trace_privacy_e2e_gap_audit),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1302", "platform_vertical_spine_reaudit_boundary"),
        ("1303", "platform_route_client_topology_inventory"),
        ("1304", "platform_runtime_profile_residue_audit"),
        ("1305", "platform_oa_ae_trust_path_audit"),
        ("1306", "platform_ae_cx_integration_path_audit"),
        ("1307", "platform_cx_mo_provider_path_audit"),
        ("1308", "platform_ae_artifact_ag_audit_path_audit"),
        ("1309", "platform_persistence_worker_process_audit"),
        ("1310", "platform_contract_trace_privacy_e2e_gap_audit"),
        ("1311", "s131_platform_vertical_spine_reaudit_closure"),
    )
)


def run_s131_platform_vertical_spine_reaudit_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    audits = {name: runner(root) for name, runner in AUDIT_RUNNERS}
    required_documents = (
        *SLICE_DOCUMENTS,
        "docs/37_platform_mvp_integration_release_plan.md",
        "docs/38_platform_mvp_vertical_spine_reaudit.md",
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    topology = _mapping(audits.get("topology"))
    profiles = _mapping(audits.get("profiles"))
    trust = _mapping(audits.get("oa_ae_trust"))
    ae_cx = _mapping(audits.get("ae_cx"))
    cx_mo = _mapping(audits.get("cx_mo"))
    ae_ag = _mapping(audits.get("ae_ag"))
    persistence = _mapping(audits.get("persistence_process"))
    e2e = _mapping(audits.get("contract_trace_privacy_e2e"))
    checks = {
        "all_nine_audits_passed": all(
            evidence.get("status") == "PASS" for evidence in audits.values()
        ),
        "all_slice_and_canonical_documents_present": all(document_presence.values()),
        "closure_registered_once_in_full_gate": quality_gate.count(CLOSURE_RUNNER) == 1,
        "service_api_topology_inventory_complete": (
            _finding(topology, "http_edge_count") == 11
            and _finding(topology, "logical_edge_count") == 7
        ),
        "cross_database_debt_is_explicit": (
            _finding(topology, "ag_cross_service_database_coupling_count") == 4
            and topology.get("decision", {}).get("cross_service_database_reads_allowed")
            is False
        ),
        "runtime_profile_gap_is_explicit": (
            _finding(profiles, "canonical_runtime_profile_manifest_present") is False
            and profiles.get("decision", {}).get("current_runner_is_release_topology")
            is False
        ),
        "protected_trust_and_owner_gaps_are_explicit": (
            _finding(trust, "default_ae_auth_session_mode") == "mock"
            and _finding(ae_cx, "local_owner_fallback_present") is True
        ),
        "provider_timeout_gap_is_explicit": (
            _finding(cx_mo, "timeout_budget_safe") is False
        ),
        "ag_owner_projection_gap_is_explicit": (
            _finding(ae_ag, "ag_generation_client_is_cx_owner_compatible") is False
        ),
        "process_and_e2e_gaps_are_explicit": (
            all(
                _finding(persistence, "process_orchestration_gaps", {}).values()
            )
            and _finding(e2e, "executable_named_golden_scenario_count") == 0
        ),
        "s132_handoff_is_frozen": all(
            token in _read_text(root / "docs/38_platform_mvp_vertical_spine_reaudit.md")
            for token in ("## S132 Handoff", "S131-GAP-01", "S131-GAP-12")
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1311",
        "slice_range": "1302-1311",
        "requirement": "S131",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s131_platform_vertical_spine_reaudit_closure_failed",
        "closure_readiness": "READY_FOR_S132" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "audit_statuses": {
            name: evidence.get("status") for name, evidence in audits.items()
        },
        "required_documents": document_presence,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                evidence.get("status") == "PASS" for evidence in audits.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "http_edge_count": int(_finding(topology, "http_edge_count", 0)),
            "migration_count": int(_finding(persistence, "migration_total", 0)),
            "trace_client_count": int(
                _finding(e2e, "trace_propagating_http_client_count", 0)
            ),
            "p0_gap_count": 8,
            "p1_gap_count": 4,
            "named_e2e_count": int(
                _finding(e2e, "executable_named_golden_scenario_count", 0)
            ),
        },
        "decision": {
            "service_ownership_model_retained": True,
            "service_merge_required": False,
            "shared_database_required": False,
            "current_vertical_spine_is_release_accepted": False,
            "database_or_provider_mutation_performed": False,
            "next_requirement": "S132" if passed else "blocked",
            "next_requirement_scope": (
                "platform_multi_service_runtime_topology_and_configuration_hardening"
                if passed
                else "blocked"
            ),
        },
    }


def _finding(
    evidence: Mapping[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    findings = evidence.get("findings")
    return findings.get(key, default) if isinstance(findings, Mapping) else default


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "s131_platform_vertical_spine_reaudit_closure=fail "
            f"checks={len(evidence.get('failed_checks') or [])}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s131_platform_vertical_spine_reaudit_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"edges={summary.get('http_edge_count', 0)} "
        f"migrations={summary.get('migration_count', 0)} "
        f"named_e2e={summary.get('named_e2e_count', 0)}/10 "
        f"next={evidence.get('decision', {}).get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s131_platform_vertical_spine_reaudit_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
