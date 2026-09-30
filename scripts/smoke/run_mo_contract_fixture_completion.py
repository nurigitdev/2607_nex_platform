#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit,
)


def run_mo_contract_fixture_completion(
    root: Path = ROOT,
    *,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = dict(audit) if audit is not None else build_mo_contract_api_drift_audit(root)
    summary = _mapping(evidence.get("summary"))
    schema_count = _count(summary, "schema_count")
    positive_count = _count(summary, "positive_fixture_covered_count")
    negative_count = _count(summary, "negative_fixture_covered_count")
    checks = {
        "drift_audit_passed": evidence.get("status") == "PASS",
        "mo_schema_inventory_complete": schema_count == 17,
        "positive_fixture_coverage_complete": positive_count == schema_count,
        "negative_fixture_coverage_complete": negative_count == schema_count,
        "missing_positive_list_empty": not evidence.get(
            "missing_positive_fixture_schemas"
        ),
        "missing_negative_list_empty": not evidence.get(
            "missing_negative_fixture_schemas"
        ),
        "fixture_drift_removed": _count(summary, "drift_count") <= 25,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_contract_fixture_completion.v1",
        "slice": "1134",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_contract_fixture_completion_failed",
        "checks": checks,
        "summary": {
            "schema_count": schema_count,
            "positive_fixture_count": positive_count,
            "negative_fixture_count": negative_count,
            "remaining_drift_count": _count(summary, "drift_count"),
        },
        "next_slice": "1135" if passed else "blocked",
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _count(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key, 0)
    return item if isinstance(item, int) and item >= 0 else 0


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_contract_fixture_completion="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"positive={summary.get('positive_fixture_count', 0)}/"
        f"{summary.get('schema_count', 0)} "
        f"negative={summary.get('negative_fixture_count', 0)}/"
        f"{summary.get('schema_count', 0)} "
        f"drift={summary.get('remaining_drift_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_contract_fixture_completion()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
