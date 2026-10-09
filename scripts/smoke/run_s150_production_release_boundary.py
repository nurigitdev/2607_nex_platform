#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s150_production_release_boundary.v1"
CANONICAL_PATH = "docs/58_platform_production_release_go_live.md"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
S149_PATH = "docs/57_platform_preproduction_reliability_acceptance.md"
SLICE_PATH = "docs/slices/1495_s150_production_release_boundary.md"
MANDATORY_GATES = (
    "all_dependency_evidence_passed",
    "evidence_fresh",
    "artifact_configuration_digest_exact",
    "no_open_p0",
    "p1_waivers_valid",
    "privacy_clean",
    "rollback_drill_passed",
    "zero_residue",
    "approval_roles_complete",
    "production_deployment_separate",
)
DISTRIBUTED_BACKLOG = (
    "multi_node_service_failover",
    "postgres_automatic_failover",
    "object_store_node_loss",
    "gpu_autoscaling_failover",
    "external_dead_man_monitoring",
)
REQUIRED_PATHS = (
    CANONICAL_PATH,
    PLAN_PATH,
    S149_PATH,
    SLICE_PATH,
    "deployment/compose/s143-staging.compose.yaml",
    "deployment/security/production-configuration.yaml",
    "deployment/environments/production.yaml",
    "docs/runbooks/platform_preproduction_reliability_acceptance.md",
)


def run_production_release_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    plan = " ".join(_read_text(root / PLAN_PATH).split())
    s149 = " ".join(_read_text(root / S149_PATH).split())
    checks = {
        "required_paths_present": all(paths.values()),
        "single_host_v1_topology_frozen": all(
            token in canonical
            for token in (
                "Single-host Docker Compose",
                "five service-owned PostgreSQL",
                "three remote model-provider",
                "NeX Platform v1.0",
            )
        ),
        "service_and_infrastructure_owners_frozen": all(
            token in canonical
            for token in ("OA, AE API/Web, CX, MO, AG", "Traefik", "OpenBao", "RustFS")
        ),
        "ten_mandatory_gates_frozen": all(
            gate in canonical for gate in MANDATORY_GATES
        ),
        "decision_states_exact": all(
            token in canonical for token in ("`GO` and `NO_GO`", "no implicit deployment")
        ),
        "distributed_backlog_explicit": all(
            item in canonical for item in DISTRIBUTED_BACKLOG
        )
        and "NOT_APPLICABLE_SINGLE_HOST" in canonical,
        "freshness_windows_frozen": all(
            token in canonical
            for token in ("GO_LIVE_WINDOW_24H", "IMMEDIATE_PREFLIGHT_4H")
        ),
        "reasoning_disabled_frozen": "reasoning mode `disabled`" in canonical,
        "external_notification_guard_open": all(
            token in canonical
            for token in ("EXTERNAL_NOT_ACTIVATED", "does not manufacture or self-approve")
        ),
        "ten_slice_sequence_frozen": all(
            f"`{slice_id}`" in canonical for slice_id in range(1495, 1505)
        )
        and "Checkpoint Gate at 1499" in canonical
        and "Full Gate at 1504" in canonical,
        "s149_dependency_closed": all(
            token in s149 for token in ("S149 complete", "S150 active")
        ),
        "program_scope_and_deployment_guard_preserved": all(
            token in plan + " " + canonical
            for token in (
                "explicit go/no-go decision",
                "Production deployment remains unapproved",
                "change approval authority",
            )
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items()
        if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1495",
        "requirement": "S150",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "mandatory_gates": list(MANDATORY_GATES),
        "distributed_backlog": list(DISTRIBUTED_BACKLOG),
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "mandatory_gate_count": len(MANDATORY_GATES),
            "backlog_count": len(DISTRIBUTED_BACKLOG),
            "slice_count": 10,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "v1_topology": "single_host_docker_compose",
            "distributed_capabilities": "NOT_APPLICABLE_SINGLE_HOST",
            "external_notification": "EXTERNAL_NOT_ACTIVATED",
            "release_decision": "PENDING_EVALUATION",
            "production_deployment_approved": False,
            "next_slice": "1496" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"s150_release_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s150_release_boundary=pass "
        f"checks={summary.get('check_count', 0)}/12 "
        f"gates={summary.get('mandatory_gate_count', 0)} "
        f"backlog={summary.get('backlog_count', 0)} "
        f"slices={summary.get('slice_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_production_release_boundary()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
