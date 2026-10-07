#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.s145_compose import (  # noqa: E402
    run_deterministic_backup_rehearsal,
    validate_s145_compose_assets,
)


def run_postgresql_compose_rehearsal(root: Path = ROOT) -> dict[str, Any]:
    assets = validate_s145_compose_assets(root)
    rehearsal = run_deterministic_backup_rehearsal(root)
    checks = {
        "single_host_compose": assets["orchestrator"] == "docker-compose-single-host",
        "operator_profile_opt_in": assets["profile"] == "postgres-operations",
        "operator_non_root": assets["non_root"] is True,
        "separate_storage_mounts": assets["bind_mount_count"] == 2,
        "external_credentials": assets["credential_source_count"] == 2,
        "postgres_16_tool_image": assets["postgres_major"] == 16,
        "application_release_set_unchanged": assets["application_release_set_changed"] is False,
        "five_service_rehearsal": rehearsal["service_count"] == rehearsal["archive_count"] == 5,
        "no_actual_database_contact": rehearsal["actual_postgres_contacted"] is False,
    }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_compose_rehearsal_audit.v1",
        "slice": "1450",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "metrics": {
            "service_count": rehearsal["service_count"],
            "archive_count": rehearsal["archive_count"],
            "attempt_count": rehearsal["attempt_count"],
        },
        "next_slice": "1451" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        f"postgres_compose_rehearsal={'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"services={metrics.get('service_count', 0)} "
        f"archives={metrics.get('archive_count', 0)} next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_postgresql_compose_rehearsal()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
