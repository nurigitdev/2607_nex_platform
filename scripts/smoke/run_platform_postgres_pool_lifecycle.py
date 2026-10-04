#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.postgres_pool_lifecycle import (  # noqa: E402
    PlatformPostgresPoolLifecycle,
    PostgresPoolLifecycleError,
)


SMOKE_ENV = "NEX_PLATFORM_POSTGRES_POOL_SMOKE"


def run_smoke(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "platform_postgres_pool_lifecycle_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    first: PlatformPostgresPoolLifecycle | None = None
    second: PlatformPostgresPoolLifecycle | None = None
    try:
        first = PlatformPostgresPoolLifecycle.build(env)
        first_tokens = first.engine_identity_tokens()
        first_ready = first.public_status()
        first_disposed = first.dispose()

        second = PlatformPostgresPoolLifecycle.build(env)
        second_tokens = second.engine_identity_tokens()
        second_ready = second.public_status()
        second_disposed = second.dispose()
    except PostgresPoolLifecycleError as exc:
        _best_effort_dispose(first, second)
        return {
            "schema_version": "platform_postgres_pool_lifecycle_smoke.v1",
            "status": "FAIL",
            "failure_code": exc.failure_code,
            "service_id": exc.service_id,
            "workload": exc.workload,
        }

    fresh_count = len(second_tokens.difference(first_tokens))
    passed = (
        first_ready["pool_count"] == 10
        and second_ready["pool_count"] == 10
        and first_disposed["pending_disposal_count"] == 0
        and second_disposed["pending_disposal_count"] == 0
        and fresh_count == 10
    )
    return {
        "schema_version": "platform_postgres_pool_lifecycle_smoke.v1",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "pool_lifecycle_incomplete",
        "service_count": second_ready["service_count"],
        "pool_count": second_ready["pool_count"],
        "fresh_engine_count": fresh_count,
        "disposed_pool_count": 20,
        "slice": "1326",
        "requirement": "S133",
        "next_slice": "1327",
    }


def _best_effort_dispose(
    *lifecycles: PlatformPostgresPoolLifecycle | None,
) -> None:
    for lifecycle in lifecycles:
        if lifecycle is None:
            continue
        try:
            lifecycle.dispose()
        except PostgresPoolLifecycleError:
            continue


def summary_line(report: Mapping[str, Any]) -> str:
    status = report.get("status")
    if status == "SKIPPED":
        return "platform_postgres_pool_lifecycle=skip"
    if status != "PASS":
        return (
            "platform_postgres_pool_lifecycle=fail "
            f"service={report.get('service_id') or 'none'} "
            f"workload={report.get('workload') or 'none'} "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_postgres_pool_lifecycle=pass "
        f"services={report.get('service_count')} pools={report.get('pool_count')} "
        f"fresh={report.get('fresh_engine_count')} next={report.get('next_slice')}"
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
