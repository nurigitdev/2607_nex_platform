from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import archive_postgres_wal as archive_module
import restore_postgres_wal as restore_module
from archive_postgres_wal import WalArchiveError, archive_wal_segment, main as archive_main
from restore_postgres_wal import main as restore_main, restore_wal_segment


SEGMENT = "000000010000000000000001"


def test_wal_archive_restore_roundtrip_and_idempotency(tmp_path: Path) -> None:
    source = tmp_path / SEGMENT
    source.write_bytes(b"wal")
    archive = tmp_path / "archive"
    digest = archive_wal_segment(source, SEGMENT, archive)
    assert digest == hashlib.sha256(b"wal").hexdigest()
    assert archive_wal_segment(source, SEGMENT, archive) == digest
    destination = tmp_path / "restore" / SEGMENT
    destination.parent.mkdir()
    assert restore_wal_segment(SEGMENT, destination, archive) == digest
    assert destination.read_bytes() == b"wal"
    assert oct(destination.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("name", ["../bad", "lowercase", "0001"])
def test_wal_archive_rejects_invalid_names(tmp_path: Path, name: str) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"wal")
    with pytest.raises(WalArchiveError, match="wal_segment_name_invalid"):
        archive_wal_segment(source, name, tmp_path / "archive")


def test_wal_archive_rejects_collision_and_symlink_root(tmp_path: Path) -> None:
    source = tmp_path / SEGMENT
    source.write_bytes(b"new")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / SEGMENT).write_bytes(b"old")
    with pytest.raises(WalArchiveError, match="wal_archive_collision"):
        archive_wal_segment(source, SEGMENT, archive)
    link = tmp_path / "link"
    link.symlink_to(archive, target_is_directory=True)
    with pytest.raises(WalArchiveError, match="wal_archive_root_symlink"):
        archive_wal_segment(source, SEGMENT, link)

    symlink_archive = tmp_path / "symlink-archive"
    symlink_archive.mkdir()
    other = tmp_path / "other"
    other.write_bytes(b"new")
    (symlink_archive / SEGMENT).symlink_to(other)
    with pytest.raises(WalArchiveError, match="wal_archive_collision"):
        archive_wal_segment(source, SEGMENT, symlink_archive)


def test_wal_archive_rejects_invalid_source_and_cleans_partial(tmp_path: Path, monkeypatch) -> None:
    mismatched = tmp_path / "different"
    mismatched.write_bytes(b"wal")
    with pytest.raises(WalArchiveError, match="wal_segment_name_invalid"):
        archive_wal_segment(mismatched, SEGMENT, tmp_path / "archive")

    directory = tmp_path / SEGMENT
    directory.mkdir()
    with pytest.raises(WalArchiveError, match="wal_source_invalid"):
        archive_wal_segment(directory, SEGMENT, tmp_path / "archive")

    source = tmp_path / "source-root" / SEGMENT
    source.parent.mkdir()
    source.write_bytes(b"wal")
    real = tmp_path / "real-source"
    source.replace(real)
    source.symlink_to(real)
    with pytest.raises(WalArchiveError, match="wal_source_invalid"):
        archive_wal_segment(source, SEGMENT, tmp_path / "archive")

    source.unlink()
    source.write_bytes(b"wal")
    digests = iter(("a", "b"))
    monkeypatch.setattr(archive_module, "_sha256", lambda _path: next(digests))
    archive = tmp_path / "copy-mismatch"
    with pytest.raises(WalArchiveError, match="wal_archive_copy_hash_mismatch"):
        archive_wal_segment(source, SEGMENT, archive)
    assert list(archive.glob("*.partial")) == []


def test_wal_restore_rejects_missing_digest_tamper_and_destination(tmp_path: Path) -> None:
    source = tmp_path / SEGMENT
    source.write_bytes(b"wal")
    archive = tmp_path / "archive"
    archive_wal_segment(source, SEGMENT, archive)
    digest_path = archive / f"{SEGMENT}.sha256"
    digest_path.unlink()
    destination = tmp_path / "restore" / SEGMENT
    destination.parent.mkdir()
    with pytest.raises(WalArchiveError, match="wal_archive_segment_missing"):
        restore_wal_segment(SEGMENT, destination, archive)
    digest_path.write_text("0" * 64, encoding="ascii")
    with pytest.raises(WalArchiveError, match="wal_archive_digest_mismatch"):
        restore_wal_segment(SEGMENT, destination, archive)
    digest_path.write_text(hashlib.sha256(b"wal").hexdigest(), encoding="ascii")
    destination.write_bytes(b"existing")
    with pytest.raises(WalArchiveError, match="wal_restore_destination_unsafe"):
        restore_wal_segment(SEGMENT, destination, archive)

    with pytest.raises(WalArchiveError, match="wal_restore_target_invalid"):
        restore_wal_segment("bad", destination, archive)


def test_wal_restore_rejects_symlinks_and_cleans_copy_mismatch(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / SEGMENT
    source.write_bytes(b"wal")
    archive = tmp_path / "archive"
    archive_wal_segment(source, SEGMENT, archive)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination = destination_root / SEGMENT

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(WalArchiveError, match="wal_restore_destination_unsafe"):
        restore_wal_segment(SEGMENT, linked_parent / SEGMENT, archive)

    digests = iter(("a", "b"))
    monkeypatch.setattr(restore_module, "_sha256", lambda _path: next(digests))
    digest_path = archive / f"{SEGMENT}.sha256"
    digest_path.write_text("a", encoding="ascii")
    with pytest.raises(WalArchiveError, match="wal_restore_copy_hash_mismatch"):
        restore_wal_segment(SEGMENT, destination, archive)
    assert not destination.exists()


def test_wal_cli_requires_root_and_executes(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / SEGMENT
    source.write_bytes(b"wal")
    monkeypatch.delenv("NEX_POSTGRES_WAL_ARCHIVE_ROOT", raising=False)
    with pytest.raises(SystemExit, match="required"):
        archive_main([str(source), SEGMENT])
    archive = tmp_path / "archive"
    monkeypatch.setenv("NEX_POSTGRES_WAL_ARCHIVE_ROOT", str(archive))
    assert archive_main([str(source), SEGMENT]) == 0
    destination = tmp_path / "restore" / SEGMENT
    destination.parent.mkdir()
    assert restore_main([SEGMENT, str(destination)]) == 0
    monkeypatch.delenv("NEX_POSTGRES_WAL_ARCHIVE_ROOT")
    with pytest.raises(SystemExit, match="required"):
        restore_main([SEGMENT, str(tmp_path / "unused" / SEGMENT)])
