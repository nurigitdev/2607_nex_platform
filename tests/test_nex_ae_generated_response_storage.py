from __future__ import annotations

from pathlib import Path

import pytest

from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    InMemoryGeneratedResponseStorage,
    LocalGeneratedResponseStorage,
    build_default_generated_response_storage,
    build_generated_response_payload,
    build_generated_response_storage_ref,
    generated_response_storage_metadata,
    validate_generated_response_payload,
)


def _payload(content: str = "Owner-private generated answer [1].") -> dict:
    return build_generated_response_payload(
        response_id="response-001",
        content=content,
        content_type="text/markdown; charset=utf-8",
    )


def test_build_payload_and_metadata_are_deterministic() -> None:
    payload = _payload()
    metadata = generated_response_storage_metadata(payload)

    assert payload["response_id"] == "response-001"
    assert payload["size_bytes"] == len(payload["content"].encode("utf-8"))
    assert payload["storage_ref"].startswith("ae://chat-responses/")
    assert payload["storage_ref"].endswith("/response-001.txt")
    assert metadata == {
        key: value for key, value in payload.items() if key != "content"
    }
    assert validate_generated_response_payload(
        metadata,
        require_content=False,
    ) == metadata


def test_payload_validation_rejects_invalid_shapes_and_values() -> None:
    payload = _payload()
    invalid_values = (
        None,
        {**payload, "extra": True},
        {**payload, "response_id": "../escape"},
        {**payload, "content_type": "application/json"},
        {**payload, "content_sha256": "bad"},
        {**payload, "size_bytes": True},
        {**payload, "size_bytes": -1},
        {**payload, "storage_ref": "ae://chat-responses/aa/bb/other.txt"},
        {**payload, "content": 7},
        {**payload, "content": payload["content"] + "tampered"},
    )

    for invalid in invalid_values:
        with pytest.raises(GeneratedResponseStorageError) as exc_info:
            validate_generated_response_payload(invalid, require_content=True)
        assert exc_info.value.error_code.startswith("ae.generated_response_")

    with pytest.raises(GeneratedResponseStorageError):
        build_generated_response_payload(response_id="ok", content=object())
    with pytest.raises(GeneratedResponseStorageError):
        build_generated_response_storage_ref("ok", "bad")


def test_in_memory_storage_round_trip_integrity_and_delete() -> None:
    storage = InMemoryGeneratedResponseStorage()
    payload = _payload()
    metadata = generated_response_storage_metadata(payload)

    assert storage.save(payload) == payload["storage_ref"]
    assert storage.save(payload) == payload["storage_ref"]
    assert storage.load(metadata) == payload["content"]
    storage.payloads[payload["storage_ref"]] = b"tampered"
    with pytest.raises(GeneratedResponseStorageError) as exc_info:
        storage.load(metadata)
    assert exc_info.value.error_code == "ae.generated_response_integrity_failed"
    storage.payloads[payload["storage_ref"]] = b"\xff"
    with pytest.raises(GeneratedResponseStorageError):
        storage.load(metadata)
    assert storage.delete(metadata) is True
    assert storage.delete(metadata) is False
    assert storage.load(metadata) is None


def test_local_storage_round_trip_permissions_integrity_and_delete(
    tmp_path: Path,
) -> None:
    storage = LocalGeneratedResponseStorage(tmp_path / "responses")
    payload = _payload("Unicode response: \ud55c\uae00 [1].")
    metadata = generated_response_storage_metadata(payload)

    assert storage.save(payload) == payload["storage_ref"]
    path = storage.path_for_storage_ref(payload["storage_ref"])
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert storage.load(metadata) == payload["content"]
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(GeneratedResponseStorageError) as exc_info:
        storage.load(metadata)
    assert exc_info.value.error_code == "ae.generated_response_integrity_failed"
    assert storage.delete(metadata) is True
    assert storage.delete(metadata) is False
    assert storage.load(metadata) is None


def test_local_storage_rejects_invalid_refs_and_wraps_io_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage = LocalGeneratedResponseStorage(tmp_path)
    payload = _payload()
    metadata = generated_response_storage_metadata(payload)
    invalid_refs = (
        "file:///tmp/response.txt",
        "ae://chat-responses/../bb/response.txt",
        "ae://chat-responses/aa/bb/not/a/file.txt",
        "ae://chat-responses/aa/bb/.txt",
    )
    for storage_ref in invalid_refs:
        with pytest.raises(GeneratedResponseStorageError):
            storage.path_for_storage_ref(storage_ref)

    monkeypatch.setattr(
        "tempfile.NamedTemporaryFile",
        lambda **_: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(GeneratedResponseStorageError) as exc_info:
        storage.save(payload)
    assert exc_info.value.retryable is True

    path = storage.path_for_storage_ref(metadata["storage_ref"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload["content"], encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(GeneratedResponseStorageError):
        storage.load(metadata)
    monkeypatch.undo()
    monkeypatch.setattr(
        Path,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(GeneratedResponseStorageError):
        storage.delete(metadata)


def test_local_storage_cleans_temp_file_and_blocks_symlink_escape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "responses"
    storage = LocalGeneratedResponseStorage(root)
    payload = _payload()
    monkeypatch.setattr(
        "os.replace",
        lambda *_: (_ for _ in ()).throw(OSError()),
    )

    with pytest.raises(GeneratedResponseStorageError):
        storage.save(payload)
    assert list(root.rglob("*.tmp")) == []

    monkeypatch.undo()
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "aa").symlink_to(outside, target_is_directory=True)
    with pytest.raises(GeneratedResponseStorageError) as exc_info:
        storage.path_for_storage_ref(
            "ae://chat-responses/aa/bb/response-001.txt"
        )
    assert exc_info.value.error_code == "ae.generated_response_storage_invalid"


def test_default_storage_selects_memory_or_local(tmp_path: Path) -> None:
    assert isinstance(
        build_default_generated_response_storage({}),
        InMemoryGeneratedResponseStorage,
    )
    assert isinstance(
        build_default_generated_response_storage(
            {"NEX_AE_CHAT_RESPONSE_STORAGE_ROOT": "  "}
        ),
        InMemoryGeneratedResponseStorage,
    )
    local = build_default_generated_response_storage(
        {"NEX_AE_CHAT_RESPONSE_STORAGE_ROOT": str(tmp_path)}
    )
    assert isinstance(local, LocalGeneratedResponseStorage)
    assert local.root == tmp_path


def test_storage_error_string_is_safe() -> None:
    error = GeneratedResponseStorageError("code", "safe detail", True)
    assert str(error) == "safe detail"
