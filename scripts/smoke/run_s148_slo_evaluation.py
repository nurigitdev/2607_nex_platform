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
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_ag.platform_slo import default_platform_slo_policies, evaluate_slo
from nex_runtime import ObservabilitySignal


def run_slo_evaluation() -> dict[str, Any]:
    policies = default_platform_slo_policies()
    evaluations = []
    for policy in policies:
        values = (10.0, 20.0, 30.0) if policy.comparator == "LTE" else (1.0, 1.0, 1.0)
        signals = [
            ObservabilitySignal(
                signal_id=f"signal:{policy.service_id}:{index}",
                service_id=policy.service_id,
                signal_kind="METRIC",
                signal_name=policy.signal_name,
                observed_at=f"2026-10-08T01:00:0{index}Z",
                severity="INFO",
                status="HEALTHY",
                correlation_key=f"slo:{policy.service_id}",
                measurements={policy.measurement_name: value},
                reason_codes=("SLO_SAMPLE",),
            )
            for index, value in enumerate(values, start=1)
        ]
        evaluations.append(
            evaluate_slo(policy, signals, evaluated_at="2026-10-08T01:00:30Z")
        )
    no_data = evaluate_slo(policies[0], [], evaluated_at="2026-10-08T01:00:30Z")
    checks = {
        "five_service_policies": len(policies) == 5,
        "policy_hashes_unique": len({policy.policy_hash for policy in policies}) == 5,
        "all_services_evaluated": len(evaluations) == 5,
        "healthy_fixture_passes": all(item["status"] == "HEALTHY" for item in evaluations),
        "no_data_fails_closed": no_data["status"] == "NO_DATA",
        "owners_and_runbooks_present": all(
            item["accountable_owner"] and item["runbook_ref"] for item in evaluations
        ),
        "policy_hash_bound": all(item["policy_hash"].startswith("sha256:") for item in evaluations),
        "private_payload_absent": all(
            item["private_payload_included"] is False for item in evaluations
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": "s148_slo_evaluation.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "policy_count": len(policies),
            "evaluation_count": len(evaluations),
            "healthy_count": sum(item["status"] == "HEALTHY" for item in evaluations),
            "no_data_count": int(no_data["status"] == "NO_DATA"),
        },
        "next_slice": "1476" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        "s148_slo_evaluation="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"policies={summary.get('policy_count', 0)} "
        f"healthy={summary.get('healthy_count', 0)} "
        f"no_data={summary.get('no_data_count', 0)} "
        f"checks={sum(bool(value) for value in dict(result.get('checks') or {}).values())}/8 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_slo_evaluation()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
