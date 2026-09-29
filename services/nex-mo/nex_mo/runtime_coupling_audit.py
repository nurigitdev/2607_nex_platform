from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ModuleBudget:
    module_id: str
    path: str
    refactor_threshold: int
    priority: str
    supporting_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CouplingFinding:
    finding_id: str
    path: str
    token: str
    disposition: str
    risk: str


MODULE_BUDGETS = (
    ModuleBudget(
        "provider_registry_api_runtime",
        "services/nex-mo/nex_mo/providers.py",
        700,
        "P1",
        (
            "services/nex-mo/nex_mo/provider_catalog.py",
            "services/nex-mo/nex_mo/provider_projection.py",
            "services/nex-mo/nex_mo/provider_registry.py",
        ),
    ),
    ModuleBudget(
        "remote_transport_normalization_telemetry_runtime",
        "services/nex-mo/nex_mo/remote_provider.py",
        1_200,
        "P1",
        (
            "services/nex-mo/nex_mo/provider_normalization.py",
            "services/nex-mo/nex_mo/provider_telemetry.py",
            "services/nex-mo/nex_mo/provider_transport.py",
        ),
    ),
)

COUPLING_FINDINGS = (
    CouplingFinding(
        "providers_dynamic_remote_import",
        "services/nex-mo/nex_mo/providers.py",
        "from nex_mo.remote_provider import execute_remote_embedding_request",
        "REFACTOR_REQUIRED",
        "MEDIUM",
    ),
    CouplingFinding(
        "remote_static_provider_import",
        "services/nex-mo/nex_mo/remote_provider.py",
        "from nex_mo.provider_registry import (",
        "REFACTOR_REQUIRED",
        "MEDIUM",
    ),
    CouplingFinding(
        "process_local_telemetry_state",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "_TELEMETRY_BUCKETS = DEFAULT_TELEMETRY_STORE._buckets",
        "REFACTOR_REQUIRED",
        "MEDIUM",
    ),
    CouplingFinding(
        "immutable_provider_route_value",
        "services/nex-mo/nex_mo/provider_registry.py",
        "class ProviderRoute:",
        "GOOD_BOUNDARY",
        "LOW",
    ),
    CouplingFinding(
        "immutable_execution_config_value",
        "services/nex-mo/nex_mo/remote_provider.py",
        "class RemoteProviderExecutionConfig:",
        "GOOD_BOUNDARY",
        "LOW",
    ),
    CouplingFinding(
        "central_failure_taxonomy",
        "services/nex-mo/nex_mo/provider_transport.py",
        "def classify_remote_provider_exception",
        "GOOD_BOUNDARY",
        "LOW",
    ),
    CouplingFinding(
        "provider_requester_injection",
        "services/nex-mo/nex_mo/remote_provider.py",
        "requester: HttpRequester | None",
        "GOOD_BOUNDARY",
        "LOW",
    ),
)


def build_mo_runtime_coupling_audit(
    root: Path = ROOT,
    *,
    module_budgets: Sequence[ModuleBudget] = MODULE_BUDGETS,
    findings: Sequence[CouplingFinding] = COUPLING_FINDINGS,
) -> dict[str, Any]:
    modules = [_inspect_module(root, budget) for budget in module_budgets]
    finding_results = [_inspect_finding(root, finding) for finding in findings]
    evidence_issues = [
        {
            "category": "runtime_coupling_evidence_missing",
            "evidence_id": item["module_id"],
            "path": item["path"],
        }
        for item in modules
        if not item["evidence_present"]
    ]
    evidence_issues.extend(
        {
            "category": "runtime_coupling_evidence_missing",
            "evidence_id": item["finding_id"],
            "path": item["path"],
        }
        for item in finding_results
        if not item["evidence_present"]
    )
    checks = {
        "module_inventory_complete": len(modules) == 2,
        "oversized_modules_classified": all(item["over_budget"] for item in modules),
        "bidirectional_coupling_classified": all(
            any(item["finding_id"] == finding_id for item in finding_results)
            for finding_id in (
                "providers_dynamic_remote_import",
                "remote_static_provider_import",
            )
        ),
        "good_boundaries_preserved": sum(
            item["disposition"] == "GOOD_BOUNDARY" for item in finding_results
        )
        == 4,
        "evidence_present": not evidence_issues,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_coupling_audit.v1",
        "slice": "1105",
        "requirement": "S111",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_coupling_audit_failed",
        "refactoring_readiness": (
            "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_MO_FEATURES"
            if passed
            else "BLOCKED"
        ),
        "checks": checks,
        "summary": {
            "module_count": len(modules),
            "oversized_module_count": sum(item["over_budget"] for item in modules),
            "finding_count": len(finding_results),
            "refactor_required_count": len(modules)
            + sum(
                item["disposition"] == "REFACTOR_REQUIRED"
                for item in finding_results
            ),
            "good_boundary_count": sum(
                item["disposition"] == "GOOD_BOUNDARY"
                for item in finding_results
            ),
            "evidence_issue_count": len(evidence_issues),
        },
        "modules": modules,
        "findings": finding_results,
        "ordered_refactoring": [
            {
                "priority": "P0",
                "action": "separate privacy-safe public provider profile projection",
                "slice": "1106",
            },
            {
                "priority": "P1",
                "action": "extract catalog and environment validation from API routes",
                "slice": "S112",
            },
            {
                "priority": "P1",
                "action": "split remote transport payload normalization and telemetry modules",
                "slice": "S112",
            },
            {
                "priority": "P2",
                "action": "replace process-local telemetry with an explicit adapter boundary",
                "slice": "S112",
            },
        ],
        "guardrails": [
            "no big-bang rewrite",
            "preserve stable CX-facing provider APIs per slice",
            "retain deterministic mock and requester injection",
            "keep raw endpoints credentials and model paths private",
            "add no table during the S111 audit",
        ],
        "issues": evidence_issues,
        "next_slice": "1106",
    }


def _inspect_module(root: Path, budget: ModuleBudget) -> dict[str, Any]:
    path = root / budget.path
    supporting = [root / item for item in budget.supporting_paths]
    present = path.is_file() and all(item.is_file() for item in supporting)
    paths = [path, *supporting]
    line_count = sum(
        len(item.read_text(encoding="utf-8").splitlines())
        for item in paths
        if item.is_file()
    )
    return {
        "module_id": budget.module_id,
        "path": budget.path,
        "line_count": line_count,
        "refactor_threshold": budget.refactor_threshold,
        "over_budget": present and line_count >= budget.refactor_threshold,
        "priority": budget.priority,
        "supporting_paths": list(budget.supporting_paths),
        "evidence_present": present,
    }


def _inspect_finding(root: Path, finding: CouplingFinding) -> dict[str, Any]:
    path = root / finding.path
    present = path.is_file() and finding.token in path.read_text(encoding="utf-8")
    return {
        "finding_id": finding.finding_id,
        "path": finding.path,
        "disposition": finding.disposition,
        "risk": finding.risk,
        "evidence_present": present,
    }
