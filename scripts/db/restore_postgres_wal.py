#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil

from archive_postgres_wal import WAL_NAME, WalArchiveError


def restore_wal_segment(segment_name: str, destination: Path, archive_root: Path) -> str:
    if not WAL_NAME.fullmatch(segment_name) or destination.name != segment_name:
        raise WalArchiveError("wal_restore_target_invalid")
    source = archive_root / segment_name
    digest_path = archive_root / f"{segment_name}.sha256"
    if source.is_symlink() or not source.is_file() or not digest_path.is_file():
        raise WalArchiveError("wal_archive_segment_missing")
    expected = digest_path.read_text(encoding="ascii").strip()
    actual = _sha256(source)
    if expected != actual:
        raise WalArchiveError("wal_archive_digest_mismatch")
    if destination.exists() or destination.parent.is_symlink():
        raise WalArchiveError("wal_restore_destination_unsafe")
    partial = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    try:
        with source.open("rb") as input_file, partial.open("xb") as output_file:
            os.chmod(partial, 0o600)
            shutil.copyfileobj(input_file, output_file, 1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if _sha256(partial) != actual:
            raise WalArchiveError("wal_restore_copy_hash_mismatch")
        os.replace(partial, destination)
        return actual
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("segment_name")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    root = os.environ.get("NEX_POSTGRES_WAL_ARCHIVE_ROOT")
    if not root:
        raise SystemExit("NEX_POSTGRES_WAL_ARCHIVE_ROOT is required")
    restore_wal_segment(args.segment_name, args.destination, Path(root))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
