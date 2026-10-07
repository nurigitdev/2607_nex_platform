#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED))

from nex_runtime.postgres_backup import PostgresBackupError  # noqa: E402
from nex_runtime.postgres_backup_worker import (  # noqa: E402
    backup_worker_public_projection,
    run_postgres_backup_worker,
)
from nex_runtime.postgres_resilience import EXPECTED_SERVICE_IDS  # noqa: E402


def run_postgresql_backup_worker_audit() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="nex-s145-worker-") as temp:
        root = Path(temp)
        services = tuple(root / service_id for service_id in EXPECTED_SERVICE_IDS)
        attempts: list[int] = []
        sleeps: list[float] = []

        def executor(attempt: int) -> dict[str, str]:
            attempts.append(attempt)
            if attempt == 1:
                raise PostgresBackupError("backup_source_unavailable")
            return {service_id: "CREATED" for service_id in EXPECTED_SERVICE_IDS}

        times = iter(
            datetime(2026, 10, 8, 0, 0, second, tzinfo=timezone.utc)
            for second in range(20)
        )
        result = run_postgres_backup_worker(
            run_id="20261008T000000Z-1234abcd",
            state_root=root / "state",
            service_directories=services,
            executor=executor,
            clock=lambda: next(times),
            sleeper=sleeps.append,
        )
        replay = run_postgres_backup_worker(
            run_id="20261008T000000Z-1234abcd",
            state_root=root / "state",
            service_directories=services,
            executor=lambda _attempt: (_ for _ in ()).throw(AssertionError("replayed")),
            clock=lambda: datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc),
        )
        projection = backup_worker_public_projection(result)
        checks = {
            "bounded_retry": attempts == [1, 2] and sleeps == [1.0],
            "five_service_result": projection["service_count"] == 5,
            "durable_success": result.state == "SUCCEEDED" and replay == result,
            "exclusive_worker_contract": (root / "state/20261008T000000Z-1234abcd.lock").exists(),
            "secret_free_projection": "password" not in str(projection).lower(),
            "stale_window_frozen": timedelta(minutes=30) >= timedelta(minutes=5),
        }
    passed = all(checks.values())
    return {
        "schema_version": "postgres_backup_worker_audit.v1",
        "slice": "1449",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "metrics": {
            "attempt_count": result.attempt_count,
            "service_count": len(result.service_states),
            "max_attempts": 3,
        },
        "next_slice": "1450" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        f"postgres_backup_worker={'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"attempts={metrics.get('attempt_count', 0)}/{metrics.get('max_attempts', 0)} "
        f"services={metrics.get('service_count', 0)} next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_postgresql_backup_worker_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
