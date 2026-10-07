#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_artifacts import (  # noqa: E402
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (  # noqa: E402
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
    packaged_entrypoints_projection,
)
from nex_runtime.deployment_oci import (  # noqa: E402
    build_default_oci_definitions,
    materialize_oci_build_context,
)


SCHEMA_VERSION = "platform_packaged_entrypoints_evidence.v1"


def run_platform_packaged_entrypoints(root: Path = ROOT) -> dict[str, Any]:
    catalog = build_default_deployment_artifact_catalog()
    manifest = build_packaged_runtime_manifest(
        "local_mock",
        environ={},
        python_executable="python",
    )
    entries = build_packaged_entrypoint_definitions(manifest, catalog)
    projection = packaged_entrypoints_projection(entries)
    entry_by_process = {entry.process_id: entry for entry in entries}
    oci_by_artifact = {
        definition.artifact_id: definition
        for definition in build_default_oci_definitions(catalog)
    }
    artifact_owners = {
        artifact.artifact_id: artifact.owner for artifact in catalog.artifacts
    }
    background_checks = []
    with TemporaryDirectory(prefix="nex-packaged-entrypoint-") as temp:
        temp_root = Path(temp)
        context_roots: dict[str, Path] = {}
        for entry in entries:
            if entry.kind not in {"worker", "daemon"}:
                continue
            context = context_roots.get(entry.artifact_id)
            if context is None:
                context = temp_root / entry.artifact_id
                materialize_oci_build_context(
                    root,
                    context,
                    oci_by_artifact[entry.artifact_id],
                )
                context_roots[entry.artifact_id] = context
            owner = artifact_owners[entry.artifact_id]
            check = _run_packaged_background_check(entry.command, context, owner)
            background_checks.append(
                {
                    "process_id": entry.process_id,
                    "artifact_id": entry.artifact_id,
                    "capability": entry.capability,
                    "returncode": check["returncode"],
                    "lifecycle_ready": check["metadata"].get("lifecycle_ready"),
                    "packaged_entrypoint": check["metadata"].get(
                        "packaged_entrypoint"
                    ),
                }
            )
    checks = {
        "thirteen_packaged_entrypoints": projection["entrypoint_count"] == 13,
        "seven_background_entrypoints": (
            projection["background_entrypoint_count"] == 7
        ),
        "all_background_checks_executed": (
            len(background_checks) == 7
            and all(item["returncode"] == 0 for item in background_checks)
        ),
        "all_background_modules_lifecycle_ready": all(
            item["lifecycle_ready"] is True for item in background_checks
        ),
        "canonical_packaged_module_used": all(
            item["packaged_entrypoint"] == "nex_runtime.background_process"
            for item in background_checks
        ),
        "no_source_tree_commands": all(
            not any(argument.endswith((".py", ".mjs")) for argument in entry.command)
            for entry in entries
        ),
        "execution_capability_is_explicit": (
            projection["job_claiming_background_count"] == 1
            and projection["lifecycle_only_background_count"] == 6
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1416",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "summary": {
            "entrypoint_count": projection["entrypoint_count"],
            "background_entrypoint_count": projection[
                "background_entrypoint_count"
            ],
            "executed_check_count": len(background_checks),
            "job_claiming_background_count": projection[
                "job_claiming_background_count"
            ],
            "lifecycle_only_background_count": projection[
                "lifecycle_only_background_count"
            ],
            "source_tree_command_count": 0,
        },
        "background_checks": background_checks,
        "decision": {
            "source_wrapper_retained": True,
            "protected_background_profiles_admitted": ["test"],
            "staging_or_production_background_admitted": False,
            "production_connection_required": False,
            "new_table_required": False,
            "next_slice": "1417" if passed else "blocked",
        },
    }


def _run_packaged_background_check(
    command: tuple[str, ...],
    context: Path,
    owner: str,
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(context / "services" / "_shared"),
            str(context / "services" / owner),
        )
    )
    completed = subprocess.run(
        (sys.executable, *command[1:], "--check"),
        cwd=context,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metadata: dict[str, Any] = {}
    if completed.stdout.strip():
        try:
            metadata = json.loads(completed.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            metadata = {"status": "INVALID_OUTPUT"}
    return {"returncode": completed.returncode, "metadata": metadata}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_packaged_entrypoints=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_packaged_entrypoints=pass "
        f"entrypoints={summary.get('entrypoint_count', 0)} "
        f"background={summary.get('background_entrypoint_count', 0)} "
        f"executed={summary.get('executed_check_count', 0)} "
        f"claiming={summary.get('job_claiming_background_count', 0)} "
        f"lifecycle_only={summary.get('lifecycle_only_background_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_packaged_entrypoints()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "FAIL", "issues": [str(exc)]}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
