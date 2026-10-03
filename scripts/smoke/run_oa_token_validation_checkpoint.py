#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.token_validation_policy import (  # noqa: E402
    PRODUCTION_TOKEN_VALIDATION_POLICY,
    build_token_validation_plan,
    evaluate_token_validation,
)


def run_oa_token_validation_checkpoint() -> dict[str, Any]:
    read_plan = build_token_validation_plan(
        route_class="READ", kid_known=True, jwks_cache_age_seconds=30
    )
    admin_plan = build_token_validation_plan(
        route_class="ADMIN", kid_known=False, jwks_cache_age_seconds=301
    )
    active = evaluate_token_validation(
        route_class="ADMIN",
        local_status="valid",
        scope_satisfied=True,
        introspection_status="active",
    )
    outage = evaluate_token_validation(
        route_class="ADMIN",
        local_status="valid",
        scope_satisfied=True,
        introspection_status="unavailable",
    )
    checks = {
        "read_uses_fresh_local_jwks": (
            not read_plan["jwks_refresh_required"]
            and not read_plan["introspection_required"]
        ),
        "unknown_kid_refresh_is_bounded": (
            admin_plan["jwks_refresh_required"]
            and admin_plan["jwks_refresh_attempts"] == 1
        ),
        "admin_requires_introspection": admin_plan["introspection_required"],
        "active_sensitive_token_accepted": active.accepted,
        "introspection_outage_fails_closed": (
            not outage.accepted and outage.http_status == 503
        ),
        "stale_jwks_never_accepted": (
            not PRODUCTION_TOKEN_VALIDATION_POLICY.stale_jwks_acceptance_allowed
        ),
        "raw_token_logging_forbidden": (
            not PRODUCTION_TOKEN_VALIDATION_POLICY.raw_token_logging_allowed
        ),
    }
    passed = all(checks.values())
    return {
        "checkpoint_schema_version": "oa_token_validation_checkpoint.v1",
        "slice": "1246",
        "requirement": "S125",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_token_validation_checkpoint_failed",
        "policy": PRODUCTION_TOKEN_VALIDATION_POLICY.to_wire(),
        "http_failure_semantics": {
            "untrusted_or_inactive_token": 401,
            "insufficient_scope": 403,
            "required_trust_dependency_unavailable": 503,
        },
        "checks": checks,
        "next_slice": "1247",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    policy = evidence.get("policy") or {}
    return (
        "oa_token_validation_checkpoint="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"jwks_ttl={policy.get('jwks_cache_ttl_seconds')} "
        f"introspection_timeout={policy.get('introspection_timeout_seconds')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_token_validation_checkpoint()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
