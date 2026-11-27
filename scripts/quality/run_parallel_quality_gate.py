#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
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
SERIAL_INTEGRATION_LANE = "serial-integration"
SERIAL_REPOSITORY_LANE = "serial-repository"
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
        if len(candidates) == 1:
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
    parser.add_argument("inventory", choices=("inventory",))
    parser.add_argument("--tier", choices=("checkpoint", "full"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = _validated_output(ROOT, args.output)
        evidence = build_test_ownership_inventory(
            root=ROOT,
            tier=args.tier,
            revision=_git_revision(ROOT),
        )
        write_inventory(output, evidence)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"parallel_quality_inventory=fail error={type(exc).__name__}")
        return 1
    if args.summary:
        print(
            "parallel_quality_inventory=pass "
            f"tier={args.tier} tests={evidence['test_file_count']} "
            f"source_unowned={evidence['source_unowned_count']} "
            f"source_multi_owned={evidence['source_multi_owned_count']} "
            f"resolved_missing={evidence['resolved_missing_count']} "
            f"resolved_duplicate={evidence['resolved_duplicate_count']}"
        )
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
