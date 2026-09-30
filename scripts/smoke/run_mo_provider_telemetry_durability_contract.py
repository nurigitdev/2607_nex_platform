#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry_durability_contract import (  # noqa: E402
    build_mo_provider_telemetry_durability_contract,
)


def run_mo_provider_telemetry_durability_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    return build_mo_provider_telemetry_durability_contract(root)


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_durability_contract="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"wire_fields={summary.get('wire_field_count', 0)} "
        f"table_columns={summary.get('table_column_count', 0)} "
        f"forbidden={summary.get('forbidden_column_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_durability_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
