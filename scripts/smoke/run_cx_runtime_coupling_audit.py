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

from nex_cx.runtime_coupling_audit import (  # noqa: E402
    build_cx_runtime_coupling_audit,
)


def run_cx_runtime_coupling_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_cx_runtime_coupling_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_runtime_coupling_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"refactor_required={summary.get('refactor_required_count', 0)} "
        f"good_boundaries={summary.get('good_boundary_count', 0)} "
        f"auth_helpers={summary.get('duplicated_authorization_helper_count', 0)} "
        f"evidence_gaps={summary.get('evidence_gap_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_runtime_coupling_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
