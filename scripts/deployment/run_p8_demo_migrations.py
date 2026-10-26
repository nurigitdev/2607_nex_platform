#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path[:0] = [str(SHARED_PATH), str(DB_SCRIPT_PATH)]

from nex_runtime import load_env_file
from nex_runtime.demo_database import (
    DemoDatabaseGuardError,
    inspect_demo_database_targets,
    load_demo_backup_set_manifest,
    resolve_demo_database_targets,
)
from nex_runtime.demo_migrations import (
    execute_demo_migration_closure,
)
from run_migrations import run_service_migrations

DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-migrations.json"


def run_demo_migrations(
    environ: Mapping[str, str],
    *,
    backup_manifest_path: Path,
    confirmation: str,
    database_root: Path = ROOT / "database",
    connect: Any = psycopg.connect,
    migration_runner: Any = run_service_migrations,
) -> dict[str, Any]:
    targets = resolve_demo_database_targets(environ)
    inspections = inspect_demo_database_targets(
        targets,
        database_root=database_root,
        connect=connect,
    )
    backup_manifest = load_demo_backup_set_manifest(backup_manifest_path)
    return execute_demo_migration_closure(
        targets,
        inspections,
        backup_manifest,
        confirmation=confirmation,
        database_root=database_root,
        migration_runner=migration_runner,
        connect=connect,
    )


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(report), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def summary_line(report: Mapping[str, Any]) -> str:
    applied = sum(len(item["applied"]) for item in report["services"])
    return (
        f"status={report['status']} services={report['service_count']} "
        f"current={report['migration_current_count']} applied={applied} "
        f"backup_id={report['backup_id']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply admitted P8 Demo migrations to the seven dev databases."
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--backup-manifest", type=Path, required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.env_file is not None:
        load_env_file(args.env_file)
    try:
        report = run_demo_migrations(
            os.environ,
            backup_manifest_path=args.backup_manifest,
            confirmation=args.confirmation,
        )
        write_report(args.report, report)
    except (DemoDatabaseGuardError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"ERROR: migration execution failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    if args.summary:
        print(summary_line(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
