#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.mvp_acceptance import build_mo_mvp_acceptance_policy  # noqa: E402


SCHEMA_VERSION = "mo_mvp_acceptance_policy_evidence.v1"


def run_mo_mvp_acceptance_policy() -> dict[str, Any]:
    policy = build_mo_mvp_acceptance_policy({})
    gates = policy["gates"]
    checks = {
        "scope_frozen": policy["acceptance_scope"] == "nex_mo_service_mvp",
        "oa_transition_frozen": policy["transition_target"] == "nex-oa",
        "nine_blocking_gates": len(gates) == 9
        and all(gate["severity"] == "BLOCKING" for gate in gates),
        "required_gates_fail_closed": all(
            gate["required_status"] == "PASS" and not gate["skipped_allowed"]
            for gate in gates
        ),
        "coverage_thresholds_hardened": policy["coverage"]
        == {
            "statement_min_percent": 98.0,
            "branch_min_percent": 96.0,
            "project_floor_statement_percent": 95.0,
            "project_floor_branch_percent": 85.0,
        },
        "regression_floor_hardened": policy["regression"]
        == {"minimum_passed_tests": 9000, "failed_tests_allowed": 0},
        "actual_postgres_required": policy["database"]["required_database"]
        == "nex_mo_test"
        and policy["database"]["zero_residue_required"] is True,
        "three_live_models_required": policy["live_providers"][
            "required_capabilities"
        ]
        == 3
        and len(policy["live_providers"]["required_models"]) == 3,
        "raw_evidence_excluded": policy["evidence"][
            "raw_evidence_in_projection"
        ]
        is False,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1193",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_mvp_acceptance_policy_failed",
        "summary": {
            "gate_count": len(gates),
            "blocking_gate_count": sum(
                gate["severity"] == "BLOCKING" for gate in gates
            ),
            "max_evidence_age_hours": policy["evidence"]["max_age_hours"],
            "minimum_regression_tests": policy["regression"][
                "minimum_passed_tests"
            ],
            "statement_min_percent": policy["coverage"][
                "statement_min_percent"
            ],
            "branch_min_percent": policy["coverage"]["branch_min_percent"],
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "checks": checks,
        "policy": policy,
        "next_slice": "1194" if passed else "blocked",
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "mo_mvp_acceptance_policy="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"gates={summary.get('blocking_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"freshness={summary.get('max_evidence_age_hours', 0)}h "
        f"regression={summary.get('minimum_regression_tests', 0)} "
        f"coverage={summary.get('statement_min_percent', 0)}/"
        f"{summary.get('branch_min_percent', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_mo_mvp_acceptance_policy()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
