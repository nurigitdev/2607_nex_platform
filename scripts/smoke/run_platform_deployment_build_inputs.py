#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_locks import (  # noqa: E402
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
    deployment_build_inputs_projection,
)


SCHEMA_VERSION = "platform_deployment_build_inputs_evidence.v1"


def run_platform_deployment_build_inputs(root: Path = ROOT) -> dict[str, Any]:
    inputs = build_deployment_build_inputs(root)
    projection = deployment_build_inputs_projection(inputs)
    lock_by_id = {item["lock_id"]: item for item in projection["locks"]}
    passed = (
        projection["python_runtime"] == "3.12"
        and projection["node_runtime"] == "22"
        and set(lock_by_id) == {"python-production", "node-production"}
        and lock_by_id["python-production"]["package_count"] >= 40
        and lock_by_id["node-production"]["package_count"] == 4
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1414",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "build_inputs_digest": deployment_build_inputs_digest(inputs),
        "build_inputs": projection,
        "summary": {
            "lock_count": len(projection["locks"]),
            "python_package_count": lock_by_id["python-production"]["package_count"],
            "python_hash_count": lock_by_id["python-production"]["integrity_count"],
            "node_package_count": lock_by_id["node-production"]["package_count"],
            "node_integrity_count": lock_by_id["node-production"]["integrity_count"],
        },
        "decision": {
            "range_only_install_allowed": False,
            "python_require_hashes_required": True,
            "node_npm_ci_required": True,
            "production_connection_required": False,
            "next_slice": "1415" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_deployment_build_inputs=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_deployment_build_inputs=pass "
        f"locks={summary.get('lock_count', 0)} "
        f"python_packages={summary.get('python_package_count', 0)} "
        f"python_hashes={summary.get('python_hash_count', 0)} "
        f"node_packages={summary.get('node_package_count', 0)} "
        f"node_integrity={summary.get('node_integrity_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_deployment_build_inputs()
    except ValueError as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

