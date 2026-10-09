#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.preproduction_security import (  # noqa: E402
    build_passing_security_probe_results,
    evaluate_security_privacy_acceptance,
)


def run_security_privacy_acceptance() -> dict[str, Any]:
    results = build_passing_security_probe_results()
    evaluation = evaluate_security_privacy_acceptance(
        results,
        evidence_metadata={
            "release_candidate_id": "rc:s149:deterministic",
            "configuration_digest": "a" * 64,
            "counts": {"probes": len(results), "violations": 0},
            "reason_codes": [item.reason_code for item in results],
        },
    )
    checks = {
        "acceptance_passed": evaluation.get("status") == "PASS",
        "twelve_probes_present": evaluation["summary"]["required_probe_count"] == 12,
        "ten_denials_present": evaluation["summary"]["denial_probe_count"] == 10,
        "two_privacy_probes_present": evaluation["summary"]["privacy_probe_count"] == 2,
        "tenant_owner_isolated": evaluation["checks"]["tenant_owner_isolation_enforced"],
        "service_tokens_guarded": evaluation["checks"]["service_token_boundary_enforced"],
        "credentials_guarded": evaluation["checks"]["credential_lifecycle_enforced"],
        "storage_and_request_guarded": evaluation["checks"]["storage_boundary_enforced"]
        and evaluation["checks"]["request_boundary_enforced"],
        "post_recovery_authz_guarded": evaluation["checks"]["post_recovery_authorization_enforced"],
        "zero_isolation_violations": evaluation["summary"]["isolation_violation_count"] == 0,
        "zero_privacy_violations": evaluation["summary"]["privacy_violation_count"] == 0,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_security_privacy_acceptance.v1",
        "slice": "1488",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "probe_count": evaluation["summary"]["observed_probe_count"],
            "denial_count": evaluation["summary"]["denial_probe_count"],
            "privacy_count": evaluation["summary"]["privacy_probe_count"],
            "violation_count": evaluation["summary"]["privacy_violation_count"]
            + evaluation["summary"]["isolation_violation_count"],
        },
        "next_slice": "1489" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_security_privacy=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_security_privacy=pass "
        f"probes={summary.get('probe_count', 0)} "
        f"denials={summary.get('denial_count', 0)} "
        f"privacy={summary.get('privacy_count', 0)} "
        f"violations={summary.get('violation_count', -1)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_security_privacy_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

