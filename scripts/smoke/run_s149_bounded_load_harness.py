#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.preproduction_load import (  # noqa: E402
    OperationOutcome,
    build_load_plan,
    run_bounded_load,
)
from nex_runtime.preproduction_workload import (  # noqa: E402
    admit_workload_profile,
    build_default_workload_profiles,
)


def run_bounded_load_harness_acceptance() -> dict[str, Any]:
    release_candidate_id = "rc:s149:deterministic"
    profile = build_default_workload_profiles(release_candidate_id)[1]
    admitted = admit_workload_profile(
        profile,
        expected_release_candidate_id=release_candidate_id,
    )
    plan = build_load_plan(admitted, sample_count=70)

    def runner(request) -> OperationOutcome:
        time.sleep(0.001)
        digest = hashlib.sha256(request.request_id.encode("utf-8")).hexdigest()
        return OperationOutcome(
            status="SUCCESS",
            reason_code="completed",
            saturation_ratio=0.5,
            side_effect_digest=digest,
        )

    result = run_bounded_load(admitted, plan, runner)
    metrics = dict(result.get("metrics") or {})
    checks = {
        "load_result_passed": result.get("status") == "PASS",
        "all_requests_completed": metrics.get("request_count") == 70,
        "all_operations_exercised": len({item.operation_id for item in plan}) == 7,
        "concurrency_observed": int(metrics.get("peak_active") or 0) >= 2,
        "concurrency_bounded": int(metrics.get("peak_active") or 0)
        <= int(admitted["concurrency"]),
        "zero_errors": metrics.get("error_count") == 0,
        "zero_duplicates": metrics.get("duplicate_side_effect_count") == 0,
        "zero_isolation_violations": metrics.get("isolation_violation_count") == 0,
        "metadata_only_result": "requests" not in result and "payload" not in result,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_bounded_load_harness_acceptance.v1",
        "slice": "1485",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "request_count": metrics.get("request_count", 0),
            "operation_count": 7,
            "peak_active": metrics.get("peak_active", 0),
        },
        "next_slice": "1486" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_bounded_load_harness=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_bounded_load_harness=pass "
        f"requests={summary.get('request_count', 0)} "
        f"operations={summary.get('operation_count', 0)} "
        f"peak={summary.get('peak_active', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_bounded_load_harness_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

