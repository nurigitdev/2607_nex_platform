#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
FULL_GATE_PATH = "scripts/quality/run_quality_gate.sh"
DEFAULT_STATEMENT_MIN = 95.0
DEFAULT_BRANCH_MIN = 94.0
SAFE_COVERAGE_TARGET = re.compile(r"^[A-Za-z0-9_./-]+$")
ALLOWED_COVERAGE_PREFIXES = ("services/", "providers/", "scripts/")


@dataclass(frozen=True)
class ServiceProfile:
    test_patterns: tuple[str, ...]
    coverage_targets: tuple[str, ...]


SERVICE_PROFILES = {
    "nex-oa": ServiceProfile(
        test_patterns=("test_nex_oa_*.py", "test_oa_*.py"),
        coverage_targets=("services/nex-oa/nex_oa",),
    ),
    "nex-ag": ServiceProfile(
        test_patterns=("test_nex_ag_*.py", "test_ag_*.py"),
        coverage_targets=("services/nex-ag/nex_ag",),
    ),
    "nex-ae-api": ServiceProfile(
        test_patterns=("test_nex_ae_*.py", "test_ae_*.py"),
        coverage_targets=("services/nex-ae-api/nex_ae_api",),
    ),
    "nex-cx": ServiceProfile(
        test_patterns=("test_nex_cx_*.py", "test_cx_*.py"),
        coverage_targets=("services/nex-cx/nex_cx",),
    ),
    "nex-mo": ServiceProfile(
        test_patterns=("test_nex_mo_*.py", "test_*provider*.py"),
        coverage_targets=("services/nex-mo/nex_mo",),
    ),
    "nex-runtime": ServiceProfile(
        test_patterns=(
            "test_nex_runtime_*.py",
            "test_database_*.py",
            "test_db_*.py",
            "test_postgres_*.py",
        ),
        coverage_targets=("services/_shared/nex_runtime",),
    ),
    "nex-compatible-provider": ServiceProfile(
        test_patterns=(
            "test_compatible_provider_*.py",
            "test_nex_compatible_provider_*.py",
        ),
        coverage_targets=(
            "providers/nex-compatible-provider/nex_compatible_provider",
        ),
    ),
}


@dataclass(frozen=True)
class GatePlan:
    tier: str
    service: str | None
    test_count: int | None
    report_path: str
    full_gate_fallback: str
    commands: tuple[tuple[str, ...], ...]


def build_slice_plan(
    *,
    root: Path,
    python_bin: str,
    service: str,
    focused_tests: Sequence[str] = (),
    coverage_targets: Sequence[str] = (),
    smoke_scripts: Sequence[str] = (),
    statement_min: float = DEFAULT_STATEMENT_MIN,
    branch_min: float = DEFAULT_BRANCH_MIN,
    report_path: str | None = None,
) -> GatePlan:
    profile = SERVICE_PROFILES.get(service)
    if profile is None:
        raise ValueError(f"unsupported service profile: {service}")

    service_tests = _expand_test_patterns(root, profile.test_patterns)
    explicit_tests = [
        _validated_file(root, path, prefix="tests", suffix=".py")
        for path in focused_tests
    ]
    tests = _deduplicated((*service_tests, *explicit_tests))
    targets = _deduplicated(
        (
            *profile.coverage_targets,
            *(_validated_coverage_target(root, item) for item in coverage_targets),
        )
    )
    smokes = [
        _validated_file(root, path, prefix="scripts/smoke", suffix=".py")
        for path in smoke_scripts
    ]
    report = report_path or f"reports/quality/slice-{service}.coverage.json"
    _validate_report_path(report)

    pytest_command = [python_bin, "-m", "pytest", "-q"]
    pytest_command.extend(tests)
    pytest_command.extend(
        f"--cov={_coverage_source_argument(target)}" for target in targets
    )
    pytest_command.extend(
        (
            "--cov-branch",
            "--cov-report=term-missing",
            f"--cov-report=json:{report}",
        )
    )
    commands: list[tuple[str, ...]] = [tuple(pytest_command)]
    commands.extend(
        _common_post_pytest_commands(
            python_bin=python_bin,
            report=report,
            statement_min=statement_min,
            branch_min=branch_min,
            scopes=tuple(coverage_targets),
        )
    )
    commands.extend((python_bin, smoke, "--summary") for smoke in smokes)
    return GatePlan(
        tier="slice",
        service=service,
        test_count=len(tests),
        report_path=report,
        full_gate_fallback=FULL_GATE_PATH,
        commands=tuple(commands),
    )


def build_checkpoint_plan(
    *,
    root: Path,
    python_bin: str,
    focused_tests: Sequence[str] = (),
    coverage_targets: Sequence[str] = (),
    smoke_scripts: Sequence[str] = (),
    statement_min: float = DEFAULT_STATEMENT_MIN,
    branch_min: float = DEFAULT_BRANCH_MIN,
    report_path: str = "reports/quality/checkpoint.coverage.json",
) -> GatePlan:
    explicit_tests = [
        _validated_file(root, path, prefix="tests", suffix=".py")
        for path in focused_tests
    ]
    closure_tests = [
        path
        for path in explicit_tests
        if Path(path).name.startswith("test_s")
        and Path(path).name.endswith("_closure.py")
    ]
    if closure_tests:
        raise ValueError("closure tests belong to the full gate")
    targets = _deduplicated(
        (
            "services",
            "providers",
            *(_validated_coverage_target(root, item) for item in coverage_targets),
        )
    )
    smokes = [
        _validated_file(root, path, prefix="scripts/smoke", suffix=".py")
        for path in smoke_scripts
    ]
    _validate_report_path(report_path)

    pytest_command = [
        python_bin,
        "-m",
        "pytest",
        "-q",
        "tests",
        "--ignore-glob=tests/test_s*_closure.py",
    ]
    pytest_command.extend(
        f"--cov={_coverage_source_argument(target)}" for target in targets
    )
    pytest_command.extend(
        (
            "--cov-branch",
            "--cov-report=term-missing",
            f"--cov-report=json:{report_path}",
        )
    )
    commands: list[tuple[str, ...]] = [tuple(pytest_command)]
    commands.extend(
        _common_post_pytest_commands(
            python_bin=python_bin,
            report=report_path,
            statement_min=statement_min,
            branch_min=branch_min,
            scopes=tuple(coverage_targets),
        )
    )
    commands.extend((python_bin, smoke, "--summary") for smoke in smokes)
    return GatePlan(
        tier="checkpoint",
        service=None,
        test_count=None,
        report_path=report_path,
        full_gate_fallback=FULL_GATE_PATH,
        commands=tuple(commands),
    )


def execute_plan(
    plan: GatePlan,
    *,
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
    runner: Callable[[Sequence[str], Path, Mapping[str, str]], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    command_runner = runner or _run_command
    env = dict(os.environ if environ is None else environ)
    started = clock()
    completed_commands = 0
    failed_command: int | None = None
    exit_code = 0

    for index, command in enumerate(plan.commands, start=1):
        exit_code = command_runner(command, root, env)
        if exit_code != 0:
            failed_command = index
            break
        completed_commands = index

    duration = max(0.0, clock() - started)
    evidence: dict[str, object] = {
        "gate_schema_version": "nex_tiered_quality_gate.v1",
        "status": "PASS" if exit_code == 0 else "FAIL",
        "tier": plan.tier,
        "service": plan.service,
        "test_count": plan.test_count,
        "command_count": len(plan.commands),
        "completed_command_count": completed_commands,
        "failed_command": failed_command,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 3),
        "coverage_report": plan.report_path,
        "full_gate_fallback": plan.full_gate_fallback,
    }
    _write_evidence(root, plan.tier, evidence)
    return evidence


def _common_post_pytest_commands(
    *,
    python_bin: str,
    report: str,
    statement_min: float,
    branch_min: float,
    scopes: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = [
        (
            python_bin,
            "scripts/quality/check_coverage_thresholds.py",
            report,
            _format_threshold(statement_min),
            _format_threshold(branch_min),
        ),
    ]
    if scopes:
        commands.append(
            (
                python_bin,
                "scripts/quality/check_coverage_scopes.py",
                report,
                _format_threshold(statement_min),
                _format_threshold(branch_min),
                *scopes,
            )
        )
    commands.append((python_bin, "scripts/quality/validate_contracts.py"))
    return tuple(commands)


def _expand_test_patterns(root: Path, patterns: Sequence[str]) -> list[str]:
    tests = sorted(
        {
            path.relative_to(root).as_posix()
            for pattern in patterns
            for path in (root / "tests").glob(pattern)
            if path.is_file()
        }
    )
    if not tests:
        raise ValueError("service profile selected no regression tests")
    return tests


def _validated_file(root: Path, raw: str, *, prefix: str, suffix: str) -> str:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must be repository-relative: {raw}")
    normalized = path.as_posix()
    if not normalized.startswith(f"{prefix}/") or not normalized.endswith(suffix):
        raise ValueError(f"path is outside the allowed {prefix} boundary: {raw}")
    if not (root / path).is_file():
        raise ValueError(f"required file does not exist: {raw}")
    return normalized


def _validated_coverage_target(root: Path, raw: str) -> str:
    if (
        not raw
        or raw.startswith("-")
        or ".." in Path(raw).parts
        or SAFE_COVERAGE_TARGET.fullmatch(raw) is None
    ):
        raise ValueError(f"invalid coverage target: {raw}")
    if not raw.startswith(ALLOWED_COVERAGE_PREFIXES):
        raise ValueError(
            "coverage target must be a services/, providers/, or scripts/ path"
        )
    if not (root / raw).exists():
        raise ValueError(f"coverage path does not exist: {raw}")
    return raw


def _coverage_source_argument(target: str) -> str:
    path = Path(target)
    if path.suffix != ".py":
        return target
    parts = path.parts
    if parts[0] == "scripts" and len(parts) == 3:
        return path.stem
    if parts[0] in {"services", "providers"} and len(parts) >= 4:
        return ".".join((*parts[2:-1], path.stem))
    raise ValueError(f"Python coverage file is outside an import root: {target}")


def _validate_report_path(raw: str) -> None:
    path = Path(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not raw.startswith("reports/quality/")
        or not raw.endswith(".json")
    ):
        raise ValueError("coverage report must be a reports/quality/*.json path")


def _deduplicated(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _format_threshold(value: float) -> str:
    return f"{value:g}"


def _run_command(
    command: Sequence[str], root: Path, environ: Mapping[str, str]
) -> int:
    completed = subprocess.run(command, cwd=root, env=dict(environ), check=False)
    return int(completed.returncode)


def _write_evidence(
    root: Path, tier: str, evidence: Mapping[str, object]
) -> None:
    path = root / "reports" / "quality" / f"{tier}-latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plan_payload(plan: GatePlan) -> dict[str, object]:
    payload = asdict(plan)
    payload["commands"] = [list(command) for command in plan.commands]
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=("slice", "checkpoint"))
    parser.add_argument("--service", choices=tuple(SERVICE_PROFILES))
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--coverage-target", action="append", default=[])
    parser.add_argument("--smoke", action="append", default=[])
    parser.add_argument("--statement-min", type=float, default=DEFAULT_STATEMENT_MIN)
    parser.add_argument("--branch-min", type=float, default=DEFAULT_BRANCH_MIN)
    parser.add_argument("--report-path")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    python_bin = os.environ.get("PYTHON_BIN", "./.venv/bin/python")
    try:
        if args.tier == "slice":
            if not args.service:
                raise ValueError("slice tier requires --service")
            plan = build_slice_plan(
                root=ROOT,
                python_bin=python_bin,
                service=args.service,
                focused_tests=args.test,
                coverage_targets=args.coverage_target,
                smoke_scripts=args.smoke,
                statement_min=args.statement_min,
                branch_min=args.branch_min,
                report_path=args.report_path,
            )
        else:
            if args.service:
                raise ValueError("checkpoint tier does not accept --service")
            plan = build_checkpoint_plan(
                root=ROOT,
                python_bin=python_bin,
                focused_tests=args.test,
                coverage_targets=args.coverage_target,
                smoke_scripts=args.smoke,
                statement_min=args.statement_min,
                branch_min=args.branch_min,
                report_path=(
                    args.report_path
                    or "reports/quality/checkpoint.coverage.json"
                ),
            )
    except ValueError as exc:
        print(f"tiered quality gate configuration error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(_plan_payload(plan), indent=2, sort_keys=True))
        return 0

    evidence = execute_plan(plan)
    print(
        "tiered_quality_gate="
        f"{str(evidence['status']).lower()} tier={evidence['tier']} "
        f"service={evidence['service'] or 'all'} "
        f"commands={evidence['completed_command_count']}/"
        f"{evidence['command_count']} duration={evidence['duration_seconds']}s "
        f"fallback={evidence['full_gate_fallback']}"
    )
    return int(evidence["exit_code"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
