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

from nex_cx.ownership_enforcement_audit import (  # noqa: E402
    build_cx_ownership_enforcement_audit,
)


def run_cx_ownership_enforcement_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    return build_cx_ownership_enforcement_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_ownership_enforcement_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"readiness={evidence.get('enforcement_readiness', 'UNKNOWN')} "
        f"surfaces={summary.get('surface_count', 0)} "
        f"high_risk_gaps={summary.get('high_risk_gap_count', 0)} "
        f"evidence_gaps={summary.get('evidence_gap_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_ownership_enforcement_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
