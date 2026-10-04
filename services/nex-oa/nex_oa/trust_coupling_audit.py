from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "oa_cross_service_trust_coupling_audit.v1"


@dataclass(frozen=True)
class RequiredEvidence:
    name: str
    relative_path: str
    token: str


REQUIRED_EVIDENCE = (
    RequiredEvidence(
        "ae_session_client",
        "services/nex-ae-api/nex_ae_api/oa_session_client.py",
        "class HttpOaUserSessionClient",
    ),
    RequiredEvidence(
        "ae_oa_facade",
        "services/nex-ae-api/nex_ae_api/auth_sessions.py",
        "def active_oa_browser_session_from_cookie",
    ),
    RequiredEvidence(
        "claim_owner_scope",
        "services/nex-ae-api/nex_ae_api/auth_guard.py",
        "def apply_claim_owner_scope",
    ),
    RequiredEvidence(
        "cx_subject_resolver",
        "services/_shared/nex_runtime/subject_resolver.py",
        "class HttpSubjectRegistryResolver",
    ),
    RequiredEvidence(
        "ae_session_client_regression",
        "tests/test_nex_ae_oa_session_client.py",
        "test_http_oa_session_client_calls_login_issue_introspect_and_revoke_shapes",
    ),
    RequiredEvidence(
        "subject_resolver_regression",
        "tests/test_nex_runtime_subject_resolver.py",
        "test_http_subject_resolver_verifies_tenant_owner_and_uploaded_by",
    ),
    RequiredEvidence(
        "oa_signed_internal_admission",
        "services/nex-oa/nex_oa/service_auth.py",
        "def authorize_oa_service_request",
    ),
)


def build_oa_trust_coupling_audit(root: Path = ROOT) -> dict[str, Any]:
    evidence = [_inspect_evidence(root, item) for item in REQUIRED_EVIDENCE]
    ae_client = _read_text(
        root / "services/nex-ae-api/nex_ae_api/oa_session_client.py"
    )
    ae_sessions = _read_text(
        root / "services/nex-ae-api/nex_ae_api/auth_sessions.py"
    )
    ae_guard = _read_text(root / "services/nex-ae-api/nex_ae_api/auth_guard.py")
    runtime_profiles = _read_text(
        root / "services/_shared/nex_runtime/runtime_profiles.py"
    )
    resolver = _read_text(root / "services/_shared/nex_runtime/subject_resolver.py")
    oa_source = "\n".join(
        _read_text(path)
        for path in sorted((root / "services/nex-oa/nex_oa").glob("*.py"))
    )

    observations = {
        "explicit_ae_oa_http_adapter_present": (
            "class HttpOaUserSessionClient" in ae_client
        ),
        "explicit_cx_oa_http_adapter_present": (
            "class HttpSubjectRegistryResolver" in resolver
        ),
        "claim_authoritative_owner_scope_present": (
            '"claim_owner_authoritative": True' in ae_guard
            and "def apply_claim_owner_scope" in ae_guard
        ),
        "mock_service_token_fallback_present": (
            "self.service_token or issue_mock_service_token(" in ae_client
            or "self.service_token or issue_mock_service_token(" in resolver
        ),
        "generic_service_scope_used_for_internal_routes": (
            oa_source.count("required_scopes=[DEFAULT_SERVICE_SCOPE]") >= 7
        ),
        "signed_internal_admission_present": (
            "authorize_oa_service_request" in oa_source
            and 'route_class="CREDENTIAL"' in oa_source
        ),
        "resolver_transport_detail_exposure_present": "detail=str(exc)" in resolver,
        "cross_service_retry_policy_present": (
            "retry_policy" in ae_client and "retry_policy" in resolver
        ),
        "browser_cookie_profile_aware": (
            "resolve_session_cookie_secure" in ae_sessions
            and "secure=resolved_cookie_secure" in ae_sessions
        ),
        "oa_auth_mode_profile_aware": (
            'AE_AUTH_SESSION_MODE_ENV: "mock" if profile == "local_mock" else "oa"'
            in runtime_profiles
        ),
    }
    controls = [
        _control("ae_oa_session_http_boundary", "EXPLICIT", "LOW", None),
        _control("cx_oa_subject_http_boundary", "EXPLICIT", "LOW", None),
        _control("claim_authoritative_owner_scope", "EXPLICIT", "LOW", None),
        _control(
            "service_token_fail_closed_configuration",
            "REFACTOR_REQUIRED",
            "HIGH",
            "missing configured service credentials silently fall back to unsigned mock tokens",
        ),
        _control(
            "route_specific_service_authorization",
            "HARDENED",
            "HIGH",
            None,
        ),
        _control(
            "cross_service_error_privacy",
            (
                "REFACTOR_REQUIRED"
                if observations["resolver_transport_detail_exposure_present"]
                else "HARDENED"
            ),
            "MEDIUM",
            (
                "subject resolver transport exceptions may expose endpoint details"
                if observations["resolver_transport_detail_exposure_present"]
                else None
            ),
        ),
        _control(
            "cross_service_resilience_policy",
            "REFACTOR_REQUIRED",
            "MEDIUM",
            "bounded timeouts exist but no shared retry circuit or admission policy is composed",
        ),
        _control(
            "production_browser_auth_defaults",
            "HARDENED",
            "MEDIUM",
            None,
        ),
    ]
    explicit_boundaries_observed = all(
        observations[name]
        for name in (
            "explicit_ae_oa_http_adapter_present",
            "explicit_cx_oa_http_adapter_present",
            "claim_authoritative_owner_scope_present",
        )
    )
    coupling_gaps_observed = (
        observations["mock_service_token_fallback_present"]
        and observations["generic_service_scope_used_for_internal_routes"] is False
        and observations["signed_internal_admission_present"]
        and observations["resolver_transport_detail_exposure_present"] is False
        and observations["cross_service_retry_policy_present"] is False
        and observations["browser_cookie_profile_aware"]
        and observations["oa_auth_mode_profile_aware"]
    )
    checks = {
        "required_evidence_present": all(item["present"] for item in evidence),
        "coupling_control_inventory_complete": len(controls) == 8,
        "explicit_boundaries_observed": explicit_boundaries_observed,
        "current_coupling_gaps_observed": coupling_gaps_observed,
        "refactor_controls_have_reasons": all(
            item["status"] in {"EXPLICIT", "HARDENED"} or bool(item["reason"])
            for item in controls
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
    if not explicit_boundaries_observed or not coupling_gaps_observed:
        issues.append({"category": "trust_coupling_classification_drift"})
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1208",
        "requirement": "S121",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_trust_coupling_audit_failed",
        "trust_readiness": (
            "ORDERED_REFACTOR_REQUIRED_BEFORE_PRODUCTION_AUTH"
            if passed
            else "BLOCKED"
        ),
        "summary": {
            "control_count": len(controls),
            "explicit_boundary_count": sum(
                item["status"] == "EXPLICIT" for item in controls
            ),
            "refactor_required_count": sum(
                item["status"] == "REFACTOR_REQUIRED" for item in controls
            ),
            "hardened_count": sum(
                item["status"] == "HARDENED" for item in controls
            ),
            "high_risk_count": sum(item["risk"] == "HIGH" for item in controls),
            "evidence_issue_count": len(issues),
        },
        "decision": {
            "http_service_boundaries_preserved": True,
            "direct_cross_database_reads_forbidden": True,
            "mock_token_fallback_production_forbidden": True,
            "route_specific_service_authorization_required": True,
            "new_table_required_now": False,
        },
        "observations": observations,
        "controls": controls,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "next_slice": "1209",
    }


def _control(
    control_id: str,
    status: str,
    risk: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "status": status,
        "risk": risk,
        "reason": reason,
    }


def _inspect_evidence(root: Path, item: RequiredEvidence) -> dict[str, Any]:
    path = root / item.relative_path
    return {
        "name": item.name,
        "path": item.relative_path,
        "present": item.token in _read_text(path),
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
