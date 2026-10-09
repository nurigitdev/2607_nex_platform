#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import (  # noqa: E402
    RELEASE_GATE_NAMES,
    canonical_digest,
)
from nex_runtime.release_candidate_closure import (  # noqa: E402
    load_full_regression_evidence,
)


ACTIVATION_ENV = "NEX_S150_CLOSURE"
DEFAULT_PROTECTED = ROOT / "reports/deployment/s150-protected-acceptance.json"
DEFAULT_DECISION = ROOT / "reports/deployment/s150-release-decision.json"
DEFAULT_JUNIT = ROOT / "reports/coverage/junit.xml"
DEFAULT_COVERAGE = ROOT / "reports/coverage/coverage.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-closure.json"
RUNBOOK_PATH = ROOT / "docs/runbooks/platform_production_release_go_live.md"
CANONICAL_PATH = ROOT / "docs/58_platform_production_release_go_live.md"
QUALITY_GATE_PATH = ROOT / "scripts/quality/run_quality_gate.sh"
S150_RUNNERS = (
    "run_s150_production_release_boundary.py",
    "run_s150_release_evidence_manifest.py",
    "run_s150_evidence_freshness_admission.py",
    "run_s150_risk_waiver_governance.py",
    "run_s150_approval_change_governance.py",
    "run_s150_immediate_preflight.py",
    "run_s150_cutover_rollback_rehearsal.py",
    "run_s150_release_decision.py",
    "run_s150_protected_acceptance.py",
    "run_s150_production_release_closure.py",
)
RUNBOOK_TOKENS = (
    "Supported Topology",
    "Evidence Preparation",
    "Immediate Preflight",
    "Cutover And Rollback",
    "Decision Evaluation",
    "GO Procedure",
    "NO_GO Procedure",
    "Failure Triage",
    "Cleanup And Zero Residue",
    "Distributed Backlog",
    "Deployment Separation",
)
_RELEASE_ID = re.compile(r"rc:s149:[0-9a-f]{16}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def run_production_release_closure(
    environ: Mapping[str, str] | None = None,
    *,
    protected_path: Path = DEFAULT_PROTECTED,
    decision_path: Path = DEFAULT_DECISION,
    junit_path: Path = DEFAULT_JUNIT,
    coverage_path: Path = DEFAULT_COVERAGE,
    output_path: Path = DEFAULT_OUTPUT,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1504",
            "requirement": "S150",
        }
    try:
        protected = _load_object(protected_path)
        decision = _load_object(decision_path)
        regression = load_full_regression_evidence(
            junit_path,
            coverage_path,
            statement_min=95.0,
            branch_min=94.0,
        )
        result = _evaluate(
            protected,
            decision,
            regression,
            protected_mtime=protected_path.stat().st_mtime,
            junit_mtime=junit_path.stat().st_mtime,
            coverage_mtime=coverage_path.stat().st_mtime,
            root=root,
        )
        _write_json(output_path, result)
        return result
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ET.ParseError) as exc:
        return _failure(
            "s150_closure_input_failed",
            {"exception_type": exc.__class__.__name__},
        )


def _evaluate(
    protected: Mapping[str, Any],
    decision: Mapping[str, Any],
    regression: Mapping[str, Any],
    *,
    protected_mtime: float,
    junit_mtime: float,
    coverage_mtime: float,
    root: Path,
) -> dict[str, Any]:
    protected_checks = _mapping(protected.get("checks"))
    gate_results = _mapping(protected.get("gate_results"))
    failed_gates = protected.get("failed_gates")
    failed_gate_list = list(failed_gates) if isinstance(failed_gates, list) else []
    regression_metrics = _mapping(regression.get("metrics"))
    runbook = _read_text(root / RUNBOOK_PATH.relative_to(ROOT))
    canonical = _read_text(root / CANONICAL_PATH.relative_to(ROOT))
    quality_gate = _read_text(root / QUALITY_GATE_PATH.relative_to(ROOT))
    runner_counts = {runner: quality_gate.count(runner) for runner in S150_RUNNERS}
    release_decision = protected.get("release_decision")
    decision_consistent = (
        release_decision in {"GO", "NO_GO"}
        and release_decision == decision.get("decision")
        and protected.get("go_live_authorized")
        is (release_decision == "GO")
        and (
            (release_decision == "GO" and not failed_gate_list)
            or (release_decision == "NO_GO" and bool(failed_gate_list))
        )
    )
    checks = {
        "protected_acceptance_passed": (
            protected.get("evidence_schema_version")
            == "s150_protected_acceptance.v1"
            and protected.get("slice") == "1503"
            and protected.get("status") == "PASS"
            and protected.get("next_slice") == "1504"
            and len(protected_checks) == 10
            and all(protected_checks.values())
        ),
        "release_identity_valid": (
            _RELEASE_ID.fullmatch(
                str(protected.get("release_candidate_id") or "")
            )
            is not None
            and _DIGEST.fullmatch(str(protected.get("release_set_digest") or ""))
            is not None
            and protected.get("release_candidate_id")
            == decision.get("release_candidate_id")
            and protected.get("release_set_digest")
            == decision.get("release_set_digest")
        ),
        "ten_gate_decision_exact": (
            set(gate_results) == set(RELEASE_GATE_NAMES)
            and len(gate_results) == 10
            and failed_gate_list
            == [name for name in RELEASE_GATE_NAMES if not gate_results.get(name)]
            and decision_consistent
        ),
        "full_regression_passed": (
            regression.get("status") == "PASS"
            and regression_metrics.get("failed_test_count") == 0
            and float(regression_metrics.get("statement_coverage") or 0) >= 95.0
            and float(regression_metrics.get("branch_coverage") or 0) >= 94.0
        ),
        "full_regression_evidence_fresh": (
            junit_mtime >= protected_mtime and coverage_mtime >= protected_mtime
        ),
        "operator_runbook_complete": bool(runbook)
        and all(token in runbook for token in RUNBOOK_TOKENS),
        "all_s150_runners_registered_once": all(
            count == 1 for count in runner_counts.values()
        ),
        "canonical_closure_recorded": all(
            token in canonical
            for token in (
                "Status: S150 complete.",
                f"Current release decision: `{release_decision}`.",
                "Production deployment remains unapproved.",
                "NOT_APPLICABLE_SINGLE_HOST",
            )
        ),
        "distributed_backlog_preserved": _mapping(protected.get("summary")).get(
            "distributed_backlog_count"
        )
        == 5,
        "production_deployment_separate": (
            protected.get("implicit_deployment_performed") is False
            and protected.get("production_deployment_approved") is False
            and decision.get("implicit_deployment_performed") is False
            and decision.get("production_deployment_approved") is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": "s150_production_release_closure.v1",
        "slice": "1504",
        "requirement": "S150",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s150_closure_failed",
        "closure_status": "S150_COMPLETE" if passed else "BLOCKED",
        "release_candidate_id": protected.get("release_candidate_id"),
        "release_set_digest": protected.get("release_set_digest"),
        "release_decision": release_decision,
        "gate_results": gate_results,
        "failed_gates": failed_gate_list,
        "checks": checks,
        "failed_checks": failed_checks,
        "runner_registration_counts": runner_counts,
        "full_regression": {
            "status": regression.get("status"),
            "passed_test_count": regression_metrics.get("passed_test_count"),
            "failed_test_count": regression_metrics.get("failed_test_count"),
            "skipped_test_count": regression_metrics.get("skipped_test_count"),
            "statement_coverage": regression_metrics.get("statement_coverage"),
            "branch_coverage": regression_metrics.get("branch_coverage"),
            "evidence_digest": regression.get("evidence_digest"),
        },
        "source_evidence_digests": {
            "protected_acceptance": canonical_digest(protected),
            "release_decision": canonical_digest(decision),
        },
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "gate_count": len(gate_results),
            "passed_gate_count": sum(gate_results.values()),
            "failed_gate_count": len(failed_gate_list),
            "registered_runner_count": sum(
                count == 1 for count in runner_counts.values()
            ),
            "distributed_backlog_count": 5,
        },
        "go_live_authorized": passed and release_decision == "GO",
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
        "next_action": (
            "GO_LIVE_EXECUTION_REQUIRES_SEPARATE_HUMAN_ACTION"
            if passed and release_decision == "GO"
            else "RELEASE_GOVERNANCE_ACTION_REQUIRED"
            if passed
            else "BLOCKED"
        ),
    }


def _failure(
    code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": "s150_production_release_closure.v1",
        "slice": "1504",
        "requirement": "S150",
        "status": "FAIL",
        "failure_code": code,
        "closure_status": "BLOCKED",
        "release_decision": "NO_GO",
        "go_live_authorized": False,
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
        "next_action": "BLOCKED",
    }
    if diagnostics:
        result["diagnostics"] = dict(diagnostics)
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("closure evidence must be an object")
    return dict(value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s150_production_release_closure=skipped"
    summary = _mapping(result.get("summary"))
    regression = _mapping(result.get("full_regression"))
    return (
        "s150_production_release_closure="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"decision={result.get('release_decision')} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"tests={regression.get('passed_test_count', 0)} "
        f"coverage={regression.get('statement_coverage', 0)}/"
        f"{regression.get('branch_coverage', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protected", type=Path, default=DEFAULT_PROTECTED)
    parser.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    parser.add_argument("--junit", type=Path, default=DEFAULT_JUNIT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_production_release_closure(
        protected_path=args.protected,
        decision_path=args.decision,
        junit_path=args.junit,
        coverage_path=args.coverage,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
