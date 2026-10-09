#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import (  # noqa: E402
    canonical_digest,
    evaluate_release_approval_governance,
)


ACTIVATION_ENV = "NEX_S150_APPROVAL_GOVERNANCE"
DEFAULT_RISK = ROOT / "reports/deployment/s150-risk-governance.json"
DEFAULT_APPROVALS = ROOT / "reports/deployment/s150-release-approvals.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-approval-governance.json"


def run_approval_change_governance(
    *,
    risk_path: Path = DEFAULT_RISK,
    approval_path: Path = DEFAULT_APPROVALS,
    output_path: Path = DEFAULT_OUTPUT,
    environ: Mapping[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1499",
            "requirement": "S150",
        }
    risk = _load_json(risk_path)
    if risk.get("status") != "PASS":
        return _failure("S150 risk governance evidence is unavailable")
    approvals = _load_json(approval_path)
    if not approvals:
        approvals = {
            "decision_only": True,
            "deployment_execution_requested": False,
            "approvals": [],
        }
    try:
        governance = evaluate_release_approval_governance(
            approvals,
            expected_release_candidate_id=str(risk.get("release_candidate_id") or ""),
            expected_release_set_digest=str(risk.get("release_set_digest") or ""),
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
    except ValueError as exc:
        return _failure(str(exc))
    result = {
        "evidence_schema_version": "s150_approval_change_governance.v1",
        "slice": "1499",
        "requirement": "S150",
        "status": governance["status"],
        "failure_code": None
        if governance["status"] == "PASS"
        else "s150_approval_governance_invalid",
        "release_candidate_id": risk.get("release_candidate_id"),
        "release_set_digest": risk.get("release_set_digest"),
        "risk_evidence_digest": canonical_digest(risk),
        "gate_results": governance["gate_results"],
        "decision_readiness": governance["decision_readiness"],
        "missing_approval_roles": governance["missing_approval_roles"],
        "change_window_valid": governance["change_window_valid"],
        "errors": governance["errors"],
        "summary": governance["summary"],
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
        "next_slice": "1500" if governance["status"] == "PASS" else "blocked",
    }
    if result["status"] == "PASS":
        _write_json(output_path, result)
    return result


def _failure(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "failure_code": "s150_approval_governance_invalid",
        "reason": reason,
        "slice": "1499",
        "requirement": "S150",
        "next_slice": "blocked",
        "implicit_deployment_performed": False,
        "production_deployment_approved": False,
    }


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
        return "s150_approval_governance=skipped"
    if result.get("status") != "PASS":
        return "s150_approval_governance=fail"
    summary = dict(result.get("summary") or {})
    gates = dict(result.get("gate_results") or {})
    return (
        "s150_approval_governance=pass "
        f"roles={summary.get('approved_role_count', 0)}/"
        f"{summary.get('required_role_count', 0)} "
        f"window={str(result.get('change_window_valid', False)).lower()} "
        f"separate={str(gates.get('production_deployment_separate', False)).lower()} "
        f"readiness={result.get('decision_readiness')} next=1500"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--risk", type=Path, default=DEFAULT_RISK)
    parser.add_argument("--approvals", type=Path, default=DEFAULT_APPROVALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_approval_change_governance(
        risk_path=args.risk,
        approval_path=args.approvals,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
