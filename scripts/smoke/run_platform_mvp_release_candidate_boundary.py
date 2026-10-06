#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_mvp_release_candidate_boundary.v1"
CANONICAL_DOCUMENT = "docs/47_platform_mvp_release_candidate_acceptance.md"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    path: str
    token: str


REQUIRED_PATHS = (
    "docs/28_generation_e2e_acceptance_contract_test_plan.md",
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/38_platform_mvp_vertical_spine_reaudit.md",
    "docs/40_platform_postgresql_restart_orchestration.md",
    "docs/41_platform_oa_backed_trust_integration.md",
    "docs/42_platform_authenticated_document_ingestion.md",
    "docs/43_platform_permission_filtered_hybrid_retrieval.md",
    "docs/44_platform_grounded_generation_artifact_e2e.md",
    "docs/45_platform_ag_cross_service_trace_operations_e2e.md",
    "docs/46_platform_ae_web_korean_golden_journey.md",
    CANONICAL_DOCUMENT,
    "scripts/smoke/run_platform_postgres_restart_smoke.py",
    "scripts/smoke/run_protected_remote_provider_live_smoke.py",
    "scripts/smoke/run_s139_ae_web_protected_acceptance.py",
    "scripts/quality/run_quality_gate.sh",
    "docs/slices/1392_platform_mvp_release_candidate_boundary.md",
)

TOKENS = (
    EvidenceToken(
        "ten_golden_scenarios",
        "docs/28_generation_e2e_acceptance_contract_test_plan.md",
        "`GEN-E2E-010`",
    ),
    EvidenceToken(
        "s140_scope",
        "docs/37_platform_mvp_integration_release_plan.md",
        "Platform MVP release-candidate acceptance and operations closure",
    ),
    EvidenceToken(
        "restart_runner",
        "scripts/smoke/run_platform_postgres_restart_smoke.py",
        "def run_smoke(",
    ),
    EvidenceToken(
        "three_provider_runner",
        "scripts/smoke/run_protected_remote_provider_live_smoke.py",
        "run_protected_remote_provider_live_smoke",
    ),
    EvidenceToken(
        "browser_runner",
        "scripts/smoke/run_s139_ae_web_protected_acceptance.py",
        "run_s139_ae_web_protected_acceptance",
    ),
    EvidenceToken(
        "s139_handoff",
        "docs/46_platform_ae_web_korean_golden_journey.md",
        "## S140 Handoff",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_mvp_release_candidate_boundary.py",
    ),
)

GAPS = {
    "typed_rc_evidence_gate_matrix": "1393",
    "named_generation_golden_scenarios": "1394",
    "protected_profile_admission": "1395",
    "five_database_restart_acceptance": "1396",
    "live_provider_calibrated_acceptance": "1397",
    "browser_trace_operations_acceptance": "1398",
    "failure_privacy_residue_deferrals": "1399",
    "protected_release_candidate_acceptance": "1400",
}


def run_platform_mvp_release_candidate_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        item.group: item.token in _read_text(root / item.path)
        for item in TOKENS
    }
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    gaps = {name: "OPEN" for name in GAPS}
    scenario_ids = tuple(f"GEN-E2E-{index:03d}" for index in range(1, 11))
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "ten_named_scenarios_frozen": all(
            scenario_id in canonical for scenario_id in scenario_ids
        ),
        "eight_release_gaps_frozen": (
            len(gaps) == 8
            and all(slice_id in canonical for slice_id in GAPS.values())
        ),
        "protected_matrix_dimensions_frozen": all(
            token in canonical
            for token in (
                "all five service-owned test databases",
                "all three live model-provider capabilities",
                "desktop/mobile browser acceptance",
            )
        ),
        "ownership_and_call_boundaries_frozen": all(
            token in canonical
            for token in (
                "CX reaches live providers only through MO capability aliases",
                "AG reads redacted service APIs",
                "Cross-service database reads",
                "browser-supplied ownership",
            )
        ),
        "privacy_and_zero_residue_frozen": all(
            token in canonical
            for token in (
                "zero owned database/file residue",
                "must not retain passwords, tokens, prompts",
                "storage references, provider endpoints, database URLs",
            )
        ),
        "release_candidate_not_production_claim": all(
            token in canonical
            for token in (
                "does not mean production deployment approval",
                "## Deployment Deferrals",
                "external signing-key custody",
                "production object storage",
            )
        ),
        "protected_execution_deferred_to_slice_1400": (
            "Protected execution is deferred to Slice 1400" in canonical
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "token_missing", "group": group}
        for group, present in tokens.items()
        if not present
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1392",
        "requirement": "S140",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "gap_states": gaps,
        "scenario_ids": list(scenario_ids),
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "release_gap_count": len(gaps),
            "open_gap_count": len(gaps),
            "scenario_count": len(scenario_ids),
            "database_count": 5,
            "provider_capability_count": 3,
            "viewport_count": 2,
            "missing_path_count": sum(not value for value in paths.values()),
            "missing_token_count": sum(not value for value in tokens.values()),
        },
        "decision": {
            "new_table_required": False,
            "database_or_provider_execution_performed": False,
            "actual_protected_execution_deferred_to_slice": "1400",
            "production_deployment_approval_claimed": False,
            "next_slice": "1393" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalized_text(path: Path) -> str:
    return " ".join(_read_text(path).split())


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_mvp_release_candidate_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_mvp_release_candidate_boundary=pass "
        f"paths={summary.get('required_path_count', 0)}/{len(REQUIRED_PATHS)} "
        f"tokens={summary.get('evidence_token_count', 0)}/{len(TOKENS)} "
        f"gaps={summary.get('open_gap_count', 0)}/"
        f"{summary.get('release_gap_count', 0)} "
        f"scenarios={summary.get('scenario_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_mvp_release_candidate_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
