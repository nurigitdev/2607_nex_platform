#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_current_state_reaudit_boundary.v1"
SLICE_ID = "1202"
REQUIREMENT = "S121"
BOUNDARY = "oa_current_state_reaudit_and_refactoring_checkpoint"


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
        "s120_closure",
        "scripts/smoke/run_s120_mo_mvp_acceptance_oa_transition_closure.py",
    ),
    RequiredPath("oa_readme", "services/nex-oa/README.md"),
    RequiredPath("oa_runtime", "services/nex-oa/nex_oa/main.py"),
    RequiredPath("subject_registry", "services/nex-oa/nex_oa/subjects.py"),
    RequiredPath("membership_registry", "services/nex-oa/nex_oa/memberships.py"),
    RequiredPath("credential_registry", "services/nex-oa/nex_oa/credentials.py"),
    RequiredPath("session_registry", "services/nex-oa/nex_oa/sessions.py"),
    RequiredPath("user_login", "services/nex-oa/nex_oa/user_login.py"),
    RequiredPath("oa_openapi", "contracts/openapi/nex-oa.openapi.yaml"),
    RequiredPath(
        "service_requirements",
        "docs/30_service_specific_requirement_partition.md",
    ),
    RequiredPath("testing_strategy", "docs/34_testing_strategy_v0_1_detail.md"),
    RequiredPath("quality_gate", "scripts/quality/run_quality_gate.sh"),
    RequiredPath("docs_index", "docs/README.md"),
    RequiredPath(
        "slice_doc",
        "docs/slices/1202_oa_current_state_reaudit_boundary.md",
    ),
)

TOKEN_REQUIREMENTS = (
    TokenRequirement(
        "s120_handoff",
        "scripts/smoke/run_s120_mo_mvp_acceptance_oa_transition_closure.py",
        '"next_requirement": "S121"',
    ),
    TokenRequirement(
        "oa_app",
        "services/nex-oa/nex_oa/main.py",
        "register_user_login_routes(app, service=USER_LOGIN_SERVICE)",
    ),
    TokenRequirement(
        "subject_registry",
        "services/nex-oa/nex_oa/subjects.py",
        "class OaSubjectRegistry",
    ),
    TokenRequirement(
        "membership_registry",
        "services/nex-oa/nex_oa/memberships.py",
        "class OaTenantMembershipRegistry",
    ),
    TokenRequirement(
        "credential_registry",
        "services/nex-oa/nex_oa/credentials.py",
        "class OaCredentialRegistry",
    ),
    TokenRequirement(
        "session_registry",
        "services/nex-oa/nex_oa/sessions.py",
        "class SqlAlchemyOaSessionRegistry",
    ),
    TokenRequirement(
        "user_login",
        "services/nex-oa/nex_oa/user_login.py",
        "class OaUserLoginService",
    ),
    TokenRequirement(
        "oa_requirements",
        "docs/30_service_specific_requirement_partition.md",
        "OA-FR-005",
    ),
    TokenRequirement(
        "privacy_boundary",
        "docs/slices/0251_oa_user_bootstrap_login_boundary_audit.md",
        "AE must not persist passwords",
    ),
    TokenRequirement(
        "coverage_policy",
        "docs/34_testing_strategy_v0_1_detail.md",
        "Branch coverage",
    ),
    TokenRequirement(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_oa_current_state_reaudit_boundary.py",
    ),
    TokenRequirement(
        "docs_index",
        "docs/README.md",
        "1202_oa_current_state_reaudit_boundary.md",
    ),
)


def run_oa_current_state_reaudit_boundary(
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
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "s120_handoff_ready": _group_present(tokens, "s120_handoff"),
        "oa_identity_runtime_reusable": all(
            _group_present(tokens, group)
            for group in (
                "oa_app",
                "subject_registry",
                "membership_registry",
                "credential_registry",
                "session_registry",
                "user_login",
            )
        ),
        "requirements_privacy_quality_inputs_reusable": all(
            _group_present(tokens, group)
            for group in (
                "oa_requirements",
                "privacy_boundary",
                "coverage_policy",
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
            None if passed else "oa_current_state_reaudit_boundary_failed"
        ),
        "boundary": BOUNDARY,
        "decision": {
            "owner": "nex-oa",
            "audit_scope": "oa_fr_001_through_005",
            "repository_state_is_primary_evidence": True,
            "opaque_user_session_introspection_preserved": True,
            "employee_id_password_login_preserved": True,
            "refactor_before_feature_when_needed": True,
            "actual_test_database_evidence_required": True,
            "protected_live_provider_evidence_required": False,
            "new_table_required": False,
            "existing_oa_records_mutated": False,
            "next_requirement": "S122",
            "decision_status": "FROZEN",
        },
        "audit_surfaces": [
            "oa_fr_001_through_005_capability_traceability",
            "schema_migration_and_repository_drift",
            "subject_membership_and_identity_lifecycle",
            "credential_session_and_login_security",
            "service_token_jwks_and_introspection_trust",
            "contracts_openapi_and_runtime_route_parity",
            "cross_service_clients_claims_and_authorization_coupling",
            "privacy_audit_events_and_test_postgresql_evidence",
        ],
        "deferred_scope": [
            "public_self_service_signup",
            "external_oidc_or_enterprise_sso",
            "multi_factor_authentication",
            "email_or_sms_password_recovery",
            "production_secret_manager_and_key_ceremony",
        ],
        "slice_plan": [
            "1202_boundary_audit",
            "1203_capability_traceability_inventory",
            "1204_persistence_migration_drift_audit",
            "1205_identity_membership_lifecycle_audit",
            "1206_credential_session_security_checkpoint",
            "1207_contract_api_drift_audit",
            "1208_cross_service_trust_coupling_audit",
            "1209_privacy_refactoring_checkpoint",
            "1210_postgresql_current_state_reaudit",
            "1211_s121_closure_s122_handoff",
        ],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1206",
            "full_gate": "1211",
        },
        "required_paths": paths,
        "required_tokens": tokens,
        "checks": checks,
        "issues": issues,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _group_present(items: list[dict[str, Any]], group: str) -> bool:
    matching = [item for item in items if item["group"] == group]
    return bool(matching) and all(item["present"] for item in matching)


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "oa_current_state_reaudit_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    decision = evidence.get("decision") or {}
    return (
        "oa_current_state_reaudit_boundary=pass "
        f"scope={decision.get('audit_scope')} "
        f"owner={decision.get('owner')} "
        f"postgres_required={decision.get('actual_test_database_evidence_required')} "
        f"live_provider_required={decision.get('protected_live_provider_evidence_required')} "
        f"new_table={decision.get('new_table_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    evidence = run_oa_current_state_reaudit_boundary()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
