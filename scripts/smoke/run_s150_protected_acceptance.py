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
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_runtime.production_release import (  # noqa: E402
    RELEASE_GATE_NAMES,
    canonical_digest,
    evaluate_release_decision_gates,
)
from run_s150_release_decision import SOURCE_PATHS  # noqa: E402


ACTIVATION_ENV = "NEX_S150_PROTECTED_ACCEPTANCE"
PROFILE_ENV = "NEX_S150_PROTECTED_ACCEPTANCE_PROFILE"
DEFAULT_PROFILE = "test"
DEFAULT_DECISION = ROOT / "reports/deployment/s150-release-decision.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-protected-acceptance.json"


def run_protected_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    source_paths: Mapping[str, Path] = SOURCE_PATHS,
    decision_path: Path = DEFAULT_DECISION,
    output_path: Path = DEFAULT_OUTPUT,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": f"--execute and {ACTIVATION_ENV}=1 are required",
            "slice": "1503",
            "requirement": "S150",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")
    if set(source_paths) != set(SOURCE_PATHS):
        return _failure("protected_acceptance_source_inventory_invalid")
    sources = {name: _load_json(path) for name, path in source_paths.items()}
    decision = _load_json(decision_path)
    if any(not value for value in sources.values()) or not decision:
        return _failure("protected_acceptance_evidence_unavailable")
    try:
        replay = evaluate_release_decision_gates(
            sources["manifest"],
            sources["admission"],
            sources["risk_governance"],
            sources["approval_governance"],
            sources["immediate_preflight"],
            sources["rollback_rehearsal"],
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
        source_digests = {
            name: canonical_digest(value) for name, value in sources.items()
        }
        decision_digests = _mapping(decision.get("source_evidence_digests"))
        gate_results = _mapping(decision.get("gate_results"))
        failed_gates = decision.get("failed_gates")
        failed_gate_list = (
            list(failed_gates)
            if isinstance(failed_gates, list)
            and all(isinstance(item, str) for item in failed_gates)
            else []
        )
        decision_value = decision.get("decision")
        decision_consistent = (
            (decision_value == "GO" and not failed_gate_list)
            or (decision_value == "NO_GO" and bool(failed_gate_list))
        )
        checks = {
            "source_inventory_exact": set(sources) == set(SOURCE_PATHS),
            "source_digests_exact": source_digests == decision_digests,
            "decision_replay_exact": (
                replay.get("decision") == decision_value
                and replay.get("gate_results") == gate_results
                and replay.get("failed_gates") == failed_gate_list
            ),
            "mandatory_gate_inventory_exact": (
                decision.get("gate_order") == list(RELEASE_GATE_NAMES)
                and set(gate_results) == set(RELEASE_GATE_NAMES)
                and len(gate_results) == 10
            ),
            "decision_state_consistent": decision_consistent,
            "exact_release_candidate_bound": (
                decision.get("release_candidate_id")
                == sources["manifest"].get("release_candidate_id")
                and decision.get("release_set_digest")
                == sources["manifest"].get("release_set_digest")
            ),
            "single_host_backlog_preserved": sources["manifest"].get(
                "single_host_backlog_count"
            )
            == 5,
            "immediate_preflight_current": replay["gate_results"].get(
                "evidence_fresh"
            )
            is True,
            "decision_contract_exact": (
                decision.get("status") == "PASS"
                and decision.get("go_authorized") is (decision_value == "GO")
                and decision_value in {"GO", "NO_GO"}
            ),
            "production_deployment_separate": (
                replay["gate_results"].get("production_deployment_separate")
                is True
                and decision.get("implicit_deployment_performed") is False
                and decision.get("production_deployment_approved") is False
            ),
        }
        failed_checks = sorted(name for name, passed in checks.items() if not passed)
        result = {
            "evidence_schema_version": "s150_protected_acceptance.v1",
            "slice": "1503",
            "requirement": "S150",
            "status": "PASS" if not failed_checks else "FAIL",
            "failure_code": None
            if not failed_checks
            else "s150_protected_acceptance_failed",
            "release_candidate_id": decision.get("release_candidate_id"),
            "release_set_digest": decision.get("release_set_digest"),
            "release_decision": decision_value,
            "gate_results": gate_results,
            "failed_gates": failed_gate_list,
            "checks": checks,
            "failed_checks": failed_checks,
            "summary": {
                "check_count": len(checks),
                "passed_check_count": sum(checks.values()),
                "gate_count": len(gate_results),
                "passed_gate_count": sum(gate_results.values()),
                "failed_gate_count": len(failed_gate_list),
                "distributed_backlog_count": 5,
            },
            "source_evidence_digests": source_digests,
            "go_live_authorized": decision_value == "GO" and not failed_checks,
            "implicit_deployment_performed": False,
            "production_deployment_approved": False,
            "next_slice": "1504" if not failed_checks else "blocked",
        }
        if result["status"] == "PASS":
            _write_json(output_path, result)
        return result
    except (TypeError, ValueError) as exc:
        return _failure(
            "protected_acceptance_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )


def _failure(
    code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": "s150_protected_acceptance.v1",
        "slice": "1503",
        "requirement": "S150",
        "status": "FAIL",
        "failure_code": code,
        "release_decision": "NO_GO",
        "go_live_authorized": False,
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
        return "s150_protected_acceptance=skipped"
    if result.get("status") != "PASS":
        return "s150_protected_acceptance=fail"
    summary = _mapping(result.get("summary"))
    return (
        "s150_protected_acceptance=pass "
        f"decision={result.get('release_decision')} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"backlog={summary.get('distributed_backlog_count', 0)} next=1504"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    for name, path in SOURCE_PATHS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, default=path)
    parser.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_protected_acceptance(
        execute=args.execute,
        source_paths={name: getattr(args, name) for name in SOURCE_PATHS},
        decision_path=args.decision,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
