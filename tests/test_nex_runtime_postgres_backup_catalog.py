from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nex_runtime.postgres_backup import build_logical_backup_plan, execute_logical_backup
from nex_runtime.postgres_backup_catalog import (
    BackupCatalog,
    BackupCatalogEntry,
    PostgresBackupCatalogError,
    build_backup_catalog,
    plan_backup_retention,
    quarantine_stale_partials,
    record_restore_verification,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy
from nex_runtime.postgres_restore import IsolatedRestoreResult, RESTORE_EVIDENCE_SCHEMA_VERSION


POLICY = load_postgres_resilience_policy(Path("deployment/postgres/s145-policy.yaml"))
TARGET = POLICY.targets[0]
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def _backup(tmp_path: Path, backup_id: str = "20261008T000000Z-1234abcd"):
    plan = build_logical_backup_plan(
        policy=POLICY, target=TARGET, backup_id=backup_id,
        backup_root=tmp_path / "backup", pg_dump_bin=Path("/usr/bin/pg_dump"),
        service_file=tmp_path / "pg_service.conf", passfile=tmp_path / ".pgpass",
    )
    def runner(_command, **kwargs):
        kwargs["stdout"].write(f"PGDMP-{backup_id}".encode())
        return SimpleNamespace(returncode=0)
    times = iter((NOW, NOW + timedelta(seconds=1)))
    result = execute_logical_backup(plan, runner=runner, clock=lambda: next(times))
    return plan, result


def _restore(result, **overrides):
    values = {
        "schema_version": RESTORE_EVIDENCE_SCHEMA_VERSION,
        "backup_id": result.backup_id, "service_id": result.service_id,
        "state": "RESTORED", "target_class": "isolated_recovery",
        "archive_sha256": result.archive_sha256, "probe_count": 4,
        "completed_at": "2026-10-08T00:00:02Z",
    }
    values.update(overrides)
    return IsolatedRestoreResult(**values)


def test_verification_catalog_and_orphan_detection(tmp_path: Path) -> None:
    plan, result = _backup(tmp_path)
    verification = record_restore_verification(manifest_path=plan.manifest_path, restore_result=_restore(result))
    assert verification.exists()
    assert oct(verification.stat().st_mode & 0o777) == "0o600"
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert catalog.issues == ()
    assert len(catalog.entries) == 1
    assert catalog.entries[0].state == "VERIFIED"

    orphan = plan.service_directory / "orphan.dump"
    orphan.write_bytes(b"orphan")
    assert build_backup_catalog(plan.service_directory, service_id=TARGET.service_id).issues == ("orphan.dump:orphan_archive",)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"backup_id": "wrong"}, "restore_verification_binding_invalid"),
        ({"service_id": "nex-ag"}, "restore_verification_binding_invalid"),
        ({"state": "FAILED"}, "restore_verification_binding_invalid"),
        ({"target_class": "active"}, "restore_verification_binding_invalid"),
        ({"probe_count": 3}, "restore_verification_binding_invalid"),
    ],
)
def test_verification_rejects_binding_drift(tmp_path: Path, overrides: dict, code: str) -> None:
    plan, result = _backup(tmp_path)
    with pytest.raises(PostgresBackupCatalogError, match=code):
        record_restore_verification(manifest_path=plan.manifest_path, restore_result=_restore(result, **overrides))


def test_catalog_reports_invalid_manifest_archive_and_verification(tmp_path: Path) -> None:
    plan, result = _backup(tmp_path)
    plan.archive_path.write_bytes(b"tampered")
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert "backup_archive_integrity_invalid" in catalog.issues[0]

    plan, result = _backup(tmp_path / "bad-verification")
    path = record_restore_verification(manifest_path=plan.manifest_path, restore_result=_restore(result))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["probe_count"] = 3
    path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert "backup_verification_binding_invalid" in catalog.issues[0]


def test_catalog_accepts_created_entry_without_verification(tmp_path: Path) -> None:
    plan, _result = _backup(tmp_path)
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert catalog.issues == ()
    assert catalog.entries[0].state == "CREATED"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload.update(extra=True), "backup_manifest_shape_invalid"),
        (lambda payload: payload.update(schema_version="wrong"), "backup_manifest_shape_invalid"),
        (lambda payload: payload.update(service_id="nex-ag"), "backup_manifest_binding_invalid"),
        (lambda payload: payload.update(state="FAILED"), "backup_manifest_binding_invalid"),
        (lambda payload: payload.update(archive_name="../escape.dump"), "backup_archive_path_invalid"),
    ],
)
def test_catalog_reports_manifest_drift(tmp_path: Path, mutation, code: str) -> None:
    plan, _result = _backup(tmp_path)
    payload = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    mutation(payload)
    plan.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert code in catalog.issues[0]


def test_catalog_reports_missing_symlink_and_unreadable_inputs(tmp_path: Path) -> None:
    missing, _result = _backup(tmp_path / "missing")
    missing.archive_path.unlink()
    assert "backup_archive_missing" in build_backup_catalog(
        missing.service_directory, service_id=TARGET.service_id
    ).issues[0]

    linked, _result = _backup(tmp_path / "linked")
    real = linked.archive_path.with_suffix(".real")
    linked.archive_path.replace(real)
    linked.archive_path.symlink_to(real)
    assert "backup_archive_path_invalid" in build_backup_catalog(
        linked.service_directory, service_id=TARGET.service_id
    ).issues[0]

    unreadable, _result = _backup(tmp_path / "unreadable")
    unreadable.manifest_path.write_text("[]", encoding="utf-8")
    assert "backup_manifest_unreadable" in build_backup_catalog(
        unreadable.service_directory, service_id=TARGET.service_id
    ).issues[0]


def test_catalog_reports_archive_open_failure_after_stat(tmp_path: Path) -> None:
    plan, _result = _backup(tmp_path)
    payload = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    plan.archive_path.unlink()
    plan.archive_path.mkdir()
    payload["archive_bytes"] = plan.archive_path.stat().st_size
    plan.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = build_backup_catalog(plan.service_directory, service_id=TARGET.service_id)
    assert "backup_archive_unreadable" in catalog.issues[0]


def test_retention_preserves_count_age_and_verified_minimum() -> None:
    entries = []
    for index in range(32):
        stamp = NOW - timedelta(days=index + 8)
        entries.append(BackupCatalogEntry(
            backup_id=f"backup-{index:02d}", service_id=TARGET.service_id,
            state="VERIFIED" if index != 31 else "CREATED",
            completed_at=stamp.isoformat().replace("+00:00", "Z"),
            archive_sha256="0" * 64, archive_bytes=1,
            manifest_path=Path("manifest"), archive_path=Path("archive"),
            verification_path=Path("verification"),
        ))
    plan = plan_backup_retention(BackupCatalog(TARGET.service_id, tuple(entries), (), ()), POLICY, now=NOW)
    assert len(plan.keep_backup_ids) == 28
    assert plan.delete_backup_ids == ("backup-28", "backup-29", "backup-30")
    assert plan.quarantine_backup_ids == ("backup-31",)


def test_retention_keeps_recent_and_minimum_verified_point() -> None:
    recent = BackupCatalogEntry("recent", TARGET.service_id, "CREATED", NOW.isoformat(), "0" * 64, 1, Path("m"), Path("a"), Path("v"))
    old_verified = replace(recent, backup_id="old", state="VERIFIED", completed_at=(NOW - timedelta(days=100)).isoformat())
    strict = replace(POLICY, retention_restore_points=1, minimum_verified_points=1)
    plan = plan_backup_retention(BackupCatalog(TARGET.service_id, (recent, old_verified), (), ()), strict, now=NOW)
    assert plan.keep_backup_ids == ("recent", "old")
    assert plan.delete_backup_ids == ()


def test_stale_partial_quarantine_and_guards(tmp_path: Path) -> None:
    service = tmp_path / "service"
    service.mkdir()
    stale = service / ".stale.partial"
    fresh = service / ".fresh.partial"
    stale.write_bytes(b"stale")
    fresh.write_bytes(b"fresh")
    old = (NOW - timedelta(days=1)).timestamp()
    os.utime(stale, (old, old))
    future = (NOW + timedelta(days=1)).timestamp()
    os.utime(fresh, (future, future))
    moved = quarantine_stale_partials(service, stale_before=NOW)
    assert len(moved) == 1 and moved[0].exists()
    assert fresh.exists()

    collision = service / ".collision.partial"
    collision.write_bytes(b"collision")
    os.utime(collision, (old, old))
    destination = service / ".quarantine" / ".collision.partial.quarantined"
    destination.write_bytes(b"existing")
    with pytest.raises(PostgresBackupCatalogError, match="quarantine_destination_exists"):
        quarantine_stale_partials(service, stale_before=NOW)


def test_catalog_and_time_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(PostgresBackupCatalogError, match="catalog_directory_invalid"):
        build_backup_catalog(tmp_path / "missing", service_id=TARGET.service_id)
    with pytest.raises(PostgresBackupCatalogError, match="catalog_timestamp_not_timezone_aware"):
        plan_backup_retention(BackupCatalog(TARGET.service_id, (), (), ()), POLICY, now=datetime(2026, 1, 1))
    bad = BackupCatalogEntry("bad", TARGET.service_id, "VERIFIED", "bad", "0" * 64, 1, Path("m"), Path("a"), Path("v"))
    with pytest.raises(PostgresBackupCatalogError, match="catalog_timestamp_invalid"):
        plan_backup_retention(BackupCatalog(TARGET.service_id, (bad,), (), ()), POLICY, now=NOW)


def test_verification_atomic_duplicate_and_write_failure_guards(tmp_path: Path, monkeypatch) -> None:
    plan, result = _backup(tmp_path)
    restore = _restore(result)
    record_restore_verification(manifest_path=plan.manifest_path, restore_result=restore)
    with pytest.raises(PostgresBackupCatalogError, match="verification_already_exists"):
        record_restore_verification(manifest_path=plan.manifest_path, restore_result=restore)

    second, second_result = _backup(tmp_path / "write-failure")
    def fail_dump(*_args, **_kwargs):
        raise OSError("simulated")
    monkeypatch.setattr("nex_runtime.postgres_backup_catalog.json.dump", fail_dump)
    with pytest.raises(OSError, match="simulated"):
        record_restore_verification(
            manifest_path=second.manifest_path,
            restore_result=_restore(second_result),
        )
    partial = second.manifest_path.with_name(
        f".{second.manifest_path.name.replace('.manifest.json', '.verification.json')}.partial"
    )
    assert not partial.exists()
