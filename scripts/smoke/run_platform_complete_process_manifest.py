#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "dev"))

from nex_runtime.process_manifest import (  # noqa: E402
    BACKGROUND_PROCESS_IDS,
    build_platform_runtime_manifest,
    validate_runtime_command_targets,
)
from nex_runtime.topology import runtime_manifest_public_projection  # noqa: E402
from nex_runtime.topology_graph import (  # noqa: E402
    build_runtime_startup_plan,
    runtime_startup_plan_projection,
)
from run_background_process import background_process_metadata  # noqa: E402


def run_platform_complete_process_manifest() -> dict[str, Any]:
    manifest = build_platform_runtime_manifest(
        environ={}, python_executable="python"
    )
    validate_runtime_command_targets(manifest, ROOT)
    projection = runtime_manifest_public_projection(manifest)
    startup = runtime_startup_plan_projection(build_runtime_startup_plan(manifest))
    background = [
        background_process_metadata(process_id, "local_mock")
        for process_id in BACKGROUND_PROCESS_IDS
    ]
    kind_counts = {
        kind: sum(item["kind"] == kind for item in projection["processes"])
        for kind in ("api", "web", "worker", "daemon")
    }
    checks = {
        "six_public_endpoints_materialized": len(projection["endpoints"]) == 6,
        "thirteen_processes_materialized": len(projection["processes"]) == 13,
        "process_kind_inventory_complete": kind_counts
        == {"api": 5, "web": 1, "worker": 5, "daemon": 2},
        "all_command_targets_exist": True,
        "all_background_modules_import": len(background) == 7
        and all(item["lifecycle_ready"] for item in background),
        "background_work_claiming_deferred": all(
            item["work_claiming_enabled"] is False for item in background
        ),
        "startup_plan_covers_every_process": len(startup["ordered_process_ids"]) == 13,
        "commands_are_not_public": all(
            "command" not in item for item in projection["processes"]
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_complete_process_manifest.v1",
        "slice": "1317",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_complete_process_manifest_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "process_kind_counts": kind_counts,
        "endpoint_count": len(projection["endpoints"]),
        "process_count": len(projection["processes"]),
        "startup_layer_count": len(startup["layers"]),
        "background_processes": background,
        "decision": {
            "background_processes_are_independently_scalable": True,
            "local_mock_process_shell_claims_jobs": False,
            "protected_worker_persistence_wiring_requirement": "S133",
            "next_slice": "1318",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_complete_process_manifest=fail issues={len(evidence.get('issues') or [])}"
    kinds = evidence.get("process_kind_counts") or {}
    return (
        "platform_complete_process_manifest=pass "
        f"endpoints={evidence.get('endpoint_count')} "
        f"processes={evidence.get('process_count')} "
        f"kinds={kinds.get('api')}/{kinds.get('web')}/{kinds.get('worker')}/{kinds.get('daemon')} "
        f"layers={evidence.get('startup_layer_count')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_complete_process_manifest()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
