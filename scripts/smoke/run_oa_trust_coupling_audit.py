#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
OA_PATH = ROOT / "services" / "nex-oa"
sys.path.insert(0, str(OA_PATH))

from nex_oa.trust_coupling_audit import build_oa_trust_coupling_audit  # noqa: E402


def run_oa_trust_coupling_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_oa_trust_coupling_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_trust_coupling_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"controls={summary.get('control_count', 0)} "
        f"explicit={summary.get('explicit_boundary_count', 0)} "
        f"refactor={summary.get('refactor_required_count', 0)} "
        f"high_risk={summary.get('high_risk_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_trust_coupling_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
