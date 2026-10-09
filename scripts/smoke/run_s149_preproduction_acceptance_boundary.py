#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s149_preproduction_acceptance_boundary.v1"
CANONICAL_PATH = "docs/57_platform_preproduction_reliability_acceptance.md"
READINESS_PATH = "docs/48_platform_production_readiness_plan.md"
SLICE_PATH = "docs/slices/1483_s149_preproduction_acceptance_boundary.md"
WORKLOAD_CLASSES = ("baseline", "concurrency", "soak")
FAULT_CLASSES = (
    "service_restart",
    "database_connection_loss",
    "object_storage_degradation",
    "provider_degradation",
    "edge_or_trust_degradation",
)
BACKLOG_CAPABILITIES = (
    "multi_node_service_failover",
    "postgres_automatic_failover",
    "object_store_node_loss",
    "gpu_autoscaling_failover",
    "external_dead_man_monitoring",
)
REQUIRED_PATHS = (
    CANONICAL_PATH,
    READINESS_PATH,
    SLICE_PATH,
    "docs/55_platform_model_serving_capacity_rollout.md",
    "docs/56_platform_observability_slo_incident_integration.md",
    "deployment/compose/s143-staging.compose.yaml",
    "services/_shared/nex_runtime/release_candidate.py",
    "services/_shared/nex_runtime/postgres_recovery_acceptance.py",
    "services/_shared/nex_runtime/model_calibration.py",
    "services/nex-ag/nex_ag/platform_slo.py",
)


def run_preproduction_acceptance_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    readiness = " ".join(_read_text(root / READINESS_PATH).split())
    checks = {
        "required_paths_present": all(paths.values()),
        "single_host_topology_frozen": all(
            token in canonical
            for token in ("one Docker Compose host", "five service-owned PostgreSQL", "RustFS")
        ),
        "release_bound_evidence_frozen": all(
            token in canonical
            for token in ("release-candidate ID", "workload digest", "fault-plan digest")
        ),
        "workload_classes_frozen": all(item in canonical for item in WORKLOAD_CLASSES),
        "slo_acceptance_frozen": all(
            token in canonical
            for token in ("`NO_DATA` is not acceptance", "p95 latency", "zero violations")
        ),
        "fault_matrix_frozen": all(item in canonical for item in FAULT_CLASSES),
        "provider_mutation_prohibited": all(
            token in canonical
            for token in ("does not stop, mutate, or reconfigure", "client-side provider degradation")
        ),
        "security_privacy_frozen": all(
            token in canonical
            for token in ("cross-tenant reads", "service-token audience", "evidence redaction")
        ),
        "rollback_zero_residue_frozen": all(
            token in canonical
            for token in ("exact last-known-good image set", "zero database rows")
        ),
        "distributed_backlog_explicit": all(
            item in canonical for item in BACKLOG_CAPABILITIES
        )
        and "NOT_APPLICABLE_SINGLE_HOST" in canonical,
        "twelve_slice_gate_sequence_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1483, 1495))
            and "Checkpoint Gate runs at Slice 1487" in canonical
            and "Full Gate runs at Slice 1494" in canonical
        ),
        "production_and_external_limits_open": all(
            token in canonical + " " + readiness
            for token in (
                "EXTERNAL_NOT_ACTIVATED",
                "Production deployment remains unapproved",
                "integrated staging environment",
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
        "slice": "1483",
        "requirement": "S149",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "workload_classes": list(WORKLOAD_CLASSES),
        "fault_classes": list(FAULT_CLASSES),
        "backlog_capabilities": list(BACKLOG_CAPABILITIES),
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "workload_class_count": len(WORKLOAD_CLASSES),
            "fault_class_count": len(FAULT_CLASSES),
            "backlog_count": len(BACKLOG_CAPABILITIES),
            "slice_count": 12,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "topology": "single_host_docker_compose",
            "provider_fault_boundary": "client_or_staging_route_only",
            "distributed_failover_evidence": "NOT_APPLICABLE_SINGLE_HOST",
            "external_incident_activation": "EXTERNAL_NOT_ACTIVATED",
            "production_deployment_approved": False,
            "next_slice": "1484" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"s149_acceptance_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "s149_acceptance_boundary=pass "
        f"checks={summary.get('check_count', 0)}/12 "
        f"workloads={summary.get('workload_class_count', 0)} "
        f"faults={summary.get('fault_class_count', 0)} "
        f"backlog={summary.get('backlog_count', 0)} "
        f"slices={summary.get('slice_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_preproduction_acceptance_boundary()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
