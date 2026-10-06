#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_operational_incompleteness_register import (  # noqa: E402
    OPERATIONAL_GAPS,
)


SCHEMA_VERSION = "platform_production_transition_dependency_plan.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class TransitionRequirement:
    requirement_id: str
    wave: int
    dependencies: tuple[str, ...]
    evidence_mode: str
    external_capabilities: tuple[str, ...]


TRANSITION_REQUIREMENTS = (
    TransitionRequirement("S142", 0, (), "build_and_restart", ()),
    TransitionRequirement(
        "S143",
        1,
        ("S142",),
        "protected_configuration",
        ("external_secret_manager", "managed_tls_certificate"),
    ),
    TransitionRequirement(
        "S144",
        2,
        ("S143",),
        "protected_trust",
        ("external_key_custody", "enterprise_idp"),
    ),
    TransitionRequirement(
        "S145",
        2,
        ("S143",),
        "protected_database_recovery",
        ("production_like_postgresql",),
    ),
    TransitionRequirement(
        "S146",
        2,
        ("S143",),
        "protected_private_storage",
        ("production_like_object_storage",),
    ),
    TransitionRequirement(
        "S147",
        2,
        ("S143",),
        "protected_model_serving",
        ("gpu_model_serving",),
    ),
    TransitionRequirement(
        "S148",
        3,
        ("S143", "S144", "S145", "S146", "S147"),
        "protected_observability_incident",
        ("monitoring_paging", "external_incident_endpoints"),
    ),
    TransitionRequirement(
        "S149",
        4,
        ("S144", "S145", "S146", "S147", "S148"),
        "integrated_preproduction",
        ("integrated_staging",),
    ),
    TransitionRequirement(
        "S150",
        5,
        ("S149",),
        "fresh_go_no_go",
        ("change_approval_authority",),
    ),
)


def run_platform_production_transition_dependency_plan(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _read_text(root / PLAN_PATH)
    ordered_ids = tuple(item.requirement_id for item in TRANSITION_REQUIREMENTS)
    topological_order = _topological_order(TRANSITION_REQUIREMENTS)
    operational_targets = {item.target for item in OPERATIONAL_GAPS}
    record_checks = {
        item.requirement_id: {
            "documented": f"| `{item.requirement_id}` | {item.wave} |" in plan,
            "dependency_ids_valid": set(item.dependencies).issubset(ordered_ids),
            "dependencies_precede_requirement": all(
                ordered_ids.index(dependency)
                < ordered_ids.index(item.requirement_id)
                for dependency in item.dependencies
            ),
            "evidence_mode_present": bool(item.evidence_mode),
        }
        for item in TRANSITION_REQUIREMENTS
    }
    checks = {
        "s142_through_s150_exact": ordered_ids
        == tuple(f"S{number}" for number in range(142, 151)),
        "dependency_graph_acyclic": topological_order == ordered_ids,
        "six_execution_waves_exact": {
            item.wave for item in TRANSITION_REQUIREMENTS
        }
        == set(range(6)),
        "parallel_control_wave_exact": {
            item.requirement_id
            for item in TRANSITION_REQUIREMENTS
            if item.wave == 2
        }
        == {"S144", "S145", "S146", "S147"},
        "all_records_complete": all(
            all(values.values()) for values in record_checks.values()
        ),
        "all_operational_targets_scheduled": operational_targets.issubset(
            ordered_ids
        ),
        "s148_waits_for_control_tracks": (
            next(
                item.dependencies
                for item in TRANSITION_REQUIREMENTS
                if item.requirement_id == "S148"
            )
            == ("S143", "S144", "S145", "S146", "S147")
        ),
        "s150_never_implicitly_deploys": (
            "never performs an implicit production deployment" in plan
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    external_capabilities = {
        capability
        for item in TRANSITION_REQUIREMENTS
        for capability in item.external_capabilities
    }
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1409",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "topological_order": list(topological_order),
        "requirements": [
            {
                "requirement_id": item.requirement_id,
                "wave": item.wave,
                "dependencies": list(item.dependencies),
                "evidence_mode": item.evidence_mode,
                "external_capabilities": list(item.external_capabilities),
                "checks": record_checks[item.requirement_id],
            }
            for item in TRANSITION_REQUIREMENTS
        ],
        "summary": {
            "requirement_count": len(TRANSITION_REQUIREMENTS),
            "wave_count": len({item.wave for item in TRANSITION_REQUIREMENTS}),
            "parallel_wave_requirement_count": sum(
                item.wave == 2 for item in TRANSITION_REQUIREMENTS
            ),
            "dependency_edge_count": sum(
                len(item.dependencies) for item in TRANSITION_REQUIREMENTS
            ),
            "external_capability_count": len(external_capabilities),
            "operational_target_count": len(operational_targets),
        },
        "decision": {
            "parallel_work_allowed_after_s143": True,
            "dependency_bypass_allowed": False,
            "production_deployment_performed": False,
            "next_slice": "1410" if passed else "blocked",
        },
    }


def _topological_order(
    requirements: Sequence[TransitionRequirement],
) -> tuple[str, ...]:
    by_id = {item.requirement_id: item for item in requirements}
    if len(by_id) != len(requirements):
        return ()
    if any(
        dependency not in by_id
        for item in requirements
        for dependency in item.dependencies
    ):
        return ()
    completed: list[str] = []
    remaining = list(requirements)
    while remaining:
        ready = [
            item
            for item in remaining
            if all(dependency in completed for dependency in item.dependencies)
        ]
        if not ready:
            return ()
        for item in ready:
            completed.append(item.requirement_id)
            remaining.remove(item)
    return tuple(completed)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_production_transition_dependency_plan=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_transition_dependency_plan=pass "
        f"requirements={summary.get('requirement_count', 0)} "
        f"waves={summary.get('wave_count', 0)} "
        f"parallel={summary.get('parallel_wave_requirement_count', 0)} "
        f"edges={summary.get('dependency_edge_count', 0)} "
        f"external={summary.get('external_capability_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_transition_dependency_plan()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
