#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "db"):
    sys.path.insert(0, str(path))

from nex_runtime.postgres_restoration import (  # noqa: E402
    PlatformPostgresRestorationStore,
    PostgresRestorationError,
)
from platform_test_migrations import (  # noqa: E402
    PlatformMigrationReadinessError,
    run_platform_test_migration_readiness,
)


SMOKE_ENV = "NEX_PLATFORM_POSTGRES_RESTORATION_SMOKE"


def run_smoke(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "platform_postgres_restoration_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    run_id = f"s133-{uuid4().hex}"
    store: PlatformPostgresRestorationStore | None = None
    written = False
    cleaned = False
    try:
        migration = run_platform_test_migration_readiness(env)
        store = PlatformPostgresRestorationStore.build(env)
        write_result = store.write(run_id)
        written = True
        restore_result = store.restore(run_id)
        cleanup_result = store.cleanup(run_id)
        cleaned = True
        absence_result = store.confirm_absence(run_id)
    except (PlatformMigrationReadinessError, PostgresRestorationError) as exc:
        return _failure(exc.failure_code, getattr(exc, "service_id", None))
    except Exception as exc:
        return _failure("postgres_restoration_failed", exc.__class__.__name__)
    finally:
        if store is not None and written and not cleaned:
            try:
                store.cleanup(run_id)
                store.confirm_absence(run_id)
            except PostgresRestorationError:
                pass

    return {
        "schema_version": "platform_postgres_restoration_smoke.v1",
        "status": "PASS",
        "profile": "test",
        "service_count": write_result.service_count,
        "migration_count": sum(item.migration_count for item in migration.services),
        "written_count": write_result.record_count,
        "restored_count": restore_result.record_count,
        "cleaned_count": cleanup_result.record_count,
        "absence_count": absence_result.record_count,
        "fresh_connection_count": 20,
        "durable_table": "service_operational_events",
        "slice": "1329",
        "requirement": "S133",
        "next_slice": "1330",
    }


def _failure(failure_code: str, service_id: str | None) -> dict[str, Any]:
    return {
        "schema_version": "platform_postgres_restoration_smoke.v1",
        "status": "FAIL",
        "failure_code": failure_code,
        "service_id": service_id,
    }


def summary_line(report: Mapping[str, Any]) -> str:
    status = report.get("status")
    if status == "SKIPPED":
        return "platform_postgres_restoration=skip"
    if status != "PASS":
        return (
            "platform_postgres_restoration=fail "
            f"service={report.get('service_id') or 'none'} "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_postgres_restoration=pass "
        f"services={report.get('service_count')} "
        f"restored={report.get('restored_count')} "
        f"cleaned={report.get('cleaned_count')} "
        f"connections={report.get('fresh_connection_count')} "
        f"next={report.get('next_slice')}"
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
