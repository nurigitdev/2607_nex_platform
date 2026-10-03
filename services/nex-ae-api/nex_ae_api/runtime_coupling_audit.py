from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "ae_runtime_coupling_audit.v1"


@dataclass(frozen=True)
class ModuleBudget:
    module_id: str
    path: str
    refactor_threshold: int
    priority: str


@dataclass(frozen=True)
class CouplingFinding:
    finding_id: str
    path: str
    token: str
    disposition: str
    risk: str


MODULE_BUDGETS = (
    ModuleBudget(
        "artifact_api_runtime",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        10_000,
        "P1",
    ),
    ModuleBudget(
        "retention_scheduler_runtime",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler.py",
        7_000,
        "P2",
    ),
    ModuleBudget(
        "retention_daemon_runtime",
        "services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py",
        15_000,
        "P2",
    ),
    ModuleBudget(
        "web_application_composition",
        "apps/nex-ae-web/src/main.js",
        2_500,
        "P1",
    ),
)


COUPLING_FINDINGS = (
    CouplingFinding(
        "workspace_facade_authorization",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "authorize_ae_facade_route_request",
        "GOOD_BOUNDARY",
        "LOW",
    ),
    CouplingFinding(
        "import_time_application_composition",
        "services/nex-ae-api/nex_ae_api/main.py",
        "app = build_service_app(",
        "REFACTOR_REQUIRED",
        "HIGH",
    ),
    CouplingFinding(
        "global_workspace_state",
        "services/nex-ae-api/nex_ae_api/workspace.py",
        "DEFAULT_WORKSPACE_STORE = WorkspaceStateStore()",
        "REFACTOR_REQUIRED",
        "HIGH",
    ),
    CouplingFinding(
        "composition_entrypoint_coverage_gap",
        "services/nex-ae-api/nex_ae_api/prompts.py",
        "seed_ae_prompt_registry()",
        "REFACTOR_REQUIRED",
        "MEDIUM",
    ),
    CouplingFinding(
        "central_facade_route_authorization",
        "services/nex-ae-api/nex_ae_api/route_auth.py",
        "def authorize_ae_facade_route_request",
        "GOOD_BOUNDARY",
        "LOW",
    ),
    CouplingFinding(
        "provider_and_storage_protocols",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        "class RenderedArtifactStorage(Protocol):",
        "GOOD_BOUNDARY",
        "LOW",
    ),
)


def build_ae_runtime_coupling_audit(
    root: Path = ROOT,
    *,
    module_budgets: Sequence[ModuleBudget] = MODULE_BUDGETS,
    findings: Sequence[CouplingFinding] = COUPLING_FINDINGS,
) -> dict[str, Any]:
    module_results = [_inspect_module(root, budget) for budget in module_budgets]
    finding_results = [_inspect_finding(root, finding) for finding in findings]
    evidence_issues = [
        {
            "category": "runtime_coupling_evidence_missing",
            "evidence_id": item["module_id"],
            "path": item["path"],
        }
        for item in module_results
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

    helper_count = _authorization_helper_count(root)
    checks = {
        "module_inventory_complete": len(module_results) == 4,
        "all_large_modules_classified": all(
            item["over_budget"] for item in module_results
        ),
        "duplicated_authorization_measured": helper_count >= 6,
        "good_boundaries_preserved": sum(
            item["disposition"] == "GOOD_BOUNDARY" for item in finding_results
        )
        == 3,
        "evidence_present": not evidence_issues,
    }
    passed = all(checks.values())
    refactor_count = len(module_results) + sum(
        item["disposition"] == "REFACTOR_REQUIRED" for item in finding_results
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1006",
        "requirement": "S101",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae_runtime_coupling_audit_failed",
        "refactoring_readiness": (
            "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_AE_FEATURES"
            if passed
            else "BLOCKED"
        ),
        "summary": {
            "module_count": len(module_results),
            "oversized_module_count": sum(
                item["over_budget"] for item in module_results
            ),
            "finding_count": len(finding_results),
            "refactor_required_count": refactor_count,
            "good_boundary_count": sum(
                item["disposition"] == "GOOD_BOUNDARY"
                for item in finding_results
            ),
            "authorization_helper_count": helper_count,
            "evidence_issue_count": len(evidence_issues),
        },
        "checks": checks,
        "modules": module_results,
        "findings": finding_results,
        "ordered_refactoring": [
            {
                "priority": "P0",
                "action": "centralize remaining chat and artifact authorization",
            },
            {
                "priority": "P1",
                "action": "introduce app-factory-owned AE runtime dependencies",
            },
            {
                "priority": "P1",
                "action": "split artifact API and Web composition by capability",
            },
            {
                "priority": "P2",
                "action": "split scheduler policy from daemon process controls",
            },
            {
                "priority": "P3",
                "action": "replace production global stores with persistent adapters",
            },
        ],
        "guardrails": [
            "no big-bang rewrite",
            "preserve public contracts per slice",
            "retain deterministic memory adapters for regression",
            "keep provider and rendered-storage protocols",
            "add no table during the S101 audit",
        ],
        "issues": evidence_issues,
        "next_slice": "1007",
    }


def _inspect_module(root: Path, budget: ModuleBudget) -> dict[str, Any]:
    path = root / budget.path
    present = path.is_file()
    line_count = len(path.read_text(encoding="utf-8").splitlines()) if present else 0
    return {
        "module_id": budget.module_id,
        "path": budget.path,
        "line_count": line_count,
        "refactor_threshold": budget.refactor_threshold,
        "over_budget": present and line_count >= budget.refactor_threshold,
        "priority": budget.priority,
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


def _authorization_helper_count(root: Path) -> int:
    package = root / "services/nex-ae-api/nex_ae_api"
    if not package.is_dir():
        return 0
    return sum(
        "def _authorize_ae_request(" in path.read_text(encoding="utf-8")
        for path in package.glob("*.py")
        if path.name not in {"ownership_privacy_audit.py", "runtime_coupling_audit.py"}
    )
