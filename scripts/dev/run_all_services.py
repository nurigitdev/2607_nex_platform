#!/usr/bin/env python3
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ["nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo"]


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)
    processes: list[subprocess.Popen[str]] = []
    try:
        for service_id in SERVICES:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "dev" / "run_service.py"),
                    service_id,
                ],
                cwd=ROOT,
                text=True,
            )
            processes.append(process)
            print(f"started {service_id} pid={process.pid}")

        print("all backend service shells started; press Ctrl-C to stop")
        return _wait_for_processes(processes)
    except KeyboardInterrupt:
        return 130
    finally:
        _terminate_processes(processes)


def _handle_stop_signal(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def _wait_for_processes(processes: list[subprocess.Popen[str]]) -> int:
    while True:
        for process in processes:
            code = process.poll()
            if code is not None:
                print(f"process pid={process.pid} exited with {code}")
                return code
        time.sleep(0.5)


def _terminate_processes(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
