#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil


WAL_NAME = re.compile(
    r"^(?:[0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)$"
)


class WalArchiveError(RuntimeError):
    pass


def archive_wal_segment(source: Path, segment_name: str, archive_root: Path) -> str:
    _validate_segment(source, segment_name)
    if archive_root.is_symlink():
        raise WalArchiveError("wal_archive_root_symlink")
    archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(archive_root, 0o700)
    destination = archive_root / segment_name
    source_digest = _sha256(source)
    if destination.exists():
        if destination.is_symlink() or _sha256(destination) != source_digest:
            raise WalArchiveError("wal_archive_collision")
        return source_digest
    partial = archive_root / f".{segment_name}.{os.getpid()}.partial"
    try:
        with source.open("rb") as input_file, partial.open("xb") as output_file:
            os.chmod(partial, 0o600)
            shutil.copyfileobj(input_file, output_file, 1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if _sha256(partial) != source_digest:
            raise WalArchiveError("wal_archive_copy_hash_mismatch")
        os.replace(partial, destination)
        _write_digest(destination.with_suffix(destination.suffix + ".sha256"), source_digest)
        return source_digest
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _validate_segment(source: Path, segment_name: str) -> None:
    if not WAL_NAME.fullmatch(segment_name) or source.name != segment_name:
        raise WalArchiveError("wal_segment_name_invalid")
    if not source.is_file() or source.is_symlink():
        raise WalArchiveError("wal_source_invalid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_digest(path: Path, digest: str) -> None:
    partial = path.with_name(f".{path.name}.partial")
    with partial.open("x", encoding="ascii") as output:
        os.chmod(partial, 0o600)
        output.write(f"{digest}\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(partial, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("segment_name")
    args = parser.parse_args(argv)
    root = os.environ.get("NEX_POSTGRES_WAL_ARCHIVE_ROOT")
    if not root:
        raise SystemExit("NEX_POSTGRES_WAL_ARCHIVE_ROOT is required")
    archive_wal_segment(args.source, args.segment_name, Path(root))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
