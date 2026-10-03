#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.token_rollout_policy import ROLLOUT_UNITS, ROLLOUT_PROFILE_ORDER  # noqa: E402
from nex_runtime.signed_token_adoption_boundary import (  # noqa: E402
    S128_CONSUMER_SERVICES,
    S128_SIGNED_TOKEN_ADOPTION_BOUNDARY,
    validate_signed_token_adoption_boundary,
)


CONSUMER_PACKAGE_PATHS = {
    "nex-ae-api": "services/nex-ae-api/nex_ae_api",
    "nex-cx": "services/nex-cx/nex_cx",
    "nex-mo": "services/nex-mo/nex_mo",
    "nex-ag": "services/nex-ag/nex_ag",
}
REQUIRED_EVIDENCE = (
    ("shared_mock_validator", "services/_shared/nex_runtime/auth.py", "return validate_mock_service_token("),
    ("shared_service_claim_route", "services/_shared/nex_runtime/app.py", '"/internal/v1/auth/service-claim"'),
    ("oa_signed_issuer", "services/nex-oa/nex_oa/token_exchange_service.py", "class OaClientCredentialTokenExchangeService"),
    ("oa_jwks_and_introspection", "services/nex-oa/nex_oa/signed_token_api.py", '"/.well-known/jwks.json"'),
    ("existing_rollout_policy", "services/nex-oa/nex_oa/token_rollout_policy.py", 'ROLLOUT_PROFILE_ORDER = ("TEST_MOCK", "DUAL_READ", "SIGNED_ONLY")'),
    ("full_gate_hook", "scripts/quality/run_quality_gate.sh", "run_platform_signed_token_adoption_boundary.py"),
    ("docs_index", "docs/README.md", "1272_platform_signed_token_adoption_boundary.md"),
    ("slice_document", "docs/slices/1272_platform_signed_token_adoption_boundary.md", "# Slice 1272:"),
)


def run_platform_signed_token_adoption_boundary(root: Path = ROOT) -> dict[str, Any]:
    boundary = S128_SIGNED_TOKEN_ADOPTION_BOUNDARY
    evidence = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in REQUIRED_EVIDENCE
    ]
    consumer_apps = {
        service_id: "build_service_app(" in _read_text(root / package / "main.py")
        for service_id, package in CONSUMER_PACKAGE_PATHS.items()
    }
    mock_fallback_files = _mock_fallback_files(root)
    checks = {
        "boundary_contract_valid": (
            validate_signed_token_adoption_boundary(boundary.to_wire()) == ()
        ),
        "required_evidence_present": all(item["present"] for item in evidence),
        "existing_rollout_policy_reused": (
            tuple(ROLLOUT_UNITS) == boundary.rollout_units
            and tuple(ROLLOUT_PROFILE_ORDER) == boundary.rollout_profiles
        ),
        "all_consumer_app_shells_present": all(consumer_apps.values()),
        "mock_fallback_debt_explicit": bool(mock_fallback_files),
        "silent_mock_fallback_forbidden": not boundary.silent_mock_fallback_allowed,
        "oa_database_reads_forbidden": not boundary.cross_service_database_reads_allowed,
        "no_new_tables_required": not boundary.new_database_tables_required,
        "remote_model_provider_not_required": not boundary.remote_model_provider_required,
        "service_access_only": (
            boundary.token_profile == "service_access"
            and boundary.deferred_token_profiles == ("delegated_user_access",)
        ),
    }
    issues = [
        {"category": "evidence_missing", "name": item["name"], "path": item["path"]}
        for item in evidence
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "consumer_app_missing",
            "name": service_id,
            "path": f"{CONSUMER_PACKAGE_PATHS[service_id]}/main.py",
        }
        for service_id, present in consumer_apps.items()
        if not present
    )
    passed = all(checks.values()) and not issues
    return {
        "boundary_schema_version": "platform_signed_token_adoption_boundary.v1",
        "slice": "1272",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_signed_token_adoption_boundary_failed",
        "boundary": boundary.to_wire(),
        "consumer_apps": consumer_apps,
        "mock_fallback_files": mock_fallback_files,
        "mock_fallback_file_count": len(mock_fallback_files),
        "checks": checks,
        "issues": issues,
        "slice_plan": (
            "1272_boundary_audit_and_refactoring_checkpoint",
            "1273_shared_jwks_verifier_foundation",
            "1274_shared_fastapi_admission_runtime",
            "1275_ae_signed_token_verification_adoption",
            "1276_cx_signed_token_verification_and_checkpoint",
            "1277_mo_signed_token_verification_adoption",
            "1278_ag_signed_token_verification_adoption",
            "1279_rollout_observability_contract_and_privacy_hardening",
            "1280_platform_loopback_actual_postgres_smoke",
            "1281_s128_closure_and_full_gate",
        ),
        "next_slice": "1273",
    }


def _mock_fallback_files(root: Path) -> tuple[str, ...]:
    paths: list[str] = []
    for package in CONSUMER_PACKAGE_PATHS.values():
        base = root / package
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "issue_mock_service_token" in _read_text(path):
                paths.append(path.relative_to(root).as_posix())
    return tuple(paths)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "platform_signed_token_adoption_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"consumers={sum((evidence.get('consumer_apps') or {}).values())}/{len(S128_CONSUMER_SERVICES)} "
        f"mock_fallback_files={evidence.get('mock_fallback_file_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_signed_token_adoption_boundary()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
