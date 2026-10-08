#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s147_model_serving_rollout_boundary.v1"
CANONICAL_PATH = "docs/55_platform_model_serving_capacity_rollout.md"
READINESS_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class CapabilityBoundary:
    capability: str
    calibration_focus: str
    current_source: str


CAPABILITIES = (
    CapabilityBoundary(
        "embedding",
        "vector dimension",
        "services/nex-mo/nex_mo/provider_catalog.py",
    ),
    CapabilityBoundary(
        "reranking",
        "score-distribution",
        "services/nex-cx/nex_cx/retrieval_confidence_calibration.py",
    ),
    CapabilityBoundary(
        "generation",
        "grounded/citation quality",
        "services/nex-mo/nex_mo/providers.py",
    ),
)

REQUIRED_PATHS = (
    READINESS_PATH,
    CANONICAL_PATH,
    "docs/slices/1463_s147_model_serving_rollout_boundary.md",
    "services/nex-mo/nex_mo/provider_catalog.py",
    "services/nex-mo/nex_mo/catalog_lifecycle.py",
    "services/nex-mo/nex_mo/provider_readiness.py",
    "services/nex-mo/nex_mo/provider_readiness_evaluator.py",
    "services/nex-mo/nex_mo/runtime_observability.py",
    "services/nex-mo/nex_mo/runtime_observability_policy.py",
    "services/_shared/nex_runtime/model_calibration.py",
    "deployment/compose/s143-staging.compose.yaml",
)


def run_model_serving_rollout_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    readiness = " ".join(_read_text(root / READINESS_PATH).split())
    source = "\n".join(
        _read_text(root / path)
        for path in REQUIRED_PATHS
        if path.startswith("services/")
    )
    checks = {
        "required_paths_present": all(paths.values()),
        "three_provider_capabilities_frozen": (
            {item.capability for item in CAPABILITIES}
            == {"embedding", "reranking", "generation"}
            and all(item.capability in source for item in CAPABILITIES)
            and all(item.calibration_focus in canonical for item in CAPABILITIES)
        ),
        "immutable_revision_identity_frozen": all(
            token in canonical
            for token in (
                "artifact_digest",
                "request_shape_hash",
                "Reusing a deployment ID",
            )
        ),
        "product_neutral_gpu_capacity_frozen": all(
            token in canonical
            for token in (
                "not a Kubernetes requirement",
                "product-neutral capacity snapshots",
                "No scheduler may overcommit",
            )
        ),
        "exact_revision_readiness_frozen": all(
            token in canonical
            for token in (
                "fresh HEALTHY runtime observation for the exact revision",
                "Missing, stale, mismatched, or incomplete evidence fails closed",
            )
        ),
        "capability_calibration_frozen": all(
            token in canonical
            for token in (
                "All three capabilities require an ACTIVE profile",
                "CALIBRATION_REQUIRED",
                "Thresholds are evaluated with data",
            )
        ),
        "canary_promotion_and_rollback_frozen": all(
            token in canonical
            for token in (
                "REGISTERED -> VALIDATING -> READY -> CANARY -> ACTIVE",
                "Only a passing canary may atomically supersede the alias",
                "exact previous catalog and alias binding",
            )
        ),
        "persistence_and_privacy_boundary_frozen": all(
            token in canonical
            for token in (
                "mo_model_rollouts",
                "mo_rollout_events",
                "raw prompts, documents, vectors",
            )
        ),
        "non_disruptive_protected_acceptance_frozen": all(
            token in canonical
            for token in (
                "Protected acceptance is opt-in and non-disruptive",
                "must not stop providers",
                "CANDIDATE_REVISION_REQUIRED",
            )
        ),
        "ten_slice_gate_sequence_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1463, 1473))
            and "Checkpoint Gate runs at Slice 1468" in canonical
            and "Full Gate runs at Slice 1472" in canonical
        ),
        "production_deferral_remains_open": (
            "production_gpu_scheduling_capacity" in readiness
            and "model_rollout_failover_calibration" in readiness
            and "production deployment remains unapproved" in canonical.lower()
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
        "slice": "1463",
        "requirement": "S147",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "capabilities": [
            {
                "provider_capability": item.capability,
                "calibration_focus": item.calibration_focus,
                "policy_key": "immutable_revision_identity",
            }
            for item in CAPABILITIES
        ],
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks),
            "capability_count": len(CAPABILITIES),
            "gap_count": 8,
            "slice_count": 10,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "policy_model_independent": True,
            "scheduler_product_neutral": True,
            "current_topology": "single_dgx_capacity_pool",
            "protected_acceptance_mutates_providers": False,
            "test_database_rehearsal_required": True,
            "production_deployment_approved": False,
            "next_slice": "1464" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "model_serving_rollout_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "model_serving_rollout_boundary=pass "
        f"checks={summary.get('check_count', 0)}/11 "
        f"capabilities={summary.get('capability_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"slices={summary.get('slice_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_model_serving_rollout_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
