#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_hardening_boundary import (  # noqa: E402
    build_mo_runtime_hardening_boundary,
)


def run_mo_runtime_hardening_boundary(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_runtime_hardening_boundary(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_hardening_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"boundaries={summary.get('refactoring_boundary_count', 0)} "
        f"durable={summary.get('durable_candidate_count', 0)} "
        f"external_metrics={summary.get('external_metrics_candidate_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_hardening_boundary()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
