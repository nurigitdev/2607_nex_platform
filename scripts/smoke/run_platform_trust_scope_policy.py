#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = ROOT / "services" / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from nex_runtime.platform_trust_scope_policy import (  # noqa: E402
    platform_trust_scope_policy,
    validate_platform_trust_scope_policy,
)


def run_platform_trust_scope_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = platform_trust_scope_policy()
    issues = list(validate_platform_trust_scope_policy())
    app_source = (root / "services/_shared/nex_runtime/app.py").read_text(
        encoding="utf-8"
    )
    checks = {
        "grant_policy_valid": not issues,
        "active_claim_route_registered": (
            '"/internal/v1/auth/service-claim/active"' in app_source
        ),
        "active_claim_route_is_sensitive": 'route_class="CREDENTIAL"' in app_source,
        "active_claim_requires_service_scope": (
            "required_scopes=(DEFAULT_SERVICE_SCOPE,)" in app_source
        ),
        "raw_tokens_excluded": policy.get("raw_tokens_included") is False,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "requirement": "S134",
        "slice": "1337",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "policy_issues": issues,
        "grant_count": policy["grant_count"],
        "service_count": len(policy["service_ids"]),
        "audience_count": len(policy["audiences"]),
        "next_slice": "1338",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_trust_scope_policy()
    if args.summary:
        print(
            "platform_trust_scope_policy="
            f"{result['status'].lower()} grants={result['grant_count']} "
            f"services={result['service_count']} audiences={result['audience_count']} "
            f"next={result['next_slice']}"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
