#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.postgres_operator import (  # noqa: E402
    check_postgres_operator_runtime,
    postgres_operator_public_projection,
)


def run_check(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    checked = check_postgres_operator_runtime(environment or os.environ)
    return postgres_operator_public_projection(checked)


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        f"postgres_operator_check={'pass' if result.get('state') == 'READY' else 'fail'} "
        f"postgres={result.get('postgres_major', 0)} "
        f"tools={result.get('tool_count', 0)} "
        f"credentials={result.get('credential_source_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required; execution is admitted by Slice 1451")
    result = run_check()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
