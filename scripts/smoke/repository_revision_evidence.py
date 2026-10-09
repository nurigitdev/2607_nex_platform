from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
import subprocess


def aggregate_digest_at_revision(
    root: Path,
    revision: str,
    paths: Sequence[str],
) -> str:
    digest = sha256()
    for relative in paths:
        payload = _git_blob(root, revision, relative)
        if payload is None:
            return ""
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def file_digests_at_revision_match(
    root: Path,
    revision: str,
    expected: Mapping[str, str],
) -> bool:
    return all(
        _file_digest(_git_blob(root, revision, relative)) == digest
        for relative, digest in expected.items()
    )


def _git_blob(root: Path, revision: str, relative: str) -> bytes | None:
    try:
        completed = subprocess.run(
            ("git", "show", f"{revision}:{relative}"),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _file_digest(payload: bytes | None) -> str:
    if payload is None:
        return ""
    return f"sha256:{sha256(payload).hexdigest()}"
