#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.topology import (
    PlatformRuntimeManifest,
    RuntimeEndpoint,
    RuntimeModes,
    RuntimeProbe,
    RuntimeProcess,
    runtime_manifest_public_projection,
)


def build_domain_evidence() -> dict[str, Any]:
    manifest = PlatformRuntimeManifest(
        schema_version="platform_runtime_manifest.v1",
        profile="local_mock",
        modes=RuntimeModes(
            persistence="memory",
            provider="mock",
            trust="test_mock",
            ag_projection="memory",
        ),
        endpoints=(RuntimeEndpoint("nex-oa", "http://127.0.0.1:8101"),),
        processes=(
            RuntimeProcess(
                process_id="nex-oa-api",
                owner="nex-oa",
                kind="api",
                command=("python", "scripts/dev/run_service.py", "nex-oa"),
                host="127.0.0.1",
                port=8101,
                liveness_probe=RuntimeProbe("/health"),
                readiness_probe=RuntimeProbe("/ready"),
                environment_names=("NEX_PROFILE",),
            ),
        ),
    )
    projection = runtime_manifest_public_projection(manifest)
    process = projection["processes"][0]
    checks = {
        "manifest_validates": projection["schema_version"]
        == "platform_runtime_manifest.v1",
        "profile_is_explicit": projection["profile"] == "local_mock",
        "endpoint_is_typed": projection["endpoints"][0]["service_id"] == "nex-oa",
        "process_is_typed": process["kind"] == "api" and process["port"] == 8101,
        "command_is_not_public": "command" not in process,
        "environment_values_are_not_public": "environment" not in process,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_runtime_manifest_domain.v1",
        "slice": "1313",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_runtime_manifest_domain_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "projection": projection,
        "decision": {
            "manifest_is_immutable": True,
            "secret_values_allowed_in_projection": False,
            "profile_composition_deferred_to_slice": "1314",
            "next_slice": "1314",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_manifest_domain=fail issues={len(evidence.get('issues') or [])}"
    projection = evidence.get("projection") or {}
    return (
        "platform_runtime_manifest_domain=pass "
        f"profile={projection.get('profile')} "
        f"endpoints={len(projection.get('endpoints') or [])} "
        f"processes={len(projection.get('processes') or [])} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = build_domain_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
