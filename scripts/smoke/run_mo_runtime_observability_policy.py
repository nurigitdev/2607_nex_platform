#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability_policy import (  # noqa: E402
    RuntimeObservationThresholds,
    classify_runtime_observation,
)


def _decision(**overrides: object):
    values: dict[str, object] = {
        "process_count": 1,
        "expected_model_seen": True,
        "requested_dtype": "bfloat16",
        "loaded_dtype": "bfloat16",
        "nvidia_available": True,
        "gpu_count": 1,
        "gpu_memory_used_mib": 4096,
        "gpu_memory_total_mib": 8192,
        "gpu_utilization_percent": 95.0,
        "gpu_temperature_c": 55.0,
        "thresholds": RuntimeObservationThresholds(),
    }
    values.update(overrides)
    return classify_runtime_observation(**values)  # type: ignore[arg-type]


def run_mo_runtime_observability_policy() -> dict[str, Any]:
    healthy = _decision()
    memory_pressure = _decision(gpu_memory_used_mib=7373)
    temperature_pressure = _decision(gpu_temperature_c=85.0)
    checks = {
        "healthy_runtime_accepted": healthy.runtime_status == "HEALTHY",
        "high_utilization_not_degraded": healthy.runtime_status == "HEALTHY",
        "memory_pressure_degraded": memory_pressure.runtime_status == "DEGRADED",
        "temperature_pressure_degraded": temperature_pressure.runtime_status
        == "DEGRADED",
        "resource_failure_code_stable": memory_pressure.failure_code
        == "gpu_runtime_resource_pressure",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_policy.v1",
        "slice": "1168",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_observability_policy_failed",
        "checks": checks,
        "summary": {
            "memory_warn_percent": 90.0,
            "temperature_warn_c": 85.0,
            "policy_case_count": 3,
        },
        "next_slice": "1169",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observability_policy="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"memory_warn={summary.get('memory_warn_percent', 0)} "
        f"temperature_warn={summary.get('temperature_warn_c', 0)} "
        f"cases={summary.get('policy_case_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observability_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
