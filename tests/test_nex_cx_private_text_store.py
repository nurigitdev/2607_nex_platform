from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivateTextStore,
    build_private_payload_key,
    sha256_private_text,
)
from nex_cx.private_text_store import (
    DEFAULT_PRIVATE_TEXT_STORAGE_ROOT,
    PRIVATE_TEXT_STORAGE_BACKEND,
    FileSystemCxPrivateTextStore,
    build_private_text_store,
)
import run_cx_private_text_store_smoke as smoke


def _context(
    *, tenant_id: str = "tenant-a", subject_id: str = "employee-1004"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0915",
        trace_id="91500000000000000000000000000001",
        scopes=("service:call",),
    )


def _key(context: CxAccessContext | None = None, *, content_id: str = "chunk-0915"):
    return build_private_payload_key(
        context or _context(),
        payload_kind="chunk_text",
        content_id=content_id,
    )


def test_filesystem_text_store_round_trip_restart_and_delete(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    text = "owner-private 한국어 text"
    checksum = sha256_private_text(text)
    store = FileSystemCxPrivateTextStore(tmp_path / "private-text")

    receipt = store.put_text(
        access_context=context,
        key=key,
        text=text,
        expected_sha256=checksum,
    )

    assert isinstance(store, CxPrivateTextStore)
    assert receipt.storage_backend == PRIVATE_TEXT_STORAGE_BACKEND
    assert receipt.sha256 == checksum
    assert receipt.size_bytes == len(text.encode("utf-8"))
    assert receipt.vector_dimension is None
    assert "tenant-a" not in receipt.storage_uri
    assert "employee-1004" not in receipt.storage_uri
    assert "chunk-0915" not in receipt.storage_uri
    restarted = FileSystemCxPrivateTextStore(tmp_path / "private-text")
    assert restarted.get_text(
        access_context=context,
        key=key,
        expected_sha256=checksum,
    ) == text
    assert restarted.delete_text(access_context=context, key=key) is True
    assert restarted.get_text(
        access_context=context,
        key=key,
        expected_sha256=checksum,
    ) is None
    assert restarted.delete_text(access_context=context, key=key) is False


def test_filesystem_text_store_put_is_idempotent_and_immutable(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("first")

    first = store.put_text(
        access_context=context,
        key=key,
        text="first",
        expected_sha256=checksum,
    )
    second = store.put_text(
        access_context=context,
        key=key,
        text="first",
        expected_sha256=checksum,
    )
    with pytest.raises(CxPrivateContentError) as caught:
        store.put_text(
            access_context=context,
            key=key,
            text="second",
            expected_sha256=sha256_private_text("second"),
        )

    assert second == first
    assert caught.value.status_code == 409
    assert caught.value.error_code == "CX_PRIVATE_TEXT_IMMUTABLE_CONFLICT"


@pytest.mark.parametrize("operation", ["put", "get", "delete"])
def test_filesystem_text_store_hides_cross_owner_access(
    tmp_path: Path,
    operation: str,
) -> None:
    owner_context = _context()
    key = _key(owner_context)
    other_context = _context(subject_id="employee-2000")
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("private")

    with pytest.raises(CxPrivateContentError) as caught:
        if operation == "put":
            store.put_text(
                access_context=other_context,
                key=key,
                text="private",
                expected_sha256=checksum,
            )
        elif operation == "get":
            store.get_text(
                access_context=other_context,
                key=key,
                expected_sha256=checksum,
            )
        else:
            store.delete_text(access_context=other_context, key=key)

    assert caught.value.status_code == 404
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"


def test_filesystem_text_store_rejects_invalid_put_hash(tmp_path: Path) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        FileSystemCxPrivateTextStore(tmp_path).put_text(
            access_context=_context(),
            key=_key(),
            text="private",
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_MISMATCH"
    assert list(tmp_path.rglob("*.utf8")) == []


def test_filesystem_text_store_detects_corruption(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("private")
    store.put_text(
        access_context=context,
        key=key,
        text="private",
        expected_sha256=checksum,
    )
    store._payload_path(key).write_text("tampered", encoding="utf-8")

    with pytest.raises(CxPrivateContentError) as caught:
        store.get_text(
            access_context=context,
            key=key,
            expected_sha256=checksum,
        )

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_MISMATCH"


def test_filesystem_text_store_rejects_invalid_utf8(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    path = store._payload_path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff")

    with pytest.raises(CxPrivateContentError) as caught:
        store.get_text(
            access_context=context,
            key=key,
            expected_sha256="0" * 64,
        )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "CX_PRIVATE_TEXT_ENCODING_INVALID"


def test_filesystem_text_store_rejects_unsafe_storage_entry(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path / "root")
    path = store._payload_path(key)
    path.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("private", encoding="utf-8")
    path.symlink_to(target)

    with pytest.raises(CxPrivateContentError) as read_error:
        store.get_text(
            access_context=context,
            key=key,
            expected_sha256=sha256_private_text("private"),
        )
    with pytest.raises(CxPrivateContentError) as delete_error:
        store.delete_text(access_context=context, key=key)

    assert read_error.value.error_code == "CX_PRIVATE_TEXT_STORAGE_UNSAFE"
    assert delete_error.value.error_code == "CX_PRIVATE_TEXT_STORAGE_UNSAFE"
    assert target.read_text(encoding="utf-8") == "private"


def test_filesystem_text_store_rejects_unsafe_parent(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path / "root")
    path = store._payload_path(key)
    store.root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / path.relative_to(store.root).parts[0]).symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(CxPrivateContentError) as caught:
        store.put_text(
            access_context=context,
            key=key,
            text="private",
            expected_sha256=sha256_private_text("private"),
        )

    assert caught.value.error_code == "CX_PRIVATE_TEXT_STORAGE_UNSAFE"
    assert list(outside.rglob("*.utf8")) == []


def test_filesystem_text_store_rejects_file_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.write_text("not-a-directory", encoding="utf-8")

    with pytest.raises(CxPrivateContentError) as caught:
        FileSystemCxPrivateTextStore(root).put_text(
            access_context=_context(),
            key=_key(),
            text="private",
            expected_sha256=sha256_private_text("private"),
        )

    assert caught.value.error_code == "CX_PRIVATE_TEXT_STORAGE_UNSAFE"


def test_filesystem_text_store_maps_read_failure_to_retryable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("private")
    store.put_text(
        access_context=context,
        key=key,
        text="private",
        expected_sha256=checksum,
    )

    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError()))
    with pytest.raises(CxPrivateContentError) as caught:
        store.get_text(
            access_context=context,
            key=key,
            expected_sha256=checksum,
        )

    assert caught.value.status_code == 503
    assert caught.value.retryable is True


def test_filesystem_text_store_handles_publish_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("private")

    def publish_then_report_race(source: str, target: Path) -> None:
        Path(target).write_bytes(Path(source).read_bytes())
        raise FileExistsError

    monkeypatch.setattr(os, "link", publish_then_report_race)
    receipt = store.put_text(
        access_context=context,
        key=key,
        text="private",
        expected_sha256=checksum,
    )

    assert receipt.sha256 == checksum
    assert store.get_text(
        access_context=context,
        key=key,
        expected_sha256=checksum,
    ) == "private"


def test_filesystem_text_store_rejects_conflicting_publish_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemCxPrivateTextStore(tmp_path)

    def publish_conflict(source: str, target: Path) -> None:
        Path(target).write_text("other", encoding="utf-8")
        raise FileExistsError

    monkeypatch.setattr(os, "link", publish_conflict)
    with pytest.raises(CxPrivateContentError) as caught:
        store.put_text(
            access_context=_context(),
            key=_key(),
            text="private",
            expected_sha256=sha256_private_text("private"),
        )

    assert caught.value.error_code == "CX_PRIVATE_TEXT_IMMUTABLE_CONFLICT"
    assert list(tmp_path.rglob(".cx-private-text-*")) == []


def test_filesystem_text_store_maps_publish_failure_and_removes_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemCxPrivateTextStore(tmp_path)

    monkeypatch.setattr(os, "link", lambda source, target: (_ for _ in ()).throw(OSError()))
    with pytest.raises(CxPrivateContentError) as caught:
        store.put_text(
            access_context=_context(),
            key=_key(),
            text="private",
            expected_sha256=sha256_private_text("private"),
        )

    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert list(tmp_path.rglob(".cx-private-text-*")) == []


def test_private_text_store_builder_uses_default_and_override(tmp_path: Path) -> None:
    assert build_private_text_store({}).root == DEFAULT_PRIVATE_TEXT_STORAGE_ROOT
    assert build_private_text_store(
        {"NEX_CX_PRIVATE_TEXT_STORAGE_ROOT": str(tmp_path)}
    ).root == tmp_path.resolve()
    with pytest.raises(CxPrivateContentError) as caught:
        FileSystemCxPrivateTextStore("  ")

    assert caught.value.error_code == "CX_PRIVATE_TEXT_ROOT_INVALID"


def test_private_text_store_file_is_private_and_uri_is_stable(tmp_path: Path) -> None:
    context = _context()
    key = _key(context)
    store = FileSystemCxPrivateTextStore(tmp_path)
    checksum = sha256_private_text("private")
    store.put_text(
        access_context=context,
        key=key,
        text="private",
        expected_sha256=checksum,
    )

    assert store._payload_path(key).stat().st_mode & 0o777 == 0o600
    assert store.storage_uri(key) == store.storage_uri(key)
    assert store.storage_uri(_key(content_id="another")) != store.storage_uri(key)


def test_private_text_store_smoke_evidence(tmp_path: Path) -> None:
    result = smoke.run_private_text_store_smoke(tmp_path / "smoke")

    assert result["status"] == "PASS"
    assert result["checks"] == 8
    assert result["restart_reload"] is True
    assert result["dgx_required"] is False
    assert "private_text" not in json.dumps(result)


def test_private_text_store_smoke_cli_summary(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cx_private_text_store_smoke.py",
            "--summary",
            "--storage-root",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("run_cx_private_text_store_smoke", run_name="__main__")

    output = capsys.readouterr().out
    assert exited.value.code == 0
    assert "cx_private_text_store=pass" in output
    assert "checks=8/8" in output
    assert "dgx_required=False" in output


def test_private_text_store_smoke_cli_json_uses_temporary_root(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["run_cx_private_text_store_smoke.py"])

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("run_cx_private_text_store_smoke", run_name="__main__")

    result = json.loads(capsys.readouterr().out)
    assert exited.value.code == 0
    assert result["status"] == "PASS"
    assert result["checks"] == 8


def test_private_text_store_smoke_main_returns_failure(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_private_text_store_smoke",
        lambda root: {
            "status": "FAIL",
            "checks": 7,
            "checks_total": 8,
            "restart_reload": False,
            "owner_scoped": True,
            "dgx_required": False,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cx_private_text_store_smoke.py", "--summary", "--storage-root", str(tmp_path)],
    )

    assert smoke.main() == 1
    assert "cx_private_text_store=fail" in capsys.readouterr().out
