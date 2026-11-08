from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .voucher_attachment_manifest import build_attachment_manifest

ATTACHMENT_BATCH_SCHEMA_VERSION = "ae_voucher_attachment_batch.v1"
MAX_ATTACHMENT_COUNT = 20
MAX_ATTACHMENT_FILE_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_BATCH_BYTES = 100 * 1024 * 1024
ALLOWED_ATTACHMENT_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/zip",
        "application/x-zip-compressed",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/x-hwp",
        "application/vnd.hancom.hwp",
    }
)
_BATCH_STATES = frozenset(
    {"DRAFT", "UPLOADING", "READY", "QUARANTINED", "FAILED", "LOCKED", "ABANDONED"}
)
_ITEM_STATES = frozenset(
    {"UPLOADING", "READY", "QUARANTINED", "FAILED", "LOCKED", "REMOVED"}
)
_SCAN_STATES = frozenset({"PENDING", "CLEAN", "REJECTED", "UNAVAILABLE"})
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,127}$")
_SAFE_NAME = re.compile(r"^[^/\\]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,255}$")


@dataclass(frozen=True)
class VoucherAttachmentPersistenceError(RuntimeError):
    error_code: str
    detail: str
    status_code: int
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyVoucherAttachmentRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_batch(self, value: Mapping[str, Any]) -> dict[str, Any]:
        batch = _batch_input(value)
        now = _aware_time(self._clock())
        params = {
            **batch,
            "state": "DRAFT",
            "attachment_count": 0,
            "total_size_bytes": 0,
            "attachment_manifest_hash": None,
            "locked_at": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self._session_factory() as session:
                session.execute(text(_INSERT_BATCH_SQL), params)
                saved = _load_batch(
                    session,
                    tenant_id=batch["tenant_id"],
                    attachment_batch_id=batch["attachment_batch_id"],
                )
                if saved is None:
                    raise _unavailable()
                _require_same_batch(saved, params)
                session.commit()
                return saved
        except VoucherAttachmentPersistenceError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Voucher attachment batch identity conflicts with persisted data."
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def register_item(self, value: Mapping[str, Any]) -> dict[str, Any]:
        item = _item_input(value)
        now = _aware_time(self._clock())
        params = {
            **item,
            "state": "UPLOADING",
            "content_sha256": None,
            "object_ref": None,
            "object_version_ref": None,
            "scan_status": "PENDING",
            "evidence_ref": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=item["tenant_id"],
                    attachment_batch_id=item["attachment_batch_id"],
                    for_update=True,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                if batch["state"] in {"LOCKED", "ABANDONED"}:
                    raise _conflict("Voucher attachment batch is immutable.")
                existing = _load_item(
                    session,
                    tenant_id=item["tenant_id"],
                    attachment_batch_id=item["attachment_batch_id"],
                    attachment_id=item["attachment_id"],
                )
                if existing is not None:
                    _require_same_item(existing, params)
                    session.commit()
                    return existing
                next_count = int(batch["attachment_count"]) + 1
                next_size = int(batch["total_size_bytes"]) + item["size_bytes"]
                if next_count > MAX_ATTACHMENT_COUNT:
                    raise _limit("Voucher attachment count exceeds the batch limit.")
                if next_size > MAX_ATTACHMENT_BATCH_BYTES:
                    raise _limit("Voucher attachment bytes exceed the batch limit.")
                session.execute(text(_INSERT_ITEM_SQL), params)
                updated = session.execute(
                    text(_UPDATE_BATCH_TOTALS_SQL),
                    {
                        "tenant_id": item["tenant_id"],
                        "attachment_batch_id": item["attachment_batch_id"],
                        "attachment_count": next_count,
                        "total_size_bytes": next_size,
                        "updated_at": now,
                    },
                )
                if updated.rowcount != 1:
                    raise _conflict("Voucher attachment batch changed concurrently.")
                saved = _load_item(
                    session,
                    tenant_id=item["tenant_id"],
                    attachment_batch_id=item["attachment_batch_id"],
                    attachment_id=item["attachment_id"],
                )
                if saved is None:
                    raise _unavailable()
                session.commit()
                return saved
        except VoucherAttachmentPersistenceError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Voucher attachment item conflicts with persisted data."
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_batch(
        self, *, tenant_id: str, attachment_batch_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        attachment_batch_id = _uuid("attachment_batch_id", attachment_batch_id)
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=tenant_id,
                    attachment_batch_id=attachment_batch_id,
                )
                if batch is None:
                    return None
                batch["items"] = _list_items(
                    session,
                    tenant_id=tenant_id,
                    attachment_batch_id=attachment_batch_id,
                )
                return batch
        except VoucherAttachmentPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def publish_item(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
        content_sha256: str,
        object_ref: str,
        object_version_ref: str | None,
        scan_status: str = "CLEAN",
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "attachment_batch_id": _uuid("attachment_batch_id", attachment_batch_id),
            "attachment_id": _uuid("attachment_id", attachment_id),
            "content_sha256": _sha256(content_sha256),
            "object_ref": _object_ref(object_ref),
            "object_version_ref": _optional_scoped_id(
                "object_version_ref", object_version_ref
            ),
            "scan_status": _scan_status(scan_status),
            "evidence_ref": _optional_scoped_id("evidence_ref", evidence_ref),
            "updated_at": _aware_time(self._clock()),
        }
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    for_update=True,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                if batch["state"] in {"LOCKED", "ABANDONED"}:
                    raise _conflict("Voucher attachment batch is immutable.")
                item = _load_item(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    attachment_id=params["attachment_id"],
                    for_update=True,
                )
                if item is None:
                    raise _not_found("Voucher attachment item was not found.")
                if item["state"] in {"READY", "LOCKED"}:
                    _require_same_publication(item, params)
                    session.commit()
                    return item
                if item["state"] not in {"UPLOADING", "FAILED"}:
                    raise _conflict("Voucher attachment item cannot be published.")
                updated = session.execute(text(_PUBLISH_ITEM_SQL), params)
                if updated.rowcount != 1:
                    raise _conflict("Voucher attachment item changed concurrently.")
                saved = _load_item(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    attachment_id=params["attachment_id"],
                )
                if saved is None:
                    raise _unavailable()
                session.commit()
                return saved
        except VoucherAttachmentPersistenceError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Voucher attachment object reference conflicts with persisted data."
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def resolve_object_ref(
        self, *, tenant_id: str, object_ref: str
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "object_ref": _object_ref(object_ref),
        }
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(text(_RESOLVE_OBJECT_REF_SQL), params)
                    .mappings()
                    .first()
                )
                return None if row is None else _resolved_record(row)
        except VoucherAttachmentPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def remove_item(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "attachment_batch_id": _uuid("attachment_batch_id", attachment_batch_id),
            "attachment_id": _uuid("attachment_id", attachment_id),
            "updated_at": _aware_time(self._clock()),
        }
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    for_update=True,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                if batch["state"] in {"LOCKED", "ABANDONED"}:
                    raise _conflict("Voucher attachment batch is immutable.")
                item = _load_item(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    attachment_id=params["attachment_id"],
                    for_update=True,
                )
                if item is None:
                    raise _not_found("Voucher attachment item was not found.")
                if item["state"] == "LOCKED":
                    raise _conflict("Voucher attachment item is immutable.")
                if item["state"] == "REMOVED":
                    session.commit()
                    return item
                next_count = max(0, int(batch["attachment_count"]) - 1)
                next_size = max(
                    0, int(batch["total_size_bytes"]) - int(item["size_bytes"])
                )
                updated = session.execute(text(_REMOVE_ITEM_SQL), params)
                if updated.rowcount != 1:
                    raise _conflict("Voucher attachment item changed concurrently.")
                batch_update = session.execute(
                    text(_UPDATE_BATCH_AFTER_REMOVAL_SQL),
                    {
                        **params,
                        "attachment_count": next_count,
                        "total_size_bytes": next_size,
                        "state": "DRAFT" if next_count == 0 else "UPLOADING",
                    },
                )
                if batch_update.rowcount != 1:
                    raise _conflict("Voucher attachment batch changed concurrently.")
                saved = _load_item(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    attachment_id=params["attachment_id"],
                )
                if saved is None:
                    raise _unavailable()
                session.commit()
                return saved
        except VoucherAttachmentPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def finalize_batch(
        self, *, tenant_id: str, attachment_batch_id: str
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "attachment_batch_id": _uuid("attachment_batch_id", attachment_batch_id),
            "updated_at": _aware_time(self._clock()),
        }
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    for_update=True,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                if batch["state"] in {"LOCKED", "ABANDONED"}:
                    raise _conflict("Voucher attachment batch is immutable.")
                items = _list_items(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                )
                active = [item for item in items if item["state"] != "REMOVED"]
                if any(item["state"] != "READY" for item in active):
                    raise _conflict(
                        "Voucher attachment batch contains incomplete items."
                    )
                if (
                    len(active) != batch["attachment_count"]
                    or sum(int(item["size_bytes"]) for item in active)
                    != batch["total_size_bytes"]
                ):
                    raise _integrity()
                if batch["state"] != "READY":
                    updated = session.execute(text(_FINALIZE_BATCH_SQL), params)
                    if updated.rowcount != 1:
                        raise _conflict(
                            "Voucher attachment batch changed concurrently."
                        )
                saved = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                )
                if saved is None:
                    raise _unavailable()
                saved["items"] = items
                session.commit()
                return saved
        except VoucherAttachmentPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def lock_manifest(
        self, *, tenant_id: str, attachment_batch_id: str
    ) -> dict[str, Any]:
        params = {
            "tenant_id": _scoped_id("tenant_id", tenant_id),
            "attachment_batch_id": _uuid("attachment_batch_id", attachment_batch_id),
            "locked_at": _aware_time(self._clock()),
        }
        try:
            with self._session_factory() as session:
                batch = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                    for_update=True,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                items = _list_items(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                )
                batch["items"] = items
                if batch["state"] == "LOCKED":
                    session.commit()
                    return build_attachment_manifest(batch)
                if batch["state"] != "READY":
                    raise _conflict(
                        "Voucher attachment batch must be READY before approval lock."
                    )
                manifest = build_attachment_manifest(batch)
                updated = session.execute(
                    text(_LOCK_BATCH_SQL),
                    {
                        **params,
                        "attachment_manifest_hash": manifest[
                            "attachment_manifest_hash"
                        ],
                    },
                )
                if updated.rowcount != 1:
                    raise _conflict("Voucher attachment batch changed concurrently.")
                locked_items = session.execute(text(_LOCK_ITEMS_SQL), params)
                if locked_items.rowcount != batch["attachment_count"]:
                    raise _integrity()
                saved = _load_batch(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                )
                if saved is None:
                    raise _unavailable()
                saved["items"] = _list_items(
                    session,
                    tenant_id=params["tenant_id"],
                    attachment_batch_id=params["attachment_batch_id"],
                )
                locked = build_attachment_manifest(saved)
                session.commit()
                return locked
        except VoucherAttachmentPersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _batch_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Voucher attachment batch must be an object.")
    trace = value.get("trace")
    owner = value.get("owner_subject_ref")
    if not isinstance(trace, Mapping) or set(trace) != {
        "trace_id",
        "correlation_id",
        "causation_id",
    }:
        raise _invalid("Voucher attachment batch trace is invalid.")
    if not isinstance(owner, Mapping) or set(owner) != {"type", "id"}:
        raise _invalid("Voucher attachment owner is invalid.")
    if owner.get("type") != "oa.user":
        raise _invalid("Voucher attachment owner must be an OA user.")
    if value.get("schema_version") != ATTACHMENT_BATCH_SCHEMA_VERSION:
        raise _invalid("Voucher attachment batch schema is invalid.")
    return {
        "tenant_id": _scoped_id("tenant_id", value.get("tenant_id")),
        "attachment_batch_id": _uuid(
            "attachment_batch_id", value.get("attachment_batch_id")
        ),
        "owner_subject_id": _scoped_id("owner_subject_id", owner.get("id")),
        "conversation_id": _uuid("conversation_id", value.get("conversation_id")),
        "interaction_id": _uuid("interaction_id", value.get("interaction_id")),
        "trace_id": _scoped_id("trace_id", trace.get("trace_id")),
        "correlation_id": _scoped_id("correlation_id", trace.get("correlation_id")),
        "causation_id": _scoped_id("causation_id", trace.get("causation_id")),
    }


def _item_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Voucher attachment item must be an object.")
    size = value.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int):
        raise _invalid("Voucher attachment size is invalid.")
    if not 1 <= size <= MAX_ATTACHMENT_FILE_BYTES:
        raise _limit("Voucher attachment size exceeds the file limit.")
    name = str(value.get("display_name") or "")
    if not 1 <= len(name) <= 255 or _SAFE_NAME.fullmatch(name) is None:
        raise _invalid("Voucher attachment display name is invalid.")
    media_type = str(value.get("media_type") or "")
    if (
        _MEDIA_TYPE.fullmatch(media_type) is None
        or media_type not in ALLOWED_ATTACHMENT_MEDIA_TYPES
    ):
        raise _invalid("Voucher attachment media type is invalid.")
    return {
        "tenant_id": _scoped_id("tenant_id", value.get("tenant_id")),
        "attachment_batch_id": _uuid(
            "attachment_batch_id", value.get("attachment_batch_id")
        ),
        "attachment_id": _uuid("attachment_id", value.get("attachment_id")),
        "display_name": name,
        "media_type": media_type,
        "size_bytes": size,
    }


def _load_batch(
    session: Session,
    *,
    tenant_id: str,
    attachment_batch_id: str,
    for_update: bool = False,
) -> dict[str, Any] | None:
    statement = _SELECT_BATCH_SQL
    if for_update and session.get_bind().dialect.name == "postgresql":
        statement += " FOR UPDATE"
    row = (
        session.execute(
            text(statement),
            {"tenant_id": tenant_id, "attachment_batch_id": attachment_batch_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _batch_record(row)


def _load_item(
    session: Session,
    *,
    tenant_id: str,
    attachment_batch_id: str,
    attachment_id: str,
    for_update: bool = False,
) -> dict[str, Any] | None:
    statement = _SELECT_ITEM_SQL
    if for_update and session.get_bind().dialect.name == "postgresql":
        statement += " FOR UPDATE"
    row = (
        session.execute(
            text(statement),
            {
                "tenant_id": tenant_id,
                "attachment_batch_id": attachment_batch_id,
                "attachment_id": attachment_id,
            },
        )
        .mappings()
        .first()
    )
    return None if row is None else _item_record(row)


def _list_items(
    session: Session, *, tenant_id: str, attachment_batch_id: str
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(_LIST_ITEMS_SQL),
            {"tenant_id": tenant_id, "attachment_batch_id": attachment_batch_id},
        )
        .mappings()
        .all()
    )
    return [_item_record(row) for row in rows]


def _batch_record(row: Mapping[str, Any]) -> dict[str, Any]:
    state = str(row["state"])
    if state not in _BATCH_STATES:
        raise _integrity()
    return {
        "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
        "attachment_batch_id": str(row["attachment_batch_id"]),
        "tenant_id": str(row["tenant_id"]),
        "owner_subject_ref": {"type": "oa.user", "id": str(row["owner_subject_id"])},
        "conversation_id": str(row["conversation_id"]),
        "interaction_id": str(row["interaction_id"]),
        "state": state,
        "attachment_count": int(row["attachment_count"]),
        "total_size_bytes": int(row["total_size_bytes"]),
        "attachment_manifest_hash": row["attachment_manifest_hash"],
        "locked_at": _wire_time(row["locked_at"]),
        "created_at": _wire_time(row["created_at"]),
        "updated_at": _wire_time(row["updated_at"]),
        "trace": {
            "trace_id": str(row["trace_id"]),
            "correlation_id": str(row["correlation_id"]),
            "causation_id": str(row["causation_id"]),
        },
    }


def _item_record(row: Mapping[str, Any]) -> dict[str, Any]:
    state = str(row["state"])
    scan_status = str(row["scan_status"])
    if state not in _ITEM_STATES or scan_status not in _SCAN_STATES:
        raise _integrity()
    return {
        "attachment_id": str(row["attachment_id"]),
        "state": state,
        "display_name": str(row["display_name"]),
        "media_type": str(row["media_type"]),
        "size_bytes": int(row["size_bytes"]),
        "content_sha256": row["content_sha256"],
        "object_ref": row["object_ref"],
        "object_version_ref": row["object_version_ref"],
        "scan_status": scan_status,
        "evidence_ref": row["evidence_ref"],
        "created_at": _wire_time(row["created_at"]),
        "updated_at": _wire_time(row["updated_at"]),
    }


def _require_same_batch(saved: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    checks = {
        "tenant_id": expected["tenant_id"],
        "attachment_batch_id": expected["attachment_batch_id"],
        "owner_subject_ref": {"type": "oa.user", "id": expected["owner_subject_id"]},
        "conversation_id": expected["conversation_id"],
        "interaction_id": expected["interaction_id"],
        "trace": {
            "trace_id": expected["trace_id"],
            "correlation_id": expected["correlation_id"],
            "causation_id": expected["causation_id"],
        },
    }
    if any(saved.get(name) != value for name, value in checks.items()):
        raise _conflict(
            "Voucher attachment batch identity conflicts with persisted data."
        )


def _require_same_item(saved: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for name in ("attachment_id", "display_name", "media_type", "size_bytes"):
        if saved.get(name) != expected.get(name):
            raise _conflict("Voucher attachment item conflicts with persisted data.")


def _require_same_publication(
    saved: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    for name in (
        "content_sha256",
        "object_ref",
        "object_version_ref",
        "scan_status",
        "evidence_ref",
    ):
        if saved.get(name) != expected.get(name):
            raise _conflict(
                "Voucher attachment publication conflicts with persisted data."
            )


def _scoped_id(name: str, value: object) -> str:
    normalized = str(value or "")
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"Voucher attachment {name} is invalid.")
    return normalized


def _uuid(name: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"Voucher attachment {name} is invalid.") from exc


def _sha256(value: object) -> str:
    normalized = str(value or "")
    if _SHA256.fullmatch(normalized) is None:
        raise _invalid("Voucher attachment content_sha256 is invalid.")
    return normalized


def _object_ref(value: object) -> str:
    normalized = str(value or "")
    if _OPAQUE_REF.fullmatch(normalized) is None or "://" in normalized:
        raise _invalid("Voucher attachment object_ref is invalid.")
    return normalized


def _optional_scoped_id(name: str, value: object) -> str | None:
    return None if value is None else _scoped_id(name, value)


def _scan_status(value: object) -> str:
    normalized = str(value or "")
    if normalized not in {"CLEAN", "REJECTED", "UNAVAILABLE"}:
        raise _invalid("Voucher attachment scan_status is invalid.")
    return normalized


def _resolved_record(row: Mapping[str, Any]) -> dict[str, Any]:
    item = _item_record(row)
    if item["state"] not in {"READY", "LOCKED"}:
        raise _integrity()
    return {
        **item,
        "tenant_id": str(row["tenant_id"]),
        "attachment_batch_id": str(row["attachment_batch_id"]),
        "owner_subject_id": str(row["owner_subject_id"]),
        "batch_state": str(row["batch_state"]),
        "attachment_manifest_hash": row["attachment_manifest_hash"],
    }


def _aware_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("Voucher attachment timestamp must be timezone-aware.")
    return value.astimezone(UTC)


def _wire_time(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = _aware_time(value)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise _integrity() from exc
        parsed = _aware_time(parsed)
    return parsed.isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.invalid", detail, 422
    )


def _limit(detail: str) -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.limit_exceeded", detail, 413
    )


def _conflict(detail: str) -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.conflict", detail, 409
    )


def _not_found(detail: str) -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.not_found", detail, 404
    )


def _integrity() -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.integrity_failed",
        "Persisted Voucher attachment data failed integrity validation.",
        500,
    )


def _unavailable() -> VoucherAttachmentPersistenceError:
    return VoucherAttachmentPersistenceError(
        "ae.voucher_attachment.persistence_unavailable",
        "Voucher attachment persistence is unavailable.",
        503,
        True,
    )


_INSERT_BATCH_SQL = """
INSERT INTO ae_voucher_attach_batch (
    tenant_id, attachment_batch_id, owner_subject_id,
    conversation_id, interaction_id, state,
    attachment_count, total_size_bytes, attachment_manifest_hash, locked_at,
    trace_id, correlation_id, causation_id, created_at, updated_at
) VALUES (
    :tenant_id, :attachment_batch_id, :owner_subject_id,
    :conversation_id, :interaction_id, :state,
    :attachment_count, :total_size_bytes, :attachment_manifest_hash, :locked_at,
    :trace_id, :correlation_id, :causation_id, :created_at, :updated_at
) ON CONFLICT (tenant_id, attachment_batch_id) DO NOTHING
"""

_SELECT_BATCH_SQL = """
SELECT tenant_id, attachment_batch_id, owner_subject_id,
       conversation_id, interaction_id, state,
       attachment_count, total_size_bytes, attachment_manifest_hash, locked_at,
       trace_id, correlation_id, causation_id, created_at, updated_at
FROM ae_voucher_attach_batch
WHERE tenant_id = :tenant_id AND attachment_batch_id = :attachment_batch_id
"""

_INSERT_ITEM_SQL = """
INSERT INTO ae_voucher_attachment (
    tenant_id, attachment_batch_id, attachment_id, state,
    display_name, media_type, size_bytes, content_sha256,
    object_ref, object_version_ref, scan_status, evidence_ref,
    created_at, updated_at
) VALUES (
    :tenant_id, :attachment_batch_id, :attachment_id, :state,
    :display_name, :media_type, :size_bytes, :content_sha256,
    :object_ref, :object_version_ref, :scan_status, :evidence_ref,
    :created_at, :updated_at
) ON CONFLICT (tenant_id, attachment_batch_id, attachment_id) DO NOTHING
"""

_SELECT_ITEM_SQL = """
SELECT attachment_id, state, display_name, media_type, size_bytes,
       content_sha256, object_ref, object_version_ref, scan_status,
       evidence_ref, created_at, updated_at
FROM ae_voucher_attachment
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND attachment_id = :attachment_id
"""

_LIST_ITEMS_SQL = """
SELECT attachment_id, state, display_name, media_type, size_bytes,
       content_sha256, object_ref, object_version_ref, scan_status,
       evidence_ref, created_at, updated_at
FROM ae_voucher_attachment
WHERE tenant_id = :tenant_id AND attachment_batch_id = :attachment_batch_id
ORDER BY attachment_id
"""

_UPDATE_BATCH_TOTALS_SQL = """
UPDATE ae_voucher_attach_batch
SET state = 'UPLOADING',
    attachment_count = :attachment_count,
    total_size_bytes = :total_size_bytes,
    updated_at = :updated_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND state IN ('DRAFT', 'UPLOADING', 'READY', 'QUARANTINED', 'FAILED')
"""

_PUBLISH_ITEM_SQL = """
UPDATE ae_voucher_attachment
SET state = 'READY',
    content_sha256 = :content_sha256,
    object_ref = :object_ref,
    object_version_ref = :object_version_ref,
    scan_status = :scan_status,
    evidence_ref = :evidence_ref,
    updated_at = :updated_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND attachment_id = :attachment_id
  AND state IN ('UPLOADING', 'FAILED')
"""

_RESOLVE_OBJECT_REF_SQL = """
SELECT a.tenant_id, a.attachment_batch_id, b.owner_subject_id,
       b.state AS batch_state, b.attachment_manifest_hash,
       a.attachment_id, a.state, a.display_name, a.media_type, a.size_bytes,
       a.content_sha256, a.object_ref, a.object_version_ref, a.scan_status,
       a.evidence_ref, a.created_at, a.updated_at
FROM ae_voucher_attachment a
JOIN ae_voucher_attach_batch b
  ON b.tenant_id = a.tenant_id
 AND b.attachment_batch_id = a.attachment_batch_id
WHERE a.tenant_id = :tenant_id
  AND a.object_ref = :object_ref
  AND a.state IN ('READY', 'LOCKED')
"""

_REMOVE_ITEM_SQL = """
UPDATE ae_voucher_attachment
SET state = 'REMOVED',
    content_sha256 = NULL,
    object_ref = NULL,
    object_version_ref = NULL,
    scan_status = 'PENDING',
    evidence_ref = NULL,
    updated_at = :updated_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND attachment_id = :attachment_id
  AND state <> 'LOCKED'
"""

_UPDATE_BATCH_AFTER_REMOVAL_SQL = """
UPDATE ae_voucher_attach_batch
SET state = :state,
    attachment_count = :attachment_count,
    total_size_bytes = :total_size_bytes,
    updated_at = :updated_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND state NOT IN ('LOCKED', 'ABANDONED')
"""

_FINALIZE_BATCH_SQL = """
UPDATE ae_voucher_attach_batch
SET state = 'READY', updated_at = :updated_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND state IN ('DRAFT', 'UPLOADING', 'READY', 'QUARANTINED', 'FAILED')
"""

_LOCK_BATCH_SQL = """
UPDATE ae_voucher_attach_batch
SET state = 'LOCKED',
    attachment_manifest_hash = :attachment_manifest_hash,
    locked_at = :locked_at,
    updated_at = :locked_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND state = 'READY'
"""

_LOCK_ITEMS_SQL = """
UPDATE ae_voucher_attachment
SET state = 'LOCKED', updated_at = :locked_at
WHERE tenant_id = :tenant_id
  AND attachment_batch_id = :attachment_batch_id
  AND state = 'READY'
"""
