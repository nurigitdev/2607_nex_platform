#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
AE_PATH = ROOT / "services" / "nex-ae-api"
sys.path.insert(0, str(AE_PATH))

from nex_ae_api.persistence_audit import (  # noqa: E402
    build_ae_persistence_gap_rebaseline,
)


def run_ae_persistence_gap_rebaseline(root: Path = ROOT) -> dict[str, Any]:
    return build_ae_persistence_gap_rebaseline(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "ae_persistence_gap_rebaseline="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"surfaces={summary.get('surface_count', 0)} "
        f"postgres_ready={summary.get('postgres_ready_count', 0)} "
        f"delegated={summary.get('delegated_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_persistence_gap_rebaseline()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
