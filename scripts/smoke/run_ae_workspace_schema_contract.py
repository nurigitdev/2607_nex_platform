#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "database/nex-ae-api/migrations/1014_ae_workspace_activity_persistence.sql"
)


def run_workspace_schema_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root / MIGRATION.relative_to(ROOT)
    source = _read_text(path)
    compact = " ".join(source.lower().split())
    identifiers = _identifiers(source)
    checks = {
        "transactional": compact.startswith("begin;") and compact.endswith("commit;"),
        "workspace_table": "create table if not exists ae_workspaces" in compact,
        "activity_table": (
            "create table if not exists ae_workspace_activities" in compact
        ),
        "chat_workspace_link": (
            "alter table ae_chat_interactions" in compact
            and "add column if not exists workspace_id uuid null" in compact
        ),
        "owner_index": "idx_ae_ws_owner_time" in compact,
        "activity_index": "idx_ae_ws_act_time" in compact,
        "chat_index": "idx_ae_chat_ws_owner_time" in compact,
        "identifier_lengths_safe": all(len(item.encode("utf-8")) <= 63 for item in identifiers),
        "private_columns_absent": not any(
            token in compact
            for token in ("raw_prompt", "raw_output", "source_bytes", "access_token")
        ),
        "migration_recorded": (
            "'1014_ae_workspace_activity_persistence'" in compact
        ),
    }
    return {
        "contract_schema_version": "ae_workspace_schema_contract.v1",
        "slice": "1014",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "tables": ["ae_workspaces", "ae_workspace_activities"],
        "altered_tables": ["ae_chat_interactions"],
        "identifier_count": len(identifiers),
        "longest_identifier_length": max(
            (len(item.encode("utf-8")) for item in identifiers),
            default=0,
        ),
        "new_table_count": 2,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_workspace_schema="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"tables={result.get('new_table_count', 0)} "
        f"max_identifier={result.get('longest_identifier_length', 0)}"
    )


def _identifiers(source: str) -> set[str]:
    patterns = (
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
        r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z][a-z0-9_]*)",
        r"\bCONSTRAINT\s+([a-z][a-z0-9_]*)",
    )
    return {
        match.group(1).lower()
        for pattern in patterns
        for match in re.finditer(pattern, source, flags=re.IGNORECASE)
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_workspace_schema_contract()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
