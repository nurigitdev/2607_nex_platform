#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 3:
        print(
            "usage: check_coverage_thresholds.py "
            "<coverage.json> <statement_min> <branch_min>",
            file=sys.stderr,
        )
        return 2

    coverage_path = Path(args[0])
    statement_min = float(args[1])
    branch_min = float(args[2])
    totals = load_totals(coverage_path)
    result = evaluate_thresholds(totals, statement_min, branch_min)

    print(
        "statement_coverage="
        f"{result['statement_coverage']:.2f}% threshold={statement_min:.2f}%"
    )
    print(
        "branch_coverage="
        f"{result['branch_coverage']:.2f}% threshold={branch_min:.2f}%"
    )

    for failure in result["failures"]:
        print(f"coverage failure: {failure}", file=sys.stderr)

    return 1 if result["failures"] else 0


def load_totals(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["totals"]


def evaluate_thresholds(
    totals: dict[str, float],
    statement_min: float,
    branch_min: float,
) -> dict[str, object]:
    statement_coverage = calculate_percent(
        float(totals.get("covered_lines", 0)),
        float(totals.get("num_statements", 0)),
    )
    branch_coverage = calculate_percent(
        float(totals.get("covered_branches", 0)),
        float(totals.get("num_branches", 0)),
    )
    failures: list[str] = []

    if statement_coverage < statement_min:
        failures.append(
            f"statement coverage {statement_coverage:.2f}% is below {statement_min:.2f}%"
        )
    if branch_coverage < branch_min:
        failures.append(
            f"branch coverage {branch_coverage:.2f}% is below {branch_min:.2f}%"
        )

    return {
        "statement_coverage": statement_coverage,
        "branch_coverage": branch_coverage,
        "failures": failures,
    }


def calculate_percent(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 100.0
    return numerator / denominator * 100


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
