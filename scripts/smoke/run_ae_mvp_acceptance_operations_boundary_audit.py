#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_mvp_acceptance_operations_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1091_s109_ae_web_grounded_generation_experience_closure.md",
    "services/nex-ae-api/nex_ae_api/main.py",
    "apps/nex-ae-web/package.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
    "docs/development_process.md",
    "docs/slices/1092_ae_mvp_acceptance_operations_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s109_handoff",
        "scripts/smoke/run_s109_ae_web_grounded_generation_experience_closure.py",
        '"READY_FOR_S110"',
    ),
    EvidenceToken(
        "ae_api_runtime",
        "services/nex-ae-api/nex_ae_api/main.py",
        "register_auth_session_routes(app)",
    ),
    EvidenceToken(
        "ae_web_runtime",
        "apps/nex-ae-web/package.json",
        '"@playwright/test"',
    ),
    EvidenceToken(
        "actual_ae_cx_postgres",
        "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
        'AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"',
    ),
    EvidenceToken(
        "live_provider_path",
        "scripts/smoke/run_ae_web_grounded_generation_playwright_postgres_smoke.py",
        "EXPECTED_MODELS",
    ),
    EvidenceToken(
        "full_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_s109_ae_web_grounded_generation_experience_closure.py",
    ),
    EvidenceToken(
        "tiered_quality",
        "docs/development_process.md",
        "Full Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1092_ae_mvp_acceptance_operations_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "acceptance_policy_missing": "docs/slices/1093_ae_mvp_acceptance_policy.md",
    "evidence_inventory_missing": "docs/slices/1094_ae_mvp_evidence_inventory.md",
    "acceptance_evaluator_missing": "docs/slices/1095_ae_mvp_acceptance_evaluator.md",
    "protected_operations_api_missing": "docs/slices/1096_ae_mvp_acceptance_api.md",
    "acceptance_contract_missing": "docs/slices/1097_ae_mvp_acceptance_contract_hardening.md",
    "operations_handoff_missing": "docs/slices/1098_ae_mvp_operations_handoff.md",
    "protected_acceptance_smoke_missing": "docs/slices/1099_ae_mvp_acceptance_postgres_live_smoke.md",
    "operator_runbook_missing": "docs/slices/1100_ae_mvp_acceptance_operator_runbook.md",
}

GAP_SLICES = {
    name: f"{1093 + index:04d}" for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_ae_mvp_acceptance_operations_boundary_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    closure_evidence = _closure_evidence(root)
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s109_handoff_ready": _group_present(tokens, "s109_handoff"),
        "ae_api_and_web_runtime_present": all(
            _group_present(tokens, group)
            for group in ("ae_api_runtime", "ae_web_runtime")
        ),
        "actual_postgres_and_live_path_reusable": all(
            _group_present(tokens, group)
            for group in ("actual_ae_cx_postgres", "live_provider_path")
        ),
        "tiered_full_gate_reusable": all(
            _group_present(tokens, group)
            for group in ("full_gate", "tiered_quality")
        ),
        "s101_s109_closures_present": all(
            item["runner_present"] and item["document_present"]
            for item in closure_evidence
        ),
        "implementation_gaps_accounted_for": len(gap_states) == 8,
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
    issues.extend(
        {
            "category": "closure_evidence_missing",
            "requirement": item["requirement"],
        }
        for item in closure_evidence
        if not item["runner_present"] or not item["document_present"]
    )
    passed = all(checks.values()) and not issues
    next_slice = next(
        (GAP_SLICES[name] for name, state in gap_states.items() if state == "OPEN"),
        "1101",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1092",
        "requirement": "S110",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "foundation_count": 7,
            "closure_count": len(closure_evidence),
            "gap_count": len(gap_states),
            "open_gap_count": sum(state == "OPEN" for state in gap_states.values()),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "closure_evidence": closure_evidence,
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1092_boundary_audit",
            "1093_acceptance_policy",
            "1094_evidence_inventory",
            "1095_acceptance_evaluator",
            "1096_protected_operations_api",
            "1097_contract_hardening",
            "1098_operations_handoff",
            "1099_postgres_live_playwright_smoke",
            "1100_operator_runbook",
            "1101_s110_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "acceptance_scope": "nex_ae_service_mvp",
        "services": ["nex-ae-api", "nex-ae-web"],
        "product_wide_release_approval": False,
        "production_deployment_certification": False,
        "server_derived_evidence_required": True,
        "all_blocking_gates_must_pass": True,
        "skipped_required_gate_allowed": False,
        "raw_evidence_in_projection": False,
        "actual_databases_required": ["nex_ae_test", "nex_cx_test"],
        "playwright_required_slice": "1099",
        "live_provider_required_slice": "1099",
        "provider_models": [
            "Qwen3-Embedding-4B",
            "Qwen3-Reranker-4B",
            "Qwen3.5-4B",
        ],
        "new_tables_expected": 0,
        "advisory_deferrals": [
            "production_identity_provider_activation",
            "object_storage_activation",
            "distributed_load_certification",
            "disaster_recovery_certification",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1096",
            "full_gate": "1101",
        },
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "ae_mvp_acceptance_operations_boundary="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"closures={summary.get('closure_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={result.get('next_slice', 'unknown')}"
    )


def _closure_evidence(root: Path) -> list[dict[str, Any]]:
    evidence = []
    for number in range(101, 110):
        runners = list((root / "scripts/smoke").glob(f"run_s{number}_*_closure.py"))
        documents = list((root / "docs/slices").glob(f"*s{number}_*closure.md"))
        evidence.append(
            {
                "requirement": f"S{number}",
                "runner_present": len(runners) == 1,
                "document_present": len(documents) == 1,
            }
        )
    return evidence


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _group_present(tokens: list[dict[str, Any]], group: str) -> bool:
    return any(item["group"] == group and item["present"] for item in tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_mvp_acceptance_operations_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
