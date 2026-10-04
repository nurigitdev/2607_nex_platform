#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_runtime_topology_boundary.v1"

REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/38_platform_mvp_vertical_spine_reaudit.md",
    "docs/39_platform_runtime_topology_and_configuration.md",
    "docs/slices/1312_platform_runtime_topology_boundary.md",
    "scripts/dev/run_all_services.py",
    "scripts/dev/run_service.py",
    "scripts/quality/run_quality_gate.sh",
)

REQUIRED_TOKENS = (
    ("plan", "docs/37_platform_mvp_integration_release_plan.md", "## S132 Slice Plan"),
    ("typed_manifest", "docs/39_platform_runtime_topology_and_configuration.md", "one typed manifest"),
    ("processes", "docs/39_platform_runtime_topology_and_configuration.md", "five backend APIs and AE Web"),
    ("api_only", "docs/39_platform_runtime_topology_and_configuration.md", "AG consumes service APIs"),
    ("local_mock", "docs/39_platform_runtime_topology_and_configuration.md", "complete `local_mock` topology"),
    ("s133_boundary", "docs/39_platform_runtime_topology_and_configuration.md", "(`S133`)"),
    ("quality_hook", "scripts/quality/run_quality_gate.sh", "run_platform_runtime_topology_boundary.py"),
    ("docs_index", "docs/README.md", "1312_platform_runtime_topology_boundary.md"),
)


def run_platform_runtime_topology_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    tokens = [
        {
            "group": group,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for group, path, token in REQUIRED_TOKENS
    ]
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "typed_manifest_and_process_scope_frozen": _groups_present(
            tokens, "typed_manifest", "processes"
        ),
        "service_api_only_projection_frozen": _groups_present(tokens, "api_only"),
        "local_mock_actual_start_required": _groups_present(tokens, "local_mock"),
        "s133_database_restart_boundary_preserved": _groups_present(
            tokens, "s133_boundary"
        ),
    }
    issues = [
        {"category": "path_missing", "path": item["path"]}
        for item in paths
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "token_missing",
            "group": item["group"],
            "path": item["path"],
        }
        for item in tokens
        if not item["present"]
    )
    passed = all(checks.values())
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": "1312",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_runtime_topology_boundary_failed",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "required_tokens": tokens,
        "decision": {
            "owner": "platform_runtime",
            "service_count": 5,
            "ae_web_required": True,
            "worker_and_daemon_processes_required": True,
            "local_mock_actual_process_smoke_required": True,
            "protected_profiles_fail_closed": True,
            "cross_service_database_reads_allowed": False,
            "postgres_restart_evidence_required": False,
            "remote_provider_evidence_required": False,
            "next_requirement": "S133",
        },
        "slice_plan": [str(value) for value in range(1312, 1322)],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1316",
            "full_gate": "1321",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _groups_present(items: list[dict[str, Any]], *groups: str) -> bool:
    return all(
        any(item["group"] == group and item["present"] for item in items)
        for group in groups
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_topology_boundary=fail issues={len(evidence.get('issues') or [])}"
    decision = evidence.get("decision") or {}
    return (
        "platform_runtime_topology_boundary=pass "
        f"services={decision.get('service_count')}+web "
        f"process_smoke={decision.get('local_mock_actual_process_smoke_required')} "
        f"postgres_restart={decision.get('postgres_restart_evidence_required')} "
        f"live={decision.get('remote_provider_evidence_required')} "
        f"next={decision.get('next_requirement')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_runtime_topology_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
