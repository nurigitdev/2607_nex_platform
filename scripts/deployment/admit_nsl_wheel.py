#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from importlib.metadata import version as installed_version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_locks import (
    PYTHON_LOCK_PATH,
    build_deployment_build_inputs,
    python_lock_package_versions,
)
from nex_runtime.nsl_package_admission import (
    build_nsl_wheel_admission,
    inspect_nsl_wheel,
    nsl_wheel_lock_projection,
    validate_nsl_wheel_lock,
)

EXECUTION_ENV = "NEX_NSL_WHEEL_ADMISSION"
DEFAULT_SOURCE = Path("/home/tprover/2608_nsl")
DEFAULT_OUTPUT = ROOT / "reports" / "deployment" / "p6-ca02-nsl-wheel"
DEFAULT_REPORT = ROOT / "reports" / "deployment" / "p6-ca02-nsl-wheel.json"
DEFAULT_LOCK = ROOT / "deployment" / "locks" / "nsl-v0.1-wheel.json"
REPOSITORY = "nurigitdev/2608_nsl"
PUBLIC_API_SYMBOLS = (
    "RuntimeEngine",
    "RuntimeResultEnvelope",
    "SkillExecutionJob",
    "SkillExecutionWorker",
)


class NslWheelBuildError(RuntimeError):
    pass


def run_nsl_wheel_admission(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    report: Path = DEFAULT_REPORT,
    lock: Path = DEFAULT_LOCK,
    write_lock: bool = False,
    uv_bin: str = "uv",
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {
            "schema_version": "p6_ca02_nsl_wheel_evidence.v1",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {EXECUTION_ENV}=1 are required",
        }
    try:
        evidence = _execute(
            source=source,
            output=output,
            lock=lock,
            write_lock=write_lock,
            uv_bin=uv_bin,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence = {
            "schema_version": "p6_ca02_nsl_wheel_evidence.v1",
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {"in_process_profile_admissible": False},
        }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _execute(
    *,
    source: Path,
    output: Path,
    lock: Path,
    write_lock: bool,
    uv_bin: str,
) -> dict[str, Any]:
    source_revision, source_tree_clean, source_epoch = _git_metadata(source)
    if not source_tree_clean:
        raise NslWheelBuildError("NSL wheel build requires a clean source tree")
    output.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="nsl-wheel-admission-") as temporary:
        temporary_root = Path(temporary)
        first_source = temporary_root / "first-source"
        second_source = temporary_root / "second-source"
        _materialize_git_archive(source, first_source)
        _materialize_git_archive(source, second_source)
        first = _build_wheel(
            first_source, temporary_root / "first", uv_bin, source_epoch
        )
        second = _build_wheel(
            second_source, temporary_root / "second", uv_bin, source_epoch
        )
        first_inspection = inspect_nsl_wheel(first)
        second_inspection = inspect_nsl_wheel(second)
        if (
            first.name != second.name
            or first_inspection.wheel_sha256 != second_inspection.wheel_sha256
        ):
            raise NslWheelBuildError("NSL wheel build is not reproducible")
        installed_symbols = _install_and_import(first, temporary_root / "installed")
        destination = output / first.name
        shutil.copyfile(first, destination)

    platform_requirement = _requirement_from_file(
        ROOT / "requirements.txt", "cryptography"
    )
    build_inputs = build_deployment_build_inputs(ROOT)
    python_lock = next(
        item for item in build_inputs.locks if item.lock_id == "python-production"
    )
    locked_versions = python_lock_package_versions(ROOT / PYTHON_LOCK_PATH)
    locked_cryptography = locked_versions.get("cryptography")
    if locked_cryptography is None:
        raise NslWheelBuildError("Platform lock does not contain cryptography")
    runtime_cryptography = installed_version("cryptography")
    if runtime_cryptography != locked_cryptography:
        raise NslWheelBuildError(
            "runtime cryptography version does not match Platform lock"
        )

    admission = build_nsl_wheel_admission(
        inspect_nsl_wheel(destination),
        source_revision=source_revision,
        source_tree_clean=True,
        expected_version="0.1.0",
        platform_cryptography_requirement=platform_requirement,
        locked_cryptography_version=locked_cryptography,
        platform_lock_sha256=f"sha256:{python_lock.sha256}",
        public_api_symbols=installed_symbols,
    )
    wheel_lock = nsl_wheel_lock_projection(admission, repository=REPOSITORY)
    if write_lock:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(
            json.dumps(wheel_lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        if not lock.is_file():
            raise NslWheelBuildError("NSL wheel lock is missing")
        validate_nsl_wheel_lock(
            admission,
            json.loads(lock.read_text(encoding="utf-8")),
            repository=REPOSITORY,
        )
    return {
        "schema_version": "p6_ca02_nsl_wheel_evidence.v1",
        "status": "PASS",
        "slice": "P6-CA02-S1",
        "admission": admission,
        "wheel_lock": str(lock.relative_to(ROOT)),
        "reproducible_build_count": 2,
        "decision": {
            "dependency_compatible": True,
            "wheel_admitted": True,
            "in_process_profile_admissible": True,
            "runtime_profile_activated": False,
        },
    }


def _git_metadata(source: Path) -> tuple[str, bool, str]:
    revision = _capture(
        ("git", "rev-parse", "HEAD"), cwd=source, operation="read NSL revision"
    ).strip()
    status = _capture(
        ("git", "status", "--porcelain"), cwd=source, operation="read NSL status"
    )
    epoch = _capture(
        ("git", "show", "-s", "--format=%ct", "HEAD"),
        cwd=source,
        operation="read NSL commit timestamp",
    ).strip()
    return revision, not bool(status.strip()), epoch


def _build_wheel(source: Path, output: Path, uv_bin: str, epoch: str) -> Path:
    output.mkdir(parents=True)
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = epoch
    environment.setdefault("UV_CACHE_DIR", "/tmp/nex-platform-uv-cache")
    process = subprocess.run(
        (uv_bin, "build", "--wheel", "--out-dir", str(output), str(source)),
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise NslWheelBuildError(
            f"NSL wheel build failed: {(process.stderr or process.stdout).strip()}"
        )
    wheels = tuple(output.glob("*.whl"))
    if len(wheels) != 1:
        raise NslWheelBuildError("NSL build did not produce exactly one wheel")
    return wheels[0]


def _materialize_git_archive(source: Path, destination: Path) -> None:
    process = subprocess.run(
        ("git", "archive", "--format=tar", "HEAD"),
        cwd=source,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        raise NslWheelBuildError(
            f"NSL source archive failed: {process.stderr.decode(errors='replace').strip()}"
        )
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(process.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")


def _install_and_import(wheel: Path, target: Path) -> tuple[str, ...]:
    process = subprocess.run(
        (
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise NslWheelBuildError(
            f"NSL wheel installation failed: {(process.stderr or process.stdout).strip()}"
        )
    script = (
        "import json, pathlib, sys; "
        f"sys.path.insert(0, {str(target)!r}); "
        "import nsl.api as api; "
        f"names={PUBLIC_API_SYMBOLS!r}; "
        "assert pathlib.Path(api.__file__).resolve().is_relative_to("
        f"pathlib.Path({str(target)!r}).resolve()); "
        "assert all(hasattr(api, name) for name in names); "
        "print(json.dumps(list(names)))"
    )
    imported = subprocess.run(
        (sys.executable, "-c", script),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if imported.returncode != 0:
        raise NslWheelBuildError(
            f"NSL public API import failed: {(imported.stderr or imported.stdout).strip()}"
        )
    return tuple(json.loads(imported.stdout))


def _requirement_from_file(path: Path, package: str) -> str:
    matches = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith(("#", "-")):
            try:
                requirement = Requirement(line)
            except InvalidRequirement as exc:
                raise NslWheelBuildError(
                    "Platform requirements contain an invalid entry"
                ) from exc
            if canonicalize_name(requirement.name) == canonicalize_name(package):
                matches.append(line)
    if len(matches) != 1:
        raise NslWheelBuildError(f"expected one {package} requirement")
    return matches[0]


def _capture(command: Sequence[str], *, cwd: Path, operation: str) -> str:
    process = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True
    )
    if process.returncode != 0:
        raise NslWheelBuildError(
            f"{operation} failed: {(process.stderr or process.stdout).strip()}"
        )
    return process.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and admit the NSL wheel")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--write-lock", action="store_true")
    parser.add_argument("--uv-bin", default="uv")
    args = parser.parse_args()
    result = run_nsl_wheel_admission(
        execute=args.execute,
        source=args.source,
        output=args.output,
        report=args.report,
        lock=args.lock,
        write_lock=args.write_lock,
        uv_bin=args.uv_bin,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
