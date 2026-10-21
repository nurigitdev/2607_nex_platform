#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_ENV = "NEX_NSL_V02_READINESS"
DEFAULT_LOCK = ROOT / "deployment" / "locks" / "nsl-v0.2-wheel.json"
DEFAULT_WHEEL_DIRECTORY = ROOT / "reports" / "deployment" / "p8-nsl-v0.2-wheel"
DEFAULT_REPORT = ROOT / "reports" / "deployment" / "p8-s04-nsl-v0.2-readiness.json"
PLATFORM_LOCK = ROOT / "deployment" / "locks" / "python-production.lock"
SHARED_SOURCE = ROOT / "services" / "_shared"


class NslV02ReadinessError(RuntimeError):
    pass


def run_nsl_v02_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    lock_path: Path = DEFAULT_LOCK,
    wheel_directory: Path = DEFAULT_WHEEL_DIRECTORY,
    report_path: Path = DEFAULT_REPORT,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {
            "schema_version": "p8_nsl_v02_installed_readiness_evidence.v1",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {EXECUTION_ENV}=1 are required",
        }
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if not isinstance(lock, Mapping):
            raise NslV02ReadinessError("NSL v0.2 wheel lock must be an object")
        wheel = wheel_directory / str(lock.get("wheel_filename", ""))
        if not wheel.is_file():
            raise NslV02ReadinessError("admitted NSL v0.2 wheel is missing")
        with TemporaryDirectory(prefix="nsl-v02-readiness-") as temporary:
            target = Path(temporary) / "site-packages"
            _run(
                (
                    python_bin,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-deps",
                    "--target",
                    str(target),
                    str(wheel),
                ),
                operation="install admitted NSL v0.2 wheel",
            )
            readiness = json.loads(
                _run(
                    (
                        python_bin,
                        "-c",
                        _child_script(
                            target=target,
                            lock_path=lock_path,
                            platform_lock_path=PLATFORM_LOCK,
                        ),
                    ),
                    operation="inspect isolated NSL v0.2 installation",
                )
            )
        if (
            not isinstance(readiness, Mapping)
            or readiness.get("status") != "PASS"
            or readiness.get("schema_version")
            != "nsl_installed_package_readiness.v2"
        ):
            raise NslV02ReadinessError("NSL v0.2 readiness result is invalid")
        evidence = {
            "schema_version": "p8_nsl_v02_installed_readiness_evidence.v1",
            "status": "PASS",
            "slice": "P8-S04",
            "host_package_version": _installed_version(),
            "isolated_install": True,
            "host_environment_mutated": False,
            "readiness": dict(readiness),
            "decision": {
                "exact_installed_wheel_ready": True,
                "v01_host_install_preserved": _installed_version() == "0.1.0",
                "runtime_profile_activated": False,
            },
        }
    except (
        json.JSONDecodeError,
        NslV02ReadinessError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        evidence = {
            "schema_version": "p8_nsl_v02_installed_readiness_evidence.v1",
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {"exact_installed_wheel_ready": False},
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _run(command: Sequence[str], *, operation: str) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise NslV02ReadinessError(
            f"{operation} failed: {(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout


def _child_script(
    *, target: Path, lock_path: Path, platform_lock_path: Path
) -> str:
    return (
        "import json,sys; "
        f"sys.path[:0]=[{str(target)!r},{str(SHARED_SOURCE)!r}]; "
        "from pathlib import Path; "
        "from nex_runtime.nsl_package_admission import inspect_installed_nsl_package; "
        f"lock=json.loads(Path({str(lock_path)!r}).read_text(encoding='utf-8')); "
        f"result=inspect_installed_nsl_package(lock,platform_lock_path=Path({str(platform_lock_path)!r})); "
        "print(json.dumps(result,sort_keys=True))"
    )


def _installed_version() -> str | None:
    try:
        return importlib.metadata.version("nex-skill-language")
    except importlib.metadata.PackageNotFoundError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check installed NSL v0.2 readiness")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--wheel-directory", type=Path, default=DEFAULT_WHEEL_DIRECTORY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_nsl_v02_readiness(
        execute=args.execute,
        lock_path=args.lock,
        wheel_directory=args.wheel_directory,
        report_path=args.report,
        python_bin=args.python_bin,
    )
    if args.summary:
        print(
            "p8_s04_nsl_v02_readiness="
            f"{str(result['status']).lower()} isolated={result.get('isolated_install', False)}"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
