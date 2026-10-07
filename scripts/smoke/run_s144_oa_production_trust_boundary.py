#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "oa_production_trust_boundary.v1"
CANONICAL_PATH = "docs/52_oa_production_trust_key_custody_federation.md"
S143_ATTESTATION_PATH = "deployment/security/s143-external-staging-attestation.json"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
RUNNER_NAME = "run_s144_oa_production_trust_boundary.py"
OPENBAO_IMAGE_PATTERN = re.compile(
    r"ghcr\.io/openbao/openbao:[^@\s]+@sha256:[0-9a-f]{64}"
)


@dataclass(frozen=True)
class ProductionTrustGap:
    gap_id: str
    owner: str
    target_slices: tuple[str, ...]


PRODUCTION_TRUST_GAPS = (
    ProductionTrustGap("external_signer_transport", "nex-oa", ("1434",)),
    ProductionTrustGap("oa_runtime_signer_wiring", "nex-oa", ("1435",)),
    ProductionTrustGap(
        "custody_key_lifecycle", "nex-oa_and_platform_integration", ("1436",)
    ),
    ProductionTrustGap(
        "rotation_jwks_introspection", "nex-oa", ("1437",)
    ),
    ProductionTrustGap(
        "federation_registration_metadata", "nex-oa", ("1438",)
    ),
    ProductionTrustGap("federation_rollover_outage", "nex-oa", ("1439",)),
    ProductionTrustGap(
        "protected_single_host_acceptance",
        "nex-oa_and_platform_integration",
        ("1440", "1441"),
    ),
    ProductionTrustGap("closure_attestation", "platform_integration", ("1442",)),
)

REQUIRED_PATHS = (
    "docs/48_platform_production_readiness_plan.md",
    "docs/51_platform_production_configuration_secret_tls.md",
    CANONICAL_PATH,
    "docs/slices/1433_oa_production_trust_boundary.md",
    "deployment/compose/s143-staging.compose.yaml",
    "deployment/compose/openbao/config.hcl",
    S143_ATTESTATION_PATH,
    "services/nex-oa/nex_oa/token_signing.py",
    "services/nex-oa/nex_oa/signing_key_service.py",
    "services/nex-oa/nex_oa/signed_token_repository.py",
    "services/nex-oa/nex_oa/oidc_verifier.py",
    "services/nex-oa/nex_oa/federated_login.py",
    "services/nex-oa/nex_oa/federated_identity_repository.py",
    QUALITY_GATE_PATH,
)


def run_oa_production_trust_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    token_signing = _read_text(root / "services/nex-oa/nex_oa/token_signing.py")
    oidc_verifier = _read_text(root / "services/nex-oa/nex_oa/oidc_verifier.py")
    federation = _read_text(root / "services/nex-oa/nex_oa/federated_login.py")
    compose = _read_text(root / "deployment/compose/s143-staging.compose.yaml")
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    attestation = _read_json(root / S143_ATTESTATION_PATH)
    checks = {
        "required_paths_present": all(paths.values()),
        "s143_dependency_accepted": (
            attestation.get("requirement_id") == "S143"
            and attestation.get("actual_execution") is True
            and all(attestation.get("checks", {}).values())
            and attestation.get("privacy", {}).get("violation_count") == 0
            and attestation.get("rollback", {}).get("drill_status") == "PASS"
        ),
        "single_host_openbao_traefik_baseline_present": (
            "name: nex-platform-s143" in compose
            and "ghcr.io/openbao/openbao:2.7.1@sha256:" in compose
            and "traefik:" in compose
            and "storage \"raft\"" in _read_text(
                root / "deployment/compose/openbao/config.hcl"
            )
        ),
        "external_signer_protocol_exists": (
            "class OaRsaSigningProvider(Protocol)" in token_signing
            and "def sign_rs256" in token_signing
        ),
        "production_signer_currently_fails_closed": (
            'NEX_OA_SIGNING_PROVIDER", "UNAVAILABLE"' in token_signing
            and "UnavailableOaRsaSigningProvider" in token_signing
            and "TEST_FILE" in token_signing
            and (
                "OPENBAO_TRANSIT" not in token_signing
                or "build_openbao_transit_signing_provider" in token_signing
            )
        ),
        "oidc_validation_foundation_exists": all(
            token in oidc_verifier
            for token in (
                "OIDC_ID_TOKEN_ALGORITHM = \"RS256\"",
                "OIDC_CACHE_TTL_SECONDS = 300",
                "OIDC_MAX_CLOCK_SKEW_SECONDS = 60",
                "jwks_uri",
                "nonce",
            )
        ),
        "federated_session_boundary_exists": (
            "class OaFederatedLoginService" in federation
            and '"auth_method": "federated_oidc"' in federation
            and "/internal/v1/auth/federated-login" in federation
        ),
        "eight_gaps_documented": (
            len(PRODUCTION_TRUST_GAPS) == 8
            and all(f"`{item.gap_id}`" in canonical for item in PRODUCTION_TRUST_GAPS)
        ),
        "ten_slice_sequence_and_gates_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1433, 1443))
            and "Checkpoint Gate at Slice 1437" in canonical
            and "Full Gate at Slice 1442" in canonical
        ),
        "single_host_decision_is_explicit": (
            "single-host topology is sufficient" in canonical.lower()
            and "no additional host package is required" in canonical.lower()
            and "production deployment remains unapproved" in canonical.lower()
        ),
        "privacy_and_fail_closed_rules_frozen": all(
            token in canonical
            for token in (
                "Automatic linking by email or employee number remains forbidden",
                "OpenBao root/admin tokens never enter OA",
                "SIGNED_ONLY",
                "silent mock fallback",
            )
        ),
        "quality_hook_registered_once": quality_gate.count(RUNNER_NAME) == 1,
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items()
        if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1433",
        "requirement": "S144",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "gaps": [
            {
                "gap_id": item.gap_id,
                "owner": item.owner,
                "target_slices": list(item.target_slices),
                "state": "OPEN",
            }
            for item in PRODUCTION_TRUST_GAPS
        ],
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "gap_count": len(PRODUCTION_TRUST_GAPS),
            "slice_count": 10,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "single_host_compose_feasible": True,
            "key_custody_adapter": "openbao_transit",
            "staging_oidc_issuer": "openbao_oidc_provider",
            "provider_neutral_runtime_contract_required": True,
            "corporate_idp_contact_required_for_staging": False,
            "actual_external_acceptance_required_for_closure": True,
            "host_software_install_required": False,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1434" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"oa_production_trust_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "oa_production_trust_boundary=pass "
        f"checks={summary.get('check_count', 0)}/12 "
        f"gaps={summary.get('gap_count', 0)} "
        f"slices={summary.get('slice_count', 0)} "
        f"single_host={str(decision.get('single_host_compose_feasible')).lower()} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_oa_production_trust_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
