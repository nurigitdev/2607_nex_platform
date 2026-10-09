#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.release_candidate_closure import (  # noqa: E402
    load_full_regression_evidence,
)


SCHEMA_VERSION = "s149_preproduction_acceptance_closure.v1"
ACTIVATION_ENV = "NEX_S149_CLOSURE"
ADMISSION_PATH_ENV = "NEX_S149_ADMISSION_PATH"
JUNIT_PATH_ENV = "NEX_S149_JUNIT_PATH"
COVERAGE_PATH_ENV = "NEX_S149_COVERAGE_PATH"
OUTPUT_PATH_ENV = "NEX_S149_CLOSURE_PATH"
DEFAULT_ADMISSION_PATH = (
    ROOT / "reports" / "deployment" / "s149-evidence-admission.json"
)
DEFAULT_JUNIT_PATH = ROOT / "reports" / "coverage" / "junit.xml"
DEFAULT_COVERAGE_PATH = ROOT / "reports" / "coverage" / "coverage.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "deployment" / "s149-closure.json"
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "platform_preproduction_reliability_acceptance.md"
CANONICAL_PATH = ROOT / "docs" / "57_platform_preproduction_reliability_acceptance.md"
QUALITY_GATE_PATH = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
S149_RUNNERS = (
    "run_s149_preproduction_acceptance_boundary.py",
    "run_s149_workload_profile.py",
    "run_s149_bounded_load_harness.py",
    "run_s149_soak_stability.py",
    "run_s149_fault_recovery.py",
    "run_s149_security_privacy.py",
    "run_s149_rollback_rehearsal.py",
    "run_s149_single_host_live_acceptance.py",
    "run_s149_release_bound_target_workload.py",
    "run_s149_under_load_fault_security_rollback.py",
    "run_s149_evidence_admission.py",
    "run_s149_preproduction_acceptance_closure.py",
)
RUNBOOK_TOKENS = (
    "Admission",
    "Protected Execution",
    "Full Gate",
    "Failure Triage",
    "Cleanup And Residue",
    "External Notification Waiver",
    "Single-host Backlog",
    "S150 Handoff",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RELEASE_ID = re.compile(r"rc:s149:[0-9a-f]{16}\Z")


def run_s149_preproduction_acceptance_closure(
    environ: Mapping[str, str] | None = None,
    *,
    admission_path: Path | None = None,
    junit_path: Path | None = None,
    coverage_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1494",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV}=1 is required.",
        }
    try:
        admission_file = admission_path or Path(
            env.get(ADMISSION_PATH_ENV) or DEFAULT_ADMISSION_PATH
        )
        junit_file = junit_path or Path(env.get(JUNIT_PATH_ENV) or DEFAULT_JUNIT_PATH)
        coverage_file = coverage_path or Path(
            env.get(COVERAGE_PATH_ENV) or DEFAULT_COVERAGE_PATH
        )
        admission = json.loads(admission_file.read_text(encoding="utf-8"))
        if not isinstance(admission, Mapping):
            raise ValueError("S149 admission evidence must be an object")
        full_regression = load_full_regression_evidence(
            junit_file,
            coverage_file,
            statement_min=95.0,
            branch_min=94.0,
        )
        result = _evaluate(
            admission,
            full_regression,
            admission_mtime=admission_file.stat().st_mtime,
            junit_mtime=junit_file.stat().st_mtime,
            coverage_mtime=coverage_file.stat().st_mtime,
            root=root,
        )
        target = output_path or Path(env.get(OUTPUT_PATH_ENV) or DEFAULT_OUTPUT_PATH)
        _write_evidence(target, result)
        return result
    except (OSError, ValueError, ET.ParseError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1494",
            "status": "FAIL",
            "failure_code": "s149_closure_input_failed",
            "diagnostics": {"exception_type": exc.__class__.__name__},
            "closure_readiness": "BLOCKED",
            "production_deployment_approved": False,
            "next_requirement": "blocked",
        }


def _evaluate(
    admission: Mapping[str, Any],
    full_regression: Mapping[str, Any],
    *,
    admission_mtime: float,
    junit_mtime: float,
    coverage_mtime: float,
    root: Path,
) -> dict[str, Any]:
    binding = _mapping(admission.get("release_binding"))
    admission_checks = _mapping(admission.get("checks"))
    admission_decision = _mapping(admission.get("s150_admission"))
    regression_metrics = _mapping(full_regression.get("metrics"))
    runbook = _read_text(root / RUNBOOK_PATH.relative_to(ROOT))
    canonical = _read_text(root / CANONICAL_PATH.relative_to(ROOT))
    quality_gate = _read_text(root / QUALITY_GATE_PATH.relative_to(ROOT))
    backlog = admission.get("single_host_backlog")
    runner_counts = {
        runner: quality_gate.count(runner) for runner in S149_RUNNERS
    }
    checks = {
        "admission_schema_and_status_valid": admission.get(
            "evidence_schema_version"
        )
        == "s149_evidence_admission.v1"
        and admission.get("slice") == "1493"
        and admission.get("status") == "PASS"
        and admission.get("next_slice") == "1494",
        "release_binding_valid": _RELEASE_ID.fullmatch(
            str(binding.get("release_candidate_id") or "")
        )
        is not None
        and _DIGEST.fullmatch(str(binding.get("release_set_digest") or ""))
        is not None
        and _DIGEST.fullmatch(str(binding.get("evidence_chain_digest") or ""))
        is not None,
        "all_admission_checks_passed": len(admission_checks) == 14
        and all(value is True for value in admission_checks.values()),
        "single_host_backlog_preserved": isinstance(backlog, list)
        and len(backlog) == 5
        and all(
            _mapping(item).get("disposition") == "NOT_APPLICABLE_SINGLE_HOST"
            for item in backlog
        ),
        "fresh_full_regression_passed": full_regression.get("status") == "PASS"
        and regression_metrics.get("failed_test_count") == 0
        and regression_metrics.get("statement_coverage", 0) >= 95.0
        and regression_metrics.get("branch_coverage", 0) >= 94.0,
        "full_regression_evidence_is_fresh": junit_mtime >= admission_mtime
        and coverage_mtime >= admission_mtime,
        "operator_runbook_complete": bool(runbook)
        and all(token in runbook for token in RUNBOOK_TOKENS),
        "all_s149_runners_registered_once": all(
            count == 1 for count in runner_counts.values()
        ),
        "canonical_closure_and_handoff_recorded": all(
            token in canonical
            for token in (
                "Status: S149 complete; S150 active.",
                "Full Gate runs at Slice 1494",
                "Production deployment remains unapproved",
            )
        ),
        "production_go_guard_preserved": admission_decision.get("status")
        == "CONDITIONALLY_READY"
        and admission_decision.get("external_notification_waiver")
        == "REQUIRED_NOT_GRANTED"
        and admission_decision.get("production_go_eligible") is False,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1494",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s149_closure_failed",
        "closure_readiness": (
            "S149_COMPLETE_S150_ACTIVE" if passed else "BLOCKED"
        ),
        "release_binding": {
            "release_candidate_id": binding.get("release_candidate_id"),
            "release_set_digest": binding.get("release_set_digest"),
            "admission_evidence_digest": _digest(admission),
            "full_regression_evidence_digest": full_regression.get(
                "evidence_digest"
            ),
        },
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "runner_registration_counts": runner_counts,
        "full_regression": {
            "status": full_regression.get("status"),
            "passed_test_count": regression_metrics.get("passed_test_count"),
            "failed_test_count": regression_metrics.get("failed_test_count"),
            "skipped_test_count": regression_metrics.get("skipped_test_count"),
            "statement_coverage": regression_metrics.get("statement_coverage"),
            "statement_coverage_min": 95.0,
            "branch_coverage": regression_metrics.get("branch_coverage"),
            "branch_coverage_min": 94.0,
        },
        "s150_handoff": {
            "status": "ACTIVE_WITH_PRODUCTION_GO_GUARD" if passed else "BLOCKED",
            "external_notification_waiver": "REQUIRED_NOT_GRANTED",
            "local_compensating_control_required": True,
            "production_go_eligible": False,
        },
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "registered_runner_count": sum(
                count == 1 for count in runner_counts.values()
            ),
            "backlog_count": len(backlog) if isinstance(backlog, list) else 0,
            "passed_test_count": regression_metrics.get("passed_test_count", 0),
        },
        "production_deployment_approved": False,
        "next_requirement": "S150" if passed else "blocked",
    }


def _write_evidence(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s149_preproduction_acceptance_closure=skipped"
    summary = _mapping(result.get("summary"))
    regression = _mapping(result.get("full_regression"))
    return (
        "s149_preproduction_acceptance_closure="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"runners={summary.get('registered_runner_count', 0)}/12 "
        f"tests={summary.get('passed_test_count', 0)} "
        f"coverage={regression.get('statement_coverage', 0)}/"
        f"{regression.get('branch_coverage', 0)} "
        f"next={result.get('next_requirement') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_s149_preproduction_acceptance_closure(
        admission_path=args.admission,
        junit_path=args.junit,
        coverage_path=args.coverage,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
