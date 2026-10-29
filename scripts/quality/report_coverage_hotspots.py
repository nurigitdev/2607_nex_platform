#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "nex_coverage_hotspots.v1"
TARGET_STATEMENT_COVERAGE = (96.25, 96.30)


def build_hotspot_report(
    coverage: Mapping[str, Any], *, top_n: int = 20
) -> dict[str, Any]:
    files = coverage.get("files")
    totals = coverage.get("totals")
    if not isinstance(files, Mapping) or not isinstance(totals, Mapping):
        raise TypeError("coverage report must contain files and totals objects")
    if top_n < 1:
        raise ValueError("top_n must be positive")

    rows = [_file_row(str(path), value) for path, value in files.items()]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["ownership_scope"]), []).append(row)

    total_statements = _integer(totals, "num_statements")
    covered_statements = _integer(totals, "covered_lines")
    total_branches = _integer(totals, "num_branches")
    covered_branches = _integer(totals, "covered_branches")
    statement_percent = _percent(covered_statements, total_statements)
    branch_percent = _percent(covered_branches, total_branches)
    targets = {
        f"{target:.2f}": max(
            0, math.ceil(total_statements * target / 100) - covered_statements
        )
        for target in TARGET_STATEMENT_COVERAGE
    }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "coverage_source": "coverage.py-json",
        "thresholds_changed": False,
        "totals": {
            "statements": total_statements,
            "covered_statements": covered_statements,
            "missing_statements": total_statements - covered_statements,
            "statement_coverage": statement_percent,
            "branches": total_branches,
            "covered_branches": covered_branches,
            "missing_branches": total_branches - covered_branches,
            "branch_coverage": branch_percent,
            "additional_existing_statements_for_targets": targets,
        },
        "ownership_scopes": {
            name: _aggregate(group) for name, group in sorted(groups.items())
        },
        "hotspots": {
            "product_code": _hotspots(rows, "product_code", top_n),
            "smoke_test_harness": _hotspots(rows, "smoke_test_harness", top_n),
            "other_runtime_tooling": _hotspots(rows, "other_runtime_tooling", top_n),
        },
    }


def _file_row(path: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"coverage file entry must be an object: {path}")
    summary = value.get("summary")
    if not isinstance(summary, Mapping):
        raise TypeError(f"coverage file summary is unavailable: {path}")
    statements = _integer(summary, "num_statements")
    covered_statements = _integer(summary, "covered_lines")
    branches = _integer(summary, "num_branches")
    covered_branches = _integer(summary, "covered_branches")
    return {
        "path": path,
        "ownership_scope": _ownership_scope(path),
        "statements": statements,
        "covered_statements": covered_statements,
        "missing_statements": statements - covered_statements,
        "statement_coverage": _percent(covered_statements, statements),
        "branches": branches,
        "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
        "branch_coverage": _percent(covered_branches, branches),
    }


def _ownership_scope(path: str) -> str:
    if path.startswith(("services/", "providers/")):
        return "product_code"
    if path.startswith(("scripts/smoke/", "scripts/quality/")):
        return "smoke_test_harness"
    return "other_runtime_tooling"


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statements = sum(int(row["statements"]) for row in rows)
    covered_statements = sum(int(row["covered_statements"]) for row in rows)
    branches = sum(int(row["branches"]) for row in rows)
    covered_branches = sum(int(row["covered_branches"]) for row in rows)
    return {
        "file_count": len(rows),
        "statements": statements,
        "covered_statements": covered_statements,
        "missing_statements": statements - covered_statements,
        "statement_coverage": _percent(covered_statements, statements),
        "branches": branches,
        "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
        "branch_coverage": _percent(covered_branches, branches),
    }


def _hotspots(
    rows: list[dict[str, Any]], scope: str, top_n: int
) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row["ownership_scope"] == scope
        and (row["missing_statements"] or row["missing_branches"])
    ]
    candidates.sort(
        key=lambda row: (
            -int(row["missing_statements"]),
            -int(row["missing_branches"]),
            str(row["path"]),
        )
    )
    return candidates[:top_n]


def _integer(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise ValueError(f"coverage metric must be a non-negative integer: {key}")
    return result


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def summary_line(report: Mapping[str, Any]) -> str:
    totals = report["totals"]
    scopes = report["ownership_scopes"]
    product = scopes.get("product_code", {})
    harness = scopes.get("smoke_test_harness", {})
    return (
        "coverage_hotspots=pass "
        f"total={totals['statement_coverage']:.2f}/{totals['branch_coverage']:.2f} "
        f"product={product.get('statement_coverage', 100.0):.2f}/"
        f"{product.get('branch_coverage', 100.0):.2f} "
        f"harness={harness.get('statement_coverage', 100.0):.2f}/"
        f"{harness.get('branch_coverage', 100.0):.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report product and smoke/test-harness coverage hotspots"
    )
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        coverage = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        report = build_hotspot_report(coverage, top_n=args.top)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(
            summary_line(report)
            if args.summary
            else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        print(f"coverage_hotspots=fail detail={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
