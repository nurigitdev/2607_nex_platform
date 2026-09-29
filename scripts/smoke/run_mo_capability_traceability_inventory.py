#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
MO_PATH = ROOT / "services" / "nex-mo"
sys.path.insert(0, str(MO_PATH))

from nex_mo.current_state_traceability import (  # noqa: E402
    build_mo_capability_traceability_inventory,
)


def run_mo_capability_traceability_inventory(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_capability_traceability_inventory(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_capability_traceability_inventory="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"requirements={summary.get('requirement_count', 0)} "
        f"traceable={summary.get('traceable_count', 0)} "
        f"implemented={summary.get('implemented_count', 0)} "
        f"partial={summary.get('partial_count', 0)} "
        f"issues={len(evidence.get('issues') or [])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_capability_traceability_inventory()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
