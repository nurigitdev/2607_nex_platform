from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Protocol, runtime_checkable

from nex_cx.access_context import CxAccessContext


CX_PRIVATE_PAYLOAD_KEY_SCHEMA_VERSION = "cx_private_payload_key.v1"
CX_PRIVATE_PAYLOAD_RECEIPT_SCHEMA_VERSION = "cx_private_payload_receipt.v1"
PRIVATE_TEXT_PAYLOAD_KINDS = frozenset({"chunk_text", "summary_text"})
PRIVATE_VECTOR_PAYLOAD_KINDS = frozenset(
    {"chunk_embedding", "summary_embedding"}
)
PRIVATE_PAYLOAD_KINDS = PRIVATE_TEXT_PAYLOAD_KINDS | PRIVATE_VECTOR_PAYLOAD_KINDS
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CxPrivateContentError(ValueError):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        detail: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


@dataclass(frozen=True)
class CxPrivatePayloadKey:
    tenant_id: str
    subject_id: str
    payload_kind: str
    content_id: str

    def to_wire(self) -> dict[str, object]:
        return {
            "key_schema_version": CX_PRIVATE_PAYLOAD_KEY_SCHEMA_VERSION,
            "tenant_ref": {"type": "oa.tenant", "id": self.tenant_id},
            "owner_subject_ref": {"type": "oa.user", "id": self.subject_id},
            "payload_kind": self.payload_kind,
            "content_id": self.content_id,
        }


@dataclass(frozen=True)
class CxPrivatePayloadReceipt:
    key: CxPrivatePayloadKey
    storage_backend: str
    storage_uri: str
    sha256: str
    size_bytes: int
    vector_dimension: int | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "receipt_schema_version": CX_PRIVATE_PAYLOAD_RECEIPT_SCHEMA_VERSION,
            "key": self.key.to_wire(),
            "storage_backend": self.storage_backend,
            "storage_uri": self.storage_uri,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "vector_dimension": self.vector_dimension,
        }


@runtime_checkable
class CxPrivateTextStore(Protocol):
    def put_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        text: str,
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        ...

    def get_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
    ) -> str | None:
        ...

    def delete_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        ...


@runtime_checkable
class CxVectorStore(Protocol):
    def put_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        vector: Sequence[float],
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        ...

    def get_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
        expected_dimension: int,
    ) -> tuple[float, ...] | None:
        ...

    def delete_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        ...


def build_private_payload_key(
    access_context: CxAccessContext,
    *,
    payload_kind: str,
    content_id: str,
) -> CxPrivatePayloadKey:
    if payload_kind not in PRIVATE_PAYLOAD_KINDS:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_PAYLOAD_KIND_INVALID",
            detail="Private payload kind is not supported.",
        )
    return CxPrivatePayloadKey(
        tenant_id=_identifier(access_context.tenant_id, field_name="tenant_id"),
        subject_id=_identifier(access_context.subject_id, field_name="subject_id"),
        payload_kind=payload_kind,
        content_id=_identifier(content_id, field_name="content_id"),
    )


def assert_private_payload_access(
    access_context: CxAccessContext,
    key: CxPrivatePayloadKey,
) -> None:
    if key.tenant_id != access_context.tenant_id or key.subject_id != access_context.subject_id:
        raise CxPrivateContentError(
            status_code=404,
            error_code="CX_PRIVATE_PAYLOAD_NOT_FOUND",
            detail="Private payload was not found for the owner scope.",
        )


def validate_private_text(
    *,
    key: CxPrivatePayloadKey,
    text: object,
    expected_sha256: str,
) -> str:
    if key.payload_kind not in PRIVATE_TEXT_PAYLOAD_KINDS:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_TEXT_KIND_INVALID",
            detail="The payload key is not valid for private text.",
        )
    if not isinstance(text, str):
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_TEXT_INVALID",
            detail="Private text must be a string.",
        )
    _assert_expected_sha256(expected_sha256, sha256_private_text(text))
    return text


def normalize_private_vector(
    *,
    key: CxPrivatePayloadKey,
    vector: object,
    expected_sha256: str,
) -> tuple[float, ...]:
    if key.payload_kind not in PRIVATE_VECTOR_PAYLOAD_KINDS:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_KIND_INVALID",
            detail="The payload key is not valid for a private vector.",
        )
    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes, bytearray))
        or not vector
    ):
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_INVALID",
            detail="Private vector must be a non-empty numeric sequence.",
        )
    normalized: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PRIVATE_VECTOR_INVALID",
                detail="Private vector values must be finite numbers.",
            )
        number = float(value)
        if not math.isfinite(number):
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PRIVATE_VECTOR_INVALID",
                detail="Private vector values must be finite numbers.",
            )
        normalized.append(number)
    result = tuple(normalized)
    _assert_expected_sha256(expected_sha256, sha256_private_vector(result))
    return result


def build_private_payload_receipt(
    *,
    key: CxPrivatePayloadKey,
    storage_backend: str,
    storage_uri: str,
    sha256: str,
    size_bytes: int,
    vector_dimension: int | None = None,
) -> CxPrivatePayloadReceipt:
    backend = _identifier(storage_backend, field_name="storage_backend")
    if not isinstance(storage_uri, str) or not storage_uri.startswith("cx-private://"):
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_STORAGE_URI_INVALID",
            detail="Private payload storage URI is invalid.",
        )
    _validate_sha256(sha256)
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_PAYLOAD_SIZE_INVALID",
            detail="Private payload size must be a non-negative integer.",
        )
    if key.payload_kind in PRIVATE_VECTOR_PAYLOAD_KINDS:
        if (
            isinstance(vector_dimension, bool)
            or not isinstance(vector_dimension, int)
            or vector_dimension < 1
        ):
            raise CxPrivateContentError(
                status_code=500,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_INVALID",
                detail="Private vector dimension must be a positive integer.",
            )
    elif vector_dimension is not None:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_TEXT_DIMENSION_INVALID",
            detail="Private text receipts cannot carry a vector dimension.",
        )
    return CxPrivatePayloadReceipt(
        key=key,
        storage_backend=backend,
        storage_uri=storage_uri,
        sha256=sha256,
        size_bytes=size_bytes,
        vector_dimension=vector_dimension,
    )


def sha256_private_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_private_vector(vector: Sequence[float]) -> str:
    payload = json.dumps(
        [float(value) for value in vector],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _assert_expected_sha256(expected: str, actual: str) -> None:
    _validate_sha256(expected)
    if expected != actual:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_PAYLOAD_HASH_MISMATCH",
            detail="Private payload integrity verification failed.",
        )


def _validate_sha256(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_PAYLOAD_HASH_INVALID",
            detail="Private payload SHA-256 must be 64 lowercase hexadecimal characters.",
        )
    return value


def _identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_PAYLOAD_KEY_INVALID",
            detail=f"{field_name} must be a valid private payload key segment.",
        )
    return value
