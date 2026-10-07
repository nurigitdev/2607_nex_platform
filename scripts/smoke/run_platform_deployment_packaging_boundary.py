#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.process_manifest import build_platform_runtime_manifest
from nex_runtime.topology import RUNTIME_PROFILES


SCHEMA_VERSION = "platform_deployment_packaging_boundary.v1"
CANONICAL_DOC = "docs/50_platform_reproducible_deployment_packaging.md"


@dataclass(frozen=True)
class ArtifactBoundary:
    artifact_id: str
    owner: str
    process_ids: tuple[str, ...]


ARTIFACT_BOUNDARIES = (
    ArtifactBoundary("nex-oa-runtime", "nex-oa", ("nex-oa-api",)),
    ArtifactBoundary(
        "nex-ae-runtime",
        "nex-ae-api",
        (
            "nex-ae-api",
            "nex-ae-artifact-render-worker",
            "nex-ae-retention-daemon",
        ),
    ),
    ArtifactBoundary(
        "nex-cx-runtime",
        "nex-cx",
        (
            "nex-cx-api",
            "nex-cx-async-generation-worker",
            "nex-cx-ingestion-worker",
            "nex-cx-remediation-worker",
        ),
    ),
    ArtifactBoundary("nex-mo-runtime", "nex-mo", ("nex-mo-api",)),
    ArtifactBoundary(
        "nex-ag-runtime",
        "nex-ag",
        (
            "nex-ag-api",
            "nex-ag-remediation-sync-worker",
            "nex-ag-dispatch-daemon",
        ),
    ),
    ArtifactBoundary("nex-ae-web", "nex-ae-web", ("nex-ae-web",)),
)

ENVIRONMENT_PROFILE_MAP = {
    "development": ("local_mock", "local_live"),
    "test": ("test",),
    "staging": ("staging_live",),
    "production": ("production",),
}

REQUIRED_PATHS = (
    "docs/49_platform_production_readiness_reaudit.md",
    CANONICAL_DOC,
    "docs/slices/1412_platform_deployment_packaging_boundary.md",
    "services/_shared/nex_runtime/process_manifest.py",
    "services/_shared/nex_runtime/runtime_profiles.py",
    "services/_shared/nex_runtime/topology_graph.py",
    "requirements.txt",
    "apps/nex-ae-web/package-lock.json",
    "scripts/quality/run_quality_gate.sh",
)

EXPECTED_GAPS = (
    "immutable_artifact_domain",
    "exact_python_production_lock",
    "oci_build_definitions",
    "process_artifact_bindings",
    "environment_compositions",
    "packaged_process_commands",
    "build_provenance_and_release_digest",
    "packaged_lifecycle_acceptance",
)


def run_platform_deployment_packaging_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    document = _normalized_text(root / CANONICAL_DOC)
    manifest = build_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    manifest_process_ids = tuple(item.process_id for item in manifest.processes)
    artifact_process_ids = tuple(
        process_id
        for artifact in ARTIFACT_BOUNDARIES
        for process_id in artifact.process_ids
    )
    source_command_count = sum(
        any(argument.endswith((".py", ".mjs")) for argument in process.command)
        for process in manifest.processes
    )
    checks = {
        "required_paths_present": all(paths.values()),
        "six_artifact_boundaries_frozen": (
            len(ARTIFACT_BOUNDARIES) == 6
            and len({item.artifact_id for item in ARTIFACT_BOUNDARIES}) == 6
        ),
        "all_processes_bound_once": (
            len(artifact_process_ids) == len(set(artifact_process_ids))
            and set(artifact_process_ids) == set(manifest_process_ids)
        ),
        "four_environment_classes_cover_profiles_once": (
            set(profile for values in ENVIRONMENT_PROFILE_MAP.values() for profile in values)
            == set(RUNTIME_PROFILES)
            and sum(map(len, ENVIRONMENT_PROFILE_MAP.values())) == len(RUNTIME_PROFILES)
        ),
        "current_source_command_gap_measured": source_command_count == 13,
        "eight_packaging_gaps_frozen": (
            len(EXPECTED_GAPS) == 8
            and all(f"`{gap}`" in document for gap in EXPECTED_GAPS)
        ),
        "slice_sequence_and_gates_frozen": (
            all(f"`{slice_id}`" in document for slice_id in range(1412, 1422))
            and "Checkpoint Gate at Slice 1416" in document
            and "Full Gate at Slice 1421" in document
        ),
        "production_remains_unapproved": (
            "production deployment remains unapproved" in document
            and "must not contact production resources" in document
        ),
        "quality_hook_registered": (
            "run_platform_deployment_packaging_boundary.py"
            in _read_text(root / "scripts/quality/run_quality_gate.sh")
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
        "slice": "1412",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "artifact_boundaries": [
            {
                "artifact_id": item.artifact_id,
                "owner": item.owner,
                "process_ids": list(item.process_ids),
            }
            for item in ARTIFACT_BOUNDARIES
        ],
        "environment_profile_map": {
            key: list(value) for key, value in ENVIRONMENT_PROFILE_MAP.items()
        },
        "packaging_gaps": list(EXPECTED_GAPS),
        "summary": {
            "required_path_count": sum(paths.values()),
            "artifact_count": len(ARTIFACT_BOUNDARIES),
            "process_count": len(manifest_process_ids),
            "source_command_count": source_command_count,
            "environment_class_count": len(ENVIRONMENT_PROFILE_MAP),
            "runtime_profile_count": len(RUNTIME_PROFILES),
            "gap_count": len(EXPECTED_GAPS),
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "packaging_format": "OCI",
            "single_platform_image_allowed": False,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1413" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalized_text(path: Path) -> str:
    return " ".join(_read_text(path).split())


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_deployment_packaging_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_deployment_packaging_boundary=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"processes={summary.get('process_count', 0)} "
        f"source_commands={summary.get('source_command_count', 0)} "
        f"environments={summary.get('environment_class_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_deployment_packaging_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
