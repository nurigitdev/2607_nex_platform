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

from nex_cx.current_state_traceability import (
    build_cx_capability_traceability_inventory,
)  # noqa: E402


def run_cx_capability_traceability_inventory(
    root: Path = ROOT,
) -> dict[str, Any]:
    return build_cx_capability_traceability_inventory(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    status = str(evidence.get("status") or "FAIL").lower()
    return (
        f"cx_capability_traceability_inventory={status} "
        f"requirements={summary.get('requirement_count', 0)} "
        f"traceable={summary.get('traceable_count', 0)} "
        f"evidence={summary.get('evidence_count', 0)} "
        f"issues={len(evidence.get('issues') or [])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_capability_traceability_inventory()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
