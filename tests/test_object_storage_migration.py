from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

import run_s146_object_storage_migration as migration_script
from nex_runtime.object_storage import ObjectMetadata, ObjectStorageError
from nex_runtime.object_storage_migration import (
    ObjectMigrationCopyResult,
    ObjectMigrationError,
    ObjectMigrationItem,
    assess_migration_cutover,
    build_migration_inventory,
    configured_migration_read_mode,
    copy_and_verify_migration,
    migration_items_from_manifest,
    read_with_migration_policy,
)
from run_s146_object_storage_migration import run_object_storage_migration


class FakeTarget:
    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.missing_after_put = False
        self.corrupt_after_put = False
        self.unsafe_metadata = False
        self.fail = False

    def put_immutable(self, *, key, payload, expected_sha256, content_type):
        if self.fail:
            raise OSError("offline")
        self.payloads.setdefault(key, payload)
        return ObjectMetadata(
            bucket="private",
            key=key,
            sha256="0" * 64 if self.unsafe_metadata else expected_sha256,
            size_bytes=len(payload),
            content_type=content_type,
            version_id="version-1",
            server_side_encryption="AES256",
        )

    def get_bytes(self, *, key, expected_sha256, expected_size_bytes, max_size_bytes):
        if self.missing_after_put:
            return None
        payload = self.payloads[key]
        return payload + b"x" if self.corrupt_after_put else payload


def _item(payload: bytes = b"private payload") -> ObjectMigrationItem:
    return ObjectMigrationItem(
        item_id="item-1",
        relative_path="owner/payload.txt",
        target_key="v1/text/aa/opaque/payload.utf8",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        content_type="text/plain; charset=utf-8",
    )


def _source(tmp_path: Path, payload: bytes = b"private payload") -> Path:
    root = tmp_path / "source"
    path = root / "owner" / "payload.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    return root


def _manifest(item: ObjectMigrationItem) -> dict[str, object]:
    return {
        "schema_version": "object_storage_migration_manifest.v1",
        "items": [
            {
                "item_id": item.item_id,
                "relative_path": item.relative_path,
                "target_key": item.target_key,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "content_type": item.content_type,
            }
        ],
    }


def test_inventory_copy_and_safe_evidence(tmp_path):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])
    target = FakeTarget()

    copied = copy_and_verify_migration(root, inventory, target)

    assert inventory.item_count == copied.item_count == 1
    assert copied.total_bytes == len(b"private payload")
    assert target.payloads[_item().target_key] == b"private payload"
    evidence = {**inventory.evidence(), **copied.evidence()}
    serialized = json.dumps(evidence)
    assert "payload.txt" not in serialized
    assert _item().target_key not in serialized
    assert evidence["source_deleted"] is False


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"item_id": "bad id"}, "MIGRATION_ITEM_INVALID"),
        ({"relative_path": "../payload"}, "MIGRATION_SOURCE_PATH_INVALID"),
        ({"relative_path": "/payload"}, "MIGRATION_SOURCE_PATH_INVALID"),
        ({"target_key": "unsafe/key"}, "MIGRATION_TARGET_KEY_INVALID"),
        ({"sha256": "bad"}, "MIGRATION_DIGEST_INVALID"),
        ({"size_bytes": True}, "MIGRATION_SIZE_INVALID"),
        ({"size_bytes": -1}, "MIGRATION_SIZE_INVALID"),
        ({"content_type": ""}, "MIGRATION_CONTENT_TYPE_INVALID"),
        ({"content_type": "text/plain\nunsafe"}, "MIGRATION_CONTENT_TYPE_INVALID"),
    ],
)
def test_inventory_rejects_invalid_item_fields(tmp_path, change, code):
    root = _source(tmp_path)
    item = replace(_item(), **change)

    with pytest.raises(ObjectMigrationError) as captured:
        build_migration_inventory(root, [item])

    assert captured.value.code == code


def test_inventory_rejects_empty_invalid_root_and_size_boundary(tmp_path):
    root = _source(tmp_path)
    with pytest.raises(ObjectMigrationError, match="empty") as empty:
        build_migration_inventory(root, [])
    assert empty.value.code == "MIGRATION_INVENTORY_EMPTY"

    with pytest.raises(ObjectMigrationError) as missing:
        build_migration_inventory(tmp_path / "missing", [_item()])
    assert missing.value.code == "MIGRATION_SOURCE_ROOT_INVALID"

    with pytest.raises(ObjectMigrationError) as boundary:
        build_migration_inventory(root, [_item()], max_item_size_bytes=0)
    assert boundary.value.code == "MIGRATION_SIZE_BOUNDARY_INVALID"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("item_id", "MIGRATION_ITEM_DUPLICATE"),
        ("relative_path", "MIGRATION_SOURCE_DUPLICATE"),
        ("target_key", "MIGRATION_TARGET_DUPLICATE"),
    ],
)
def test_inventory_rejects_duplicate_identifiers(tmp_path, field, code):
    root = _source(tmp_path)
    second_payload = b"second"
    second_path = root / "owner" / "second.txt"
    second_path.write_bytes(second_payload)
    second = ObjectMigrationItem(
        item_id="item-2",
        relative_path="owner/second.txt",
        target_key="v1/text/bb/opaque/second.utf8",
        sha256=hashlib.sha256(second_payload).hexdigest(),
        size_bytes=len(second_payload),
        content_type="text/plain",
    )
    second = replace(second, **{field: getattr(_item(), field)})

    with pytest.raises(ObjectMigrationError) as captured:
        build_migration_inventory(root, [_item(), second])

    assert captured.value.code == code


def test_inventory_rejects_source_drift_and_unsafe_links(tmp_path):
    root = _source(tmp_path)
    with pytest.raises(ObjectMigrationError) as digest:
        build_migration_inventory(root, [replace(_item(), sha256="0" * 64)])
    assert digest.value.code == "MIGRATION_SOURCE_INTEGRITY_MISMATCH"

    with pytest.raises(ObjectMigrationError) as size:
        build_migration_inventory(root, [replace(_item(), size_bytes=1)])
    assert size.value.code == "MIGRATION_SOURCE_SIZE_MISMATCH"

    link_root = tmp_path / "link-root"
    link_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(ObjectMigrationError) as root_link:
        build_migration_inventory(link_root, [_item()])
    assert root_link.value.code == "MIGRATION_SOURCE_ROOT_INVALID"

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_bytes(b"private payload")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    linked_item = replace(_item(), relative_path="linked/payload.txt")
    with pytest.raises(ObjectMigrationError) as source_link:
        build_migration_inventory(root, [linked_item])
    assert source_link.value.code == "MIGRATION_SOURCE_UNSAFE"


def test_copy_revalidates_inventory_and_source(tmp_path):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])
    (root / "owner" / "payload.txt").write_bytes(b"changed")
    with pytest.raises(ObjectMigrationError) as changed:
        copy_and_verify_migration(root, inventory, FakeTarget())
    assert changed.value.code == "MIGRATION_SOURCE_SIZE_MISMATCH"

    invalid_inventory = replace(inventory, total_bytes=999)
    with pytest.raises(ObjectMigrationError) as invalid:
        copy_and_verify_migration(root, invalid_inventory, FakeTarget())
    assert invalid.value.code == "MIGRATION_INVENTORY_INVALID"


def test_copy_rejects_missing_unreadable_and_oversized_source(tmp_path, monkeypatch):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])
    path = root / "owner" / "payload.txt"
    path.unlink()
    with pytest.raises(ObjectMigrationError) as missing:
        copy_and_verify_migration(root, inventory, FakeTarget())
    assert missing.value.code == "MIGRATION_SOURCE_UNAVAILABLE"

    path.write_bytes(b"private payload")
    with pytest.raises(ObjectMigrationError) as oversized:
        copy_and_verify_migration(
            root,
            inventory,
            FakeTarget(),
            max_item_size_bytes=1,
        )
    assert oversized.value.code == "MIGRATION_SIZE_INVALID"

    original = Path.read_bytes

    def fail_read(candidate):
        if candidate.name == "payload.txt":
            raise OSError("unreadable")
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(ObjectMigrationError) as unreadable:
        copy_and_verify_migration(root, inventory, FakeTarget())
    assert unreadable.value.code == "MIGRATION_SOURCE_UNAVAILABLE"
    assert unreadable.value.retryable is True


@pytest.mark.parametrize(
    ("flag", "code"),
    [
        ("missing_after_put", "MIGRATION_TARGET_NOT_VISIBLE"),
        ("corrupt_after_put", "MIGRATION_TARGET_INTEGRITY_MISMATCH"),
        ("unsafe_metadata", "MIGRATION_TARGET_METADATA_MISMATCH"),
        ("fail", "MIGRATION_TARGET_UNAVAILABLE"),
    ],
)
def test_copy_fails_closed_when_target_is_not_verified(tmp_path, flag, code):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])
    target = FakeTarget()
    setattr(target, flag, True)

    with pytest.raises(ObjectMigrationError) as captured:
        copy_and_verify_migration(root, inventory, target)

    assert captured.value.code == code


def test_copy_preserves_explicit_migration_target_error(tmp_path):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])

    class ExplicitFailure(FakeTarget):
        def put_immutable(self, **kwargs):
            raise ObjectMigrationError("TARGET_POLICY_REJECTED", "rejected")

    with pytest.raises(ObjectMigrationError) as captured:
        copy_and_verify_migration(root, inventory, ExplicitFailure())
    assert captured.value.code == "TARGET_POLICY_REJECTED"


@pytest.mark.parametrize(
    ("storage_error", "code", "retryable"),
    [
        (
            ObjectStorageError("OBJECT_STORAGE_IMMUTABLE_CONFLICT", "private"),
            "MIGRATION_TARGET_REJECTED",
            False,
        ),
        (
            ObjectStorageError("OBJECT_STORAGE_UNAVAILABLE", "private", retryable=True),
            "MIGRATION_TARGET_UNAVAILABLE",
            True,
        ),
    ],
)
def test_copy_redacts_object_storage_errors(tmp_path, storage_error, code, retryable):
    root = _source(tmp_path)
    inventory = build_migration_inventory(root, [_item()])

    class StorageFailure(FakeTarget):
        def put_immutable(self, **kwargs):
            raise storage_error

    with pytest.raises(ObjectMigrationError) as captured:
        copy_and_verify_migration(root, inventory, StorageFailure())
    assert captured.value.code == code
    assert captured.value.retryable is retryable
    assert "private" not in captured.value.detail


def test_cutover_and_retirement_guards(tmp_path):
    inventory = build_migration_inventory(_source(tmp_path), [_item()])
    copied = ObjectMigrationCopyResult(
        item_count=inventory.item_count,
        total_bytes=inventory.total_bytes,
        inventory_digest=inventory.inventory_digest,
        target_digest="a" * 64,
    )
    dual = assess_migration_cutover(
        inventory,
        copied,
        requested_read_mode="object_first",
    )
    rollback = assess_migration_cutover(
        inventory,
        None,
        requested_read_mode="filesystem_first",
    )
    blocked = assess_migration_cutover(
        inventory,
        copied,
        requested_read_mode="object_only",
    )
    cutover = assess_migration_cutover(
        inventory,
        copied,
        requested_read_mode="object_only",
        rollback_window_elapsed=True,
        purge_decision_recorded=True,
    )

    assert dual.admitted is True
    assert rollback.admitted is True
    assert blocked.admitted is False
    assert blocked.reason_codes == ("rollback_window_open",)
    assert cutover.admitted is True
    assert cutover.source_retirement_eligible is True
    assert cutover.evidence()["source_delete_automatic"] is False


def test_cutover_rejects_incomplete_copy_and_marks_missing_purge(tmp_path):
    inventory = build_migration_inventory(_source(tmp_path), [_item()])
    incomplete = ObjectMigrationCopyResult(0, 0, "bad", "a" * 64)
    blocked = assess_migration_cutover(
        inventory,
        incomplete,
        requested_read_mode="OBJECT_FIRST",
    )
    retained = assess_migration_cutover(
        inventory,
        replace(
            incomplete,
            item_count=inventory.item_count,
            total_bytes=inventory.total_bytes,
            inventory_digest=inventory.inventory_digest,
        ),
        requested_read_mode="OBJECT_ONLY",
        rollback_window_elapsed=True,
    )
    assert blocked.reason_codes == ("verified_copy_incomplete",)
    assert retained.admitted is True
    assert retained.source_retirement_eligible is False
    assert retained.reason_codes == ("purge_decision_missing",)


def test_dual_read_preference_and_fail_closed_error():
    calls: list[str] = []

    def object_missing():
        calls.append("object")
        return None

    def filesystem_value():
        calls.append("filesystem")
        return "legacy"

    assert read_with_migration_policy(
        "OBJECT_FIRST",
        object_read=object_missing,
        filesystem_read=filesystem_value,
    ) == "legacy"
    assert calls == ["object", "filesystem"]
    assert read_with_migration_policy(
        "FILESYSTEM_FIRST",
        object_read=lambda: "object",
        filesystem_read=lambda: "legacy",
    ) == "legacy"
    assert read_with_migration_policy(
        "FILESYSTEM_FIRST",
        object_read=lambda: "object",
        filesystem_read=lambda: None,
    ) == "object"
    assert read_with_migration_policy(
        "OBJECT_ONLY",
        object_read=lambda: "object",
        filesystem_read=lambda: pytest.fail("must not read filesystem"),
    ) == "object"

    with pytest.raises(RuntimeError, match="integrity"):
        read_with_migration_policy(
            "OBJECT_FIRST",
            object_read=lambda: (_ for _ in ()).throw(RuntimeError("integrity")),
            filesystem_read=lambda: "legacy",
        )


def test_read_mode_configuration_requires_explicit_admission():
    assert configured_migration_read_mode("nex-cx", {}) == "OBJECT_ONLY"
    assert configured_migration_read_mode(
        "nex-cx",
        {
            "NEX_CX_OBJECT_STORAGE_READ_MODE": "OBJECT_FIRST",
            "NEX_CX_OBJECT_STORAGE_MIGRATION_ADMITTED": "true",
        },
    ) == "OBJECT_FIRST"
    assert configured_migration_read_mode(
        "nex-ae-api",
        {
            "NEX_AE_OBJECT_STORAGE_READ_MODE": "FILESYSTEM_FIRST",
            "NEX_AE_OBJECT_STORAGE_ROLLBACK_ADMITTED": "true",
        },
    ) == "FILESYSTEM_FIRST"

    with pytest.raises(ObjectMigrationError) as missing:
        configured_migration_read_mode(
            "nex-cx", {"NEX_CX_OBJECT_STORAGE_READ_MODE": "OBJECT_FIRST"}
        )
    assert missing.value.code == "MIGRATION_ADMISSION_REQUIRED"
    with pytest.raises(ObjectMigrationError) as invalid:
        configured_migration_read_mode(
            "nex-cx",
            {
                "NEX_CX_OBJECT_STORAGE_READ_MODE": "FILESYSTEM_FIRST",
                "NEX_CX_OBJECT_STORAGE_ROLLBACK_ADMITTED": "sometimes",
            },
        )
    assert invalid.value.code == "MIGRATION_ADMISSION_INVALID"
    with pytest.raises(ObjectMigrationError) as owner:
        configured_migration_read_mode("nex-unknown", {})
    assert owner.value.code == "MIGRATION_OWNER_UNSUPPORTED"
    with pytest.raises(ObjectMigrationError) as mode:
        configured_migration_read_mode(
            "nex-cx", {"NEX_CX_OBJECT_STORAGE_READ_MODE": "unknown"}
        )
    assert mode.value.code == "MIGRATION_READ_MODE_INVALID"


def test_manifest_and_runner_inventory_and_copy(tmp_path):
    root = _source(tmp_path)
    item = _item()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(item)), encoding="utf-8")
    env = {
        "NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root),
        "NEX_CX_OBJECT_STORAGE_READ_MODE": "OBJECT_FIRST",
        "NEX_CX_OBJECT_STORAGE_MIGRATION_ADMITTED": "true",
    }

    inventory_result = run_object_storage_migration(
        owner="nex-cx",
        manifest_path=manifest_path,
        environ=env,
        inventory_only=True,
    )
    copy_result = run_object_storage_migration(
        owner="nex-cx",
        manifest_path=manifest_path,
        environ=env,
        inventory_only=False,
        target=FakeTarget(),
    )

    assert inventory_result["phase"] == "INVENTORY_VERIFIED"
    assert copy_result["phase"] == "CUTOVER_ADMITTED"
    assert copy_result["source_delete_performed"] is False


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema_version": "wrong", "items": []},
        {"schema_version": "object_storage_migration_manifest.v1", "items": {}},
        {
            "schema_version": "object_storage_migration_manifest.v1",
            "items": [{"item_id": "only"}],
        },
    ],
)
def test_manifest_rejects_invalid_shapes(value):
    with pytest.raises(ObjectMigrationError) as captured:
        migration_items_from_manifest(value)
    assert captured.value.code == "MIGRATION_MANIFEST_INVALID"


def test_inventory_rejects_non_item_and_non_string_path(tmp_path):
    root = _source(tmp_path)
    with pytest.raises(ObjectMigrationError) as item:
        build_migration_inventory(root, [object()])
    assert item.value.code == "MIGRATION_ITEM_INVALID"
    with pytest.raises(ObjectMigrationError) as path:
        build_migration_inventory(root, [replace(_item(), relative_path=None)])
    assert path.value.code == "MIGRATION_SOURCE_PATH_INVALID"


def test_runner_rejects_owner_root_manifest_and_insecure_profile(tmp_path):
    root = _source(tmp_path)
    item = _item()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(item)), encoding="utf-8")

    with pytest.raises(ObjectMigrationError) as owner:
        run_object_storage_migration(
            owner="unknown",
            manifest_path=manifest_path,
            environ={},
            inventory_only=True,
        )
    assert owner.value.code == "MIGRATION_OWNER_UNSUPPORTED"
    with pytest.raises(ObjectMigrationError) as root_missing:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=manifest_path,
            environ={},
            inventory_only=True,
        )
    assert root_missing.value.code == "MIGRATION_SOURCE_ROOT_REQUIRED"

    link = tmp_path / "manifest-link.json"
    link.symlink_to(manifest_path)
    with pytest.raises(ObjectMigrationError) as manifest:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=link,
            environ={"NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root)},
            inventory_only=True,
        )
    assert manifest.value.code == "MIGRATION_MANIFEST_UNAVAILABLE"

    env = {
        "NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root),
        "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
        "NEX_RUNTIME_PROFILE": "production",
    }
    with pytest.raises(ObjectMigrationError) as insecure:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=manifest_path,
            environ=env,
            inventory_only=False,
        )
    assert insecure.value.code == "MIGRATION_INSECURE_ENDPOINT_FORBIDDEN"


def test_runner_rejects_invalid_manifest_json_and_insecure_flag(tmp_path):
    root = _source(tmp_path)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    env = {"NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root)}
    with pytest.raises(ObjectMigrationError) as manifest:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=invalid,
            environ=env,
            inventory_only=True,
        )
    assert manifest.value.code == "MIGRATION_MANIFEST_INVALID"

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(_item())), encoding="utf-8")
    env.update(
        {
            "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "sometimes",
            "NEX_RUNTIME_PROFILE": "test",
        }
    )
    with pytest.raises(ObjectMigrationError) as flag:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=manifest_path,
            environ=env,
            inventory_only=False,
        )
    assert flag.value.code == "MIGRATION_CONFIGURATION_INVALID"


def test_runner_uses_secure_endpoint_by_default():
    assert migration_script._allow_insecure("nex-cx", {}) is False


def test_runner_redacts_target_configuration_and_client_failures(
    tmp_path, monkeypatch
):
    root = _source(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(_item())), encoding="utf-8")
    env = {"NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root)}
    with pytest.raises(ObjectMigrationError) as configuration:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=manifest_path,
            environ=env,
            inventory_only=False,
        )
    assert configuration.value.code == "MIGRATION_TARGET_CONFIGURATION_INVALID"

    monkeypatch.setattr(
        migration_script,
        "object_storage_settings",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        migration_script,
        "build_s3_client",
        lambda settings: (_ for _ in ()).throw(ImportError("private")),
    )
    with pytest.raises(ObjectMigrationError) as client:
        run_object_storage_migration(
            owner="nex-cx",
            manifest_path=manifest_path,
            environ=env,
            inventory_only=False,
        )
    assert client.value.code == "MIGRATION_TARGET_UNAVAILABLE"
    assert client.value.retryable is True


def test_runner_builds_target_and_can_return_blocked(tmp_path, monkeypatch):
    root = _source(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(_item())), encoding="utf-8")
    target = FakeTarget()
    settings = object()
    monkeypatch.setattr(migration_script, "object_storage_settings", lambda *a, **k: settings)
    monkeypatch.setattr(migration_script, "build_s3_client", lambda value: target)
    monkeypatch.setattr(migration_script, "S3ObjectStore", lambda client, value: client)
    env = {
        "NEX_CX_OBJECT_STORAGE_MIGRATION_ROOT": str(root),
        "NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE": "true",
        "NEX_RUNTIME_PROFILE": "test",
    }

    result = run_object_storage_migration(
        owner="nex-cx",
        manifest_path=manifest_path,
        environ=env,
        inventory_only=False,
    )

    assert result["status"] == "BLOCKED"
    assert result["phase"] == "COPY_VERIFIED"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"status": "PASS"}, 0),
        ({"status": "BLOCKED"}, 2),
    ],
)
def test_cli_main_returns_result_status(monkeypatch, capsys, result, expected):
    monkeypatch.setattr(
        migration_script,
        "run_object_storage_migration",
        lambda **kwargs: result,
    )
    status = migration_script.main(
        ["--owner", "nex-cx", "--manifest", "runtime.json"]
    )
    assert status == expected
    assert json.loads(capsys.readouterr().out)["status"] == result["status"]


def test_cli_main_redacts_migration_error(monkeypatch, capsys):
    def fail(**kwargs):
        raise ObjectMigrationError("MIGRATION_FAILED", "private/path")

    monkeypatch.setattr(migration_script, "run_object_storage_migration", fail)
    status = migration_script.main(
        ["--owner", "nex-cx", "--manifest", "runtime.json"]
    )
    output = json.loads(capsys.readouterr().out)
    assert status == 1
    assert output["error_code"] == "MIGRATION_FAILED"
    assert "private/path" not in json.dumps(output)
