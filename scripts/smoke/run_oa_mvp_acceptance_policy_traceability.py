#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.mvp_acceptance import (  # noqa: E402
    OA_MVP_REQUIREMENTS,
    build_oa_mvp_acceptance_policy,
    evaluate_oa_mvp_acceptance_inputs,
)
from nex_oa.mvp_acceptance_traceability import (  # noqa: E402
    build_oa_mvp_traceability_inventory,
)


SCHEMA_VERSION = "oa_mvp_acceptance_policy_traceability_evidence.v1"


def run_oa_mvp_acceptance_policy_traceability(
    root: Path = ROOT,
) -> dict[str, Any]:
    policy = build_oa_mvp_acceptance_policy()
    inventory = build_oa_mvp_traceability_inventory(root)
    dry_run = evaluate_oa_mvp_acceptance_inputs(
        {
            "repository": True,
            "postgres_restart": False,
            "key_rotation": False,
            "revocation": False,
            "cross_service": False,
            "failure_audit": True,
            "contracts_privacy": False,
            "full_gate": False,
        }
    )
    requirement_ids = tuple(
        item["requirement_id"] for item in policy["requirements"]
    )
    priorities = tuple(item["priority"] for item in policy["requirements"])
    checks = {
        "five_requirements_exact": requirement_ids == OA_MVP_REQUIREMENTS,
        "must_should_priorities_exact": priorities
        == ("MUST", "MUST", "MUST", "MUST", "SHOULD"),
        "all_repository_evidence_present": (
            inventory["ready_count"] == 5
            and inventory["missing_evidence_count"] == 0
        ),
        "actual_postgres_required": all(
            item["actual_postgres_required"]
            for item in policy["requirements"]
        ),
        "restart_required": all(
            item["restart_required"] for item in policy["requirements"]
        ),
        "browser_and_service_profiles_separated": (
            policy["browser_access_profile"] == "OPAQUE_OA_BACKED_SESSION"
            and policy["service_access_profile"] == "RS256_SIGNED_ONLY"
        ),
        "private_material_forbidden": (
            policy["raw_secret_or_token_evidence_allowed"] is False
            and policy["database_private_key_material_allowed"] is False
        ),
        "live_gates_fail_closed_until_executed": (
            dry_run["status"] == "BLOCKED"
            and dry_run["passed_gate_count"] == 2
            and dry_run["gate_count"] == 8
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1294",
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "oa_mvp_acceptance_policy_traceability_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "policy": policy,
        "inventory": inventory,
        "dry_run": dry_run,
        "summary": {
            "requirement_count": inventory["requirement_count"],
            "ready_count": inventory["ready_count"],
            "evidence_count": sum(
                item["evidence_count"] for item in inventory["requirements"]
            ),
            "live_gate_count": dry_run["gate_count"] - 2,
            "new_table_count": len(policy["new_tables"]),
        },
        "next_slice": "1295" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_mvp_acceptance_policy_traceability="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"requirements={summary.get('ready_count', 0)}/"
        f"{summary.get('requirement_count', 0)} "
        f"evidence={summary.get('evidence_count', 0)} "
        f"live_gates={summary.get('live_gate_count', 0)} "
        f"tables={summary.get('new_table_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_mvp_acceptance_policy_traceability()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
