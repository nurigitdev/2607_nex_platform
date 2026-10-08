from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Protocol, TypeVar

from nex_runtime.object_storage import ObjectMetadata, ObjectStorageError


MIGRATION_READ_MODES = frozenset(
    {"OBJECT_FIRST", "FILESYSTEM_FIRST", "OBJECT_ONLY"}
)
_OWNER_PREFIXES = {
    "nex-cx": "NEX_CX",
    "nex-ae-api": "NEX_AE",
}
_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")


@dataclass(frozen=True)
class ObjectMigrationError(RuntimeError):
    code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ObjectMigrationItem:
    item_id: str
    relative_path: str
    target_key: str
    sha256: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class ObjectMigrationInventory:
    items: tuple[ObjectMigrationItem, ...]
    item_count: int
    total_bytes: int
    inventory_digest: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_storage_migration_inventory.v1",
            "status": "VERIFIED",
            "item_count": self.item_count,
            "total_bytes": self.total_bytes,
            "inventory_digest": self.inventory_digest,
            "source_paths_disclosed": False,
            "target_keys_disclosed": False,
        }


@dataclass(frozen=True)
class ObjectMigrationCopyResult:
    item_count: int
    total_bytes: int
    inventory_digest: str
    target_digest: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_storage_migration_copy.v1",
            "status": "VERIFIED",
            "item_count": self.item_count,
            "total_bytes": self.total_bytes,
            "inventory_digest": self.inventory_digest,
            "target_digest": self.target_digest,
            "source_deleted": False,
            "payloads_disclosed": False,
            "source_paths_disclosed": False,
            "target_keys_disclosed": False,
        }


@dataclass(frozen=True)
class ObjectMigrationDecision:
    requested_read_mode: str
    admitted: bool
    source_retirement_eligible: bool
    reason_codes: tuple[str, ...]

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_storage_migration_decision.v1",
            "requested_read_mode": self.requested_read_mode,
            "admitted": self.admitted,
            "source_retirement_eligible": self.source_retirement_eligible,
            "reason_codes": list(self.reason_codes),
            "source_delete_automatic": False,
        }


class ObjectMigrationTarget(Protocol):
    def put_immutable(
        self,
        *,
        key: str,
        payload: bytes,
        expected_sha256: str,
        content_type: str,
    ) -> ObjectMetadata: ...

    def get_bytes(
        self,
        *,
        key: str,
        expected_sha256: str,
        expected_size_bytes: int,
        max_size_bytes: int,
    ) -> bytes | None: ...


def build_migration_inventory(
    root: str | Path,
    items: Sequence[ObjectMigrationItem],
    *,
    max_item_size_bytes: int = 512 * 1024 * 1024,
) -> ObjectMigrationInventory:
    source_root = _safe_root(root)
    if not items:
        raise _error("MIGRATION_INVENTORY_EMPTY", "Migration inventory is empty.")
    if max_item_size_bytes < 1:
        raise _error(
            "MIGRATION_SIZE_BOUNDARY_INVALID",
            "Migration size boundary is invalid.",
        )

    normalized = tuple(_validate_item(item, max_item_size_bytes) for item in items)
    _assert_unique(normalized)
    for item in normalized:
        _read_verified_source(source_root, item, max_item_size_bytes)
    return ObjectMigrationInventory(
        items=normalized,
        item_count=len(normalized),
        total_bytes=sum(item.size_bytes for item in normalized),
        inventory_digest=_inventory_digest(normalized),
    )


def copy_and_verify_migration(
    root: str | Path,
    inventory: ObjectMigrationInventory,
    target: ObjectMigrationTarget,
    *,
    max_item_size_bytes: int = 512 * 1024 * 1024,
) -> ObjectMigrationCopyResult:
    source_root = _safe_root(root)
    if (
        inventory.item_count != len(inventory.items)
        or inventory.total_bytes != sum(item.size_bytes for item in inventory.items)
        or inventory.inventory_digest != _inventory_digest(inventory.items)
    ):
        raise _error(
            "MIGRATION_INVENTORY_INVALID",
            "Migration inventory integrity validation failed.",
        )

    target_records: list[dict[str, object]] = []
    for item in inventory.items:
        payload = _read_verified_source(source_root, item, max_item_size_bytes)
        try:
            metadata = target.put_immutable(
                key=item.target_key,
                payload=payload,
                expected_sha256=item.sha256,
                content_type=item.content_type,
            )
            downloaded = target.get_bytes(
                key=item.target_key,
                expected_sha256=item.sha256,
                expected_size_bytes=item.size_bytes,
                max_size_bytes=max_item_size_bytes,
            )
        except ObjectMigrationError:
            raise
        except ObjectStorageError as exc:
            raise ObjectMigrationError(
                (
                    "MIGRATION_TARGET_UNAVAILABLE"
                    if exc.retryable
                    else "MIGRATION_TARGET_REJECTED"
                ),
                "Migration target operation failed.",
                exc.retryable,
            ) from exc
        except Exception as exc:
            raise ObjectMigrationError(
                "MIGRATION_TARGET_UNAVAILABLE",
                "Migration target operation failed.",
                True,
            ) from exc
        if downloaded is None:
            raise _error(
                "MIGRATION_TARGET_NOT_VISIBLE",
                "Migrated object was not readable after publication.",
            )
        _verify_target_payload(downloaded, item)
        if (
            metadata.sha256 != item.sha256
            or metadata.size_bytes != item.size_bytes
            or metadata.content_type != item.content_type
            or metadata.server_side_encryption != "AES256"
        ):
            raise _error(
                "MIGRATION_TARGET_METADATA_MISMATCH",
                "Migrated object metadata failed verification.",
            )
        target_records.append(
            {
                "item_id": item.item_id,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "versioned": metadata.version_id is not None,
            }
        )
    return ObjectMigrationCopyResult(
        item_count=inventory.item_count,
        total_bytes=inventory.total_bytes,
        inventory_digest=inventory.inventory_digest,
        target_digest=_digest_json(target_records),
    )


def assess_migration_cutover(
    inventory: ObjectMigrationInventory,
    copied: ObjectMigrationCopyResult | None,
    *,
    requested_read_mode: str,
    rollback_window_elapsed: bool = False,
    purge_decision_recorded: bool = False,
) -> ObjectMigrationDecision:
    mode = _read_mode(requested_read_mode)
    copy_complete = copied is not None and (
        copied.item_count == inventory.item_count
        and copied.total_bytes == inventory.total_bytes
        and copied.inventory_digest == inventory.inventory_digest
    )
    reasons: list[str] = []
    if mode in {"OBJECT_FIRST", "OBJECT_ONLY"} and not copy_complete:
        reasons.append("verified_copy_incomplete")
    if mode == "OBJECT_ONLY" and not rollback_window_elapsed:
        reasons.append("rollback_window_open")
    admitted = not reasons
    retirement_eligible = (
        admitted
        and mode == "OBJECT_ONLY"
        and rollback_window_elapsed
        and purge_decision_recorded
    )
    if admitted and mode == "OBJECT_ONLY" and not purge_decision_recorded:
        reasons.append("purge_decision_missing")
    return ObjectMigrationDecision(
        requested_read_mode=mode,
        admitted=admitted,
        source_retirement_eligible=retirement_eligible,
        reason_codes=tuple(reasons),
    )


def read_with_migration_policy(
    mode: str,
    *,
    object_read: Callable[[], _T | None],
    filesystem_read: Callable[[], _T | None],
) -> _T | None:
    normalized = _read_mode(mode)
    if normalized == "OBJECT_ONLY":
        return object_read()
    readers = (
        (object_read, filesystem_read)
        if normalized == "OBJECT_FIRST"
        else (filesystem_read, object_read)
    )
    first = readers[0]()
    return readers[1]() if first is None else first


def configured_migration_read_mode(
    owner: str,
    environ: Mapping[str, str],
) -> str:
    try:
        prefix = _OWNER_PREFIXES[owner]
    except KeyError as exc:
        raise _error(
            "MIGRATION_OWNER_UNSUPPORTED",
            "Migration owner is not supported.",
        ) from exc
    mode = _read_mode(
        str(environ.get(f"{prefix}_OBJECT_STORAGE_READ_MODE", "OBJECT_ONLY"))
    )
    if mode == "OBJECT_FIRST":
        _require_admission(environ, f"{prefix}_OBJECT_STORAGE_MIGRATION_ADMITTED")
    elif mode == "FILESYSTEM_FIRST":
        _require_admission(environ, f"{prefix}_OBJECT_STORAGE_ROLLBACK_ADMITTED")
    return mode


def migration_items_from_manifest(value: object) -> tuple[ObjectMigrationItem, ...]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "items"}:
        raise _error(
            "MIGRATION_MANIFEST_INVALID",
            "Migration manifest shape is invalid.",
        )
    if value.get("schema_version") != "object_storage_migration_manifest.v1":
        raise _error(
            "MIGRATION_MANIFEST_INVALID",
            "Migration manifest version is invalid.",
        )
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        raise _error(
            "MIGRATION_MANIFEST_INVALID",
            "Migration manifest items are invalid.",
        )
    expected = {
        "item_id",
        "relative_path",
        "target_key",
        "sha256",
        "size_bytes",
        "content_type",
    }
    items: list[ObjectMigrationItem] = []
    for raw in raw_items:
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise _error(
                "MIGRATION_MANIFEST_INVALID",
                "Migration manifest item shape is invalid.",
            )
        items.append(
            ObjectMigrationItem(
                item_id=raw.get("item_id"),
                relative_path=raw.get("relative_path"),
                target_key=raw.get("target_key"),
                sha256=raw.get("sha256"),
                size_bytes=raw.get("size_bytes"),
                content_type=raw.get("content_type"),
            )
        )
    return tuple(items)


def _safe_root(root: str | Path) -> Path:
    raw = Path(str(root).strip()).expanduser()
    if not str(root).strip() or raw.is_symlink() or not raw.is_dir():
        raise _error(
            "MIGRATION_SOURCE_ROOT_INVALID",
            "Migration source root is not a safe directory.",
        )
    return raw.resolve()


def _validate_item(
    item: ObjectMigrationItem,
    max_item_size_bytes: int,
) -> ObjectMigrationItem:
    if not isinstance(item, ObjectMigrationItem):
        raise _error("MIGRATION_ITEM_INVALID", "Migration item is invalid.")
    if not isinstance(item.item_id, str) or _ITEM_ID.fullmatch(item.item_id) is None:
        raise _error("MIGRATION_ITEM_INVALID", "Migration item identifier is invalid.")
    relative = item.relative_path
    if not isinstance(relative, str):
        raise _error("MIGRATION_SOURCE_PATH_INVALID", "Migration source path is invalid.")
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or str(path) != relative
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise _error("MIGRATION_SOURCE_PATH_INVALID", "Migration source path is invalid.")
    if (
        not isinstance(item.target_key, str)
        or not item.target_key.startswith("v1/")
        or ".." in item.target_key
        or "//" in item.target_key
        or len(item.target_key) > 512
    ):
        raise _error("MIGRATION_TARGET_KEY_INVALID", "Migration target key is invalid.")
    if not isinstance(item.sha256, str) or _SHA256.fullmatch(item.sha256) is None:
        raise _error("MIGRATION_DIGEST_INVALID", "Migration digest is invalid.")
    if (
        isinstance(item.size_bytes, bool)
        or not isinstance(item.size_bytes, int)
        or item.size_bytes < 0
        or item.size_bytes > max_item_size_bytes
    ):
        raise _error("MIGRATION_SIZE_INVALID", "Migration item size is invalid.")
    if (
        not isinstance(item.content_type, str)
        or not item.content_type.strip()
        or len(item.content_type.strip()) > 160
        or "\n" in item.content_type
        or "\r" in item.content_type
    ):
        raise _error("MIGRATION_CONTENT_TYPE_INVALID", "Migration content type is invalid.")
    return ObjectMigrationItem(
        item_id=item.item_id,
        relative_path=relative,
        target_key=item.target_key,
        sha256=item.sha256,
        size_bytes=item.size_bytes,
        content_type=item.content_type.strip(),
    )


def _assert_unique(items: Sequence[ObjectMigrationItem]) -> None:
    for values, code in (
        ([item.item_id for item in items], "MIGRATION_ITEM_DUPLICATE"),
        ([item.relative_path for item in items], "MIGRATION_SOURCE_DUPLICATE"),
        ([item.target_key for item in items], "MIGRATION_TARGET_DUPLICATE"),
    ):
        if len(values) != len(set(values)):
            raise _error(code, "Migration inventory contains a duplicate entry.")


def _read_verified_source(
    root: Path,
    item: ObjectMigrationItem,
    max_item_size_bytes: int,
) -> bytes:
    candidate = root.joinpath(*PurePosixPath(item.relative_path).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _error(
            "MIGRATION_SOURCE_UNAVAILABLE",
            "Migration source is unavailable.",
        ) from exc
    if (
        not resolved.is_relative_to(root)
        or candidate.is_symlink()
        or not resolved.is_file()
    ):
        raise _error("MIGRATION_SOURCE_UNSAFE", "Migration source is unsafe.")
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise ObjectMigrationError(
            "MIGRATION_SOURCE_UNAVAILABLE",
            "Migration source is unavailable.",
            True,
        ) from exc
    if len(payload) > max_item_size_bytes:
        raise _error("MIGRATION_SIZE_INVALID", "Migration item size is invalid.")
    _verify_payload(payload, item)
    return payload


def _verify_payload(payload: bytes, item: ObjectMigrationItem) -> None:
    if len(payload) != item.size_bytes:
        raise _error(
            "MIGRATION_SOURCE_SIZE_MISMATCH",
            "Migration source size does not match its inventory.",
        )
    if hashlib.sha256(payload).hexdigest() != item.sha256:
        raise _error(
            "MIGRATION_SOURCE_INTEGRITY_MISMATCH",
            "Migration source digest does not match its inventory.",
        )


def _verify_target_payload(payload: bytes, item: ObjectMigrationItem) -> None:
    if (
        len(payload) != item.size_bytes
        or hashlib.sha256(payload).hexdigest() != item.sha256
    ):
        raise _error(
            "MIGRATION_TARGET_INTEGRITY_MISMATCH",
            "Migrated object failed downloaded integrity verification.",
        )


def _inventory_digest(items: Sequence[ObjectMigrationItem]) -> str:
    return _digest_json(
        [
            {
                "item_id": item.item_id,
                "relative_path": item.relative_path,
                "target_key": item.target_key,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "content_type": item.content_type,
            }
            for item in items
        ]
    )


def _digest_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_mode(value: str) -> str:
    mode = str(value).strip().upper()
    if mode not in MIGRATION_READ_MODES:
        raise _error(
            "MIGRATION_READ_MODE_INVALID",
            "Object-storage migration read mode is invalid.",
        )
    return mode


def _require_admission(environ: Mapping[str, str], name: str) -> None:
    value = str(environ.get(name, "false")).strip().lower()
    if value not in {"true", "false"}:
        raise _error(
            "MIGRATION_ADMISSION_INVALID",
            "Object-storage migration admission flag is invalid.",
        )
    if value != "true":
        raise _error(
            "MIGRATION_ADMISSION_REQUIRED",
            "Object-storage migration or rollback requires explicit admission.",
        )


def _error(code: str, detail: str) -> ObjectMigrationError:
    return ObjectMigrationError(code, detail)
