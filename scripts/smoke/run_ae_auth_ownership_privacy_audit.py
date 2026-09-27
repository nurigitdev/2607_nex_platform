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

from nex_ae_api.ownership_privacy_audit import (  # noqa: E402
    build_ae_auth_ownership_privacy_audit,
)


def run_ae_auth_ownership_privacy_audit(root: Path = ROOT) -> dict[str, Any]:
    return build_ae_auth_ownership_privacy_audit(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "ae_auth_ownership_privacy_audit="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"surfaces={summary.get('surface_count', 0)} "
        f"hardened={summary.get('hardened_count', 0)} "
        f"refactors={summary.get('refactor_count', 0)} "
        f"high_risk={summary.get('high_risk_count', 0)} "
        f"issues={summary.get('evidence_issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_auth_ownership_privacy_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
