#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_artifacts import (  # noqa: E402
    build_default_deployment_artifact_catalog,
    deployment_artifact_catalog_digest,
    deployment_artifact_catalog_projection,
    immutable_image_reference,
    validate_deployment_artifact_catalog,
)
from nex_runtime.process_manifest import build_platform_runtime_manifest  # noqa: E402


SCHEMA_VERSION = "platform_deployment_artifact_catalog_evidence.v1"


def run_platform_deployment_artifact_catalog() -> dict[str, Any]:
    catalog = build_default_deployment_artifact_catalog()
    manifest = build_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    validate_deployment_artifact_catalog(catalog, manifest)
    projection = deployment_artifact_catalog_projection(catalog)
    catalog_digest = deployment_artifact_catalog_digest(catalog)
    sample_digest = "sha256:" + "0" * 64
    immutable_references = {
        artifact["artifact_id"]: immutable_image_reference(
            f"nex-platform/{artifact['artifact_id']}", sample_digest
        )
        for artifact in projection["artifacts"]
    }
    process_ids = {
        binding["process_id"] for binding in projection["process_bindings"]
    }
    runtime_process_ids = {process.process_id for process in manifest.processes}
    passed = (
        len(projection["artifacts"]) == 6
        and len(process_ids) == 13
        and process_ids == runtime_process_ids
        and catalog_digest.startswith("sha256:")
        and all("@sha256:" in value for value in immutable_references.values())
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1413",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "catalog_digest": catalog_digest,
        "artifacts": projection["artifacts"],
        "process_bindings": projection["process_bindings"],
        "immutable_reference_samples": immutable_references,
        "summary": {
            "artifact_count": len(projection["artifacts"]),
            "process_binding_count": len(projection["process_bindings"]),
            "owner_count": len(
                {artifact["owner"] for artifact in projection["artifacts"]}
            ),
            "unbound_process_count": len(runtime_process_ids - process_ids),
        },
        "decision": {
            "catalog_is_canonical": passed,
            "mutable_tag_admitted": False,
            "secret_value_present": False,
            "production_connection_required": False,
            "next_slice": "1414" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_deployment_artifact_catalog=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_deployment_artifact_catalog=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"bindings={summary.get('process_binding_count', 0)} "
        f"owners={summary.get('owner_count', 0)} "
        f"unbound={summary.get('unbound_process_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_deployment_artifact_catalog()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

