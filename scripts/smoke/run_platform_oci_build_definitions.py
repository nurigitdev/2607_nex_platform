#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_oci import (  # noqa: E402
    build_default_oci_definitions,
    materialize_oci_build_context,
    oci_build_context_digest,
    oci_build_context_projection,
    validate_oci_containerfiles,
)


SCHEMA_VERSION = "platform_oci_build_definitions_evidence.v1"


def run_platform_oci_build_definitions(root: Path = ROOT) -> dict[str, Any]:
    definitions = build_default_oci_definitions()
    validate_oci_containerfiles(root, definitions)
    contexts = []
    with TemporaryDirectory(prefix="nex-oci-context-") as temp:
        temp_root = Path(temp)
        for definition in definitions:
            manifest = materialize_oci_build_context(
                root, temp_root / definition.artifact_id, definition
            )
            projection = oci_build_context_projection(manifest)
            contexts.append(
                {
                    "artifact_id": definition.artifact_id,
                    "target": definition.target,
                    "platform": definition.platform,
                    "base_image": definition.base_image,
                    "context_digest": oci_build_context_digest(manifest),
                    "file_count": projection["file_count"],
                    "byte_count": projection["byte_count"],
                }
            )
    passed = (
        len(definitions) == 6
        and len(contexts) == 6
        and len({item["target"] for item in contexts}) == 6
        and all(item["file_count"] > 0 for item in contexts)
        and all("@sha256:" in item["base_image"] for item in contexts)
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1415",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "contexts": contexts,
        "summary": {
            "artifact_count": len(definitions),
            "target_count": len({item["target"] for item in contexts}),
            "context_file_count": sum(item["file_count"] for item in contexts),
            "context_byte_count": sum(item["byte_count"] for item in contexts),
            "digest_pinned_base_count": sum(
                "@sha256:" in item["base_image"] for item in contexts
            ),
        },
        "decision": {
            "repository_root_build_context_allowed": False,
            "owner_allowlist_context_required": True,
            "non_root_runtime_required": True,
            "docker_daemon_required_for_this_evidence": False,
            "production_connection_required": False,
            "next_slice": "1416" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_oci_build_definitions=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_oci_build_definitions=pass "
        f"artifacts={summary.get('artifact_count', 0)} "
        f"targets={summary.get('target_count', 0)} "
        f"files={summary.get('context_file_count', 0)} "
        f"base_digests={summary.get('digest_pinned_base_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_oci_build_definitions()
    except ValueError as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

