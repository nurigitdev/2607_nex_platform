from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

import repository_revision_evidence as evidence


def test_revision_digest_helpers_read_exact_git_blobs(monkeypatch) -> None:
    payloads = {
        "rev:one": b"first",
        "rev:two": b"second",
    }

    def run(arguments, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=payloads[arguments[-1]],
        )

    monkeypatch.setattr(evidence.subprocess, "run", run)
    aggregate = sha256()
    expected = {}
    for relative, payload in (("one", b"first"), ("two", b"second")):
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(payload)
        aggregate.update(b"\0")
        expected[relative] = f"sha256:{sha256(payload).hexdigest()}"

    assert evidence.aggregate_digest_at_revision(
        Path("/repo"), "rev", ("one", "two")
    ) == f"sha256:{aggregate.hexdigest()}"
    assert evidence.file_digests_at_revision_match(
        Path("/repo"), "rev", expected
    )
    expected["two"] = "sha256:wrong"
    assert not evidence.file_digests_at_revision_match(
        Path("/repo"), "rev", expected
    )


def test_revision_digest_helpers_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        evidence.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout=b""),
    )
    assert evidence.aggregate_digest_at_revision(
        Path("/repo"), "rev", ("missing",)
    ) == ""
    assert not evidence.file_digests_at_revision_match(
        Path("/repo"), "rev", {"missing": "sha256:any"}
    )

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr(evidence.subprocess, "run", raise_timeout)
    assert evidence._git_blob(Path("/repo"), "rev", "missing") is None
    assert evidence._file_digest(None) == ""
