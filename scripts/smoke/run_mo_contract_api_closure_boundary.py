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

from nex_mo.contract_api_closure_boundary import (  # noqa: E402
    build_mo_contract_api_closure_boundary,
)


def run_mo_contract_api_closure_boundary(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_contract_api_closure_boundary(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_contract_api_closure_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"classes={summary.get('drift_class_count', 0)} "
        f"drift={summary.get('baseline_drift_count', 0)}->"
        f"{summary.get('current_drift_count', 0)}->"
        f"{summary.get('target_drift_count', 0)} "
        f"issues={summary.get('baseline_issue_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_contract_api_closure_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
