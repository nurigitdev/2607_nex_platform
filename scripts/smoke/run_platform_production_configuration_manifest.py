#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_configuration import (  # noqa: E402
    load_production_configuration_manifest,
    production_configuration_manifest_projection,
)


SCHEMA_VERSION = "platform_production_configuration_manifest_evidence.v1"


def run_platform_production_configuration_manifest(
    root: Path = ROOT,
) -> dict[str, Any]:
    manifest = load_production_configuration_manifest(root)
    projection = production_configuration_manifest_projection(manifest)
    owner_count = len({item["owner"] for item in projection["bindings"]})
    passed = (
        projection["binding_count"] == 31
        and projection["secret_reference_count"] == 20
        and projection["public_connection_count"] == 11
        and projection["control_environment_count"] == 6
        and owner_count == 6
        and not projection["raw_secret_values_included"]
        and not projection["reference_values_included"]
        and not projection["connection_values_included"]
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1424",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "manifest": projection,
        "summary": {
            "binding_count": projection["binding_count"],
            "secret_reference_count": projection["secret_reference_count"],
            "public_connection_count": projection["public_connection_count"],
            "control_environment_count": projection[
                "control_environment_count"
            ],
            "owner_count": owner_count,
        },
        "decision": {
            "raw_secret_environment_is_deployment_input": False,
            "external_reference_is_deployment_input": True,
            "runtime_materialization_performed": False,
            "production_connection_required": False,
            "new_table_required": False,
            "next_slice": "1425" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_configuration_manifest=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_configuration_manifest=pass "
        f"bindings={summary.get('binding_count', 0)} "
        f"secrets={summary.get('secret_reference_count', 0)} "
        f"connections={summary.get('public_connection_count', 0)} "
        f"controls={summary.get('control_environment_count', 0)} "
        f"owners={summary.get('owner_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_configuration_manifest()
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
