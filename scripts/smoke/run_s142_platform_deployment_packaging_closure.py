#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_deployment_artifact_catalog import (  # noqa: E402
    run_platform_deployment_artifact_catalog,
)
from run_platform_deployment_build_inputs import (  # noqa: E402
    run_platform_deployment_build_inputs,
)
from run_platform_deployment_packaging_boundary import (  # noqa: E402
    run_platform_deployment_packaging_boundary,
)
from run_platform_deployment_provenance import (  # noqa: E402
    run_platform_deployment_provenance,
)
from run_platform_environment_compositions import (  # noqa: E402
    run_platform_environment_compositions,
)
from run_platform_oci_build_definitions import (  # noqa: E402
    run_platform_oci_build_definitions,
)
from run_platform_packaged_entrypoints import (  # noqa: E402
    run_platform_packaged_entrypoints,
)
from run_platform_packaged_lifecycle import (  # noqa: E402
    run_platform_packaged_lifecycle,
)


SCHEMA_VERSION = "s142_platform_deployment_packaging_closure.v1"
CANONICAL_PATH = "docs/50_platform_reproducible_deployment_packaging.md"
PROGRAM_PATH = "docs/48_platform_production_readiness_plan.md"
RUNBOOK_PATH = "docs/runbooks/platform_reproducible_deployment_packaging.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s142_platform_deployment_packaging_closure.py"
IMAGE_BUILD_RUNNER = "build_platform_images.py"
EvidenceRunner = Callable[[], dict[str, Any]]
EVIDENCE_RUNNERS: tuple[tuple[str, str, EvidenceRunner], ...] = (
    (
        "boundary",
        "run_platform_deployment_packaging_boundary.py",
        lambda: run_platform_deployment_packaging_boundary(ROOT),
    ),
    (
        "artifacts",
        "run_platform_deployment_artifact_catalog.py",
        run_platform_deployment_artifact_catalog,
    ),
    (
        "build_inputs",
        "run_platform_deployment_build_inputs.py",
        lambda: run_platform_deployment_build_inputs(ROOT),
    ),
    (
        "oci_definitions",
        "run_platform_oci_build_definitions.py",
        lambda: run_platform_oci_build_definitions(ROOT),
    ),
    (
        "entrypoints",
        "run_platform_packaged_entrypoints.py",
        lambda: run_platform_packaged_entrypoints(ROOT),
    ),
    (
        "environments",
        "run_platform_environment_compositions.py",
        lambda: run_platform_environment_compositions(ROOT),
    ),
    (
        "lifecycle",
        "run_platform_packaged_lifecycle.py",
        run_platform_packaged_lifecycle,
    ),
    (
        "provenance",
        "run_platform_deployment_provenance.py",
        lambda: run_platform_deployment_provenance(ROOT),
    ),
)
SLICE_DOCUMENTS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1412", "platform_deployment_packaging_boundary"),
        ("1413", "platform_deployment_artifact_catalog"),
        ("1414", "platform_deployment_build_input_locks"),
        ("1415", "platform_owner_scoped_oci_build_definitions"),
        ("1416", "platform_packaged_background_entrypoints"),
        ("1417", "platform_environment_compositions"),
        ("1418", "platform_packaged_deployment_lifecycle"),
        ("1419", "platform_deployment_provenance"),
        ("1420", "platform_packaged_runtime_acceptance"),
        ("1421", "s142_platform_deployment_packaging_closure"),
        ("1422", "s142_oci_image_build_supplement"),
    )
)


def run_s142_platform_deployment_packaging_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_documents = (
        *SLICE_DOCUMENTS,
        CANONICAL_PATH,
        PROGRAM_PATH,
        RUNBOOK_PATH,
    )
    document_presence = {
        path: (root / path).is_file() for path in required_documents
    }
    evidence = _run_evidence(root) if all(document_presence.values()) else {}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    program = " ".join(_read_text(root / PROGRAM_PATH).split())
    runbook = _read_text(root / RUNBOOK_PATH)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    protected_acceptance = _read_text(
        root / "docs/slices/1420_platform_packaged_runtime_acceptance.md"
    )

    artifacts = _summary(evidence, "artifacts")
    build_inputs = _summary(evidence, "build_inputs")
    oci = _summary(evidence, "oci_definitions")
    entrypoints = _summary(evidence, "entrypoints")
    environments = _summary(evidence, "environments")
    lifecycle = _summary(evidence, "lifecycle")
    provenance = _summary(evidence, "provenance")

    checks = {
        "all_eight_packaging_audits_passed": len(evidence) == 8
        and all(item.get("status") == "PASS" for item in evidence.values()),
        "all_slice_canonical_runbook_documents_present": all(
            document_presence.values()
        ),
        "closure_registered_once_in_full_gate": quality_gate.count(
            CLOSURE_RUNNER
        )
        == 1,
        "protected_image_build_registered_once_in_full_gate": (
            quality_gate.count(IMAGE_BUILD_RUNNER) == 1
        ),
        "canonical_completion_and_s143_handoff_frozen": all(
            token in canonical
            for token in (
                "Status: S142 complete with supplemental Slice 1422",
                "Production deployment remains unapproved.",
                "No production resource was contacted by S142.",
                "Completion signal: Met.",
                "Supplemental Slice 1422 adds a protected clean-commit command",
                "## S143 Handoff",
            )
        ),
        "program_activates_s143_without_production_approval": all(
            token in program
            for token in (
                "S142 is complete and S143 is active",
                "production deployment remains unapproved",
            )
        ),
        "artifact_catalog_exact": artifacts
        == {
            "artifact_count": 6,
            "owner_count": 6,
            "process_binding_count": 13,
            "unbound_process_count": 0,
        },
        "dependency_locks_are_integrity_complete": (
            build_inputs.get("lock_count") == 2
            and build_inputs.get("python_package_count") == 45
            and int(build_inputs.get("python_hash_count") or 0) >= 1200
            and build_inputs.get("node_package_count") == 4
            and build_inputs.get("node_integrity_count") == 4
        ),
        "owner_scoped_oci_definitions_exact": (
            oci.get("artifact_count") == 6
            and oci.get("target_count") == 6
            and oci.get("digest_pinned_base_count") == 6
            and int(oci.get("context_file_count") or 0) > 0
        ),
        "packaged_entrypoints_exact": (
            entrypoints.get("entrypoint_count") == 13
            and entrypoints.get("background_entrypoint_count") == 7
            and entrypoints.get("executed_check_count") == 7
            and entrypoints.get("source_tree_command_count") == 0
        ),
        "environment_compositions_exact": environments
        == {
            "blocked_profile_count": 3,
            "environment_class_count": 4,
            "immutable_profile_count": 3,
            "limited_profile_count": 2,
            "profile_count": 5,
        },
        "packaged_lifecycle_exact": lifecycle
        == {
            "artifact_set_size": 6,
            "blocked_profile_count": 3,
            "migration_step_count": 20,
            "process_step_count": 65,
            "profile_count": 5,
        },
        "repository_provenance_defers_runtime_image_evidence": provenance
        == {
            "artifact_count": 6,
            "image_digest_count": 0,
            "provenance_digest_count": 6,
            "synthetic_complete_set_proof_count": 1,
        },
        "protected_package_context_acceptance_recorded": all(
            token in protected_acceptance
            for token in (
                "five actual test PostgreSQL",
                "seven background checks",
                "two complete HTTP process startup",
                "UNAVAILABLE_PERMISSION_OR_SOCKET",
                "does not claim an OCI image build",
            )
        ),
        "runbook_reproduces_audits_acceptance_and_full_gate": all(
            script_name in runbook
            for _, script_name, _ in EVIDENCE_RUNNERS
        )
        and "run_platform_packaged_runtime_acceptance.py" in runbook
        and IMAGE_BUILD_RUNNER in runbook
        and "NEX_PLATFORM_OCI_IMAGE_BUILD=1" in runbook
        and CLOSURE_RUNNER in runbook
        and "scripts/quality/run_quality_gate.sh" in runbook,
        "production_and_release_set_not_overclaimed": (
            _decision(evidence, "boundary").get(
                "production_deployment_approved"
            )
            is False
            and _decision(evidence, "environments").get(
                "production_deployment_approved"
            )
            is False
            and _decision(evidence, "provenance").get(
                "image_build_performed"
            )
            is False
            and _decision(evidence, "provenance").get(
                "release_set_published"
            )
            is False
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1421",
        "slice_range": "1412-1422",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s142_platform_deployment_packaging_closure_failed",
        "closure_readiness": "READY_FOR_S143" if passed else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "required_documents": document_presence,
        "summary": {
            "audit_count": len(evidence),
            "passed_audit_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "artifact_count": int(artifacts.get("artifact_count") or 0),
            "process_binding_count": int(
                artifacts.get("process_binding_count") or 0
            ),
            "profile_count": int(environments.get("profile_count") or 0),
            "packaged_process_step_count": int(
                lifecycle.get("process_step_count") or 0
            ),
            "image_digest_count": int(
                provenance.get("image_digest_count") or 0
            ),
        },
        "decision": {
            "package_context_accepted": passed,
            "oci_image_execution_prerequisite_open": False,
            "oci_image_build_command_protected": passed,
            "oci_image_build_report_tracked": False,
            "release_set_published": False,
            "production_deployment_approved": False,
            "production_resources_contacted": False,
            "full_gate_registered": quality_gate.count(CLOSURE_RUNNER) == 1,
            "next_requirement": "S143" if passed else "blocked",
            "next_requirement_scope": (
                "production_configuration_secret_and_tls_lifecycle"
                if passed
                else "blocked"
            ),
        },
    }


def _run_evidence(root: Path) -> dict[str, dict[str, Any]]:
    if root.resolve() != ROOT.resolve():
        return {}
    return {name: runner() for name, _, runner in EVIDENCE_RUNNERS}


def _summary(
    evidence: Mapping[str, Mapping[str, Any]], name: str
) -> dict[str, Any]:
    return _mapping(_mapping(evidence.get(name)).get("summary"))


def _decision(
    evidence: Mapping[str, Mapping[str, Any]], name: str
) -> dict[str, Any]:
    return _mapping(_mapping(evidence.get(name)).get("decision"))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "s142_platform_deployment_packaging_closure=fail "
            f"checks={len(result.get('failed_checks') or [])}"
        )
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "s142_platform_deployment_packaging_closure=pass "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"bindings={summary.get('process_binding_count', 0)} "
        f"profiles={summary.get('profile_count', 0)} "
        f"process_steps={summary.get('packaged_process_step_count', 0)} "
        f"images={summary.get('image_digest_count', 0)} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s142_platform_deployment_packaging_closure()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
