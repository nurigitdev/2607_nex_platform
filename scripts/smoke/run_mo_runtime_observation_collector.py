#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability_collector import (  # noqa: E402
    collect_runtime_observations,
)
from nex_mo.runtime_observability_plan import (  # noqa: E402
    build_runtime_observation_plan,
)


def run_mo_runtime_observation_collector() -> dict[str, Any]:
    snapshot = collect_runtime_observations(build_runtime_observation_plan({})).to_wire()
    serialized = json.dumps(snapshot, sort_keys=True)
    checks = {
        "mock_snapshot_healthy": snapshot["runtime_status"] == "HEALTHY",
        "three_models_collected": len(snapshot["models"]) == 3,
        "network_not_required": snapshot["observation_mode"] == "mock",
        "private_runtime_values_omitted": all(
            token not in serialized
            for token in (
                "ssh_target",
                "process_id",
                "process_command_line",
                "model_path",
                "gpu_uuid",
            )
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observation_collector.v1",
        "slice": "1165",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_runtime_observation_collector_failed"
        ),
        "checks": checks,
        "summary": {
            "model_count": len(snapshot["models"]),
            "healthy_count": snapshot["summary"]["status_counts"]["HEALTHY"],
            "private_field_count": 0 if checks["private_runtime_values_omitted"] else 1,
        },
        "next_slice": "1166",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observation_collector="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"models={summary.get('model_count', 0)} "
        f"healthy={summary.get('healthy_count', 0)} "
        f"private_fields={summary.get('private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observation_collector()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
