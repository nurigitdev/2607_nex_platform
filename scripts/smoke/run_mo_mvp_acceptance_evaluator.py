#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_mo_mvp_acceptance,
)


SCHEMA_VERSION = "mo_mvp_acceptance_evaluator_evidence.v1"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
OBSERVED_AT = "2026-10-01T08:30:00Z"


def build_passing_evidence() -> dict[str, Any]:
    common = {"status": "PASS", "observed_at": OBSERVED_AT}
    return {
        "mo_requirement_closures": {
            **common,
            "requirement_count": 9,
            "issue_count": 0,
        },
        "contract_validation": {
            **common,
            "schema_count": 129,
            "example_count": 187,
            "negative_fixture_count": 155,
            "openapi_count": 7,
        },
        "unit_regression": {
            **common,
            "passed_tests": 9608,
            "failed_tests": 0,
        },
        "statement_coverage": {**common, "percent": 98.61},
        "branch_coverage": {**common, "percent": 97.00},
        "postgres_smoke": {
            **common,
            "backend": "postgresql",
            "database": "nex_mo_test",
            "zero_residue": True,
        },
        "live_provider_acceptance": {
            **common,
            "provider_models": {
                "embedding": "Qwen3-Embedding-4B",
                "reranking": "Qwen3-Reranker-4B",
                "generation": "Qwen3.5-4B",
            },
            "ready_capabilities": 3,
            "failed_calls": 0,
            "explicit_bfloat16": True,
        },
        "privacy_failure_runbooks": {**common, "runbook_count": 4},
        "oa_transition_handoff": {
            **common,
            "target_service": "nex-oa",
            "manifest_status": "SEALED",
        },
    }


def run_mo_mvp_acceptance_evaluator() -> dict[str, Any]:
    first = evaluate_mo_mvp_acceptance(build_passing_evidence(), now=NOW)
    second = evaluate_mo_mvp_acceptance(build_passing_evidence(), now=NOW)
    checks = {
        "accepted": first["status"] == "ACCEPTED",
        "ready_for_oa": first["transition_status"] == "READY_FOR_OA",
        "all_gates_passed": first["summary"]
        == {"gate_count": 9, "passed_gate_count": 9, "blocked_gate_count": 0},
        "deterministic": first == second,
        "raw_evidence_excluded": first["raw_evidence_included"] is False,
        "acceptance_id_sha256": len(first["acceptance_id"]) == 64,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1195",
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_mvp_acceptance_evaluator_failed",
        "summary": {
            **first["summary"],
            "deterministic": checks["deterministic"],
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "checks": checks,
        "report": first,
        "next_slice": "1196" if passed else "blocked",
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        "mo_mvp_acceptance_evaluator="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"blocked={summary.get('blocked_gate_count', 0)} "
        f"deterministic={str(summary.get('deterministic', False)).lower()} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_mo_mvp_acceptance_evaluator()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
