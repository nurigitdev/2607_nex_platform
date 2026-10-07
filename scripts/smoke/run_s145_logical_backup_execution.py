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

from nex_runtime.postgres_backup import (  # noqa: E402
    backup_result_public_projection,
    build_logical_backup_plan,
    execute_logical_backup,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy  # noqa: E402


POLICY_PATH = ROOT / "deployment/postgres/s145-policy.yaml"


def run_logical_backup_execution(root: Path = ROOT) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / POLICY_PATH.relative_to(ROOT))
    target = policy.targets[0]
    calls: list[dict[str, Any]] = []

    def runner(command, *, env, stdout, stderr, check):
        calls.append({"command": tuple(command), "environment": dict(env), "stderr": stderr, "check": check})
        stdout.write(b"PGDMP\x01deterministic-s145")
        return SimpleNamespace(returncode=0)

    times = iter(
        (
            datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 8, 0, 0, 1, tzinfo=timezone.utc),
        )
    )
    with tempfile.TemporaryDirectory(prefix="nex-s145-backup-") as temp:
        base = Path(temp)
        plan = build_logical_backup_plan(
            policy=policy,
            target=target,
            backup_id="20261008T000000Z-1234abcd",
            backup_root=base / "backup",
            pg_dump_bin=Path("/usr/bin/pg_dump"),
            service_file=base / "pg_service.conf",
            passfile=base / ".pgpass",
            parent_environ={"PATH": "/usr/bin", "PGPASSWORD": "forbidden", "DATABASE_URL": "forbidden"},
        )
        result = execute_logical_backup(plan, runner=runner, clock=lambda: next(times))
        projection = backup_result_public_projection(result)
        manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
        command_text = " ".join(calls[0]["command"])
        checks = {
            "policy_target_used": result.service_id == target.service_id,
            "custom_archive_created": plan.archive_path.read_bytes().startswith(b"PGDMP"),
            "atomic_partial_removed": not plan.partial_path.exists(),
            "manifest_matches_result": manifest == result.__dict__,
            "credential_not_in_arguments": "password" not in command_text.lower() and "postgresql://" not in command_text,
            "unsafe_environment_not_inherited": "PGPASSWORD" not in calls[0]["environment"] and "DATABASE_URL" not in calls[0]["environment"],
            "libpq_file_transport_used": set(("PGSERVICEFILE", "PGPASSFILE")) <= calls[0]["environment"].keys(),
            "public_projection_value_free": "archive_name" not in projection and "PGPASSFILE" not in str(projection),
        }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_logical_backup_execution_audit.v1",
        "slice": "1445",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "metrics": {"database_targets": len(policy.targets), "archive_bytes": projection["archive_bytes"]},
        "next_slice": "1446" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        "postgres_logical_backup_execution="
        f"{'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"targets={metrics.get('database_targets', 0)} "
        f"bytes={metrics.get('archive_bytes', 0)} "
        f"next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_logical_backup_execution()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

