#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from nex_cx.database_drift_audit import build_cx_database_drift_audit  # noqa: E402


def run_cx_database_drift_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_cx_database_drift_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    strategy = evidence.get("migration_strategy") or {}
    return (
        "cx_database_drift_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"migrations={summary.get('migration_count', 0)} "
        f"core_tables={summary.get('core_table_count', 0)} "
        f"max_identifier={summary.get('longest_identifier_length', 0)} "
        f"alembic={strategy.get('alembic_status', 'UNKNOWN')} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_database_drift_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
