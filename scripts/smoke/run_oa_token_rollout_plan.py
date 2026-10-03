#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.token_rollout_policy import (  # noqa: E402
    ROLLOUT_UNITS,
    TOKEN_ROLLOUT_PROFILES,
    allowed_rollout_transition,
    validate_rollout_admission,
)


def run_oa_token_rollout_plan() -> dict[str, Any]:
    common = {
        "jwks_ready": True,
        "introspection_ready": True,
        "service_principal_ready": True,
        "outbound_signed_token_ready": True,
        "audience_scope_mapping_reviewed": True,
        "negative_auth_tests_passed": True,
        "telemetry_redacted": True,
        "mock_fallback_disabled": True,
    }
    dual_errors = validate_rollout_admission(
        unit="nex-ae-api",
        profile_name="DUAL_READ",
        controls=common
        | {
            "legacy_mock_callers_allowlisted": True,
            "compatibility_deadline_set": True,
            "legacy_mock_caller_count": 20,
        },
        completed_units=(ROLLOUT_UNITS[0],),
    )
    signed_errors = validate_rollout_admission(
        unit="nex-cx",
        profile_name="SIGNED_ONLY",
        controls=common
        | {
            "legacy_mock_acceptance_disabled": True,
            "legacy_mock_caller_count": 0,
        },
        completed_units=ROLLOUT_UNITS[:2],
    )
    checks = {
        "three_explicit_profiles": len(TOKEN_ROLLOUT_PROFILES) == 3,
        "no_profile_allows_silent_fallback": all(
            not profile.silent_mock_fallback_allowed
            for profile in TOKEN_ROLLOUT_PROFILES.values()
        ),
        "dual_read_never_issues_mock": (
            not TOKEN_ROLLOUT_PROFILES["DUAL_READ"].issue_mock_tokens
        ),
        "forward_transitions_only": (
            allowed_rollout_transition("TEST_MOCK", "DUAL_READ")
            and allowed_rollout_transition("DUAL_READ", "SIGNED_ONLY")
            and not allowed_rollout_transition("SIGNED_ONLY", "DUAL_READ")
        ),
        "ordered_dual_read_admitted": dual_errors == (),
        "ordered_signed_only_admitted": signed_errors == (),
    }
    passed = all(checks.values())
    return {
        "rollout_schema_version": "oa_token_rollout_plan.v1",
        "slice": "1248",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_token_rollout_plan_failed",
        "profiles": {
            name: profile.to_wire()
            for name, profile in TOKEN_ROLLOUT_PROFILES.items()
        },
        "rollout_units": ROLLOUT_UNITS,
        "rollback_policy": "stop_forward_rollout_never_auto_broaden_trust",
        "checks": checks,
        "next_slice": "1249",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_token_rollout_plan="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"profiles={len(evidence.get('profiles') or {})} "
        f"units={len(evidence.get('rollout_units') or ())} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_token_rollout_plan()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
