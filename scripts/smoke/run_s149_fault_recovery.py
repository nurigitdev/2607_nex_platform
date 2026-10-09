#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.preproduction_faults import (  # noqa: E402
    FaultRehearsalResult,
    FaultState,
    build_default_fault_plan,
    evaluate_fault_rehearsals,
    transition_fault_state,
)


def run_fault_recovery_acceptance() -> dict[str, Any]:
    plan = build_default_fault_plan(
        release_candidate_id="rc:s149:deterministic",
        workload_digest=hashlib.sha256(b"s149-workload").hexdigest(),
    )
    final_states = []
    results = []
    for scenario in plan["scenarios"]:
        state = FaultState(str(scenario["scenario_id"]))
        for index, event in enumerate(
            ("begin_injection", "degradation_observed", "begin_recovery", "recovery_verified"),
            start=1,
        ):
            state = transition_fault_state(state, event, changed_at_ms=index * 100)
        final_states.append(state)
        results.append(
            FaultRehearsalResult(
                scenario_id=state.scenario_id,
                final_state=state.state,
                detection_ms=500,
                recovery_ms=5_000,
            )
        )
    evaluation = evaluate_fault_rehearsals(plan, results)
    checks = {
        "plan_admitted": plan.get("admission") == "ADMITTED",
        "eight_scenarios_present": len(plan["scenarios"]) == 8,
        "five_fault_classes_present": len({item["fault_class"] for item in plan["scenarios"]}) == 5,
        "all_state_machines_recovered": all(item.state == "RECOVERED" for item in final_states),
        "all_revisions_complete": all(item.revision == 4 for item in final_states),
        "rehearsal_passed": evaluation.get("status") == "PASS",
        "detection_budget_satisfied": evaluation["checks"]["detection_budget_satisfied"],
        "recovery_budget_satisfied": evaluation["checks"]["recovery_budget_satisfied"],
        "zero_data_loss": evaluation["checks"]["zero_data_loss"],
        "zero_isolation_violations": evaluation["checks"]["zero_isolation_violations"],
        "zero_residue": evaluation["checks"]["zero_residue"],
        "provider_processes_not_mutated": evaluation["checks"]["provider_processes_not_mutated"],
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_fault_recovery_acceptance.v1",
        "slice": "1487",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "scenario_count": len(results),
            "fault_class_count": evaluation["summary"]["fault_class_count"],
            "recovered_count": evaluation["summary"]["recovered_count"],
            "residue_count": evaluation["summary"]["residue_count"],
        },
        "next_slice": "1488" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_fault_recovery=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_fault_recovery=pass "
        f"scenarios={summary.get('scenario_count', 0)} "
        f"classes={summary.get('fault_class_count', 0)} "
        f"recovered={summary.get('recovered_count', 0)} "
        f"residue={summary.get('residue_count', -1)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_fault_recovery_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

