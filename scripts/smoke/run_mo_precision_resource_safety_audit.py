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

from nex_mo.precision_resource_audit import (  # noqa: E402
    build_mo_precision_resource_safety_audit,
)


def run_mo_precision_resource_safety_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_precision_resource_safety_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_precision_resource_safety_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"precision={evidence.get('precision_readiness', 'BLOCKED')} "
        f"bf16={summary.get('bf16_selected_count', 0)}/"
        f"{summary.get('selected_profile_count', 0)} "
        f"runtime_gaps={summary.get('runtime_gap_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_precision_resource_safety_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
