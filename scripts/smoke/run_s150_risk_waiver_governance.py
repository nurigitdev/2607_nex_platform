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
    evaluate_release_risk_governance,
)


ACTIVATION_ENV = "NEX_S150_RISK_GOVERNANCE"
DEFAULT_ADMISSION = ROOT / "reports/deployment/s150-evidence-admission.json"
DEFAULT_WAIVERS = ROOT / "reports/deployment/s150-p1-waivers.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-risk-governance.json"


def run_risk_waiver_governance(
    *,
    admission_path: Path = DEFAULT_ADMISSION,
    waiver_path: Path = DEFAULT_WAIVERS,
    output_path: Path = DEFAULT_OUTPUT,
    environ: Mapping[str, str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1498",
            "requirement": "S150",
        }
    admission = _load_json(admission_path)
    if admission.get("status") != "PASS":
        return _failure("fresh S150 evidence admission is unavailable")
    waivers_document = _load_json(waiver_path)
    waivers = waivers_document.get("waivers", []) if waivers_document else []
    if not isinstance(waivers, list):
        return _failure("waivers must be a list")
    risks = [
        {
            "risk_id": "external_notification_delivery",
            "priority": "P1",
            "status": "OPEN",
            "owner": "ag_operations_owner",
        }
    ]
    try:
        governance = evaluate_release_risk_governance(
            risks,
            waivers,
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
    except ValueError as exc:
        return _failure(str(exc))
    result = {
        "evidence_schema_version": "s150_risk_waiver_governance.v1",
        "slice": "1498",
        "requirement": "S150",
        "status": governance["status"],
        "failure_code": None
        if governance["status"] == "PASS"
        else "s150_risk_governance_invalid",
        "release_candidate_id": admission.get("release_candidate_id"),
        "release_set_digest": admission.get("release_set_digest"),
        "admission_evidence_digest": canonical_digest(admission),
        "risk_inventory": risks,
        "gate_results": governance["gate_results"],
        "decision_readiness": governance["decision_readiness"],
        "errors": governance["errors"],
        "waiver_required_risk_ids": governance["waiver_required_risk_ids"],
        "summary": governance["summary"],
        "distributed_backlog_is_release_risk": False,
        "production_deployment_approved": False,
        "next_slice": "1499" if governance["status"] == "PASS" else "blocked",
    }
    if result["status"] == "PASS":
        _write_json(output_path, result)
    return result


def _failure(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "failure_code": "s150_risk_governance_invalid",
        "reason": reason,
        "slice": "1498",
        "requirement": "S150",
        "next_slice": "blocked",
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
        return "s150_risk_governance=skipped"
    if result.get("status") != "PASS":
        return "s150_risk_governance=fail"
    summary = dict(result.get("summary") or {})
    gates = dict(result.get("gate_results") or {})
    return (
        "s150_risk_governance=pass "
        f"p0_open={summary.get('open_p0_count', 0)} "
        f"p1_open={summary.get('open_p1_count', 0)} "
        f"p1_waivers_valid={str(gates.get('p1_waivers_valid', False)).lower()} "
        f"readiness={result.get('decision_readiness')} next=1499"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission", type=Path, default=DEFAULT_ADMISSION)
    parser.add_argument("--waivers", type=Path, default=DEFAULT_WAIVERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_risk_waiver_governance(
        admission_path=args.admission,
        waiver_path=args.waivers,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
