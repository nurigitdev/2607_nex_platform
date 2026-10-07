#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_artifacts import (  # noqa: E402
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_provenance import (  # noqa: E402
    collect_deployment_release_manifest,
    deployment_release_manifest_projection,
)


SCHEMA_VERSION = "platform_deployment_provenance_evidence.v1"


def run_platform_deployment_provenance(root: Path = ROOT) -> dict[str, Any]:
    source_revision, source_tree_clean = _git_metadata(root)
    inputs_manifest = collect_deployment_release_manifest(
        root,
        source_revision=source_revision,
        source_tree_clean=source_tree_clean,
    )
    projection = deployment_release_manifest_projection(inputs_manifest)
    synthetic_ready = collect_deployment_release_manifest(
        root,
        source_revision=source_revision,
        source_tree_clean=True,
        image_references=_synthetic_image_references(),
    )
    serialized = json.dumps(projection, sort_keys=True)
    checks = {
        "six_artifact_provenance_records": len(projection["artifacts"]) == 6,
        "build_inputs_are_not_release_overclaimed": (
            projection["status"] == "BUILD_INPUTS_READY"
            and "image_digests_not_recorded" in projection["reason_codes"]
            and projection["release_set_digest"] is None
        ),
        "artifact_provenance_digests_unique": (
            len(
                {
                    item["provenance_digest"]
                    for item in projection["artifacts"]
                }
            )
            == 6
        ),
        "owner_context_and_definition_digests_present": all(
            item["build_definition_digest"].startswith("sha256:")
            and item["build_context_digest"].startswith("sha256:")
            for item in projection["artifacts"]
        ),
        "synthetic_complete_set_rule_proven": (
            synthetic_ready.status == "RELEASE_SET_READY"
            and synthetic_ready.reason_codes == ()
            and bool(synthetic_ready.release_set_digest)
        ),
        "source_and_build_inputs_match_across_collection": (
            synthetic_ready.source_revision == projection["source_revision"]
            and synthetic_ready.build_inputs_digest
            == projection["build_inputs_digest"]
            and [item.build_context_digest for item in synthetic_ready.artifacts]
            == [item["build_context_digest"] for item in projection["artifacts"]]
        ),
        "metadata_projection_is_private_and_reproducible": (
            projection["runtime_values_included"] is False
            and projection["timestamps_included"] is False
            and projection["machine_paths_included"] is False
            and "postgresql://" not in serialized
            and "synthetic-token" not in serialized
            and '"password"' not in serialized.lower()
        ),
        "production_deployment_not_approved": (
            projection["production_deployment_approved"] is False
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1419",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "release_manifest": projection,
        "summary": {
            "artifact_count": len(projection["artifacts"]),
            "provenance_digest_count": len(
                {item["provenance_digest"] for item in projection["artifacts"]}
            ),
            "image_digest_count": sum(
                item["image_reference"] is not None
                for item in projection["artifacts"]
            ),
            "synthetic_complete_set_proof_count": int(
                synthetic_ready.status == "RELEASE_SET_READY"
            ),
        },
        "decision": {
            "image_build_performed": False,
            "release_set_published": False,
            "production_contact_required": False,
            "production_deployment_approved": False,
            "next_slice": "1420" if passed else "blocked",
        },
    }


def _synthetic_image_references() -> dict[str, str]:
    return {
        artifact.artifact_id: (
            f"registry.example/nex/{artifact.artifact_id}@sha256:"
            f"{hashlib.sha256(('image:' + artifact.artifact_id).encode('ascii')).hexdigest()}"
        )
        for artifact in build_default_deployment_artifact_catalog().artifacts
    }


def _git_metadata(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ("git", "status", "--porcelain"),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Git source metadata is unavailable") from exc
    return revision, not bool(status.strip())


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"platform_deployment_provenance=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_deployment_provenance=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"provenance={summary.get('provenance_digest_count', 0)} "
        f"images={summary.get('image_digest_count', 0)} "
        f"complete_set_proofs={summary.get('synthetic_complete_set_proof_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_deployment_provenance()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "issues": [str(exc)]}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
