#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_production_readiness_boundary.v1"
CANONICAL_PLAN = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    path: str
    token: str


REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/47_platform_mvp_release_candidate_acceptance.md",
    "docs/48_platform_production_readiness_plan.md",
    "docs/slices/1401_s140_platform_release_candidate_closure.md",
    "docs/slices/1402_platform_production_readiness_boundary.md",
    "services/_shared/nex_runtime/runtime_profiles.py",
    "services/_shared/nex_runtime/release_candidate_assurance.py",
    "scripts/quality/run_quality_gate.sh",
)

TOKENS = (
    EvidenceToken(
        "s140_complete",
        "docs/47_platform_mvp_release_candidate_acceptance.md",
        "Status: S140 complete through Slice 1401",
    ),
    EvidenceToken(
        "production_unapproved",
        "docs/47_platform_mvp_release_candidate_acceptance.md",
        "Production\ndeployment is not approved.",
    ),
    EvidenceToken(
        "nine_deferrals",
        "services/_shared/nex_runtime/release_candidate_assurance.py",
        "DEPLOYMENT_DEFERRALS",
    ),
    EvidenceToken(
        "production_profile",
        "services/_shared/nex_runtime/runtime_profiles.py",
        '"production": RuntimeModes("postgres", "live", "signed", "api")',
    ),
    EvidenceToken(
        "s141_sequence",
        CANONICAL_PLAN,
        "| `S141` | Platform production-readiness re-audit",
    ),
    EvidenceToken(
        "s150_sequence",
        CANONICAL_PLAN,
        "| `S150` | Production release-candidate and go-live readiness closure",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_production_readiness_boundary.py",
    ),
)

DEFERRALS = (
    "external_signing_key_custody",
    "managed_tls_certificate_lifecycle",
    "production_secret_injection_rotation",
    "enterprise_idp_registration",
    "production_object_storage_lifecycle",
    "production_postgresql_backup_ha_dr",
    "external_notification_incident_endpoints",
    "production_gpu_scheduling_capacity",
    "production_monitoring_paging_slo_approval",
)

AUDIT_SURFACES = (
    "production_deferral_traceability",
    "mock_test_local_only_execution_paths",
    "environment_configuration_and_secrets",
    "direct_runtime_and_deployment_coupling",
    "service_and_platform_responsibility",
    "operational_lifecycle_incompleteness",
    "dependency_ordered_transition_plan",
    "production_evidence_privacy_and_rollback",
)


def run_platform_production_readiness_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        item.group: item.token in _read_text(root / item.path) for item in TOKENS
    }
    plan = _normalized_text(root / CANONICAL_PLAN)
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "nine_production_deferrals_frozen": (
            len(DEFERRALS) == 9
            and all(target in plan for target in ("`S143`", "`S144`", "`S145`", "`S146`", "`S147`", "`S148`", "`S150`"))
        ),
        "nine_audit_slices_frozen": all(
            f"`{slice_id}`" in plan for slice_id in range(1402, 1411)
        ),
        "closure_slice_frozen": "`1411`" in plan and "Full Gate" in plan,
        "production_approval_remains_false": all(
            token in plan
            for token in (
                "production deployment remains unapproved",
                "performs no production deployment",
            )
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
        "slice": "1402",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "deferral_ids": list(DEFERRALS),
        "audit_surfaces": list(AUDIT_SURFACES),
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "deferral_count": len(DEFERRALS),
            "audit_count": len(AUDIT_SURFACES) + 1,
            "missing_path_count": sum(not value for value in paths.values()),
            "missing_token_count": sum(not value for value in tokens.values()),
        },
        "decision": {
            "repository_state_is_primary_evidence": True,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1403" if passed else "blocked",
            "next_requirement_after_closure": "S142",
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
            "platform_production_readiness_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_readiness_boundary=pass "
        f"paths={summary.get('required_path_count', 0)}/{len(REQUIRED_PATHS)} "
        f"tokens={summary.get('evidence_token_count', 0)}/{len(TOKENS)} "
        f"deferrals={summary.get('deferral_count', 0)} "
        f"audits={summary.get('audit_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_readiness_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
