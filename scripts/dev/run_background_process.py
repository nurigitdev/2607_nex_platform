#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import signal
import sys
import time
from typing import Callable, Sequence, TextIO


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
BACKGROUND_MODULES = {
    "nex-ae-artifact-render-worker": (
        "nex-ae-api",
        "nex_ae_api.async_artifact_render_worker",
    ),
    "nex-ae-retention-daemon": (
        "nex-ae-api",
        "nex_ae_api.artifact_retention_scheduler_daemon",
    ),
    "nex-ag-remediation-sync-worker": (
        "nex-ag",
        "nex_ag.remediation_execution_status_sync_worker",
    ),
    "nex-ag-dispatch-daemon": (
        "nex-ag",
        "nex_ag.operator_review_dispatch_daemon",
    ),
    "nex-cx-async-generation-worker": (
        "nex-cx",
        "nex_cx.async_generation_worker",
    ),
    "nex-cx-ingestion-worker": ("nex-cx", "nex_cx.ingestion_worker"),
    "nex-cx-remediation-worker": (
        "nex-cx",
        "nex_cx.remediation_execution_worker",
    ),
}
_STOP_REQUESTED = False


def background_process_metadata(process_id: str, profile: str) -> dict[str, object]:
    if process_id not in BACKGROUND_MODULES:
        raise ValueError(f"unsupported background process: {process_id}")
    if profile != "local_mock":
        raise ValueError(
            "protected background process execution requires S133 persistence wiring"
        )
    service_id, module_name = BACKGROUND_MODULES[process_id]
    _configure_import_path(service_id)
    importlib.import_module(module_name)
    return {
        "schema_version": "platform_background_process_shell.v1",
        "process_id": process_id,
        "service_id": service_id,
        "module": module_name,
        "profile": profile,
        "work_claiming_enabled": False,
        "lifecycle_ready": True,
    }


def run_background_process_shell(
    process_id: str,
    profile: str,
    *,
    poll_interval_seconds: float = 0.25,
    should_stop: Callable[[], bool] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: TextIO | None = None,
) -> int:
    stream = out or sys.stdout
    metadata = background_process_metadata(process_id, profile)
    print(json.dumps({**metadata, "state": "STARTED"}, sort_keys=True), file=stream)
    stop = should_stop or (lambda: _STOP_REQUESTED)
    while not stop():
        sleeper(poll_interval_seconds)
    print(
        json.dumps({**metadata, "state": "STOPPED"}, sort_keys=True),
        file=stream,
    )
    return 0


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("process_id", choices=sorted(BACKGROUND_MODULES))
    parser.add_argument("--profile", default="local_mock")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    try:
        metadata = background_process_metadata(args.process_id, args.profile)
        if args.check:
            print(json.dumps(metadata, sort_keys=True), file=out or sys.stdout)
            return 0
        if args.poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        return run_background_process_shell(
            args.process_id,
            args.profile,
            poll_interval_seconds=args.poll_interval_seconds,
            out=out,
        )
    except ValueError as exc:
        print(json.dumps({"status": "BLOCKED", "detail": str(exc)}), file=out or sys.stdout)
        return 2


def _configure_import_path(service_id: str) -> None:
    for path in (SHARED_PATH, ROOT / "services" / service_id):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _handle_stop_signal(signum: int, frame: object) -> None:
    del signum, frame
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


if __name__ == "__main__":  # pragma: no cover
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)
    raise SystemExit(main())
