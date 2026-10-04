#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_oa_backed_trust_boundary.v1"
CANONICAL_DOCUMENT = "docs/41_platform_oa_backed_trust_integration.md"
REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/40_platform_postgresql_restart_orchestration.md",
    CANONICAL_DOCUMENT,
    "services/nex-oa/nex_oa/user_login.py",
    "services/nex-oa/nex_oa/sessions.py",
    "services/nex-oa/nex_oa/signed_token_api.py",
    "services/nex-ae-api/nex_ae_api/oa_session_client.py",
    "services/nex-ae-api/nex_ae_api/service_auth.py",
    "services/nex-cx/nex_cx/authorization.py",
    "services/nex-mo/nex_mo/provider_auth.py",
    "services/nex-ag/nex_ag/service_auth.py",
)
REQUIRED_TOKENS = (
    ("outcome", CANONICAL_DOCUMENT, "## Required Outcome"),
    ("invariants", CANONICAL_DOCUMENT, "## Trust Invariants"),
    ("gaps", CANONICAL_DOCUMENT, "## Current Gaps"),
    ("sequence", CANONICAL_DOCUMENT, "## Slice Sequence"),
    ("completion", CANONICAL_DOCUMENT, "## Completion Signal"),
    ("handoff", CANONICAL_DOCUMENT, "## S135 Handoff"),
    ("plan", "docs/37_platform_mvp_integration_release_plan.md", "## S134 Slice Plan"),
    ("quality", "scripts/quality/run_quality_gate.sh", "run_platform_oa_backed_trust_boundary.py"),
    ("index", "docs/README.md", "1332_platform_oa_backed_trust_boundary.md"),
)


def run_platform_oa_backed_trust_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = [{"path": path, "present": (root / path).is_file()} for path in REQUIRED_PATHS]
    tokens = [
        {"group": group, "path": path, "present": token in _read_text(root / path)}
        for group, path, token in REQUIRED_TOKENS
    ]
    sources = {
        "oa_user_login": _read_text(root / "services/nex-oa/nex_oa/user_login.py"),
        "oa_main": _read_text(root / "services/nex-oa/nex_oa/main.py"),
        "oa_token_signing": _read_text(
            root / "services/nex-oa/nex_oa/token_signing.py"
        ),
        "ae_sessions": _read_text(root / "services/nex-ae-api/nex_ae_api/auth_sessions.py"),
        "ae_oa_client": _read_text(root / "services/nex-ae-api/nex_ae_api/oa_session_client.py"),
        "admission": _read_text(root / "services/_shared/nex_runtime/service_token_admission.py"),
    }
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "actual_oa_credential_login_exists": "/internal/v1/auth/user-login" in sources["oa_user_login"],
        "ae_oa_session_facade_exists": "AUTH_SESSION_MODE_OA" in sources["ae_sessions"],
        "ae_signed_oa_client_exists": "resolve_ae_outbound_service_token" in sources["ae_oa_client"],
        "shared_jwks_introspection_admission_exists": (
            "HttpOaJwksSource" in sources["admission"]
            and "HttpOaTokenIntrospector" in sources["admission"]
        ),
        "default_signing_remains_fail_closed": (
            "build_oa_signing_provider()" in sources["oa_main"]
            and 'NEX_OA_SIGNING_PROVIDER", "UNAVAILABLE"'
            in sources["oa_token_signing"]
        ),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": "1332",
        "requirement": "S134",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_oa_backed_trust_boundary_failed",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "required_tokens": tokens,
        "findings": {
            "service_count": 5,
            "trust_axis_count": 2,
            "current_gap_count": 4,
            "denial_scenario_count": 4,
        },
        "decision": {
            "oa_remains_trust_authority": True,
            "opaque_user_session_retained": True,
            "signed_service_tokens_required": True,
            "default_signer_fail_closed": True,
            "test_file_custody_allowed": True,
            "shared_database_allowed": False,
            "actual_test_databases_required": True,
            "remote_provider_required": False,
            "next_slice": "1333",
        },
        "slice_plan": [str(value) for value in range(1332, 1342)],
        "quality_cadence": {"slice_gate": "every_slice", "checkpoint_gate": "1336", "full_gate": "1341"},
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_oa_backed_trust_boundary=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_oa_backed_trust_boundary=pass "
        f"services={findings.get('service_count', 0)} "
        f"trust_axes={findings.get('trust_axis_count', 0)} "
        f"gaps={findings.get('current_gap_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_oa_backed_trust_boundary()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
