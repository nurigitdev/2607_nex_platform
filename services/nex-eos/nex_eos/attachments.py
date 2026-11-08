from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime import build_unit_of_work
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA
from .vouchers import EOS_VOUCHER_DRAFT_TABLE

EOS_VOUCHER_ATTACHMENT_PURPOSE = "EOS_VOUCHER_ATTACHMENT"
EOS_OBJECT_READY_STATUS = "READY"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,255}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_CREDENTIAL_TOKEN = re.compile(
    r"(?:access[_-]?key|secret|password|credential|session[_-]?token)",
    re.IGNORECASE,
)
_AWS_ACCESS_KEY = re.compile(r"^AKIA[0-9A-Z]{16}$")

EOS_VOUCHER_ATTACHMENT_TABLE = Table(
    "eos_voucher_draft_attachment",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("attachment_id", Uuid(as_uuid=False), primary_key=True),
    Column("voucher_id", Uuid(as_uuid=False), nullable=False),
    Column("object_ref", String(256), nullable=False),
    Column("storage_owner", String(128), nullable=False),
    Column("object_version_ref", String(128), nullable=True),
    Column("display_name", String(512), nullable=False),
    Column("media_type", String(192), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("evidence_ref", String(128), nullable=True),
    Column("resolver_authenticated", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "voucher_id"),
        ("eos_voucher_draft.tenant_id", "eos_voucher_draft.voucher_id"),
        name="fk_eos_attachment_voucher",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "tenant_id", "voucher_id", "object_ref", name="ux_eos_attachment_object"
    ),
)


class EosAttachmentError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ResolvedObjectRef:
    object_ref: str
    storage_owner: str
    tenant_id: str
    purpose: str
    status: str
    content_sha256: str
    size_bytes: int
    media_type: str
    authenticated: bool
    immutable: bool
    version_ref: str | None = None
    attachment_id: str | None = None
    attachment_batch_id: str | None = None
    attachment_manifest_hash: str | None = None


class ObjectRefResolver(Protocol):
    def resolve_object_ref(
        self,
        *,
        requester_service: str,
        tenant_id: str,
        object_ref: str,
        required_purpose: str,
    ) -> ResolvedObjectRef: ...


@dataclass(frozen=True)
class VoucherAttachmentInput:
    attachment_id: str
    object_ref: str
    display_name: str
    media_type: str
    size_bytes: int
    content_sha256: str
    evidence_ref: str | None = None


class SqlAlchemyEosAttachmentRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        resolver: ObjectRefResolver,
        *,
        requester_service: str = "nex-eos",
    ) -> None:
        self._session_factory = session_factory
        self._resolver = resolver
        self._requester_service = _scoped_id("requester_service", requester_service)

    def attach_many(
        self,
        *,
        tenant_id: str,
        voucher_id: str,
        attachments: Sequence[VoucherAttachmentInput],
    ) -> list[dict[str, Any]]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                return self.attach_many_in_session(
                    transaction.db,
                    tenant_id=tenant_id,
                    voucher_id=voucher_id,
                    attachments=attachments,
                )
        except EosAttachmentError:
            raise
        except IntegrityError as exc:
            raise EosAttachmentError(
                "EOS_ATTACHMENT_CONFLICT",
                "Attachment identity or object reference already exists",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    def attach_many_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        voucher_id: str,
        attachments: Sequence[VoucherAttachmentInput],
        attachment_batch_id: str | None = None,
        attachment_manifest_hash: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        voucher_id = _uuid("voucher_id", voucher_id)
        if isinstance(attachments, (str, bytes)) or not isinstance(
            attachments, Sequence
        ):
            raise _invalid("attachments", "must be a sequence")
        if not attachments:
            return []
        expected_batch_id, expected_manifest_hash = _attachment_lineage(
            attachment_batch_id,
            attachment_manifest_hash,
        )
        records = [
            self._resolve_attachment(
                tenant_id=tenant_id,
                voucher_id=voucher_id,
                value=value,
                attachment_batch_id=expected_batch_id,
                attachment_manifest_hash=expected_manifest_hash,
            )
            for value in attachments
        ]
        if len({record["attachment_id"] for record in records}) != len(records):
            raise _invalid("attachment_id", "must be unique within the request")
        if len({record["object_ref"] for record in records}) != len(records):
            raise _invalid("object_ref", "must be unique within the Voucher")
        voucher_exists = session.execute(
            select(EOS_VOUCHER_DRAFT_TABLE.c.voucher_id).where(
                EOS_VOUCHER_DRAFT_TABLE.c.tenant_id == tenant_id,
                EOS_VOUCHER_DRAFT_TABLE.c.voucher_id == voucher_id,
            )
        ).scalar_one_or_none()
        if voucher_exists is None:
            raise EosAttachmentError(
                "EOS_ATTACHMENT_VOUCHER_NOT_FOUND",
                "Voucher Draft was not found in tenant scope",
                status_code=404,
            )
        session.execute(EOS_VOUCHER_ATTACHMENT_TABLE.insert(), records)
        return [dict(record) for record in records]

    def list_attachments(
        self, *, tenant_id: str, voucher_id: str
    ) -> list[dict[str, Any]]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        voucher_id = _uuid("voucher_id", voucher_id)
        statement = (
            select(EOS_VOUCHER_ATTACHMENT_TABLE)
            .where(
                EOS_VOUCHER_ATTACHMENT_TABLE.c.tenant_id == tenant_id,
                EOS_VOUCHER_ATTACHMENT_TABLE.c.voucher_id == voucher_id,
            )
            .order_by(
                EOS_VOUCHER_ATTACHMENT_TABLE.c.created_at,
                EOS_VOUCHER_ATTACHMENT_TABLE.c.attachment_id,
            )
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(statement).mappings().all()
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return [dict(row) for row in rows]

    def _resolve_attachment(
        self,
        *,
        tenant_id: str,
        voucher_id: str,
        value: VoucherAttachmentInput,
        attachment_batch_id: str | None,
        attachment_manifest_hash: str | None,
    ) -> dict[str, Any]:
        if not isinstance(value, VoucherAttachmentInput):
            raise _invalid("attachments", "must contain VoucherAttachmentInput values")
        object_ref = _object_ref(value.object_ref)
        media_type = _media_type(value.media_type)
        size_bytes = _size(value.size_bytes)
        content_sha256 = _sha256(value.content_sha256)
        try:
            resolved = self._resolver.resolve_object_ref(
                requester_service=self._requester_service,
                tenant_id=tenant_id,
                object_ref=object_ref,
                required_purpose=EOS_VOUCHER_ATTACHMENT_PURPOSE,
            )
        except Exception as exc:
            raise EosAttachmentError(
                "EOS_ATTACHMENT_RESOLVER_UNAVAILABLE",
                "Object reference resolver is unavailable",
                status_code=503,
            ) from exc
        _require_resolved_match(
            resolved,
            tenant_id=tenant_id,
            object_ref=object_ref,
            media_type=media_type,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            attachment_id=_uuid("attachment_id", value.attachment_id),
            attachment_batch_id=attachment_batch_id,
            attachment_manifest_hash=attachment_manifest_hash,
        )
        return {
            "tenant_id": tenant_id,
            "attachment_id": _uuid("attachment_id", value.attachment_id),
            "voucher_id": voucher_id,
            "object_ref": object_ref,
            "storage_owner": _scoped_id("storage_owner", resolved.storage_owner),
            "object_version_ref": (
                _scoped_id("version_ref", resolved.version_ref)
                if resolved.version_ref is not None
                else None
            ),
            "display_name": _text("display_name", value.display_name, 512),
            "media_type": media_type,
            "size_bytes": size_bytes,
            "content_sha256": content_sha256,
            "evidence_ref": (
                _scoped_id("evidence_ref", value.evidence_ref)
                if value.evidence_ref is not None
                else None
            ),
            "resolver_authenticated": True,
            "created_at": datetime.now(UTC),
        }


def _require_resolved_match(
    value: object,
    *,
    tenant_id: str,
    object_ref: str,
    media_type: str,
    size_bytes: int,
    content_sha256: str,
    attachment_id: str,
    attachment_batch_id: str | None,
    attachment_manifest_hash: str | None,
) -> None:
    if not isinstance(value, ResolvedObjectRef):
        raise _rejected("resolver returned an invalid result")
    if not value.authenticated:
        raise _rejected("resolver result is not authenticated")
    if value.object_ref != object_ref or value.tenant_id != tenant_id:
        raise _rejected("object reference or tenant does not match")
    if value.purpose != EOS_VOUCHER_ATTACHMENT_PURPOSE:
        raise _rejected("object purpose does not permit Voucher attachment use")
    if value.status != EOS_OBJECT_READY_STATUS or not value.immutable:
        raise _rejected("object is not ready and immutable")
    if (
        value.content_sha256 != content_sha256
        or value.size_bytes != size_bytes
        or value.media_type != media_type
    ):
        raise _rejected("object metadata does not match the association")
    if attachment_batch_id is not None and (
        value.attachment_id != attachment_id
        or value.attachment_batch_id != attachment_batch_id
        or value.attachment_manifest_hash != attachment_manifest_hash
    ):
        raise _rejected(
            "object lineage does not match the approved attachment manifest"
        )


def _object_ref(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if (
        not _OPAQUE_REF.fullmatch(normalized)
        or "://" in normalized
        or "/" in normalized
        or "?" in normalized
        or _CREDENTIAL_TOKEN.search(normalized)
        or _AWS_ACCESS_KEY.fullmatch(normalized)
    ):
        raise _invalid("object_ref", "must be an owner-issued opaque reference")
    return normalized


def _attachment_lineage(
    batch_id: object,
    manifest_hash: object,
) -> tuple[str | None, str | None]:
    if batch_id is None and manifest_hash is None:
        return None, None
    if batch_id is None or manifest_hash is None:
        raise _invalid(
            "attachment_lineage",
            "must contain both attachment_batch_id and attachment_manifest_hash",
        )
    normalized_hash = str(manifest_hash).strip()
    if _HASH_REF.fullmatch(normalized_hash) is None:
        raise _invalid("attachment_manifest_hash", "must be a sha256 hash reference")
    return _uuid("attachment_batch_id", batch_id), normalized_hash


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SCOPED_ID.fullmatch(normalized):
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _media_type(value: object) -> str:
    normalized = str(value).strip().lower() if value is not None else ""
    if not _MEDIA_TYPE.fullmatch(normalized):
        raise _invalid("media_type", "has invalid syntax")
    return normalized


def _sha256(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _SHA256.fullmatch(normalized):
        raise _invalid("content_sha256", "must be 64 lowercase hexadecimal chars")
    return normalized


def _size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid("size_bytes", "must be a non-negative integer")
    return value


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _invalid(field_name: str, detail: str) -> EosAttachmentError:
    return EosAttachmentError(
        "EOS_ATTACHMENT_INVALID", f"{field_name} {detail}", status_code=422
    )


def _rejected(detail: str) -> EosAttachmentError:
    return EosAttachmentError("EOS_ATTACHMENT_OBJECT_REJECTED", detail, status_code=422)


def _persistence_error() -> EosAttachmentError:
    return EosAttachmentError(
        "EOS_ATTACHMENT_PERSISTENCE_FAILED",
        "Attachment persistence is unavailable",
        status_code=503,
    )
