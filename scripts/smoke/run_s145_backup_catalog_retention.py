#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.postgres_backup import build_logical_backup_plan, execute_logical_backup  # noqa: E402
from nex_runtime.postgres_backup_catalog import (  # noqa: E402
    BackupCatalog,
    BackupCatalogEntry,
    build_backup_catalog,
    plan_backup_retention,
    quarantine_stale_partials,
    record_restore_verification,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy  # noqa: E402
from nex_runtime.postgres_restore import IsolatedRestoreResult, RESTORE_EVIDENCE_SCHEMA_VERSION  # noqa: E402


def run_backup_catalog_retention(root: Path = ROOT) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / "deployment/postgres/s145-policy.yaml")
    target = policy.targets[0]
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix="nex-s145-catalog-") as temp:
        base = Path(temp)
        plan = build_logical_backup_plan(
            policy=policy, target=target, backup_id="20261008T000000Z-1234abcd",
            backup_root=base / "backup", pg_dump_bin=Path("/usr/bin/pg_dump"),
            service_file=base / "pg_service.conf", passfile=base / ".pgpass",
        )

        def runner(_command, **kwargs):
            kwargs["stdout"].write(b"PGDMP-catalog")
            return SimpleNamespace(returncode=0)

        times = iter((now, now + timedelta(seconds=1)))
        backup = execute_logical_backup(plan, runner=runner, clock=lambda: next(times))
        restore = IsolatedRestoreResult(
            schema_version=RESTORE_EVIDENCE_SCHEMA_VERSION,
            backup_id=backup.backup_id, service_id=backup.service_id,
            state="RESTORED", target_class="isolated_recovery",
            archive_sha256=backup.archive_sha256, probe_count=4,
            completed_at="2026-10-08T00:00:02Z",
        )
        record_restore_verification(manifest_path=plan.manifest_path, restore_result=restore)
        catalog = build_backup_catalog(plan.service_directory, service_id=target.service_id)
        stale = plan.service_directory / ".stale.dump.partial"
        stale.write_bytes(b"partial")
        old = (now - timedelta(days=1)).timestamp()
        os.utime(stale, (old, old))
        moved = quarantine_stale_partials(plan.service_directory, stale_before=now)

        synthetic = []
        for offset in range(30):
            stamp = now - timedelta(days=offset + 8)
            synthetic.append(
                BackupCatalogEntry(
                    backup_id=f"synthetic-{offset:02d}", service_id=target.service_id,
                    state="VERIFIED", completed_at=stamp.isoformat().replace("+00:00", "Z"),
                    archive_sha256="0" * 64, archive_bytes=1,
                    manifest_path=base / "manifest", archive_path=base / "archive",
                    verification_path=base / "verification",
                )
            )
        retention = plan_backup_retention(
            BackupCatalog(target.service_id, tuple(synthetic), (), ()), policy, now=now
        )
        checks = {
            "verified_catalog_entry": len(catalog.entries) == 1 and catalog.entries[0].state == "VERIFIED",
            "catalog_integrity_clean": catalog.issues == (),
            "stale_partial_quarantined": len(moved) == 1 and moved[0].exists() and not stale.exists(),
            "retention_keeps_28": len(retention.keep_backup_ids) == 28,
            "retention_deletes_only_verified": len(retention.delete_backup_ids) == 2 and retention.quarantine_backup_ids == (),
            "minimum_verified_point_preserved": bool(retention.keep_backup_ids),
        }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_backup_catalog_retention_audit.v1",
        "slice": "1447", "requirement": "S145",
        "status": "PASS" if passed else "FAIL", "checks": checks,
        "metrics": {"catalog_entries": 1, "retained": len(retention.keep_backup_ids), "deleted": len(retention.delete_backup_ids), "quarantined_partials": len(moved)},
        "next_slice": "1448" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        "postgres_backup_catalog_retention="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} retained={metrics.get('retained', 0)} "
        f"deleted={metrics.get('deleted', 0)} quarantine={metrics.get('quarantined_partials', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_backup_catalog_retention()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

