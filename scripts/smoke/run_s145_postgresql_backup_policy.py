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

from nex_runtime.postgres_resilience import (  # noqa: E402
    load_postgres_resilience_policy,
    policy_public_projection,
)


POLICY_PATH = ROOT / "deployment/postgres/s145-policy.yaml"


def run_postgresql_backup_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / POLICY_PATH.relative_to(ROOT))
    projection = policy_public_projection(policy)
    checks = {
        "five_database_targets": projection["database_count"] == 5,
        "single_host_no_ha": (
            projection["topology_mode"] == "single_host_cold_recovery"
            and projection["high_availability"] is False
            and projection["automatic_failover"] is False
            and projection["operator_cutover_required"] is True
        ),
        "logical_backup_objectives": (
            projection["backup_format"] == "custom"
            and projection["interval_hours"] <= 6
            and projection["service_restore_rto_minutes"] <= 30
        ),
        "retention_guard": (
            projection["retention_restore_points"] >= 28
            and projection["retention_days"] >= 7
            and projection["minimum_verified_points"] >= 1
        ),
        "pitr_objectives": (
            projection["cluster_recovery_method"] == "basebackup_wal_pitr"
            and projection["archive_timeout_seconds"] <= 300
            and projection["cluster_rto_minutes"] <= 60
            and projection["retained_base_generations"] >= 2
        ),
        "storage_and_credential_guards": (
            projection["production_storage_class"] == "separate_mount"
            and projection["credential_transport"] == "libpq_service_passfile"
        ),
        "postgres_16_extension_inventory": (
            projection["postgres_major"] == 16
            and projection["extension_target_count"] == 2
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_backup_policy_audit.v1",
        "slice": "1444",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "policy": projection,
        "next_slice": "1445" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    policy = dict(result.get("policy") or {})
    return (
        "postgresql_backup_policy="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"databases={policy.get('database_count', 0)} "
        f"rpo={policy.get('interval_hours', 0)}h "
        f"rto={policy.get('cluster_rto_minutes', 0)}m "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_postgresql_backup_policy()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

