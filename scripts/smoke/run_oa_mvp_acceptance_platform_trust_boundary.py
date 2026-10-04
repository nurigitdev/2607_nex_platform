#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_mvp_acceptance_platform_trust_boundary.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    relative_path: str
    token: str


REQUIRED_PATHS = (
    "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
    "docs/30_service_specific_requirement_partition.md",
    "docs/development_process.md",
    "docs/slices/1291_s129_federated_auth_ag_integration_closure.md",
    "services/nex-oa/nex_oa/main.py",
    "services/nex-oa/nex_oa/auth_events.py",
    "services/nex-oa/nex_oa/signing_key_service.py",
    "services/nex-oa/nex_oa/token_validation_service.py",
    "services/_shared/nex_runtime/service_token_admission.py",
    "scripts/smoke/run_platform_signed_token_postgres_smoke.py",
    "scripts/quality/run_quality_gate.sh",
    "docs/slices/1292_oa_mvp_acceptance_platform_trust_boundary.md",
    "docs/README.md",
)

EVIDENCE_TOKENS = (
    EvidenceToken(
        "requirements",
        "docs/29_nex_platform_mvp_srs_v0_1_assembly.md",
        "OA-FR-005",
    ),
    EvidenceToken(
        "s129_handoff",
        "scripts/smoke/run_s129_federated_auth_ag_integration_closure.py",
        '"READY_FOR_S130"',
    ),
    EvidenceToken(
        "actual_postgres",
        "scripts/smoke/run_platform_signed_token_postgres_smoke.py",
        'DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"',
    ),
    EvidenceToken(
        "key_rotation",
        "services/nex-oa/nex_oa/signing_key_service.py",
        "reconcile_key_states",
    ),
    EvidenceToken(
        "revocation",
        "services/nex-oa/nex_oa/token_validation_service.py",
        "is_jti_revoked",
    ),
    EvidenceToken(
        "cross_service",
        "services/_shared/nex_runtime/service_token_admission.py",
        'rollout_profile == "SIGNED_ONLY"',
    ),
    EvidenceToken(
        "full_gate",
        "scripts/quality/run_quality_gate.sh",
        "run_s129_federated_auth_ag_integration_closure.py",
    ),
    EvidenceToken(
        "tiered_quality",
        "docs/development_process.md",
        "Full Gate",
    ),
    EvidenceToken(
        "docs_index",
        "docs/README.md",
        "1292_oa_mvp_acceptance_platform_trust_boundary.md",
    ),
)

GAP_RESOLUTION_PATHS = {
    "signed_token_failure_audit_missing": (
        "docs/slices/1293_oa_signed_token_failure_audit_hardening.md"
    ),
    "acceptance_policy_traceability_missing": (
        "docs/slices/1294_oa_mvp_acceptance_policy_traceability.md"
    ),
    "identity_session_restart_missing": (
        "docs/slices/1295_oa_identity_session_authorization_restart_smoke.md"
    ),
    "key_rotation_restart_missing": (
        "docs/slices/1296_oa_signing_key_rotation_restart_smoke.md"
    ),
    "revocation_restart_missing": (
        "docs/slices/1297_oa_token_revocation_restart_smoke.md"
    ),
    "cross_service_protected_smoke_missing": (
        "docs/slices/1298_platform_signed_only_protected_smoke.md"
    ),
    "contracts_privacy_runbook_missing": (
        "docs/slices/1299_oa_mvp_acceptance_contract_privacy_runbook.md"
    ),
    "integrated_acceptance_missing": (
        "docs/slices/1300_oa_mvp_postgresql_platform_trust_acceptance.md"
    ),
}

GAP_SLICES = {
    name: f"{1293 + index:04d}"
    for index, name in enumerate(GAP_RESOLUTION_PATHS)
}


def run_oa_mvp_acceptance_platform_trust_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": item.group,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in EVIDENCE_TOKENS
    ]
    closures = _closure_evidence(root)
    gap_states = {
        name: "RESOLVED" if (root / path).is_file() else "OPEN"
        for name, path in GAP_RESOLUTION_PATHS.items()
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "oa_requirements_traceable": _group_present(tokens, "requirements"),
        "s129_handoff_ready": _group_present(tokens, "s129_handoff"),
        "postgres_restart_foundation_reusable": _group_present(
            tokens, "actual_postgres"
        ),
        "rotation_and_revocation_foundations_reusable": all(
            _group_present(tokens, group)
            for group in ("key_rotation", "revocation")
        ),
        "signed_only_cross_service_foundation_reusable": _group_present(
            tokens, "cross_service"
        ),
        "tiered_full_gate_reusable": all(
            _group_present(tokens, group)
            for group in ("full_gate", "tiered_quality")
        ),
        "s121_s129_closures_present": all(
            item["runner_present"] and item["document_present"]
            for item in closures
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
        for item in closures
        if not item["runner_present"] or not item["document_present"]
    )
    passed = all(checks.values()) and not issues
    next_slice = next(
        (
            GAP_SLICES[name]
            for name, state in gap_states.items()
            if state == "OPEN"
        ),
        "1301",
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1292",
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "decision": boundary_decision(),
        "summary": {
            "requirement_count": 5,
            "closure_count": len(closures),
            "gap_count": len(gap_states),
            "open_gap_count": sum(
                state == "OPEN" for state in gap_states.values()
            ),
            "resolved_gap_count": sum(
                state == "RESOLVED" for state in gap_states.values()
            ),
            "consumer_count": 4,
            "planned_slice_count": 10,
            "issue_count": len(issues),
        },
        "closure_evidence": closures,
        "gap_states": gap_states,
        "gap_resolution_paths": GAP_RESOLUTION_PATHS,
        "slice_plan": [
            "1292_boundary_audit",
            "1293_signed_token_failure_audit",
            "1294_acceptance_policy_traceability",
            "1295_identity_session_authorization_restart",
            "1296_signing_key_rotation_restart_checkpoint",
            "1297_token_revocation_restart",
            "1298_cross_service_signed_only_protected_smoke",
            "1299_contract_privacy_runbook",
            "1300_integrated_postgres_acceptance",
            "1301_s130_closure_full_gate",
        ],
        "checks": checks,
        "required_paths": paths,
        "required_tokens": tokens,
        "issues": issues,
        "next_slice": next_slice,
    }


def boundary_decision() -> dict[str, Any]:
    return {
        "acceptance_scope": "oa_fr_001_through_005_platform_trust",
        "service_id": "nex-oa",
        "actual_database": "nex_oa_test",
        "actual_role": "nex_oa_user",
        "restart_evidence_required": True,
        "key_rotation_overlap_required": True,
        "revocation_after_restart_required": True,
        "cross_service_consumers": (
            "nex-ae-api",
            "nex-cx",
            "nex-mo",
            "nex-ag",
        ),
        "cross_service_profile": "SIGNED_ONLY",
        "sensitive_route_introspection_required": True,
        "external_private_key_custody_required": True,
        "database_private_key_material_allowed": False,
        "remote_model_provider_required": False,
        "new_tables_expected": 0,
        "product_wide_release_approval": False,
        "production_deployment_certification": False,
        "advisory_deferrals": (
            "external_idp_registration",
            "browser_pkce_product_integration",
            "production_hsm_or_kms_activation",
            "delegated_user_access_tokens",
            "saml_2_0",
        ),
        "quality_cadence": {
            "slice_gate": "1292-1300",
            "checkpoint_gate": "1296",
            "full_gate": "1301",
        },
    }


def _closure_evidence(root: Path) -> list[dict[str, Any]]:
    evidence = []
    for number in range(121, 130):
        runners = list(
            (root / "scripts/smoke").glob(f"run_s{number}_*_closure.py")
        )
        documents = list(
            (root / "docs/slices").glob(f"*s{number}_*closure.md")
        )
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


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "oa_mvp_acceptance_platform_trust_boundary="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"requirements={summary.get('requirement_count', 0)} "
        f"closures={summary.get('closure_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"open={summary.get('open_gap_count', 0)} "
        f"issues={summary.get('issue_count', 0)} "
        f"next={result.get('next_slice', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_mvp_acceptance_platform_trust_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
