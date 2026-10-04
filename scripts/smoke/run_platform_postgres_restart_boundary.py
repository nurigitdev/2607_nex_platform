#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_postgres_restart_boundary.v1"
SERVICES = ("nex-oa", "nex-mo", "nex-cx", "nex-ae-api", "nex-ag")
CANONICAL_DOCUMENT = "docs/40_platform_postgresql_restart_orchestration.md"
REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/39_platform_runtime_topology_and_configuration.md",
    CANONICAL_DOCUMENT,
    "docs/slices/1322_platform_postgres_restart_boundary.md",
    "scripts/db/run_migrations.py",
    "scripts/dev/run_platform.py",
    "services/_shared/nex_runtime/database.py",
    "services/_shared/nex_runtime/persistence.py",
    "services/_shared/nex_runtime/process_manifest.py",
    "services/_shared/nex_runtime/runtime_orchestrator.py",
)
REQUIRED_TOKENS = (
    ("completion", CANONICAL_DOCUMENT, "five test databases migrate and recover"),
    ("migrations", CANONICAL_DOCUMENT, "all 89 versioned SQL migrations"),
    ("pool", CANONICAL_DOCUMENT, "API and worker engines remain separate"),
    ("restart", CANONICAL_DOCUMENT, "fresh runtime instance restarts the topology"),
    ("cleanup", CANONICAL_DOCUMENT, "cleanup leaves no S133 test residue"),
    ("s134", CANONICAL_DOCUMENT, "## S134 Handoff"),
    ("plan", "docs/37_platform_mvp_integration_release_plan.md", "## S133 Slice Plan"),
    (
        "quality",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_postgres_restart_boundary.py",
    ),
    ("index", "docs/README.md", "1322_platform_postgres_restart_boundary.md"),
)


def run_platform_postgres_restart_boundary(root: Path = ROOT) -> dict[str, Any]:
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
    migration_counts = {
        service_id: len(
            tuple((root / "database" / service_id / "migrations").glob("*.sql"))
        )
        for service_id in SERVICES
    }
    canonical = _read_text(root / CANONICAL_DOCUMENT)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "required_tokens_present": all(item["present"] for item in tokens),
        "all_five_services_own_migrations": all(
            count > 0 for count in migration_counts.values()
        ),
        "migration_inventory_is_89": sum(migration_counts.values()) == 89,
        "test_child_database_alias_boundary_is_recorded": (
            "test database URLs are not yet projected" in canonical
        ),
        "protected_background_persistence_boundary_is_recorded": (
            "protected background process shells are blocked" in canonical
        ),
        "migration_before_start_boundary_is_recorded": (
            "migration execution is not integrated" in canonical
        ),
        "coordinated_restart_boundary_is_recorded": (
            "no coordinated stop/rebuild/restart controller exists" in canonical
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    return {
        "boundary_schema_version": SCHEMA_VERSION,
        "slice": "1322",
        "requirement": "S133",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None
        if not issues
        else "platform_postgres_restart_boundary_failed",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "required_tokens": tokens,
        "findings": {
            "service_count": len(SERVICES),
            "migration_counts": migration_counts,
            "migration_total": sum(migration_counts.values()),
            "integration_gap_count": 5,
        },
        "decision": {
            "service_local_database_ownership_retained": True,
            "shared_database_allowed": False,
            "actual_test_databases_required": True,
            "production_database_execution_allowed": False,
            "remote_provider_required": False,
            "restart_builds_fresh_runtime": True,
            "next_requirement": "S134",
            "next_slice": "1323",
        },
        "slice_plan": [str(value) for value in range(1322, 1332)],
        "quality_cadence": {
            "slice_gate": "every_slice",
            "checkpoint_gate": "1326",
            "full_gate": "1331",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_postgres_restart_boundary=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    return (
        "platform_postgres_restart_boundary=pass "
        f"services={findings.get('service_count', 0)} "
        f"migrations={findings.get('migration_total', 0)} "
        f"gaps={findings.get('integration_gap_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_postgres_restart_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
