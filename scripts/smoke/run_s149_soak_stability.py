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

from nex_runtime.preproduction_soak import (  # noqa: E402
    SoakWindow,
    evaluate_soak_windows,
)
from nex_runtime.preproduction_workload import (  # noqa: E402
    admit_workload_profile,
    build_default_workload_profiles,
)


def run_soak_stability_acceptance() -> dict[str, Any]:
    release_candidate_id = "rc:s149:deterministic"
    profile = build_default_workload_profiles(release_candidate_id)[2]
    admitted = admit_workload_profile(
        profile,
        expected_release_candidate_id=release_candidate_id,
    )
    windows = tuple(
        SoakWindow(
            window_id=f"window:{index}",
            sequence=index,
            duration_seconds=300.0,
            request_count=1_200,
            error_rate=0.001,
            p95_latency_ms=1_000.0 + index * 5.0,
            throughput_rps=4.0,
            saturation_ratio=0.60,
            process_memory_bytes=100_000_000 + index * 500_000,
            open_connection_count=10,
            queue_age_ms=20.0 + index,
        )
        for index in range(6)
    )
    result = evaluate_soak_windows(admitted, windows)
    checks = {
        "soak_evaluation_passed": result.get("status") == "PASS",
        "all_windows_observed": result["metrics"]["window_count"] == 6,
        "full_duration_observed": result["metrics"]["duration_seconds"] == 1_800.0,
        "all_requests_accounted": result["metrics"]["request_count"] == 7_200,
        "memory_stable": result["checks"]["memory_trend_stable"],
        "connections_stable": result["checks"]["connection_trend_stable"],
        "queue_stable": result["checks"]["queue_age_trend_stable"],
        "tail_stable": result["checks"]["tail_error_stable"]
        and result["checks"]["tail_latency_stable"],
        "zero_duplicates": result["metrics"]["duplicate_side_effect_count"] == 0,
        "zero_isolation_violations": result["metrics"]["isolation_violation_count"] == 0,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_soak_stability_acceptance.v1",
        "slice": "1486",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "window_count": result["metrics"]["window_count"],
            "duration_seconds": result["metrics"]["duration_seconds"],
            "request_count": result["metrics"]["request_count"],
        },
        "next_slice": "1487" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_soak_stability=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_soak_stability=pass "
        f"windows={summary.get('window_count', 0)} "
        f"duration={summary.get('duration_seconds', 0):g}s "
        f"requests={summary.get('request_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_soak_stability_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

