#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.postgres_restart_coordinator import (  # noqa: E402
    PlatformPostgresRestartCoordinator,
    PostgresRestartCoordinatorError,
)


class _Pool:
    def __init__(self, generation: int, log: list[str]) -> None:
        self._generation = generation
        self._log = log

    def engine_identity_tokens(self) -> frozenset[int]:
        start = self._generation * 10
        return frozenset(range(start, start + 10))

    def dispose(self) -> dict[str, str]:
        self._log.append(f"pool-{self._generation}-disposed")
        return {"state": "DISPOSED"}


class _Runtime:
    def __init__(self, generation: int, log: list[str]) -> None:
        self._generation = generation
        self._log = log

    def start(self) -> dict[str, str]:
        self._log.append(f"runtime-{self._generation}-started")
        return {"state": "RUNNING"}

    def stop(self) -> dict[str, str]:
        self._log.append(f"runtime-{self._generation}-stopped")
        return {"state": "STOPPED"}

    def check_running(self) -> dict[str, str]:
        self._log.append(f"runtime-{self._generation}-checked")
        return {"state": "RUNNING"}


def run_smoke() -> dict[str, Any]:
    log: list[str] = []
    migration_count = 0
    generation = 0

    def migration_gate() -> None:
        nonlocal migration_count
        migration_count += 1

    def pool_factory() -> _Pool:
        nonlocal generation
        generation += 1
        return _Pool(generation, log)

    def runtime_factory() -> _Runtime:
        return _Runtime(generation, log)

    runner = PlatformPostgresRestartCoordinator(
        migration_gate=migration_gate,
        pool_factory=pool_factory,
        runtime_factory=runtime_factory,
    )
    try:
        runner.start()
        runner.check_running()
        restarted = runner.restart()
        runner.check_running()
        stopped = runner.stop()
    except PostgresRestartCoordinatorError as exc:
        return {
            "schema_version": "platform_postgres_restart_state_machine_smoke.v1",
            "status": "FAIL",
            "failure_code": exc.failure_code,
        }

    passed = (
        restarted["generation"] == 2
        and restarted["fresh_engine_count"] == 10
        and stopped["state"] == "STOPPED"
        and stopped["restart_count"] == 1
        and migration_count == 2
        and log.index("runtime-1-stopped") < log.index("pool-1-disposed")
        and log.index("runtime-2-stopped") < log.index("pool-2-disposed")
    )
    return {
        "schema_version": "platform_postgres_restart_state_machine_smoke.v1",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "state_machine_incomplete",
        "generation_count": stopped["generation"],
        "restart_count": stopped["restart_count"],
        "migration_gate_count": migration_count,
        "fresh_engine_count": restarted["fresh_engine_count"],
        "shutdown_order": stopped["last_shutdown_order"],
        "slice": "1328",
        "requirement": "S133",
        "next_slice": "1329",
    }


def summary_line(report: Mapping[str, Any]) -> str:
    if report.get("status") != "PASS":
        return (
            "platform_postgres_restart_state_machine=fail "
            f"code={report.get('failure_code') or 'failed'}"
        )
    return (
        "platform_postgres_restart_state_machine=pass "
        f"generations={report.get('generation_count')} "
        f"restarts={report.get('restart_count')} "
        f"fresh={report.get('fresh_engine_count')} "
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
