#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.postgres_backup import build_logical_backup_plan, execute_logical_backup  # noqa: E402
from nex_runtime.postgres_resilience import load_postgres_resilience_policy  # noqa: E402
from nex_runtime.postgres_restore import (  # noqa: E402
    build_isolated_restore_plan,
    execute_isolated_restore,
    restore_result_public_projection,
)


def run_isolated_restore_guard(root: Path = ROOT) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / "deployment/postgres/s145-policy.yaml")
    target = policy.targets[0]
    commands = []

    def dump_runner(command, **kwargs):
        kwargs["stdout"].write(b"PGDMP-s145-restore")
        return SimpleNamespace(returncode=0)

    def command_runner(command, **_kwargs):
        commands.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout="archive-list\n", stderr="")

    probes = {key: True for key in ("database_identity", "migration_head_current", "select_one", "required_extensions")}
    with tempfile.TemporaryDirectory(prefix="nex-s145-restore-") as temp:
        base = Path(temp)
        times = iter((datetime(2026, 10, 8, tzinfo=timezone.utc), datetime(2026, 10, 8, 0, 0, 1, tzinfo=timezone.utc)))
        backup = build_logical_backup_plan(
            policy=policy, target=target, backup_id="20261008T000000Z-1234abcd",
            backup_root=base / "backup", pg_dump_bin=Path("/usr/bin/pg_dump"),
            service_file=base / "pg_service.conf", passfile=base / ".pgpass",
        )
        execute_logical_backup(backup, runner=dump_runner, clock=lambda: next(times))
        restore = build_isolated_restore_plan(
            policy=policy, target=target, backup_id=backup.backup_id,
            archive_path=backup.archive_path, manifest_path=backup.manifest_path,
            pg_restore_bin=Path("/usr/bin/pg_restore"),
            recovery_service=f"{target.libpq_service}-recovery",
            target_class="isolated_recovery", service_file=base / "pg_service.conf",
            passfile=base / ".pgpass",
        )
        result = execute_isolated_restore(
            restore, inspect_runner=command_runner, restore_runner=command_runner,
            probe=lambda _plan: probes,
            clock=lambda: datetime(2026, 10, 8, 0, 0, 2, tzinfo=timezone.utc),
        )
        projection = restore_result_public_projection(result)
        command_parts = [part for command in commands for part in command]
        command_text = " ".join(command_parts)
        checks = {
            "archive_integrity_admitted": result.archive_sha256 == projection["archive_sha256"],
            "isolated_target_enforced": result.target_class == "isolated_recovery",
            "active_service_absent": f"--dbname=service={target.libpq_service}" not in command_parts,
            "recovery_service_present": f"--dbname=service={target.libpq_service}-recovery" in command_parts,
            "single_transaction_restore": "--single-transaction" in command_text,
            "four_post_restore_probes": result.probe_count == 4,
            "public_projection_value_free": "path" not in str(projection).lower() and "PGPASSFILE" not in str(projection),
        }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_isolated_restore_guard_audit.v1",
        "slice": "1446", "requirement": "S145",
        "status": "PASS" if passed else "FAIL", "checks": checks,
        "metrics": {"database_targets": len(policy.targets), "restore_probes": result.probe_count},
        "next_slice": "1447" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        "postgres_isolated_restore_guard="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"targets={metrics.get('database_targets', 0)} probes={metrics.get('restore_probes', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_isolated_restore_guard()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
