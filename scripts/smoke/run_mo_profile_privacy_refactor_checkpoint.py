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

from nex_mo.profile_privacy_audit import (  # noqa: E402
    build_mo_profile_privacy_refactor_checkpoint,
)


def run_mo_profile_privacy_refactor_checkpoint(root: Path = ROOT) -> dict[str, Any]:
    return build_mo_profile_privacy_refactor_checkpoint(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_profile_privacy_refactor_checkpoint="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"readiness={evidence.get('refactor_readiness', 'BLOCKED')} "
        f"profiles={summary.get('public_profile_count', 0)} "
        f"forbidden_fields={summary.get('forbidden_public_field_count', 0)} "
        f"remaining_drift={summary.get('remaining_catalog_drift_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_profile_privacy_refactor_checkpoint()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
