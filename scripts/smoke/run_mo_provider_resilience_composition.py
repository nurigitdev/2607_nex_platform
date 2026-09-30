#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_resilience import compose_provider_resilience  # noqa: E402
from nex_mo.provider_retry import build_provider_retry_policy  # noqa: E402


CAPABILITIES = ("embedding", "reranking", "generation")


def run_mo_provider_resilience_composition() -> dict[str, Any]:
    readiness = {
        "readiness_status": "READY",
        "checked_at": "2026-09-30T00:00:00Z",
        "cache_status": "FRESH",
        "required_capabilities": list(CAPABILITIES),
        "routes": [
            {
                "provider_capability": capability,
                "deployment_id": f"{capability}-deployment",
                "model_revision": f"{capability}-revision",
                "status": "READY",
            }
            for capability in CAPABILITIES
        ],
    }
    telemetry = [
        {
            "capability": "embedding",
            "request_count": 1,
            "attempt_count": 2,
            "retry_count": 1,
            "last_outcome": "success",
            "last_failure_kind": None,
        },
        {
            "capability": "generation",
            "request_count": 1,
            "attempt_count": 1,
            "retry_count": 0,
            "last_outcome": "failure",
            "last_failure_kind": "read_timeout",
        },
    ]
    policies = [build_provider_retry_policy(item, {}) for item in CAPABILITIES]
    snapshot = compose_provider_resilience(readiness, telemetry, policies)
    serialized = json.dumps(snapshot)
    providers = {item["capability"]: item for item in snapshot["providers"]}
    checks = {
        "readiness_and_execution_composed": snapshot["resilience_status"]
        == "DEGRADED",
        "successful_retry_not_degraded": providers["embedding"]["resilience_status"]
        == "HEALTHY",
        "retry_pressure_visible": providers["embedding"]["retry_observed"] is True,
        "last_failure_degrades_ready_route": providers["generation"][
            "resilience_status"
        ]
        == "DEGRADED",
        "idle_ready_route_healthy": providers["reranking"]["resilience_status"]
        == "HEALTHY",
        "private_runtime_values_absent": all(
            token not in serialized
            for token in ("provider.invalid", "api-key", "authorization_header")
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_resilience_composition.v1",
        "slice": "1148",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_resilience_composition_failed",
        "checks": checks,
        "snapshot": snapshot,
        "summary": {
            "capability_count": snapshot["summary"]["capability_count"],
            "retry_count": snapshot["summary"]["retry_count"],
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
        },
        "next_slice": "1149",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_resilience_composition="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_resilience_composition()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
