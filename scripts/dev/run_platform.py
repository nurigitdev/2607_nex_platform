#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path
import signal
import sys
import time
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.process_manifest import (  # noqa: E402
    build_platform_runtime_manifest,
    validate_runtime_command_targets,
)
from nex_runtime.runtime_orchestrator import (  # noqa: E402
    RuntimeOrchestrationError,
    RuntimeOrchestrator,
    SubprocessRuntimeLauncher,
)
from nex_runtime.topology import RUNTIME_PROFILES, runtime_manifest_public_projection  # noqa: E402


def build_platform_orchestrator(
    profile: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path = ROOT,
    launcher: Any | None = None,
) -> RuntimeOrchestrator:
    manifest = build_platform_runtime_manifest(
        profile,
        environ=environ,
        python_executable=sys.executable,
    )
    validate_runtime_command_targets(manifest, root)
    return RuntimeOrchestrator(
        manifest,
        launcher=launcher or SubprocessRuntimeLauncher(root),
        environ=environ,
    )


def run_platform_session(
    orchestrator: RuntimeOrchestrator,
    *,
    run_seconds: float | None,
    out: TextIO,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    if run_seconds is not None and run_seconds < 0:
        raise ValueError("run_seconds must be non-negative")
    exit_code = 0
    try:
        _write_status(out, orchestrator.start())
        deadline = None if run_seconds is None else clock() + run_seconds
        while deadline is None or clock() < deadline:
            remaining = 0.25 if deadline is None else min(0.25, deadline - clock())
            sleeper(max(0.0, remaining))
            orchestrator.check_running()
    except KeyboardInterrupt:
        exit_code = 130
    except RuntimeOrchestrationError as exc:
        _write_status(out, exc.status)
        exit_code = 1
    finally:
        _write_status(out, orchestrator.stop())
    return exit_code


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the NeX platform topology.")
    parser.add_argument("--profile", choices=RUNTIME_PROFILES, default="local_mock")
    parser.add_argument("--run-seconds", type=float)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    try:
        orchestrator = build_platform_orchestrator(args.profile)
        if args.check_config:
            print(
                json.dumps(
                    runtime_manifest_public_projection(orchestrator.manifest),
                    sort_keys=True,
                ),
                file=stream,
            )
            return 0
        return run_platform_session(
            orchestrator,
            run_seconds=args.run_seconds,
            out=stream,
        )
    except (RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "platform_runtime_command_error.v1",
                    "state": "BLOCKED",
                    "failure_code": exc.__class__.__name__,
                },
                sort_keys=True,
            ),
            file=stream,
        )
        return 2


def _write_status(out: TextIO, status: Mapping[str, Any]) -> None:
    print(json.dumps(dict(status), sort_keys=True), file=out)


def _handle_stop_signal(signum: int, frame: object) -> None:
    del signum, frame
    raise KeyboardInterrupt


if __name__ == "__main__":  # pragma: no cover
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)
    raise SystemExit(main())
