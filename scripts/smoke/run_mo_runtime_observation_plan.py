#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability_plan import (  # noqa: E402
    build_runtime_observation_plan,
    project_runtime_observation_plan,
)


def run_mo_runtime_observation_plan() -> dict[str, Any]:
    plan = project_runtime_observation_plan(build_runtime_observation_plan({}))
    serialized = json.dumps(plan, sort_keys=True)
    checks = {
        "mock_mode_default": plan["mode"] == "mock",
        "mock_mode_configured": plan["configured"] is True,
        "three_capabilities_planned": plan["capabilities"]
        == ["embedding", "reranking", "generation"],
        "selected_models_complete": len(plan["model_revisions"]) == 3,
        "requested_dtype_complete": plan["requested_dtypes"]
        == ["bfloat16", "bfloat16", "bfloat16"],
        "private_configuration_omitted": all(
            token not in serialized
            for token in ("ssh_target", "process_port", "provider_api_key")
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observation_plan.v1",
        "slice": "1164",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_observation_plan_failed",
        "checks": checks,
        "summary": {
            "target_count": plan["target_count"],
            "model_count": len(plan["model_revisions"]),
            "dtype_count": len(plan["requested_dtypes"]),
        },
        "plan": plan,
        "next_slice": "1165",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observation_plan="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"targets={summary.get('target_count', 0)} "
        f"models={summary.get('model_count', 0)} "
        f"dtypes={summary.get('dtype_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observation_plan()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
