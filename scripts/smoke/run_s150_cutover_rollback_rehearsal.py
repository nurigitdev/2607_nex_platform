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

from nex_runtime.preproduction_rollback import (  # noqa: E402
    RollbackComponentResult,
    RollbackResidue,
    RollbackState,
    build_default_rollback_plan,
    evaluate_rollback_rehearsal,
    transition_rollback_state,
)
from nex_runtime.production_release import (  # noqa: E402
    REQUIRED_CUTOVER_PHASES,
    canonical_digest,
    evaluate_cutover_rollback_rehearsal,
)


ACTIVATION_ENV = "NEX_S150_CUTOVER_ROLLBACK_REHEARSAL"
DEFAULT_MANIFEST = ROOT / "reports/deployment/s150-release-manifest.json"
DEFAULT_PREFLIGHT = ROOT / "reports/deployment/s150-immediate-preflight.json"
DEFAULT_UNDER_LOAD = ROOT / "reports/deployment/s149-under-load-acceptance.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/s150-cutover-rollback-rehearsal.json"


def run_cutover_rollback_rehearsal(
    environ: Mapping[str, str] | None = None,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    under_load_path: Path = DEFAULT_UNDER_LOAD,
    output_path: Path = DEFAULT_OUTPUT,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "status": "SKIPPED",
            "reason": ACTIVATION_ENV,
            "slice": "1501",
            "requirement": "S150",
        }
    manifest = _load_json(manifest_path)
    preflight = _load_json(preflight_path)
    under_load = _load_json(under_load_path)
    if not manifest or not preflight or not under_load:
        return _failure("required_rehearsal_evidence_unavailable")
    try:
        release_candidate_id = str(manifest.get("release_candidate_id") or "")
        release_set_digest = str(manifest.get("release_set_digest") or "")
        binding = _mapping(under_load.get("release_binding"))
        cutover_plan = {
            "control_schema_version": "s150_cutover_control_plan.v1",
            "release_candidate_id": release_candidate_id,
            "release_set_digest": release_set_digest,
            "topology": "single_host_docker_compose",
            "phases": list(REQUIRED_CUTOVER_PHASES),
            "rollback_trigger_count": 4,
            "dry_run_only": True,
            "deployment_execution_requested": False,
        }
        rollback_plan = build_default_rollback_plan(
            release_candidate_id=release_candidate_id,
            fault_plan_digest=str(binding.get("fault_plan_digest") or ""),
        )
        state = RollbackState(f"rollback:s150:{release_candidate_id.rsplit(':', 1)[-1]}")
        for index, event in enumerate(
            ("trigger", "begin_restore", "begin_verification", "verification_passed"),
            start=1,
        ):
            state = transition_rollback_state(
                state,
                event,
                changed_at_ms=index * 1_000,
            )
        component_results = tuple(
            RollbackComponentResult(
                component_id=str(item["component_id"]),
                restored_digest=str(item["last_known_good_digest"]),
                verification_passed=True,
            )
            for item in rollback_plan["components"]
        )
        rollback_evaluation = evaluate_rollback_rehearsal(
            rollback_plan,
            final_state=state,
            component_results=component_results,
            recovery_ms=120_000,
            residue=RollbackResidue(),
        )
        evaluation = evaluate_cutover_rollback_rehearsal(
            manifest,
            preflight,
            under_load,
            cutover_plan,
            rollback_plan,
            rollback_evaluation,
            evaluated_at=evaluated_at or datetime.now(UTC),
        )
        result = {
            "evidence_schema_version": "s150_cutover_rollback_rehearsal.v1",
            "slice": "1501",
            "requirement": "S150",
            "status": evaluation["status"],
            "failure_code": None
            if evaluation["status"] == "PASS"
            else "s150_cutover_rollback_rehearsal_failed",
            "release_candidate_id": evaluation["release_candidate_id"],
            "release_set_digest": evaluation["release_set_digest"],
            "checks": evaluation["checks"],
            "failed_checks": evaluation["failed_checks"],
            "summary": evaluation["summary"],
            "source_evidence_digests": {
                "manifest": canonical_digest(manifest),
                "immediate_preflight": canonical_digest(preflight),
                "under_load_acceptance": canonical_digest(under_load),
                "cutover_plan": canonical_digest(cutover_plan),
                "rollback_evaluation": canonical_digest(rollback_evaluation),
            },
            "cutover_execution_performed": False,
            "implicit_deployment_performed": False,
            "production_deployment_approved": False,
            "next_slice": "1502" if evaluation["status"] == "PASS" else "blocked",
        }
        if result["status"] == "PASS":
            _write_json(output_path, result)
        return result
    except (KeyError, TypeError, ValueError) as exc:
        return _failure(
            "cutover_rollback_rehearsal_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )


def _failure(
    code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": "s150_cutover_rollback_rehearsal.v1",
        "slice": "1501",
        "requirement": "S150",
        "status": "FAIL",
        "failure_code": code,
        "cutover_execution_performed": False,
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
        return "s150_cutover_rollback_rehearsal=skipped"
    if result.get("status") != "PASS":
        return "s150_cutover_rollback_rehearsal=fail"
    summary = _mapping(result.get("summary"))
    return (
        "s150_cutover_rollback_rehearsal=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"phases={summary.get('cutover_phase_count', 0)} "
        f"components={summary.get('rollback_component_count', 0)} "
        f"recovery={summary.get('recovery_ms', 0)}ms "
        f"residue={summary.get('residue_count', -1)} next=1502"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--under-load", type=Path, default=DEFAULT_UNDER_LOAD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cutover_rollback_rehearsal(
        manifest_path=args.manifest,
        preflight_path=args.preflight,
        under_load_path=args.under_load,
        output_path=args.output,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
