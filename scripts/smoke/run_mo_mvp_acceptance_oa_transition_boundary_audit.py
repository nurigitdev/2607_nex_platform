#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "mo_mvp_acceptance_oa_transition_boundary_audit.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/slices/1191_s119_mo_operations_integration_acceptance_closure.md",
    "services/nex-mo/nex_mo/main.py",
    "contracts/openapi/nex-mo.openapi.yaml",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_mo_operations_postgres_smoke.py",
    "scripts/smoke/run_mo_operations_live_acceptance.py",
    "docs/development_process.md",
    "docs/slices/1192_mo_mvp_acceptance_oa_transition_boundary_audit.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "s119_handoff",
        "scripts/smoke/run_s119_mo_operations_integration_acceptance_closure.py",
        '"READY_FOR_S120"',
    ),
    EvidenceToken(
        "mo_runtime",
        "services/nex-mo/nex_mo/main.py",
        "register_operations_routes(app, service=MO_OPERATIONS)",
    ),
    EvidenceToken(
        "actual_mo_postgres",
        "scripts/smoke/run_mo_operations_postgres_smoke.py",
        'DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"',
    ),
    EvidenceToken(
        "live_provider_path",
        "scripts/smoke/run_mo_operations_live_acceptance.py",
        "PROTECTED_ENV_KEYS = (",
    ),
    EvidenceToken(
        "full_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_s119_mo_operations_integration_acceptance_closure.py",
    ),
    EvidenceToken(
        "tiered_quality",
        "docs/development_process.md",
        "Full Gate",
    ),
    EvidenceToken(
        "oa_requirement_partition",
        "docs/30_service_specific_requirement_partition.md",
        "OA-FR-001",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1192_mo_mvp_acceptance_oa_transition_boundary_audit.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "acceptance_policy_missing": "docs/slices/1193_mo_mvp_acceptance_policy.md",
    "evidence_inventory_missing": "docs/slices/1194_mo_mvp_evidence_inventory.md",
    "acceptance_evaluator_missing": "docs/slices/1195_mo_mvp_acceptance_evaluator.md",
    "protected_operations_api_missing": "docs/slices/1196_mo_mvp_acceptance_api.md",
    "acceptance_contract_missing": "docs/slices/1197_mo_mvp_acceptance_contract_hardening.md",
    "oa_transition_handoff_missing": "docs/slices/1198_mo_oa_transition_handoff.md",
    "protected_acceptance_smoke_missing": "docs/slices/1199_mo_mvp_acceptance_postgres_live_smoke.md",
    "operator_runbook_missing": "docs/slices/1200_mo_mvp_acceptance_operator_runbook.md",
}

GAP_SLICES = {
    name: f"{1193 + index:04d}" for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_mo_mvp_acceptance_oa_transition_boundary_audit(
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
        "s119_handoff_ready": _group_present(tokens, "s119_handoff"),
        "mo_runtime_present": _group_present(tokens, "mo_runtime"),
        "actual_postgres_and_live_paths_reusable": all(
            _group_present(tokens, group)
            for group in ("actual_mo_postgres", "live_provider_path")
        ),
        "tiered_full_gate_reusable": all(
            _group_present(tokens, group)
            for group in ("full_gate", "tiered_quality")
        ),
        "oa_transition_target_traceable": _group_present(
            tokens, "oa_requirement_partition"
        ),
        "s111_s119_closures_present": all(
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
        "1201",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1192",
        "requirement": "S120",
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
            "1192_boundary_audit",
            "1193_acceptance_policy",
            "1194_evidence_inventory",
            "1195_acceptance_evaluator",
            "1196_protected_operations_api_checkpoint",
            "1197_contract_hardening",
            "1198_oa_transition_handoff",
            "1199_postgres_live_smoke",
            "1200_operator_runbook",
            "1201_s120_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "acceptance_scope": "nex_mo_service_mvp",
        "service_id": "nex-mo",
        "transition_target": "nex-oa",
        "product_wide_release_approval": False,
        "production_deployment_certification": False,
        "server_derived_evidence_required": True,
        "all_blocking_gates_must_pass": True,
        "skipped_required_gate_allowed": False,
        "raw_evidence_in_projection": False,
        "actual_databases_required": ["nex_mo_test"],
        "live_provider_required_slice": "1199",
        "provider_models": [
            "Qwen3-Embedding-4B",
            "Qwen3-Reranker-4B",
            "Qwen3.5-4B",
        ],
        "new_tables_expected": 0,
        "advisory_deferrals": [
            "production_identity_provider_activation",
            "external_metrics_backend_activation",
            "distributed_load_certification",
            "disaster_recovery_certification",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1196",
            "full_gate": "1201",
        },
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "mo_mvp_acceptance_oa_transition_boundary="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"closures={summary.get('closure_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={result.get('next_slice', 'unknown')}"
    )


def _closure_evidence(root: Path) -> list[dict[str, Any]]:
    evidence = []
    for number in range(111, 120):
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
    result = run_mo_mvp_acceptance_oa_transition_boundary_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
