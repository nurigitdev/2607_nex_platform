#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
DB_SCRIPTS = ROOT / "scripts" / "db"
sys.path[:0] = [str(SHARED), str(DB_SCRIPTS)]

from archive_postgres_wal import archive_wal_segment  # noqa: E402
from restore_postgres_wal import restore_wal_segment  # noqa: E402
from nex_runtime.postgres_pitr import (  # noqa: E402
    build_postgres_pitr_plan,
    pitr_plan_public_projection,
    validate_pitr_cutover,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy  # noqa: E402


def run_postgresql_pitr_plan(root: Path = ROOT) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / "deployment/postgres/s145-policy.yaml")
    with tempfile.TemporaryDirectory(prefix="nex-s145-pitr-") as temp:
        base = Path(temp)
        plan = build_postgres_pitr_plan(
            policy=policy, recovery_id="pitr-20261008-001",
            backup_root=base / "backup", pg_basebackup_bin=Path("/usr/bin/pg_basebackup"),
            service_file=base / "pg_service.conf", passfile=base / ".pgpass",
            recovery_target_time=datetime(2026, 10, 8, tzinfo=timezone.utc),
            parent_environ={"PATH": "/usr/bin", "PGPASSWORD": "forbidden"},
        )
        projection = pitr_plan_public_projection(plan)
        segment = "000000010000000000000001"
        source = base / segment
        source.write_bytes(b"wal-segment")
        digest = archive_wal_segment(source, segment, base / "wal")
        restored = base / "restore" / segment
        restored.parent.mkdir()
        restored_digest = restore_wal_segment(segment, restored, base / "wal")
        paused = validate_pitr_cutover(
            recovery_paused=True, timeline_verified=True, five_databases_verified=True,
            migration_heads_verified=True, operator_approved=False,
        )
        command = " ".join(plan.basebackup_command)
        checks = {
            "basebackup_uses_safe_service": "--dbname=service=nex-platform-cluster-backup" in plan.basebackup_command,
            "credential_not_in_arguments": "password" not in command.lower() and "postgresql://" not in command,
            "unsafe_environment_not_inherited": "PGPASSWORD" not in plan.environment,
            "wal_archive_roundtrip": digest == restored_digest and restored.read_bytes() == source.read_bytes(),
            "pitr_pauses_before_cutover": paused == "PAUSED_AWAITING_OPERATOR" and projection["recovery_target_action"] == "pause",
            "automatic_promotion_disabled": projection["automatic_promotion"] is False,
            "five_minute_archive_bound": projection["archive_timeout"] == "300s",
            "public_projection_value_free": "path" not in str(projection).lower() and "PGPASSFILE" not in str(projection),
        }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_pitr_plan_audit.v1", "slice": "1448",
        "requirement": "S145", "status": "PASS" if passed else "FAIL",
        "checks": checks, "metrics": {"database_targets": len(policy.targets), "base_generations": policy.retained_base_generations, "archive_timeout_seconds": policy.archive_timeout_seconds},
        "next_slice": "1449" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        "postgres_pitr_plan=" f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} databases={metrics.get('database_targets', 0)} "
        f"bases={metrics.get('base_generations', 0)} wal={metrics.get('archive_timeout_seconds', 0)}s "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_postgresql_pitr_plan()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
