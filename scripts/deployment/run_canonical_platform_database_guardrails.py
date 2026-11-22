#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime import (
    DemoDatabaseGuardError,
    current_platform_backup_set_public_projection,
    current_platform_database_admission_public_projection,
    execute_current_platform_pre_migration_backup_set,
    inspect_demo_database_targets,
    load_env_file,
    resolve_current_platform_database_targets,
)

SCHEMA_VERSION = "current_platform_database_guardrail_evidence.v1"
DEFAULT_BACKUP_ROOT = Path("/data/nex-platform/current/postgres-backups")
DEFAULT_REPORT = ROOT / "reports/deployment/current-platform-database-guardrails.json"


def run_current_platform_database_guardrails(
    environ: Mapping[str, str],
    *,
    database_root: Path = ROOT / "database",
    connect: Any = psycopg.connect,
    execute_backup: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    backup_id: str | None = None,
    backup_confirmation: str = "",
    pg_dump_bin: Path = Path("/usr/bin/pg_dump"),
    backup_runner: Any = subprocess.run,
) -> dict[str, Any]:
    targets = resolve_current_platform_database_targets(environ)
    inspections = inspect_demo_database_targets(
        targets,
        database_root=database_root,
        connect=connect,
    )
    admission = current_platform_database_admission_public_projection(inspections)
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "actual_postgres": True,
        "migration_executed": False,
        "admission": admission,
        "backup": {"state": "NOT_REQUESTED"},
        "redaction": {
            "database_urls_included": False,
            "credentials_included": False,
            "confirmation_values_included": False,
        },
    }
    if execute_backup:
        backup = execute_current_platform_pre_migration_backup_set(
            targets,
            inspections,
            backup_id=backup_id or _new_backup_id(),
            backup_root=backup_root,
            pg_dump_bin=pg_dump_bin,
            confirmation=backup_confirmation,
            runner=backup_runner,
            parent_environ=environ,
        )
        evidence["backup"] = current_platform_backup_set_public_projection(backup)
    return evidence


def summary_line(evidence: Mapping[str, Any]) -> str:
    admission = evidence.get("admission", {})
    backup = evidence.get("backup", {})
    return (
        f"current_platform_database_guardrails="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"identity={admission.get('state', 'UNKNOWN')} "
        f"databases={admission.get('service_count', 0)} "
        f"migrations_current={admission.get('migration_current_count', 0)} "
        f"backup={backup.get('state', 'UNKNOWN')}"
    )


def write_report(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(dict(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Admit and protect the eight current Platform development databases."
        )
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--backup-id")
    parser.add_argument("--backup-confirmation", default="")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.check:
        print("ERROR: --check is required", file=sys.stderr)
        return 2
    if args.env_file is not None:
        load_env_file(args.env_file)
    try:
        evidence = run_current_platform_database_guardrails(
            os.environ,
            execute_backup=args.backup,
            backup_root=args.backup_root,
            backup_id=args.backup_id,
            backup_confirmation=args.backup_confirmation,
        )
        write_report(args.report, evidence)
    except (DemoDatabaseGuardError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0


def _new_backup_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(8)}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
