#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from platform_test_migrations import (  # noqa: E402
    PlatformMigrationReadinessError,
    run_platform_test_migration_readiness,
)


SMOKE_ENV = "NEX_PLATFORM_TEST_MIGRATION_SMOKE"


def run_smoke(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "platform_test_migration_readiness_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    try:
        result = run_platform_test_migration_readiness(env)
    except PlatformMigrationReadinessError as exc:
        return {
            "schema_version": "platform_test_migration_readiness_smoke.v1",
            "status": "FAIL",
            "failure_code": exc.failure_code,
            "service_id": exc.service_id,
        }
    return {
        **result.to_public_projection(),
        "schema_version": "platform_test_migration_readiness_smoke.v1",
        "slice": "1325",
        "requirement": "S133",
        "next_slice": "1326",
    }


def summary_line(report: Mapping[str, Any]) -> str:
    status = report.get("status")
    if status == "SKIPPED":
        return "platform_test_migration_readiness=skip"
    if status != "PASS":
        return (
            "platform_test_migration_readiness=fail "
            f"service={report.get('service_id') or 'none'} "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_test_migration_readiness=pass "
        f"services={report.get('service_count')} "
        f"migrations={report.get('migration_count')} "
        f"applied={report.get('applied_count')} next={report.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = run_smoke()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
