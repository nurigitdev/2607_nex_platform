#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_production_trust_boundary.v1"
SLICE_ID = "1242"
REQUIREMENT = "S125"
BOUNDARY = "oa_production_trust_boundary_and_token_profile_decision"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "s124_handoff",
        "scripts/smoke/run_s124_oa_group_role_authorization_closure.py",
        '"next_requirement": "S125"',
    ),
    RequiredEvidence(
        "mock_service_token_issuer",
        "services/_shared/nex_runtime/auth.py",
        "def issue_mock_service_token(",
    ),
    RequiredEvidence(
        "mock_user_token_issuer",
        "services/_shared/nex_runtime/auth.py",
        "def issue_mock_user_token(",
    ),
    RequiredEvidence(
        "shared_token_validator",
        "services/_shared/nex_runtime/auth.py",
        "def validate_authorization_header(",
    ),
    RequiredEvidence(
        "opaque_session_registry",
        "services/nex-oa/nex_oa/sessions.py",
        "class SqlAlchemyOaSessionRegistry",
    ),
    RequiredEvidence(
        "service_token_route",
        "services/_shared/nex_runtime/app.py",
        '@app.post("/api/v1/auth/service-token"',
    ),
    RequiredEvidence(
        "introspection_route",
        "services/_shared/nex_runtime/app.py",
        '@app.post("/api/v1/auth/introspect")',
    ),
    RequiredEvidence(
        "oa_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "OA-FR-003",
    ),
    RequiredEvidence(
        "s124_decision",
        "docs/slices/1241_s124_oa_group_role_authorization_closure.md",
        "signed service tokens and JWKS verification",
    ),
    RequiredEvidence(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_oa_production_trust_boundary.py",
    ),
    RequiredEvidence(
        "docs_index",
        "docs/README.md",
        "1242_oa_production_trust_boundary.md",
    ),
    RequiredEvidence(
        "slice_document",
        "docs/slices/1242_oa_production_trust_boundary.md",
        "# Slice 1242:",
    ),
)


def run_oa_production_trust_boundary(root: Path = ROOT) -> dict[str, Any]:
    evidence = [
        {
            "name": item.name,
            "path": item.relative_path,
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in REQUIRED_EVIDENCE
    ]
    decision = _decision()
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "oa_owns_production_trust": decision["owner"] == "nex-oa",
        "opaque_browser_session_preserved": decision[
            "browser_session_profile"
        ]
        == "opaque_oa_backed",
        "signed_token_targets_explicit": decision["signed_token_profiles"]
        == ("service_access", "delegated_user_access"),
        "production_mock_fallback_forbidden": decision[
            "production_mock_token_fallback"
        ]
        is False,
        "actual_postgres_evidence_required": decision[
            "actual_test_database_evidence_required"
        ],
        "remote_provider_not_required": not decision[
            "protected_live_provider_evidence_required"
        ],
        "implementation_deferred_to_followup": (
            decision["new_table_required"] is False
            and decision["existing_oa_records_mutated"] is False
        ),
    }
    issues = [
        {
            "category": "evidence_missing",
            "name": item["name"],
            "path": item["path"],
        }
        for item in evidence
        if not item["present"]
    ]
    passed = all(checks.values()) and not issues
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_production_trust_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": decision,
        "audit_surfaces": (
            "mock_service_and_user_token_issuance",
            "shared_authorization_header_validation",
            "opaque_user_session_issue_introspection_revocation",
            "service_principal_and_client_credential_lifecycle",
            "signing_algorithm_key_custody_and_rotation",
            "jwks_cache_introspection_and_revocation_semantics",
            "cross_service_issuer_audience_scope_and_claim_validation",
            "privacy_safe_auth_events_and_actual_postgres_evidence",
        ),
        "slice_plan": (
            "1242_production_trust_boundary",
            "1243_token_surface_inventory",
            "1244_canonical_token_profile_policy",
            "1245_signing_key_custody_policy",
            "1246_validation_revocation_checkpoint",
            "1247_service_principal_credential_boundary",
            "1248_cross_service_migration_rollout",
            "1249_trust_privacy_threat_contract_evidence",
            "1250_postgresql_trust_baseline_smoke",
            "1251_s125_closure_full_gate",
        ),
        "quality_cadence": {
            "slice_gate": "1242-1250",
            "checkpoint_gate": "1246",
            "full_gate": "1251",
        },
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
    }


def _decision() -> dict[str, Any]:
    return {
        "owner": "nex-oa",
        "trust_scope": "oa_fr_002_through_005_production_trust",
        "browser_session_profile": "opaque_oa_backed",
        "signed_token_profiles": (
            "service_access",
            "delegated_user_access",
        ),
        "production_mock_token_fallback": False,
        "test_profile_mock_token_compatibility": True,
        "local_signature_verification_required": True,
        "revocation_sensitive_introspection_required": True,
        "private_key_plaintext_database_storage_allowed": False,
        "actual_test_database_evidence_required": True,
        "protected_live_provider_evidence_required": False,
        "new_table_required": False,
        "existing_oa_records_mutated": False,
        "deferred_scope": (
            "external_oidc_or_saml",
            "multi_factor_authentication",
            "self_service_password_recovery_delivery",
            "hardware_security_module_integration",
            "explicit_deny_and_nested_group_authorization",
        ),
        "next_requirement": "S126",
        "decision_status": "FROZEN",
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "oa_production_trust_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "oa_production_trust_boundary=pass "
        f"profiles={len(decision.get('signed_token_profiles') or ())} "
        f"browser={decision.get('browser_session_profile')} "
        f"mock_prod={decision.get('production_mock_token_fallback')} "
        f"postgres={decision.get('actual_test_database_evidence_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_production_trust_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
