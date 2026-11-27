#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[2]
SHARED_SERVICE_ROOT = ROOT / "services" / "_shared"
if str(SHARED_SERVICE_ROOT) not in sys.path:  # pragma: no cover - direct CLI path
    sys.path.insert(0, str(SHARED_SERVICE_ROOT))

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402
from run_tiered_quality_gate import SERVICE_PROFILES  # noqa: E402

INVENTORY_SCHEMA_VERSION = "nex.parallel_quality_test_inventory.v1"
ORCHESTRATOR_SCHEMA_VERSION = "nex.parallel_quality_owner_lanes.v1"
SERIAL_INTEGRATION_LANE = "serial-integration"
SERIAL_REPOSITORY_LANE = "serial-repository"
INITIAL_OWNER_LANES = ("nex-ae-api", "nex-eos", "nex-wc", "nex-oa")
CHECKPOINT_STATEMENT_MIN = "95"
CHECKPOINT_BRANCH_MIN = "94"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
LANE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class TestAssignment:
    path: str
    lane: str
    reason: str
    candidate_owners: tuple[str, ...]


@dataclass(frozen=True)
class LaneArtifactPaths:
    run_id: str
    lane: str
    base_dir: Path
    raw_coverage: Path
    coverage_json: Path
    junit_xml: Path
    stdout_log: Path
    stderr_log: Path
    evidence_json: Path

    def relative_payload(self, root: Path) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "lane": self.lane,
            "base_dir": self.base_dir.relative_to(root).as_posix(),
            "raw_coverage": self.raw_coverage.relative_to(root).as_posix(),
            "coverage_json": self.coverage_json.relative_to(root).as_posix(),
            "junit_xml": self.junit_xml.relative_to(root).as_posix(),
            "stdout_log": self.stdout_log.relative_to(root).as_posix(),
            "stderr_log": self.stderr_log.relative_to(root).as_posix(),
            "evidence_json": self.evidence_json.relative_to(root).as_posix(),
        }


@dataclass(frozen=True)
class LaneExecutionPlan:
    lane: str
    tests: tuple[str, ...]
    command: tuple[str, ...]
    artifacts: LaneArtifactPaths


def discover_test_files(root: Path, *, tier: str) -> tuple[str, ...]:
    if tier not in {"checkpoint", "full"}:
        raise ValueError("tier must be checkpoint or full")
    tests_root = root / "tests"
    files = []
    for path in tests_root.rglob("test_*.py"):
        relative = path.relative_to(root).as_posix()
        if tier == "checkpoint" and _is_checkpoint_closure(relative):
            continue
        files.append(relative)
    return tuple(sorted(files))


def build_test_ownership_inventory(
    *,
    root: Path,
    tier: str,
    revision: str,
    generated_at: str | None = None,
) -> dict[str, object]:
    test_files = discover_test_files(root, tier=tier)
    profile_files = _profile_test_files(root)
    assignments: list[TestAssignment] = []
    source_unowned = 0
    source_multi_owned = 0

    for path in test_files:
        candidates = tuple(
            service for service, files in profile_files.items() if path in files
        )
        if candidates == ("platform",):
            lane = SERIAL_INTEGRATION_LANE
            reason = "PLATFORM_CROSS_SERVICE"
        elif len(candidates) == 1:
            lane = candidates[0]
            reason = "OWNER_SERVICE_PROFILE"
        elif len(candidates) > 1:
            source_multi_owned += 1
            lane = SERIAL_INTEGRATION_LANE
            reason = "MULTI_OWNER_CROSS_SERVICE"
        else:
            source_unowned += 1
            lane = SERIAL_REPOSITORY_LANE
            reason = "REPOSITORY_UNOWNED"
        assignments.append(
            TestAssignment(
                path=path,
                lane=lane,
                reason=reason,
                candidate_owners=candidates,
            )
        )

    assigned_paths = [item.path for item in assignments]
    assignment_counts = Counter(assigned_paths)
    resolved_missing = sorted(set(test_files) - set(assigned_paths))
    resolved_duplicates = sorted(
        path for path, count in assignment_counts.items() if count != 1
    )
    lane_counts = Counter(item.lane for item in assignments)
    stable_payload = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "tier": tier,
        "revision": revision,
        "assignments": [asdict(item) for item in assignments],
    }
    evidence: dict[str, object] = {
        **stable_payload,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "test_file_count": len(test_files),
        "source_unowned_count": source_unowned,
        "source_multi_owned_count": source_multi_owned,
        "resolved_missing_count": len(resolved_missing),
        "resolved_duplicate_count": len(resolved_duplicates),
        "resolved_missing_paths": resolved_missing,
        "resolved_duplicate_paths": resolved_duplicates,
        "lane_counts": dict(sorted(lane_counts.items())),
        "inventory_digest": semantic_sha256_hash_ref(stable_payload),
    }
    if resolved_missing or resolved_duplicates:  # pragma: no cover - defensive invariant
        raise ValueError("test ownership inventory is not exact-once")
    return evidence


def write_inventory(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_lane_artifact_paths(
    *, root: Path, run_id: str, lane: str
) -> LaneArtifactPaths:
    _validate_run_id(run_id)
    _validate_lane(lane)
    base = root / "reports" / "quality" / "parallel" / run_id / lane
    return LaneArtifactPaths(
        run_id=run_id,
        lane=lane,
        base_dir=base,
        raw_coverage=base / ".coverage",
        coverage_json=base / "coverage.json",
        junit_xml=base / "junit.xml",
        stdout_log=base / "stdout.log",
        stderr_log=base / "stderr.log",
        evidence_json=base / "evidence.json",
    )


def prepare_lane_artifacts(paths: LaneArtifactPaths) -> None:
    paths.base_dir.parent.mkdir(parents=True, exist_ok=True)
    paths.base_dir.mkdir(exist_ok=False)


def lane_environment(
    paths: LaneArtifactPaths, environ: dict[str, str] | None = None
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.update(
        {
            "COVERAGE_FILE": str(paths.raw_coverage),
            "NEX_QUALITY_GATE_RUN_ID": paths.run_id,
            "NEX_QUALITY_GATE_LANE": paths.lane,
        }
    )
    return result


def validate_artifact_isolation(paths: Sequence[LaneArtifactPaths]) -> None:
    seen_lanes: set[tuple[str, str]] = set()
    seen_paths: set[Path] = set()
    for item in paths:
        lane_key = (item.run_id, item.lane)
        if lane_key in seen_lanes:
            raise ValueError(f"duplicate run/lane artifact assignment: {item.lane}")
        seen_lanes.add(lane_key)
        for path in (
            item.raw_coverage,
            item.coverage_json,
            item.junit_xml,
            item.stdout_log,
            item.stderr_log,
            item.evidence_json,
        ):
            resolved = path.resolve()
            if resolved in seen_paths:
                raise ValueError(f"artifact path collision: {path}")
            seen_paths.add(resolved)


def build_owner_lane_plan(
    *,
    root: Path,
    inventory: Mapping[str, object],
    run_id: str,
    lane: str,
    python_bin: str,
) -> LaneExecutionPlan:
    _validate_lane(lane)
    if lane in {SERIAL_INTEGRATION_LANE, SERIAL_REPOSITORY_LANE}:
        raise ValueError("owner lane plan cannot use a serial lane")
    return build_test_lane_plan(
        root=root,
        inventory=inventory,
        run_id=run_id,
        lane=lane,
        python_bin=python_bin,
    )


def build_test_lane_plan(
    *,
    root: Path,
    inventory: Mapping[str, object],
    run_id: str,
    lane: str,
    python_bin: str,
) -> LaneExecutionPlan:
    _validate_lane(lane)
    tests = tuple(
        str(item["path"])
        for item in inventory["assignments"]  # type: ignore[index,union-attr]
        if item["lane"] == lane  # type: ignore[index]
    )
    if not tests:
        raise ValueError(f"owner lane has no assigned tests: {lane}")
    artifacts = build_lane_artifact_paths(root=root, run_id=run_id, lane=lane)
    coverage_sources = (
        ("services", "providers")
        if inventory["tier"] == "checkpoint"
        else ("services", "scripts", "providers")
    )
    command = [python_bin, "-m", "pytest", "-q", *tests]
    command.extend(f"--cov={source}" for source in coverage_sources)
    command.extend(
        (
            "--cov-branch",
            "--cov-report=term-missing",
            f"--cov-report=json:{artifacts.coverage_json}",
            f"--junitxml={artifacts.junit_xml}",
        )
    )
    return LaneExecutionPlan(
        lane=lane,
        tests=tests,
        command=tuple(command),
        artifacts=artifacts,
    )


def execute_owner_service_lanes(
    *,
    root: Path,
    tier: str,
    run_id: str,
    lanes: Sequence[str] = INITIAL_OWNER_LANES,
    max_parallel: int = 4,
    python_bin: str = "./.venv/bin/python",
    revision: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    if not 1 <= max_parallel <= 8:
        raise ValueError("max_parallel must be between 1 and 8")
    ordered_lanes = _ordered_owner_lanes(lanes)
    inventory = build_test_ownership_inventory(
        root=root,
        tier=tier,
        revision=revision or _git_revision(root),
    )
    run_root = root / "reports" / "quality" / "parallel" / run_id
    write_inventory(run_root / "inventory.json", inventory)
    plans = [
        build_owner_lane_plan(
            root=root,
            inventory=inventory,
            run_id=run_id,
            lane=lane,
            python_bin=python_bin,
        )
        for lane in ordered_lanes
    ]
    validate_artifact_isolation([plan.artifacts for plan in plans])
    for plan in plans:
        prepare_lane_artifacts(plan.artifacts)

    started = clock()
    base_env = dict(os.environ if environ is None else environ)
    ae_started = threading.Event()
    results: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=min(max_parallel, len(plans))) as executor:
        futures: dict[Future[dict[str, object]], str] = {}
        first = plans[0]
        first_signal = ae_started if first.lane == "nex-ae-api" else None
        futures[
            executor.submit(
                _execute_lane_plan,
                first,
                root=root,
                environ=base_env,
                runner=runner,
                clock=clock,
                started_signal=first_signal,
            )
        ] = first.lane
        if first_signal is not None and not first_signal.wait(timeout=10):  # pragma: no cover - thread startup failure
            raise RuntimeError("AE owner lane did not start within 10 seconds")
        for plan in plans[1:]:
            futures[
                executor.submit(
                    _execute_lane_plan,
                    plan,
                    root=root,
                    environ=base_env,
                    runner=runner,
                    clock=clock,
                    started_signal=None,
                )
            ] = plan.lane
        for future in as_completed(futures):
            lane = futures[future]
            results[lane] = future.result()

    duration = max(0.0, clock() - started)
    ordered_results = [results[lane] for lane in ordered_lanes]
    evidence: dict[str, object] = {
        "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
        "status": (
            "PASS" if all(item["status"] == "PASS" for item in ordered_results) else "FAIL"
        ),
        "tier": tier,
        "run_id": run_id,
        "revision": inventory["revision"],
        "inventory_digest": inventory["inventory_digest"],
        "lane_start_order": list(ordered_lanes),
        "max_parallel": max_parallel,
        "duration_seconds": round(duration, 3),
        "lanes": ordered_results,
    }
    write_inventory(run_root / "owner-lanes.json", evidence)
    return evidence


def execute_parallel_checkpoint_gate(
    *,
    root: Path,
    run_id: str,
    max_parallel: int = 4,
    python_bin: str = "./.venv/bin/python",
    revision: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    gate_started = clock()
    revision_value = revision or _git_revision(root)
    inventory = build_test_ownership_inventory(
        root=root,
        tier="checkpoint",
        revision=revision_value,
    )
    lane_counts = inventory["lane_counts"]
    owner_lanes = tuple(
        lane
        for lane in SERVICE_PROFILES
        if lane != "platform" and lane_counts.get(lane, 0)  # type: ignore[union-attr]
    )
    owner_evidence = execute_owner_service_lanes(
        root=root,
        tier="checkpoint",
        run_id=run_id,
        lanes=owner_lanes,
        max_parallel=max_parallel,
        python_bin=python_bin,
        revision=revision_value,
        environ=environ,
        runner=runner,
        clock=clock,
    )
    run_root = root / "reports" / "quality" / "parallel" / run_id
    if owner_evidence["status"] != "PASS":
        return _write_checkpoint_result(
            root=root,
            run_root=run_root,
            run_id=run_id,
            revision=revision_value,
            inventory=inventory,
            owner_evidence=owner_evidence,
            serial_results=[],
            closure_results=[],
            combined_coverage=None,
            started=gate_started,
            clock=clock,
        )

    serial_results: list[dict[str, object]] = []
    serial_plans: list[LaneExecutionPlan] = []
    for lane in (SERIAL_INTEGRATION_LANE, SERIAL_REPOSITORY_LANE):
        if lane_counts.get(lane, 0):  # type: ignore[union-attr]
            plan = build_test_lane_plan(
                root=root,
                inventory=inventory,
                run_id=run_id,
                lane=lane,
                python_bin=python_bin,
            )
            prepare_lane_artifacts(plan.artifacts)
            serial_plans.append(plan)
            result = _execute_lane_plan(
                plan,
                root=root,
                environ=dict(os.environ if environ is None else environ),
                runner=runner,
                clock=clock,
                started_signal=None,
            )
            serial_results.append(result)
            if result["status"] != "PASS":
                return _write_checkpoint_result(
                    root=root,
                    run_root=run_root,
                    run_id=run_id,
                    revision=revision_value,
                    inventory=inventory,
                    owner_evidence=owner_evidence,
                    serial_results=serial_results,
                    closure_results=[],
                    combined_coverage=None,
                    started=gate_started,
                    clock=clock,
                )

    raw_coverage_paths = [
        root / str(item["artifacts"]["raw_coverage"])  # type: ignore[index]
        for item in owner_evidence["lanes"]  # type: ignore[union-attr]
    ] + [plan.artifacts.raw_coverage for plan in serial_plans]
    closure_dir = run_root / "closure"
    closure_dir.mkdir(exist_ok=False)
    combined_raw = closure_dir / ".coverage"
    combined_json = closure_dir / "coverage.json"
    closure_results = _execute_logged_commands(
        commands=_checkpoint_closure_commands(
            python_bin=python_bin,
            combined_raw=combined_raw,
            combined_json=combined_json,
            raw_coverage_paths=raw_coverage_paths,
        ),
        root=root,
        environ=dict(os.environ if environ is None else environ),
        stdout_path=closure_dir / "stdout.log",
        stderr_path=closure_dir / "stderr.log",
        runner=runner,
        clock=clock,
    )
    closure_passed = all(item["exit_code"] == 0 for item in closure_results)
    return _write_checkpoint_result(
        root=root,
        run_root=run_root,
        run_id=run_id,
        revision=revision_value,
        inventory=inventory,
        owner_evidence=owner_evidence,
        serial_results=serial_results,
        closure_results=closure_results,
        combined_coverage=(
            combined_json.relative_to(root).as_posix() if closure_passed else None
        ),
        started=gate_started,
        clock=clock,
    )


def _checkpoint_closure_commands(
    *,
    python_bin: str,
    combined_raw: Path,
    combined_json: Path,
    raw_coverage_paths: Sequence[Path],
) -> tuple[tuple[str, ...], ...]:
    return (
        (
            python_bin,
            "-m",
            "coverage",
            "combine",
            "--keep",
            f"--data-file={combined_raw}",
            *(str(path) for path in raw_coverage_paths),
        ),
        (
            python_bin,
            "-m",
            "coverage",
            "json",
            f"--data-file={combined_raw}",
            "-o",
            str(combined_json),
        ),
        (
            python_bin,
            "scripts/quality/check_coverage_thresholds.py",
            str(combined_json),
            CHECKPOINT_STATEMENT_MIN,
            CHECKPOINT_BRANCH_MIN,
        ),
        (python_bin, "scripts/quality/validate_contracts.py"),
        (
            python_bin,
            "scripts/quality/run_golden_journey_transition_audit.py",
            "--summary",
        ),
        (
            python_bin,
            "scripts/quality/run_demo_product_dependency_audit.py",
            "--summary",
        ),
    )


def _execute_logged_commands(
    *,
    commands: Sequence[Sequence[str]],
    root: Path,
    environ: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    clock: Callable[[], float],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with stdout_path.open("w", encoding="utf-8") as stdout_file:
        with stderr_path.open("w", encoding="utf-8") as stderr_file:
            for index, command in enumerate(commands, start=1):
                started = clock()
                completed = runner(
                    tuple(command),
                    cwd=root,
                    env=dict(environ),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    check=False,
                )
                results.append(
                    {
                        "index": index,
                        "label": _command_label(command),
                        "duration_seconds": round(max(0.0, clock() - started), 3),
                        "exit_code": int(completed.returncode),
                    }
                )
                if completed.returncode != 0:
                    break
    return results


def _write_checkpoint_result(
    *,
    root: Path,
    run_root: Path,
    run_id: str,
    revision: str,
    inventory: Mapping[str, object],
    owner_evidence: Mapping[str, object],
    serial_results: Sequence[Mapping[str, object]],
    closure_results: Sequence[Mapping[str, object]],
    combined_coverage: str | None,
    started: float,
    clock: Callable[[], float],
) -> dict[str, object]:
    passed = (
        owner_evidence["status"] == "PASS"
        and all(item["status"] == "PASS" for item in serial_results)
        and len(serial_results) == 2
        and len(closure_results) == 6
        and all(item["exit_code"] == 0 for item in closure_results)
        and combined_coverage is not None
    )
    evidence: dict[str, object] = {
        "schema_version": "nex.parallel_checkpoint_gate.v1",
        "status": "PASS" if passed else "FAIL",
        "tier": "checkpoint",
        "run_id": run_id,
        "revision": revision,
        "inventory_digest": inventory["inventory_digest"],
        "test_file_count": inventory["test_file_count"],
        "owner_lanes": owner_evidence,
        "serial_lanes": list(serial_results),
        "closure_commands": list(closure_results),
        "combined_coverage": combined_coverage,
        "duration_seconds": round(max(0.0, clock() - started), 3),
        "serial_fallback": "scripts/quality/run_checkpoint_gate.sh",
    }
    write_inventory(run_root / "checkpoint.json", evidence)
    write_inventory(
        root / "reports" / "quality" / "checkpoint-parallel-latest.json", evidence
    )
    return evidence


def _command_label(command: Sequence[str]) -> str:
    for item in command[1:]:
        if item in {"combine", "json"} or item.endswith((".py", ".sh")):
            return Path(item).name
    return Path(command[0]).name


def _execute_lane_plan(
    plan: LaneExecutionPlan,
    *,
    root: Path,
    environ: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
    clock: Callable[[], float],
    started_signal: threading.Event | None,
) -> dict[str, object]:
    env = lane_environment(plan.artifacts, dict(environ))
    started = clock()
    with plan.artifacts.stdout_log.open("w", encoding="utf-8") as stdout_file:
        with plan.artifacts.stderr_log.open("w", encoding="utf-8") as stderr_file:
            if started_signal is not None:
                started_signal.set()
            completed = runner(
                plan.command,
                cwd=root,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                check=False,
            )
    duration = max(0.0, clock() - started)
    evidence: dict[str, object] = {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "lane": plan.lane,
        "test_file_count": len(plan.tests),
        "exit_code": int(completed.returncode),
        "duration_seconds": round(duration, 3),
        "artifacts": plan.artifacts.relative_payload(root),
        "command_digest": semantic_sha256_hash_ref(list(plan.command)),
    }
    write_inventory(plan.artifacts.evidence_json, evidence)
    return evidence


def _ordered_owner_lanes(lanes: Sequence[str]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(lanes))
    if not unique:
        raise ValueError("at least one owner lane is required")
    for lane in unique:
        _validate_lane(lane)
        if lane in {SERIAL_INTEGRATION_LANE, SERIAL_REPOSITORY_LANE}:
            raise ValueError("serial lanes are not owner-service lanes")
    if "nex-ae-api" in unique:
        return ("nex-ae-api", *(lane for lane in unique if lane != "nex-ae-api"))
    return unique


def _validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id must be a safe lowercase identifier")
    return value


def _validate_lane(value: str) -> str:
    admitted = {
        *SERVICE_PROFILES,
        SERIAL_INTEGRATION_LANE,
        SERIAL_REPOSITORY_LANE,
    }
    if LANE_PATTERN.fullmatch(value) is None or value not in admitted:
        raise ValueError(f"unsupported quality gate lane: {value}")
    return value


def _profile_test_files(root: Path) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for service, profile in SERVICE_PROFILES.items():
        files: set[str] = set()
        for pattern in profile.test_patterns:
            files.update(
                path.relative_to(root).as_posix()
                for path in (root / "tests").glob(pattern)
                if path.is_file()
            )
        files.update(path for path in profile.owned_tests if (root / path).is_file())
        result[service] = frozenset(files)
    return result


def _is_checkpoint_closure(path: str) -> bool:
    parsed = Path(path)
    return (
        parsed.parent == Path("tests")
        and parsed.name.startswith("test_s")
        and parsed.name.endswith("_closure.py")
    )


def _git_revision(
    root: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    completed = runner(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if not revision:
        raise ValueError("repository revision is empty")
    return revision


def _validated_output(root: Path, raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("output must be repository-relative")
    if relative.suffix != ".json" or relative.parts[:3] != (
        "reports",
        "quality",
        "parallel",
    ):
        raise ValueError("output must be a reports/quality/parallel/*.json path")
    return root / relative


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument(
        "--tier", choices=("checkpoint", "full"), required=True
    )
    inventory.add_argument("--output", required=True)
    inventory.add_argument("--summary", action="store_true")
    run = subparsers.add_parser("run-owner-lanes")
    run.add_argument("--tier", choices=("checkpoint", "full"), required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--lane", action="append", default=[])
    run.add_argument("--max-parallel", type=int, default=4)
    run.add_argument("--summary", action="store_true")
    checkpoint = subparsers.add_parser("checkpoint")
    checkpoint.add_argument("--run-id")
    checkpoint.add_argument("--max-parallel", type=int, default=4)
    checkpoint.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            output = _validated_output(ROOT, args.output)
            evidence = build_test_ownership_inventory(
                root=ROOT,
                tier=args.tier,
                revision=_git_revision(ROOT),
            )
            write_inventory(output, evidence)
        elif args.command == "run-owner-lanes":
            evidence = execute_owner_service_lanes(
                root=ROOT,
                tier=args.tier,
                run_id=_validate_run_id(args.run_id),
                lanes=tuple(args.lane) or INITIAL_OWNER_LANES,
                max_parallel=args.max_parallel,
                python_bin=os.environ.get("PYTHON_BIN", "./.venv/bin/python"),
            )
        else:
            revision = _git_revision(ROOT)
            evidence = execute_parallel_checkpoint_gate(
                root=ROOT,
                run_id=(
                    _validate_run_id(args.run_id)
                    if args.run_id
                    else _default_run_id("checkpoint", revision)
                ),
                max_parallel=args.max_parallel,
                python_bin=os.environ.get("PYTHON_BIN", "./.venv/bin/python"),
                revision=revision,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"parallel_quality_gate=fail error={type(exc).__name__}")
        return 1
    if args.summary:
        if args.command == "inventory":
            print(
                "parallel_quality_inventory=pass "
                f"tier={args.tier} tests={evidence['test_file_count']} "
                f"source_unowned={evidence['source_unowned_count']} "
                f"source_multi_owned={evidence['source_multi_owned_count']} "
                f"resolved_missing={evidence['resolved_missing_count']} "
                f"resolved_duplicate={evidence['resolved_duplicate_count']}"
            )
        elif args.command == "run-owner-lanes":
            print(
                "parallel_owner_lanes="
                f"{str(evidence['status']).lower()} tier={args.tier} "
                f"lanes={len(evidence['lanes'])} "
                f"duration={evidence['duration_seconds']}s"
            )
        else:
            print(
                "parallel_checkpoint_gate="
                f"{str(evidence['status']).lower()} "
                f"tests={evidence['test_file_count']} "
                f"duration={evidence['duration_seconds']}s"
            )
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence.get("status", "PASS") == "PASS" else 1


def _default_run_id(prefix: str, revision: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz").lower()
    return _validate_run_id(f"{prefix}-{timestamp}-{revision[:8].lower()}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
