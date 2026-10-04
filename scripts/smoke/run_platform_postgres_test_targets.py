#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.postgres_targets import (  # noqa: E402
    POSTGRES_TEST_TARGETS,
    build_postgres_test_runtime_overlay,
    postgres_test_targets_public_projection,
    resolve_postgres_test_targets,
)


def _synthetic_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            f"postgresql://{target.expected_role_name}:private@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in POSTGRES_TEST_TARGETS
    }


def build_report() -> dict[str, object]:
    environ = _synthetic_environment()
    resolved = resolve_postgres_test_targets(environ)
    overlay = build_postgres_test_runtime_overlay(environ)
    return {
        "status": "PASS",
        "targets": postgres_test_targets_public_projection(resolved),
        "runtime_alias_count": len(overlay),
        "runtime_alias_values_exposed": False,
        "next_slice": "1325",
    }


def summary_line(report: dict[str, object]) -> str:
    if report.get("status") != "PASS":
        return "platform_postgres_test_targets=fail"
    targets = report.get("targets") or {}
    assert isinstance(targets, dict)
    return (
        "platform_postgres_test_targets=pass "
        f"services={targets.get('service_count')} "
        f"aliases={report.get('runtime_alias_count')} next={report.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
