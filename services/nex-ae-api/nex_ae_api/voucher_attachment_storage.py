from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO

from nex_runtime.object_storage import (
    ObjectMetadata,
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
)

from .voucher_attachments import (
    MAX_ATTACHMENT_FILE_BYTES,
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)

ATTACHMENT_RESOLUTION_SCHEMA_VERSION = "ae_voucher_attachment_resolution.v1"
ATTACHMENT_PURPOSE = "EOS_VOUCHER_ATTACHMENT"
ATTACHMENT_STORAGE_OWNER = "nex-ae-api"
ATTACHMENT_SPOOL_MEMORY_BYTES = 1024 * 1024
_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class VoucherAttachmentStorageError(RuntimeError):
    error_code: str
    detail: str
    status_code: int
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class VoucherAttachmentDownload:
    source: BinaryIO
    display_name: str
    media_type: str
    size_bytes: int


class VoucherAttachmentObjectGateway:
    def __init__(
        self,
        object_store: S3ObjectStore,
        repository: SqlAlchemyVoucherAttachmentRepository,
    ) -> None:
        self._object_store = object_store
        self._repository = repository

    def publish(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
        source: BinaryIO,
    ) -> dict[str, Any]:
        batch, item = self._registered_item(
            tenant_id=tenant_id,
            attachment_batch_id=attachment_batch_id,
            attachment_id=attachment_id,
        )
        if batch["state"] == "ABANDONED" or item["state"] in {
            "QUARANTINED",
            "REMOVED",
        }:
            raise _conflict("Voucher attachment item is not publishable.")
        if item["state"] in {"READY", "LOCKED"}:
            return self._resolve_persisted_item(
                tenant_id=tenant_id,
                object_ref=str(item["object_ref"]),
                requester_service="nex-eos",
                authenticated=True,
            )
        with SpooledTemporaryFile(max_size=ATTACHMENT_SPOOL_MEMORY_BYTES) as spool:
            digest, size = _copy_bounded(source, spool)
            if size != item["size_bytes"]:
                raise _invalid("Attachment byte count does not match registration.")
            key = _object_key(batch, item)
            try:
                stored = self._object_store.put_immutable_stream(
                    key=key,
                    source=spool,
                    expected_sha256=digest,
                    expected_size_bytes=size,
                    max_size_bytes=MAX_ATTACHMENT_FILE_BYTES,
                    content_type=str(item["media_type"]),
                )
            except ObjectStorageError as exc:
                raise _storage_error(exc) from exc
        object_ref = _opaque_object_ref(
            tenant_id=tenant_id,
            attachment_batch_id=attachment_batch_id,
            attachment_id=attachment_id,
        )
        try:
            self._repository.publish_item(
                tenant_id=tenant_id,
                attachment_batch_id=attachment_batch_id,
                attachment_id=attachment_id,
                content_sha256=digest,
                object_ref=object_ref,
                object_version_ref=stored.version_id,
                scan_status="CLEAN",
            )
        except VoucherAttachmentPersistenceError as exc:
            raise _persistence_error(exc) from exc
        return self._resolve_persisted_item(
            tenant_id=tenant_id,
            object_ref=object_ref,
            requester_service="nex-eos",
            authenticated=True,
        )

    def resolve(
        self,
        *,
        requester_service: str,
        tenant_id: str,
        object_ref: str,
        required_purpose: str,
        authenticated: bool,
    ) -> dict[str, Any]:
        if not authenticated or requester_service != "nex-eos":
            raise _forbidden("Authenticated nex-eos service authority is required.")
        if required_purpose != ATTACHMENT_PURPOSE:
            raise _forbidden("Voucher attachment purpose is required.")
        return self._resolve_persisted_item(
            tenant_id=tenant_id,
            object_ref=object_ref,
            requester_service=requester_service,
            authenticated=authenticated,
        )

    def read_for_owner(
        self,
        *,
        tenant_id: str,
        owner_subject_id: str,
        object_ref: str,
    ) -> bytes:
        persisted = self._persisted_resolution(
            tenant_id=tenant_id, object_ref=object_ref
        )
        if persisted["owner_subject_id"] != owner_subject_id:
            raise _forbidden("Attachment owner scope does not match.")
        key = _object_key_from_persisted(persisted)
        try:
            payload = self._object_store.get_bytes(
                key=key,
                expected_sha256=str(persisted["content_sha256"]),
                expected_size_bytes=int(persisted["size_bytes"]),
                max_size_bytes=MAX_ATTACHMENT_FILE_BYTES,
            )
        except ObjectStorageError as exc:
            raise _storage_error(exc) from exc
        if payload is None:
            raise _integrity("Attachment object is missing.")
        return payload

    def open_for_owner(
        self,
        *,
        tenant_id: str,
        owner_subject_id: str,
        object_ref: str,
    ) -> VoucherAttachmentDownload:
        persisted = self._persisted_resolution(
            tenant_id=tenant_id, object_ref=object_ref
        )
        if persisted["owner_subject_id"] != owner_subject_id:
            raise _forbidden("Attachment owner scope does not match.")
        return self._open_persisted(persisted)

    def open_for_service(
        self,
        *,
        requester_service: str,
        tenant_id: str,
        object_ref: str,
    ) -> VoucherAttachmentDownload:
        if requester_service not in {"nex-wc", "nex-eos"}:
            raise _forbidden("Attachment review service is not authorized.")
        return self._open_persisted(
            self._persisted_resolution(tenant_id=tenant_id, object_ref=object_ref)
        )

    def remove(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        batch, item = self._registered_item(
            tenant_id=tenant_id,
            attachment_batch_id=attachment_batch_id,
            attachment_id=attachment_id,
        )
        if batch["state"] in {"LOCKED", "ABANDONED"} or item["state"] == "LOCKED":
            raise _conflict("Locked Voucher attachment evidence cannot be removed.")
        try:
            removed = self._repository.remove_item(
                tenant_id=tenant_id,
                attachment_batch_id=attachment_batch_id,
                attachment_id=attachment_id,
            )
        except VoucherAttachmentPersistenceError as exc:
            raise _persistence_error(exc) from exc
        key = _object_key(batch, item)
        try:
            if self._object_store.head(key) is not None:
                self._object_store.delete(key)
        except ObjectStorageError as exc:
            raise _storage_error(exc) from exc
        return removed

    def cleanup_unreferenced(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
    ) -> bool:
        batch, item = self._registered_item(
            tenant_id=tenant_id,
            attachment_batch_id=attachment_batch_id,
            attachment_id=attachment_id,
        )
        if batch["state"] == "LOCKED" or item["state"] in {"READY", "LOCKED"}:
            raise _conflict("Referenced or locked attachment objects cannot be deleted.")
        key = _object_key(batch, item)
        try:
            if self._object_store.head(key) is None:
                return False
            self._object_store.delete(key)
        except ObjectStorageError as exc:
            raise _storage_error(exc) from exc
        return True

    def _registered_item(
        self,
        *,
        tenant_id: str,
        attachment_batch_id: str,
        attachment_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            batch = self._repository.get_batch(
                tenant_id=tenant_id,
                attachment_batch_id=attachment_batch_id,
            )
        except VoucherAttachmentPersistenceError as exc:
            raise _persistence_error(exc) from exc
        if batch is None:
            raise _not_found("Voucher attachment batch was not found.")
        item = next(
            (
                candidate
                for candidate in batch["items"]
                if candidate["attachment_id"] == attachment_id
            ),
            None,
        )
        if item is None:
            raise _not_found("Voucher attachment item was not found.")
        return batch, item

    def _persisted_resolution(
        self, *, tenant_id: str, object_ref: str
    ) -> dict[str, Any]:
        try:
            value = self._repository.resolve_object_ref(
                tenant_id=tenant_id, object_ref=object_ref
            )
        except VoucherAttachmentPersistenceError as exc:
            raise _persistence_error(exc) from exc
        if value is None:
            raise _not_found("Voucher attachment object reference was not found.")
        if value["scan_status"] != "CLEAN":
            raise _integrity("Voucher attachment object is not admitted.")
        return value

    def _resolve_persisted_item(
        self,
        *,
        tenant_id: str,
        object_ref: str,
        requester_service: str,
        authenticated: bool,
    ) -> dict[str, Any]:
        persisted = self._persisted_resolution(
            tenant_id=tenant_id, object_ref=object_ref
        )
        key = _object_key_from_persisted(persisted)
        try:
            stored = self._object_store.head(key)
        except ObjectStorageError as exc:
            raise _storage_error(exc) from exc
        _require_storage_match(stored, persisted)
        return {
            "schema_version": ATTACHMENT_RESOLUTION_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "object_ref": object_ref,
            "storage_owner": ATTACHMENT_STORAGE_OWNER,
            "purpose": ATTACHMENT_PURPOSE,
            "status": "READY",
            "content_sha256": persisted["content_sha256"],
            "size_bytes": persisted["size_bytes"],
            "media_type": persisted["media_type"],
            "authenticated": authenticated and requester_service == "nex-eos",
            "immutable": True,
            "object_version_ref": persisted["object_version_ref"],
            "resolved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def _open_persisted(
        self, persisted: Mapping[str, Any]
    ) -> VoucherAttachmentDownload:
        destination = SpooledTemporaryFile(  # noqa: SIM115 - owned by response
            max_size=ATTACHMENT_SPOOL_MEMORY_BYTES
        )
        try:
            found = self._object_store.copy_to_stream(
                key=_object_key_from_persisted(persisted),
                destination=destination,
                expected_sha256=str(persisted["content_sha256"]),
                expected_size_bytes=int(persisted["size_bytes"]),
                max_size_bytes=MAX_ATTACHMENT_FILE_BYTES,
            )
        except ObjectStorageError as exc:
            destination.close()
            raise _storage_error(exc) from exc
        if not found:
            destination.close()
            raise _integrity("Attachment object is missing.")
        return VoucherAttachmentDownload(
            source=destination,
            display_name=str(persisted["display_name"]),
            media_type=str(persisted["media_type"]),
            size_bytes=int(persisted["size_bytes"]),
        )


def _copy_bounded(source: BinaryIO, destination: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        try:
            chunk = source.read(_CHUNK_BYTES)
        except (AttributeError, OSError) as exc:
            raise _invalid("Attachment input stream is unreadable.") from exc
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise _invalid("Attachment input stream must produce bytes.")
        size += len(chunk)
        if size > MAX_ATTACHMENT_FILE_BYTES:
            raise VoucherAttachmentStorageError(
                "ae.voucher_attachment.limit_exceeded",
                "Attachment exceeds the maximum file size.",
                413,
            )
        destination.write(chunk)
        digest.update(chunk)
    if size < 1:
        raise _invalid("Attachment must not be empty.")
    destination.seek(0)
    return digest.hexdigest(), size


def _object_key(batch: Mapping[str, Any], item: Mapping[str, Any]) -> str:
    return build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=str(batch["tenant_id"]),
        subject_id=str(batch["owner_subject_ref"]["id"]),
        content_id=str(item["attachment_id"]),
        suffix="bin",
    )


def _object_key_from_persisted(value: Mapping[str, Any]) -> str:
    return build_owner_object_key(
        payload_family="voucher-evidence",
        tenant_id=str(value["tenant_id"]),
        subject_id=str(value["owner_subject_id"]),
        content_id=str(value["attachment_id"]),
        suffix="bin",
    )


def _opaque_object_ref(
    *, tenant_id: str, attachment_batch_id: str, attachment_id: str
) -> str:
    digest = hashlib.sha256(
        (
            "nex-ae:voucher-attachment-object-ref:v1\0"
            f"{tenant_id}\0{attachment_batch_id}\0{attachment_id}"
        ).encode()
    ).hexdigest()
    return f"objref:ae:voucher:{digest}"


def _require_storage_match(
    stored: ObjectMetadata | None, persisted: Mapping[str, Any]
) -> None:
    if stored is None:
        raise _integrity("Attachment object is missing.")
    if (
        stored.sha256 != persisted["content_sha256"]
        or stored.size_bytes != persisted["size_bytes"]
        or stored.content_type != persisted["media_type"]
        or stored.server_side_encryption != "AES256"
        or (
            persisted["object_version_ref"] is not None
            and stored.version_id != persisted["object_version_ref"]
        )
    ):
        raise _integrity("Attachment object metadata failed integrity validation.")


def _invalid(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.invalid", detail, 422
    )


def _forbidden(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.forbidden", detail, 403
    )


def _not_found(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.not_found", detail, 404
    )


def _conflict(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.conflict", detail, 409
    )


def _integrity(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.integrity_failed", detail, 500
    )


def _storage_error(exc: ObjectStorageError) -> VoucherAttachmentStorageError:
    if exc.code == "OBJECT_STORAGE_IMMUTABLE_CONFLICT":
        return VoucherAttachmentStorageError(
            "ae.voucher_attachment.conflict",
            "Voucher attachment object conflicts with immutable storage.",
            409,
        )
    if exc.code in {
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_SIZE_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
        "OBJECT_STORAGE_STREAM_INVALID",
    }:
        return VoucherAttachmentStorageError(
            "ae.voucher_attachment.invalid",
            "Voucher attachment object failed storage validation.",
            422,
        )
    return VoucherAttachmentStorageError(
        "ae.voucher_attachment.storage_unavailable",
        "Voucher attachment object storage is unavailable.",
        503,
        exc.retryable,
    )


def _persistence_error(
    exc: VoucherAttachmentPersistenceError,
) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError(
        exc.error_code, exc.detail, exc.status_code, exc.retryable
    )
