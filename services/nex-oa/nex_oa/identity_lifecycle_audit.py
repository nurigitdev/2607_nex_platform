from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_identity_membership_lifecycle_audit.v1"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "subject_registry",
        "services/nex-oa/nex_oa/subjects.py",
        "class SqlAlchemyOaSubjectRegistry",
    ),
    RequiredEvidence(
        "membership_registry",
        "services/nex-oa/nex_oa/memberships.py",
        "class SqlAlchemyOaTenantMembershipRegistry",
    ),
    RequiredEvidence(
        "active_membership_gate",
        "services/nex-oa/nex_oa/sessions.py",
        "def _required_active_membership",
    ),
    RequiredEvidence(
        "subject_regression",
        "tests/test_nex_oa_subjects.py",
        "test_subject_registry_defaults_are_local_refs_and_idempotent",
    ),
    RequiredEvidence(
        "membership_regression",
        "tests/test_nex_oa_memberships.py",
        "test_in_memory_membership_registry_is_idempotent_and_readable",
    ),
    RequiredEvidence(
        "subject_migration",
        "database/nex-oa/migrations/0193_oa_subject_registry_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_subjects",
    ),
    RequiredEvidence(
        "membership_migration",
        "database/nex-oa/migrations/0242_oa_tenant_membership_foundation.sql",
        "CREATE TABLE IF NOT EXISTS oa_tenant_memberships",
    ),
)


def build_oa_identity_lifecycle_audit(root: Path = ROOT) -> dict[str, Any]:
    evidence = [_inspect_evidence(root, item) for item in REQUIRED_EVIDENCE]
    subject_source = _read_text(root / "services/nex-oa/nex_oa/subjects.py")
    membership_source = _read_text(root / "services/nex-oa/nex_oa/memberships.py")
    session_source = _read_text(root / "services/nex-oa/nex_oa/sessions.py")
    migration_source = "\n".join(
        _read_text(path)
        for path in sorted((root / "database/nex-oa/migrations").glob("*.sql"))
    )

    observations = {
        "subject_transition_api_present": "def update_subject_status(" in subject_source,
        "membership_transition_api_present": (
            "def update_membership_status(" in membership_source
        ),
        "deprovision_session_cascade_present": (
            "def revoke_sessions_for_subject(" in session_source
        ),
        "group_registry_present": (
            "oa_groups" in migration_source and "class OaGroup" in subject_source
        ),
        "subject_capability_projection_current": (
            '"password_login": True' in subject_source
        ),
        "membership_capability_projection_current": (
            '"oa_session_issuance": True' in membership_source
            and '"password_login": True' in membership_source
        ),
        "admin_bootstrap_scope_present": (
            "identity:bootstrap" in subject_source
            or "identity:bootstrap" in membership_source
        ),
    }
    projection_current = (
        observations["subject_capability_projection_current"]
        and observations["membership_capability_projection_current"]
    )
    controls = [
        _control("stable_subject_refs", "IMPLEMENTED", None),
        _control("tenant_scoped_identity_storage", "IMPLEMENTED", None),
        _control("membership_role_scope_session_gate", "IMPLEMENTED", None),
        _control(
            "subject_membership_status_transitions",
            "GAP",
            "status values exist but no explicit transition API or optimistic update policy exists",
        ),
        _control(
            "deprovision_session_revocation_cascade",
            "GAP",
            "session issuance checks active membership but later deprovisioning does not revoke existing sessions",
        ),
        _control(
            "group_identity_lifecycle",
            "GAP",
            "roles and scopes exist but no group registry or membership relation exists",
        ),
        _control(
            "capability_projection_freshness",
            "IMPLEMENTED" if projection_current else "STALE",
            None
            if projection_current
            else "subject and membership snapshots still report implemented login/session capabilities as deferred",
        ),
        _control(
            "admin_bootstrap_authorization",
            "GAP",
            "ensure routes use the generic service-call scope without a dedicated bootstrap/admin policy",
        ),
    ]
    expected_gaps_observed = (
        observations["subject_transition_api_present"] is False
        and observations["membership_transition_api_present"] is False
        and observations["deprovision_session_cascade_present"] is False
        and observations["group_registry_present"] is False
        and observations["admin_bootstrap_scope_present"] is False
    )
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "control_inventory_complete": len(controls) == 8,
        "non_implemented_controls_have_explicit_gaps": all(
            item["status"] == "IMPLEMENTED" or bool(item["gap"])
            for item in controls
        ),
        "current_lifecycle_gaps_observed": expected_gaps_observed,
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
    if not expected_gaps_observed:
        issues.append({"category": "lifecycle_classification_drift"})
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1205",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_identity_lifecycle_audit_failed",
        "lifecycle_readiness": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "summary": {
            "control_count": len(controls),
            "implemented_count": sum(
                item["status"] == "IMPLEMENTED" for item in controls
            ),
            "gap_count": sum(item["status"] != "IMPLEMENTED" for item in controls),
            "stale_projection_count": sum(
                item["status"] == "STALE" for item in controls
            ),
            "evidence_issue_count": len(issues),
        },
        "decision": {
            "stable_oa_subject_refs_remain_authoritative": True,
            "roles_and_scopes_remain_membership_attributes": True,
            "group_model_deferred_to_targeted_hardening": True,
            "lifecycle_transition_design_required_before_new_mutation_routes": True,
            "stale_projection_refactor_target_slice": "1209",
            "stale_projection_refactor_status": (
                "REPAIRED" if projection_current else "PENDING"
            ),
            "new_table_required_now": False,
        },
        "observations": observations,
        "controls": controls,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "next_slice": "1206",
    }


def _control(control_id: str, status: str, gap: str | None) -> dict[str, Any]:
    return {"control_id": control_id, "status": status, "gap": gap}


def _inspect_evidence(root: Path, item: RequiredEvidence) -> dict[str, Any]:
    path = root / item.relative_path
    return {
        "name": item.name,
        "path": item.relative_path,
        "present": item.token in _read_text(path),
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
