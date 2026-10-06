#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.release_candidate_closure import (  # noqa: E402
    RELEASE_CANDIDATE_CLOSURE_SCHEMA_VERSION,
    build_release_candidate_closure,
    load_full_regression_evidence,
)


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_CLOSURE"
PROTECTED_EVIDENCE_ENV = "NEX_S140_PROTECTED_EVIDENCE_PATH"
JUNIT_PATH_ENV = "NEX_S140_JUNIT_PATH"
COVERAGE_PATH_ENV = "NEX_S140_COVERAGE_PATH"
OUTPUT_PATH_ENV = "NEX_S140_CLOSURE_EVIDENCE_PATH"
DEFAULT_JUNIT_PATH = ROOT / "reports" / "coverage" / "junit.xml"
DEFAULT_COVERAGE_PATH = ROOT / "reports" / "coverage" / "coverage.json"


def run_s140_platform_release_candidate_closure(
    environ: Mapping[str, str] | None = None,
    *,
    protected_evidence_path: Path | None = None,
    junit_path: Path | None = None,
    coverage_path: Path | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_CLOSURE_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "readiness": "NOT_EVALUATED",
            "production_deployment_approved": False,
        }
    try:
        protected_path = protected_evidence_path or _required_path(
            env.get(PROTECTED_EVIDENCE_ENV), PROTECTED_EVIDENCE_ENV
        )
        junit = junit_path or Path(env.get(JUNIT_PATH_ENV) or DEFAULT_JUNIT_PATH)
        coverage = coverage_path or Path(
            env.get(COVERAGE_PATH_ENV) or DEFAULT_COVERAGE_PATH
        )
        protected = json.loads(protected_path.read_text(encoding="utf-8"))
        if not isinstance(protected, Mapping):
            raise ValueError("protected evidence must be an object")
        full_regression = load_full_regression_evidence(junit, coverage)
        return build_release_candidate_closure(protected, full_regression)
    except (OSError, ValueError, ET.ParseError):
        return {
            "schema_version": RELEASE_CANDIDATE_CLOSURE_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "platform_release_candidate_closure_input_failed",
            "readiness": "BLOCKED",
            "production_deployment_approved": False,
            "checks": {},
            "failed_checks": ["closure_inputs_valid"],
            "summary": {},
        }


def _required_path(value: str | None, name: str) -> Path:
    if not value:
        raise ValueError(f"{name} is required")
    return Path(value)


def write_evidence(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "s140_platform_release_candidate_closure=skip"
    summary = dict(result.get("summary") or {})
    return (
        "s140_platform_release_candidate_closure="
        f"{status.lower()} gates={summary.get('passed_gate_count', 0)}/9 "
        f"protected={summary.get('actual_protected_gate_count', 0)}/5 "
        f"tests={summary.get('passed_test_count', 0)} "
        f"privacy={summary.get('privacy_violation_count', 0)} "
        f"decision={result.get('readiness', 'BLOCKED')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--protected-evidence", type=Path)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_s140_platform_release_candidate_closure(
        protected_evidence_path=args.protected_evidence,
        junit_path=args.junit,
        coverage_path=args.coverage,
    )
    output = args.output or (
        Path(os.environ[OUTPUT_PATH_ENV]) if os.environ.get(OUTPUT_PATH_ENV) else None
    )
    if output is not None:
        write_evidence(output, result)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
