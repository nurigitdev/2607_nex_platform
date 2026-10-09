#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import (  # noqa: E402
    RELEASE_GATE_NAMES,
    canonical_digest,
    evaluate_release_decision_gates,
)


ACTIVATION_ENV = "NEX_S150_RELEASE_DECISION"
SOURCE_PATHS = {
    "manifest": ROOT / "reports/deployment/s150-release-manifest.json",
    "admission": ROOT / "reports/deployment/s150-evidence-admission.json",
    "risk_governance": ROOT / "reports/deployment/s150-risk-governance.json",
    "approval_governance": ROOT / "reports/deployment/s150-approval-governance.json",
    "immediate_preflight": ROOT / "reports/deployment/s150-immediate-preflight.json",
    "rollback_rehearsal": ROOT
    / "reports/deployment/s150-cutover-rollback-rehearsal.json",
}
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-release-decision.json"


def run_release_decision(
    environ: Mapping[str, str] | None = None,
    *,
    source_paths: Mapping[str, Path] = SOURCE_PATHS,
    output_path: Path = DEFAULT_OUTPUT,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1502",
            "requirement": "S150",
        }
    if set(source_paths) != set(SOURCE_PATHS):
        return _failure("release_decision_source_inventory_invalid")
    sources = {name: _load_json(path) for name, path in source_paths.items()}
    if any(not value for value in sources.values()):
        return _failure("release_decision_source_evidence_unavailable")
    try:
        evaluation = evaluate_release_decision_gates(
            sources["manifest"],
            sources["admission"],
            sources["risk_governance"],
            sources["approval_governance"],
            sources["immediate_preflight"],
            sources["rollback_rehearsal"],
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
    except ValueError as exc:
        return _failure(
            "release_decision_evaluation_failed",
            {"exception_type": exc.__class__.__name__},
        )
    result = {
        "evidence_schema_version": "s150_release_decision.v1",
        "slice": "1502",
        "requirement": "S150",
        "status": evaluation["status"],
        "failure_code": None,
        "decision": evaluation["decision"],
        "release_candidate_id": evaluation["release_candidate_id"],
        "release_set_digest": evaluation["release_set_digest"],
        "gate_order": list(RELEASE_GATE_NAMES),
        "gate_results": evaluation["gate_results"],
        "failed_gates": evaluation["failed_gates"],
        "summary": evaluation["summary"],
        "source_evidence_digests": {
            name: canonical_digest(value) for name, value in sources.items()
        },
        "go_authorized": evaluation["decision"] == "GO",
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
        "next_slice": "1503",
    }
    _write_json(output_path, result)
    return result


def _failure(
    code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": "s150_release_decision.v1",
        "slice": "1502",
        "requirement": "S150",
        "status": "FAIL",
        "failure_code": code,
        "decision": "NO_GO",
        "go_authorized": False,
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
        "next_slice": "blocked",
    }
    if diagnostics:
        result["diagnostics"] = dict(diagnostics)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
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
        return "s150_release_decision=skipped"
    if result.get("status") != "PASS":
        return "s150_release_decision=fail"
    summary = dict(result.get("summary") or {})
    return (
        "s150_release_decision=pass "
        f"decision={result.get('decision')} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"failed={summary.get('failed_gate_count', 0)} next=1503"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name, path in SOURCE_PATHS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, default=path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_release_decision(
        source_paths={name: getattr(args, name) for name in SOURCE_PATHS},
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
