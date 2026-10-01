#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.operations_integration_boundary import (  # noqa: E402
    build_mo_operations_integration_boundary,
)


def run_mo_operations_integration_boundary(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_operations_integration_boundary(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_integration_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"boundaries={summary.get('boundary_count', 0)} "
        f"sources={summary.get('source_count', 0)} "
        f"capabilities={summary.get('required_capability_count', 0)} "
        f"new_tables={summary.get('new_table_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_integration_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
