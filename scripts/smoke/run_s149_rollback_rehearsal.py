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

from nex_runtime.preproduction_rollback import (  # noqa: E402
    RollbackComponentResult,
    RollbackResidue,
    RollbackState,
    build_default_rollback_plan,
    evaluate_rollback_rehearsal,
    transition_rollback_state,
)


def run_rollback_rehearsal_acceptance() -> dict[str, Any]:
    plan = build_default_rollback_plan(
        release_candidate_id="rc:s149:deterministic",
        fault_plan_digest=hashlib.sha256(b"s149-fault-plan").hexdigest(),
    )
    state = RollbackState("rollback:s149:deterministic")
    for index, event in enumerate(
        ("trigger", "begin_restore", "begin_verification", "verification_passed"),
        start=1,
    ):
        state = transition_rollback_state(state, event, changed_at_ms=index * 1_000)
    results = tuple(
        RollbackComponentResult(
            component_id=str(item["component_id"]),
            restored_digest=str(item["last_known_good_digest"]),
            verification_passed=True,
        )
        for item in plan["components"]
    )
    evaluation = evaluate_rollback_rehearsal(
        plan,
        final_state=state,
        component_results=results,
        recovery_ms=120_000,
        residue=RollbackResidue(),
    )
    checks = {
        "plan_admitted": plan.get("admission") == "ADMITTED",
        "six_components_present": len(plan["components"]) == 6,
        "state_machine_completed": state.state == "COMPLETED" and state.revision == 4,
        "rehearsal_passed": evaluation.get("status") == "PASS",
        "all_components_verified": evaluation["checks"]["all_components_verified"],
        "last_known_good_exact": evaluation["checks"]["last_known_good_exact"],
        "recovery_budget_satisfied": evaluation["checks"]["recovery_budget_satisfied"],
        "committed_data_preserved": evaluation["checks"]["committed_data_preserved"],
        "zero_residue": evaluation["checks"]["zero_residue"],
        "production_not_targeted": evaluation["checks"]["production_not_targeted"],
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s149_rollback_rehearsal_acceptance.v1",
        "slice": "1489",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "component_count": evaluation["summary"]["component_count"],
            "verified_count": evaluation["summary"]["verified_component_count"],
            "recovery_ms": evaluation["summary"]["recovery_ms"],
            "residue_count": evaluation["summary"]["residue_count"],
        },
        "next_slice": "1490" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "s149_rollback_rehearsal=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s149_rollback_rehearsal=pass "
        f"components={summary.get('component_count', 0)} "
        f"verified={summary.get('verified_count', 0)} "
        f"recovery={summary.get('recovery_ms', 0)}ms "
        f"residue={summary.get('residue_count', -1)} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_rollback_rehearsal_acceptance()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

