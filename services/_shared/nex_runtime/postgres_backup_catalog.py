from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .postgres_backup import BACKUP_MANIFEST_SCHEMA_VERSION
from .postgres_resilience import PostgresResiliencePolicy
from .postgres_restore import IsolatedRestoreResult, RESTORE_EVIDENCE_SCHEMA_VERSION


VERIFICATION_SCHEMA_VERSION = "postgres_backup_verification.v1"


class PostgresBackupCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupCatalogEntry:
    backup_id: str
    service_id: str
    state: str
    completed_at: str
    archive_sha256: str
    archive_bytes: int
    manifest_path: Path
    archive_path: Path
    verification_path: Path


@dataclass(frozen=True)
class BackupCatalog:
    service_id: str
    entries: tuple[BackupCatalogEntry, ...]
    issues: tuple[str, ...]
    partials: tuple[Path, ...]


@dataclass(frozen=True)
class RetentionPlan:
    keep_backup_ids: tuple[str, ...]
    delete_backup_ids: tuple[str, ...]
    quarantine_backup_ids: tuple[str, ...]


def record_restore_verification(
    *,
    manifest_path: Path,
    restore_result: IsolatedRestoreResult,
) -> Path:
    manifest = _load_json(manifest_path, "backup_manifest_unreadable")
    if (
        manifest.get("schema_version") != BACKUP_MANIFEST_SCHEMA_VERSION
        or manifest.get("backup_id") != restore_result.backup_id
        or manifest.get("service_id") != restore_result.service_id
        or manifest.get("archive_sha256") != restore_result.archive_sha256
        or restore_result.schema_version != RESTORE_EVIDENCE_SCHEMA_VERSION
        or restore_result.state != "RESTORED"
        or restore_result.target_class != "isolated_recovery"
        or restore_result.probe_count != 4
    ):
        raise PostgresBackupCatalogError("restore_verification_binding_invalid")
    path = manifest_path.with_name(
        manifest_path.name.replace(".manifest.json", ".verification.json")
    )
    payload = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "backup_id": restore_result.backup_id,
        "service_id": restore_result.service_id,
        "state": "VERIFIED",
        "archive_sha256": restore_result.archive_sha256,
        "target_class": restore_result.target_class,
        "probe_count": restore_result.probe_count,
        "verified_at": restore_result.completed_at,
    }
    _write_json_atomic(path, payload)
    return path


def build_backup_catalog(service_directory: Path, *, service_id: str) -> BackupCatalog:
    if not service_directory.is_dir() or service_directory.is_symlink():
        raise PostgresBackupCatalogError("catalog_directory_invalid")
    entries: list[BackupCatalogEntry] = []
    issues: list[str] = []
    partials = tuple(sorted(service_directory.glob(".*.partial")))
    manifests = tuple(sorted(service_directory.glob("*.manifest.json")))
    known_archives: set[Path] = set()
    for manifest_path in manifests:
        try:
            manifest = _load_json(manifest_path, "backup_manifest_unreadable")
            entry = _catalog_entry(manifest_path, manifest, service_id=service_id)
        except PostgresBackupCatalogError as exc:
            issues.append(f"{manifest_path.name}:{exc}")
            continue
        entries.append(entry)
        known_archives.add(entry.archive_path)
    for archive_path in sorted(service_directory.glob("*.dump")):
        if archive_path not in known_archives:
            issues.append(f"{archive_path.name}:orphan_archive")
    return BackupCatalog(
        service_id=service_id,
        entries=tuple(sorted(entries, key=lambda item: item.completed_at, reverse=True)),
        issues=tuple(issues),
        partials=partials,
    )


def plan_backup_retention(
    catalog: BackupCatalog,
    policy: PostgresResiliencePolicy,
    *,
    now: datetime,
) -> RetentionPlan:
    current = _aware(now)
    cutoff = current - timedelta(days=policy.retention_days)
    entries = tuple(sorted(catalog.entries, key=lambda item: item.completed_at, reverse=True))
    keep: set[str] = {
        item.backup_id for item in entries[: policy.retention_restore_points]
    }
    keep.update(
        item.backup_id
        for item in entries
        if _parse_timestamp(item.completed_at) >= cutoff
    )
    verified = [item for item in entries if item.state == "VERIFIED"]
    keep.update(
        item.backup_id for item in verified[: policy.minimum_verified_points]
    )
    delete = tuple(
        item.backup_id
        for item in entries
        if item.backup_id not in keep and item.state == "VERIFIED"
    )
    quarantine = tuple(
        item.backup_id
        for item in entries
        if item.backup_id not in keep and item.state != "VERIFIED"
    )
    return RetentionPlan(
        keep_backup_ids=tuple(item.backup_id for item in entries if item.backup_id in keep),
        delete_backup_ids=delete,
        quarantine_backup_ids=quarantine,
    )


def quarantine_stale_partials(
    service_directory: Path,
    *,
    stale_before: datetime,
) -> tuple[Path, ...]:
    cutoff = _aware(stale_before).timestamp()
    quarantine = service_directory / ".quarantine"
    moved: list[Path] = []
    for path in sorted(service_directory.glob(".*.partial")):
        if path.is_symlink() or path.stat().st_mtime >= cutoff:
            continue
        quarantine.mkdir(mode=0o700, exist_ok=True)
        os.chmod(quarantine, 0o700)
        destination = quarantine / f"{path.name}.quarantined"
        if destination.exists():
            raise PostgresBackupCatalogError("quarantine_destination_exists")
        os.replace(path, destination)
        moved.append(destination)
    return tuple(moved)


def _catalog_entry(
    manifest_path: Path, manifest: Mapping[str, Any], *, service_id: str
) -> BackupCatalogEntry:
    required = {
        "schema_version", "backup_id", "service_id", "state", "archive_name",
        "archive_sha256", "archive_bytes", "backup_format", "compression",
        "postgres_major", "started_at", "completed_at",
    }
    if set(manifest) != required or manifest.get("schema_version") != BACKUP_MANIFEST_SCHEMA_VERSION:
        raise PostgresBackupCatalogError("backup_manifest_shape_invalid")
    if manifest.get("service_id") != service_id or manifest.get("state") != "CREATED":
        raise PostgresBackupCatalogError("backup_manifest_binding_invalid")
    archive_path = manifest_path.parent / str(manifest["archive_name"])
    if archive_path.parent != manifest_path.parent or archive_path.is_symlink():
        raise PostgresBackupCatalogError("backup_archive_path_invalid")
    try:
        size = archive_path.stat().st_size
    except OSError as exc:
        raise PostgresBackupCatalogError("backup_archive_missing") from exc
    if size != manifest.get("archive_bytes") or _sha256(archive_path) != manifest.get("archive_sha256"):
        raise PostgresBackupCatalogError("backup_archive_integrity_invalid")
    verification_path = manifest_path.with_name(
        manifest_path.name.replace(".manifest.json", ".verification.json")
    )
    state = "CREATED"
    if verification_path.exists():
        verification = _load_json(verification_path, "backup_verification_unreadable")
        expected = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "backup_id": manifest["backup_id"],
            "service_id": service_id,
            "state": "VERIFIED",
            "archive_sha256": manifest["archive_sha256"],
            "target_class": "isolated_recovery",
            "probe_count": 4,
        }
        if any(verification.get(key) != value for key, value in expected.items()) or not verification.get("verified_at"):
            raise PostgresBackupCatalogError("backup_verification_binding_invalid")
        _parse_timestamp(str(verification["verified_at"]))
        state = "VERIFIED"
    _parse_timestamp(str(manifest["completed_at"]))
    return BackupCatalogEntry(
        backup_id=str(manifest["backup_id"]), service_id=service_id, state=state,
        completed_at=str(manifest["completed_at"]),
        archive_sha256=str(manifest["archive_sha256"]), archive_bytes=size,
        manifest_path=manifest_path, archive_path=archive_path,
        verification_path=verification_path,
    )


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PostgresBackupCatalogError(code) from exc
    if not isinstance(value, Mapping):
        raise PostgresBackupCatalogError(code)
    return dict(value)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    partial = path.with_name(f".{path.name}.partial")
    if path.exists() or partial.exists():
        raise PostgresBackupCatalogError("verification_already_exists")
    try:
        with partial.open("x", encoding="utf-8") as output:
            os.chmod(partial, 0o600)
            json.dump(dict(payload), output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PostgresBackupCatalogError("backup_archive_unreadable") from exc
    return digest.hexdigest()


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresBackupCatalogError("catalog_timestamp_invalid") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresBackupCatalogError("catalog_timestamp_not_timezone_aware")
    return value.astimezone(timezone.utc)
