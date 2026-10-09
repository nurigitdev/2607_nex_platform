#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.preproduction_workload import (  # noqa: E402
    WorkloadProfileError,
    admit_workload_profile,
    build_default_workload_profiles,
)


def run_workload_profile_acceptance() -> dict[str, Any]:
    release_candidate_id = "rc:s149:deterministic"
    profiles = build_default_workload_profiles(release_candidate_id)
    admitted = [
        admit_workload_profile(
            profile,
            expected_release_candidate_id=release_candidate_id,
        )
        for profile in profiles
    ]
    mismatch_blocked = False
    try:
        admit_workload_profile(
            replace(profiles[0], release_candidate_id="rc:s149:other"),
            expected_release_candidate_id=release_candidate_id,
        )
    except WorkloadProfileError:
        mismatch_blocked = True
    checks = {
        "three_profiles_admitted": len(admitted) == 3,
        "workload_classes_exact": {item["workload_class"] for item in admitted}
        == {"baseline", "concurrency", "soak"},
        "release_binding_exact": all(
            item["release_candidate_id"] == release_candidate_id for item in admitted
        ),
        "operation_mix_complete": all(len(item["operations"]) == 7 for item in admitted),
        "digests_unique": len({item["workload_digest"] for item in admitted}) == 3,
        "production_capacity_not_claimed": all(
            item["production_capacity_claimed"] is False for item in admitted
        ),
        "candidate_mismatch_blocked": mismatch_blocked,
        "isolation_budget_zero": all(
            item["budget"]["max_isolation_violations"] == 0 for item in admitted
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_workload_profile_acceptance.v1",
        "slice": "1484",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "profiles": [
            {
                "profile_id": item["profile_id"],
                "workload_class": item["workload_class"],
                "concurrency": item["concurrency"],
                "target_rps": item["target_rps"],
                "measurement_seconds": item["measurement_seconds"],
                "operation_count": len(item["operations"]),
                "workload_digest": item["workload_digest"],
            }
            for item in admitted
        ],
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "profile_count": len(admitted),
            "operation_count": len(admitted[0]["operations"]) if admitted else 0,
        },
        "next_slice": "1485" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_workload_profile=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_workload_profile=pass "
        f"profiles={summary.get('profile_count', 0)} "
        f"operations={summary.get('operation_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_workload_profile_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

