#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Mapping


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        print(
            "usage: check_coverage_scopes.py "
            "<coverage.json> <statement_min> <branch_min> <scope> [<scope> ...]",
            file=sys.stderr,
        )
        return 2

    coverage_path = Path(args[0])
    statement_min = float(args[1])
    branch_min = float(args[2])
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    failed = False
    for scope in args[3:]:
        result = evaluate_scope(
            coverage,
            scope=scope,
            statement_min=statement_min,
            branch_min=branch_min,
        )
        print(
            f"coverage_scope={scope} files={result['file_count']} "
            f"statement={result['statement_coverage']:.2f}% "
            f"branch={result['branch_coverage']:.2f}%"
        )
        for failure in result["failures"]:
            failed = True
            print(f"coverage scope failure: {failure}", file=sys.stderr)
    return 1 if failed else 0


def evaluate_scope(
    coverage: Mapping[str, Any],
    *,
    scope: str,
    statement_min: float,
    branch_min: float,
) -> dict[str, Any]:
    normalized = Path(scope).as_posix().rstrip("/")
    files = _mapping(coverage.get("files"))
    matches = [
        _mapping(value)
        for path, value in files.items()
        if path == normalized or path.startswith(f"{normalized}/")
    ]
    statements = sum(
        int(_mapping(item.get("summary")).get("num_statements") or 0)
        for item in matches
    )
    covered_statements = sum(
        int(_mapping(item.get("summary")).get("covered_lines") or 0)
        for item in matches
    )
    branches = sum(
        int(_mapping(item.get("summary")).get("num_branches") or 0)
        for item in matches
    )
    covered_branches = sum(
        int(_mapping(item.get("summary")).get("covered_branches") or 0)
        for item in matches
    )
    statement_coverage = _percent(covered_statements, statements)
    branch_coverage = _percent(covered_branches, branches)
    failures: list[str] = []
    if not matches:
        failures.append(f"{scope} is absent from the coverage report")
    if statement_coverage < statement_min:
        failures.append(
            f"{scope} statement coverage {statement_coverage:.2f}% "
            f"is below {statement_min:.2f}%"
        )
    if branch_coverage < branch_min:
        failures.append(
            f"{scope} branch coverage {branch_coverage:.2f}% "
            f"is below {branch_min:.2f}%"
        )
    return {
        "scope": scope,
        "file_count": len(matches),
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "failures": failures,
    }


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
