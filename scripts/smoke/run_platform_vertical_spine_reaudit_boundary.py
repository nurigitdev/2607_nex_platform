#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_vertical_spine_reaudit_boundary.v1"
SLICE_ID = "1302"
REQUIREMENT = "S131"
BOUNDARY = "platform_mvp_vertical_spine_current_state_reaudit"
INVENTORY_EXCLUDED_NAMES = frozenset(
    {
        "run_platform_vertical_spine_reaudit_boundary.py",
        "test_platform_vertical_spine_reaudit_boundary.py",
    }
)


@dataclass(frozen=True)
class RequiredPath:
    name: str
    relative_path: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    RequiredPath(
        "s130_closure",
        "scripts/smoke/run_s130_oa_mvp_platform_trust_closure.py",
    ),
    RequiredPath("oa_runtime", "services/nex-oa/nex_oa/main.py"),
    RequiredPath("ae_web_runtime", "apps/nex-ae-web/src/main.js"),
    RequiredPath("ae_api_runtime", "services/nex-ae-api/nex_ae_api/main.py"),
    RequiredPath("cx_runtime", "services/nex-cx/nex_cx/main.py"),
    RequiredPath("mo_runtime", "services/nex-mo/nex_mo/main.py"),
    RequiredPath("ag_runtime", "services/nex-ag/nex_ag/main.py"),
    RequiredPath("service_runner", "scripts/dev/run_all_services.py"),
    RequiredPath("mvp_srs", "docs/29_nex_platform_mvp_srs_v0_1_assembly.md"),
    RequiredPath(
        "e2e_plan",
        "docs/28_generation_e2e_acceptance_contract_test_plan.md",
    ),
    RequiredPath(
        "integration_plan",
        "docs/37_platform_mvp_integration_release_plan.md",
    ),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/1302_platform_vertical_spine_reaudit_boundary.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s130_handoff",
        "scripts/smoke/run_s130_oa_mvp_platform_trust_closure.py",
        '"next_requirement": "S131"',
    ),
    TokenRequirement(
        "oa_entry",
        "services/nex-oa/nex_oa/main.py",
        "register_user_login_routes(",
    ),
    TokenRequirement(
        "ae_web_entry",
        "apps/nex-ae-web/src/main.js",
        "bootstrapAuthenticatedSessionRuntime",
    ),
    TokenRequirement(
        "ae_api_entry",
        "services/nex-ae-api/nex_ae_api/main.py",
        "register_upload_routes(app)",
    ),
    TokenRequirement(
        "cx_entry",
        "services/nex-cx/nex_cx/main.py",
        "register_retrieval_routes(",
    ),
    TokenRequirement(
        "mo_entry",
        "services/nex-mo/nex_mo/main.py",
        "register_mock_provider_routes(app)",
    ),
    TokenRequirement(
        "ag_entry",
        "services/nex-ag/nex_ag/main.py",
        "register_generation_audit_routes(app)",
    ),
    TokenRequirement(
        "service_runner",
        "scripts/dev/run_all_services.py",
        'SERVICES = ["nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"]',
    ),
    TokenRequirement(
        "vertical_acceptance",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "## 6. MVP Vertical Acceptance",
    ),
    TokenRequirement(
        "golden_scenarios",
        "docs/28_generation_e2e_acceptance_contract_test_plan.md",
        "GEN-E2E-010",
    ),
    TokenRequirement(
        "frozen_sequence",
        "docs/37_platform_mvp_integration_release_plan.md",
        "| `S140` |",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_vertical_spine_reaudit_boundary.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "1302_platform_vertical_spine_reaudit_boundary.md",
    ),
)


def run_platform_vertical_spine_reaudit_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": (root / item.relative_path).is_file(),
        }
        for item in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in TOKEN_REQUIREMENTS
    ]
    executable_e2e_ids = _executable_golden_scenario_ids(root)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s130_handoff_ready": _group_present(tokens, "s130_handoff"),
        "five_service_and_web_entries_present": all(
            _group_present(tokens, group)
            for group in (
                "oa_entry",
                "ae_web_entry",
                "ae_api_entry",
                "cx_entry",
                "mo_entry",
                "ag_entry",
            )
        ),
        "requirements_and_golden_scenarios_frozen": all(
            _group_present(tokens, group)
            for group in (
                "vertical_acceptance",
                "golden_scenarios",
                "frozen_sequence",
            )
        ),
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "source_token_missing",
            "path": item["path"],
            "group": item["group"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "platform_vertical_spine_reaudit_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "platform_integration",
            "audit_scope": "oa_to_ae_web_api_to_cx_to_mo_to_ag",
            "repository_state_is_primary_evidence": True,
            "refactor_before_feature_when_needed": True,
            "cross_service_http_api_only": True,
            "shared_database_reads_allowed": False,
            "actual_test_database_evidence_required": False,
            "protected_live_provider_evidence_required": False,
            "new_table_required": False,
            "existing_service_records_mutated": False,
            "next_requirement": "S132",
            "decision_status": "FROZEN",
        },
        "baseline_findings": {
            "backend_service_shell_count": 5,
            "ae_web_shell_present": True,
            "service_runner_present": _group_present(tokens, "service_runner"),
            "golden_scenario_contract_count": 10,
            "executable_named_golden_scenario_count": len(executable_e2e_ids),
            "executable_named_golden_scenario_ids": executable_e2e_ids,
            "runtime_topology_hardening_required": True,
            "integrated_vertical_acceptance_required": True,
        },
        "audit_surfaces": [
            "cross_service_route_and_client_topology",
            "runtime_profiles_mock_residue_and_direct_calls",
            "oa_to_ae_user_and_service_trust",
            "ae_to_cx_content_retrieval_and_generation",
            "cx_to_mo_provider_alias_execution",
            "ae_artifact_and_ag_audit_handoffs",
            "persistence_jobs_restart_and_process_orchestration",
            "contracts_trace_privacy_and_gen_e2e_gaps",
        ],
        "slice_plan": [
            "1302_boundary_and_scope_freeze",
            "1303_route_client_topology_inventory",
            "1304_runtime_profile_mock_direct_call_audit",
            "1305_oa_ae_trust_path_audit",
            "1306_ae_cx_path_audit_checkpoint",
            "1307_cx_mo_provider_path_audit",
            "1308_ae_artifact_ag_audit_handoff",
            "1309_persistence_job_restart_orchestration",
            "1310_contract_trace_privacy_e2e_gap",
            "1311_s131_closure_s132_handoff",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1306",
            "full_gate": "1311",
        },
        "required_paths": paths,
        "required_tokens": tokens,
        "checks": checks,
        "issues": issues,
    }


def _executable_golden_scenario_ids(root: Path) -> list[str]:
    found: set[str] = set()
    for directory in (root / "tests", root / "scripts"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".mjs"}:
                continue
            if path.name in INVENTORY_EXCLUDED_NAMES:
                continue
            text = _read_text(path)
            for index in range(1, 11):
                scenario_id = f"GEN-E2E-{index:03d}"
                if scenario_id in text:
                    found.add(scenario_id)
    return sorted(found)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    matching = [item for item in items if item["group"] == group]
    return bool(matching) and all(item["present"] for item in matching)


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_vertical_spine_reaudit_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    findings = evidence.get("baseline_findings") or {}
    return (
        "platform_vertical_spine_reaudit_boundary=pass "
        f"scope={decision.get('audit_scope')} "
        f"services={findings.get('backend_service_shell_count', 0)}+web "
        f"named_e2e={findings.get('executable_named_golden_scenario_count', 0)}/10 "
        f"postgres_required={decision.get('actual_test_database_evidence_required')} "
        f"live_required={decision.get('protected_live_provider_evidence_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_vertical_spine_reaudit_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
