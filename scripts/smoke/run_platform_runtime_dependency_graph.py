#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.topology import (  # noqa: E402
    PlatformRuntimeManifest,
    RuntimeEndpoint,
    RuntimeModes,
    RuntimeProbe,
    RuntimeProcess,
)
from nex_runtime.topology_graph import (  # noqa: E402
    build_runtime_startup_plan,
    runtime_startup_plan_projection,
)


def run_platform_runtime_dependency_graph() -> dict[str, Any]:
    manifest = _manifest()
    local_plan = runtime_startup_plan_projection(build_runtime_startup_plan(manifest))
    protected_plan = runtime_startup_plan_projection(
        build_runtime_startup_plan(replace(manifest, profile="test"))
    )
    checks = {
        "startup_has_three_layers": len(local_plan["layers"]) == 3,
        "oa_starts_first": local_plan["layers"][0] == ["nex-oa-api"],
        "ae_api_starts_after_oa": local_plan["layers"][1] == ["nex-ae-api"],
        "web_starts_after_ae_api": local_plan["layers"][2] == ["nex-ae-web"],
        "local_mock_uses_liveness": all(
            item["probe_mode"] == "liveness"
            for item in local_plan["dependency_probes"]
        ),
        "protected_uses_readiness": all(
            item["probe_mode"] == "readiness"
            for item in protected_plan["dependency_probes"]
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_runtime_dependency_graph.v1",
        "slice": "1315",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_runtime_dependency_graph_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "local_mock_plan": local_plan,
        "protected_plan": protected_plan,
        "decision": {
            "dependency_graph_must_be_acyclic": True,
            "local_mock_database_readiness_required": False,
            "protected_database_readiness_required": True,
            "next_slice": "1316",
        },
    }


def _manifest() -> PlatformRuntimeManifest:
    def api(process_id: str, owner: str, port: int, dependencies=()):
        return RuntimeProcess(
            process_id,
            owner,
            "api",
            ("python", "run_service.py", owner),
            host="127.0.0.1",
            port=port,
            dependencies=dependencies,
            liveness_probe=RuntimeProbe("/health"),
            readiness_probe=RuntimeProbe("/ready"),
        )

    return PlatformRuntimeManifest(
        "platform_runtime_manifest.v1",
        "local_mock",
        RuntimeModes("memory", "mock", "test_mock", "memory"),
        endpoints=(RuntimeEndpoint("nex-oa", "http://127.0.0.1:8101"),),
        processes=(
            api("nex-oa-api", "nex-oa", 8101),
            api("nex-ae-api", "nex-ae-api", 8103, ("nex-oa-api",)),
            RuntimeProcess(
                "nex-ae-web",
                "nex-ae-web",
                "web",
                ("node", "serve.mjs"),
                host="127.0.0.1",
                port=5173,
                dependencies=("nex-ae-api",),
                liveness_probe=RuntimeProbe("/"),
                readiness_probe=RuntimeProbe("/"),
            ),
        ),
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_dependency_graph=fail issues={len(evidence.get('issues') or [])}"
    local_plan = evidence.get("local_mock_plan") or {}
    return (
        "platform_runtime_dependency_graph=pass "
        f"layers={len(local_plan.get('layers') or [])} "
        f"probes={len(local_plan.get('dependency_probes') or [])} "
        f"local=liveness protected=readiness "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_runtime_dependency_graph()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
