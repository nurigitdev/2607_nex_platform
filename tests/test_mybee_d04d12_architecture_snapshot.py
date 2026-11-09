from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/mybee_phase1/baselines/source_manifest.json"
PLATFORM_LOCK = ROOT / "domains/mybee/compatibility/platform.lock.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_version(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def test_s0_01_manifest_pins_a_reachable_clean_master_baseline() -> None:
    manifest = _load(MANIFEST)
    repository = manifest["repository"]

    assert manifest["schema_version"] == "nex.mybee.source-manifest.v1"
    assert repository["clean_worktree_at_capture"] is True
    assert repository["master_baseline_commit"] == repository["capture_commit"]
    subprocess.run(
        ["git", "cat-file", "-e", f'{repository["master_baseline_commit"]}^{{commit}}'],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            repository["master_baseline_commit"],
            "HEAD",
        ],
        cwd=ROOT,
        check=True,
    )


def test_s0_01_frozen_authority_and_migration_heads_are_exact() -> None:
    manifest = _load(MANIFEST)
    authority = manifest["frozen_authority"]
    assert _sha256(ROOT / authority["path"]) == authority["sha256"]

    for service_id, expected in manifest["migration_heads"].items():
        migration_dir = ROOT / "database" / service_id / "migrations"
        actual_head = max(migration_dir.glob("[0-9]*_*.sql"), key=_migration_version)
        assert actual_head.relative_to(ROOT).as_posix() == expected["path"]
        assert _migration_version(actual_head) == expected["version"]
        assert _sha256(actual_head) == expected["sha256"]


def test_s0_01_platform_lock_matches_canonical_contracts_and_nsl() -> None:
    manifest = _load(MANIFEST)
    platform_lock = _load(PLATFORM_LOCK)

    assert set(platform_lock["openapi"]) == set(manifest["canonical_contracts"])
    for service_id, expected in platform_lock["openapi"].items():
        assert expected["path"] == manifest["canonical_contracts"][service_id]
        assert _sha256(ROOT / expected["path"]) == expected["sha256"]

    nsl = platform_lock["nsl_runtime"]
    nsl_lock_path = ROOT / nsl["lock_path"]
    nsl_lock = _load(nsl_lock_path)
    assert _sha256(nsl_lock_path) == nsl["lock_sha256"]
    assert nsl["distribution"] == nsl_lock["distribution"]
    assert nsl["package_version"] == nsl_lock["package_version"]
    assert nsl["source_revision"] == nsl_lock["source_revision"]
    assert nsl["wheel_sha256"] == nsl_lock["wheel_sha256"]


def test_s0_01_ownership_prevents_a_second_mybee_platform() -> None:
    manifest = _load(MANIFEST)
    owners = manifest["service_ownership"]

    assert owners["nex-eos"].endswith("source of record")
    assert "human approval" in owners["nex-wc"]
    assert "current authorization" in owners["nex-oa"]
    assert "NSL integration" in owners["nex-ae-api"]
    assert "evidence" in owners["nex-wa"]
    assert owners["domains/mybee"].endswith("canonical API consumers")
    assert len(manifest["open_entry_gates"]) == 4
