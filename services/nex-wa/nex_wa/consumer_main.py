from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable, TextIO

from .installed_consumer import (
    WaInstalledConsumerProcess,
    build_installed_consumer_process,
)

from .persistence import (
    WaPersistenceError,
    WaPersistenceRuntime,
    build_wa_persistence_runtime,
)


def check_consumer_readiness(
    environ: Mapping[str, str],
    *,
    persistence_builder=build_wa_persistence_runtime,
) -> dict[str, Any]:
    persistence: WaPersistenceRuntime | None = None
    try:
        persistence = persistence_builder(environ=environ)
        checks = (
            persistence.migration_readiness(),
            persistence.consumer_storage_readiness(),
        )
        ready = all(check.get("ok") is True for check in checks)
        return {
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "readiness_status": "READY" if ready else "NOT_READY",
            "checks": list(checks),
        }
    except (WaPersistenceError, ValueError):
        return {
            "service_id": "nex-wa",
            "process_id": "nex-wa-evidence-consumer",
            "readiness_status": "NOT_READY",
            "checks": [
                {
                    "name": "wa_consumer_bootstrap",
                    "ok": False,
                    "error_code": "WA_CONSUMER_READINESS_FAILED",
                }
            ],
        }
    finally:
        if persistence is not None:
            persistence.dispose()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    persistence_builder=build_wa_persistence_runtime,
    process_builder=build_installed_consumer_process,
) -> int:
    parser = argparse.ArgumentParser(prog="nex-wa-evidence-consumer")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=float, default=0.25)
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    if args.check:
        result = check_consumer_readiness(
            env,
            persistence_builder=persistence_builder,
        )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if result["readiness_status"] == "READY" else 1
    if args.poll_interval_seconds <= 0:
        parser.error("poll interval must be positive")
    if args.max_cycles is not None and args.max_cycles < 1:
        parser.error("max cycles must be positive")
    try:
        process = process_builder(environ=env)
        return run_installed_consumer(
            process,
            poll_interval_seconds=args.poll_interval_seconds,
            max_cycles=args.max_cycles,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "service_id": "nex-wa",
                    "process_id": "nex-wa-evidence-consumer",
                    "status": "BLOCKED",
                    "error_code": "WA_INSTALLED_CONSUMER_STARTUP_FAILED",
                },
                sort_keys=True,
            )
        )
        return 2


@dataclass
class _ShutdownToken:
    requested: bool = False

    def request(self, signum: int, frame: object) -> None:
        del signum, frame
        self.requested = True


def run_installed_consumer(
    process: WaInstalledConsumerProcess,
    *,
    poll_interval_seconds: float = 0.25,
    max_cycles: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
) -> int:
    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    if max_cycles is not None and max_cycles < 1:
        raise ValueError("max cycles must be positive")
    stream = out or sys.stdout
    token = _ShutdownToken()
    previous: dict[signal.Signals, Any] = {}
    if should_stop is None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, token.request)
        stop = lambda: token.requested
    else:
        stop = should_stop
    metadata = process.metadata()
    print(json.dumps({**metadata, "state": "STARTED"}, sort_keys=True), file=stream)
    cycles = 0
    try:
        startup = process.startup()
        print(
            json.dumps({**metadata, **startup, "state": "RECOVERED"}, sort_keys=True),
            file=stream,
        )
        while not stop() and (max_cycles is None or cycles < max_cycles):
            result = process.run_once()
            cycles += 1
            if result["status"] != "IDLE":
                print(
                    json.dumps(
                        {**metadata, "state": "WORK", "execution": result},
                        sort_keys=True,
                    ),
                    file=stream,
                )
            if not stop() and (max_cycles is None or cycles < max_cycles):
                sleeper(poll_interval_seconds)
    finally:
        try:
            process.close()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    print(
        json.dumps(
            {**metadata, "state": "STOPPED", "completed_cycles": cycles},
            sort_keys=True,
        ),
        file=stream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
