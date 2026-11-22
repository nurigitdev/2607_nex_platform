#!/usr/bin/env python3
"""Validate the MyBee Phase-1 Platform lock from a source checkout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
if str(DOMAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(DOMAIN_ROOT))

from mybee_ax.compatibility import CompatibilityError, validate_platform_lock


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("domains/mybee/compatibility/platform.lock.json"),
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    lock_path = args.lock if args.lock.is_absolute() else root / args.lock
    try:
        report = validate_platform_lock(root, lock_path)
    except CompatibilityError as error:
        print(f"mybee_platform_lock=fail code={error.code}")
        return 2

    if args.summary:
        print(
            "mybee_platform_lock=pass "
            f"openapi={report.openapi_count} "
            f"nsl={report.nsl_package_version} "
            f"baseline={report.baseline_commit[:8]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
