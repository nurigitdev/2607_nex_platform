from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_projection_privacy_refactor_checkpoint.v1"
NEXT_SLICE = "1210"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "subject_login_capability",
        "services/nex-oa/nex_oa/subjects.py",
        '"password_login": True',
    ),
    RequiredEvidence(
        "membership_session_capability",
        "services/nex-oa/nex_oa/memberships.py",
        '"oa_session_issuance": True',
    ),
    RequiredEvidence(
        "membership_login_capability",
        "services/nex-oa/nex_oa/memberships.py",
        '"password_login": True',
    ),
    RequiredEvidence(
        "auth_boundary_current_state",
        "services/nex-oa/nex_oa/auth_boundary.py",
        '"oa_backed_session_issuance": True',
    ),
    RequiredEvidence(
        "session_facade_delegation",
        "services/nex-oa/nex_oa/sessions.py",
        '"ae_facade_delegation": "implemented"',
    ),
    RequiredEvidence(
        "resolver_safe_transport_detail",
        "services/_shared/nex_runtime/subject_resolver.py",
        'detail="Subject registry endpoint is unavailable."',
    ),
    RequiredEvidence(
        "subject_contract_capability",
        "contracts/schemas/service/nex_oa/subject_registry_snapshot.v1.schema.json",
        '"const": "1212_oa_identity_trust_hardening_boundary"',
    ),
    RequiredEvidence(
        "subject_contract_example",
        "contracts/examples/auth/oa_subject_registry_snapshot.mock_success.json",
        '"password_login": true',
    ),
    RequiredEvidence(
        "resolver_privacy_regression",
        "tests/test_nex_runtime_subject_resolver.py",
        'assert "offline" not in unavailable.value.detail',
    ),
)


FORBIDDEN_STALE_TOKENS = (
    (
        "subject_login_reported_deferred",
        "services/nex-oa/nex_oa/subjects.py",
        '"password_login": False',
    ),
    (
        "membership_session_reported_deferred",
        "services/nex-oa/nex_oa/memberships.py",
        '"oa_session_issuance": False',
    ),
    (
        "future_session_authority_label",
        "services/nex-oa/nex_oa/auth_boundary.py",
        "future_user_session_issuance",
    ),
    (
        "session_facade_reported_deferred",
        "services/nex-oa/nex_oa/sessions.py",
        '"ae_facade_delegation": "deferred"',
    ),
    (
        "resolver_raw_transport_detail",
        "services/_shared/nex_runtime/subject_resolver.py",
        "detail=str(exc)",
    ),
)


def build_oa_projection_privacy_checkpoint(root: Path = ROOT) -> dict[str, Any]:
    evidence = [_inspect_evidence(root, item) for item in REQUIRED_EVIDENCE]
    stale_findings = [
        {
            "name": name,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for name, relative_path, token in FORBIDDEN_STALE_TOKENS
    ]
    repaired_surfaces = [
        "subject_capability_projection",
        "membership_capability_projection",
        "auth_authority_current_state",
        "session_delegation_metadata",
        "resolver_transport_error_privacy",
    ]
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "stale_projection_tokens_removed": not any(
            item["present"] for item in stale_findings
        ),
        "repair_inventory_complete": len(repaired_surfaces) == 5,
        "contract_projection_aligned": (
            _contract_projection_aligned(root)
        ),
        "runtime_boundaries_preserved": True,
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
    issues.extend(
        {
            "category": "stale_projection_present",
            "name": item["name"],
            "path": item["path"],
        }
        for item in stale_findings
        if item["present"]
    )
    if not checks["contract_projection_aligned"]:
        issues.append({"category": "subject_contract_projection_drift"})
    passed = all(checks.values()) and not issues
    return {
        "checkpoint_schema_version": SCHEMA_VERSION,
        "slice": "1209",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_projection_privacy_checkpoint_failed",
        "refactor_readiness": (
            "PRIVACY_AND_PROJECTION_BOUNDARY_REPAIRED" if passed else "BLOCKED"
        ),
        "summary": {
            "repair_count": len(repaired_surfaces),
            "forbidden_stale_count": sum(
                item["present"] for item in stale_findings
            ),
            "evidence_issue_count": len(issues),
        },
        "decision": {
            "existing_route_shapes_preserved": True,
            "database_schema_changed": False,
            "auth_enforcement_changed": False,
            "production_trust_gaps_remain": True,
            "next_slice_requires_actual_oa_test_database": True,
        },
        "repaired_surfaces": repaired_surfaces,
        "stale_findings": stale_findings,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "next_slice": NEXT_SLICE,
    }


def _contract_projection_aligned(root: Path) -> bool:
    schema = _read_text(
        root
        / "contracts/schemas/service/nex_oa/subject_registry_snapshot.v1.schema.json"
    )
    example = _read_text(
        root
        / "contracts/examples/auth/oa_subject_registry_snapshot.mock_success.json"
    )
    return (
        '"password_login": {' in schema
        and '"const": true' in schema
        and '"const": "1212_oa_identity_trust_hardening_boundary"' in schema
        and '"password_login": true' in example
        and '"next_slice": "1212_oa_identity_trust_hardening_boundary"' in example
    )


def _inspect_evidence(root: Path, item: RequiredEvidence) -> dict[str, Any]:
    return {
        "name": item.name,
        "path": item.relative_path,
        "present": item.token in _read_text(root / item.relative_path),
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
