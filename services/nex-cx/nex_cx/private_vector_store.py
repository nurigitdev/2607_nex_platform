from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    PRIVATE_VECTOR_PAYLOAD_KINDS,
    CxPrivateContentError,
    CxPrivatePayloadKey,
    CxPrivatePayloadReceipt,
    CxVectorStore,
    assert_private_payload_access,
    build_private_payload_key,
    build_private_payload_receipt,
    normalize_private_vector,
    serialize_private_vector,
)
from nex_cx.private_file_storage import (
    ImmutableOwnerScopedFileStorage,
    PrivateFileErrorCodes,
)


DEFAULT_PRIVATE_VECTOR_STORAGE_ROOT = Path(
    "/data/nex-platform/cx/private-vectors"
)
PRIVATE_VECTOR_STORAGE_ROOT_ENV = "NEX_CX_PRIVATE_VECTOR_STORAGE_ROOT"
PRIVATE_VECTOR_STORAGE_BACKEND = "filesystem-vector-v1"
_PRIVATE_VECTOR_FILE_ERRORS = PrivateFileErrorCodes(
    root_invalid="CX_PRIVATE_VECTOR_ROOT_INVALID",
    storage_unsafe="CX_PRIVATE_VECTOR_STORAGE_UNSAFE",
    storage_unavailable="CX_PRIVATE_VECTOR_STORAGE_UNAVAILABLE",
    immutable_conflict="CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT",
)


class FileSystemCxVectorStore:
    """Restart-safe local reference implementation of the CX vector port."""

    def __init__(self, root: str | Path) -> None:
        self._storage = ImmutableOwnerScopedFileStorage(
            root,
            backend=PRIVATE_VECTOR_STORAGE_BACKEND,
            suffix=".json",
            errors=_PRIVATE_VECTOR_FILE_ERRORS,
        )

    @property
    def root(self) -> Path:
        return self._storage.root

    def put_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        vector: Sequence[float],
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        assert_private_payload_access(access_context, key)
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=expected_sha256,
        )
        payload = serialize_private_vector(normalized)
        self._storage.publish(
            key=key,
            payload=payload,
            expected_sha256=expected_sha256,
        )
        return build_private_payload_receipt(
            key=key,
            storage_backend=PRIVATE_VECTOR_STORAGE_BACKEND,
            storage_uri=self.storage_uri(key),
            sha256=expected_sha256,
            size_bytes=len(payload),
            vector_dimension=len(normalized),
        )

    def get_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
        expected_dimension: int,
    ) -> tuple[float, ...] | None:
        assert_private_payload_access(access_context, key)
        _assert_vector_key(key)
        if (
            isinstance(expected_dimension, bool)
            or not isinstance(expected_dimension, int)
            or expected_dimension < 1
        ):
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_INVALID",
                detail="Expected vector dimension must be a positive integer.",
            )
        payload = self._storage.read(key)
        if payload is None:
            return None
        vector = _deserialize_vector(payload)
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=expected_sha256,
        )
        if len(normalized) != expected_dimension:
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
                detail="Stored private vector dimension verification failed.",
            )
        return normalized

    def delete_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        assert_private_payload_access(access_context, key)
        _assert_vector_key(key)
        return self._storage.delete(key)

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        _assert_vector_key(key)
        return self._storage.storage_uri(key)

    def _payload_path(self, key: CxPrivatePayloadKey) -> Path:
        return self._storage.payload_path(key)


def build_private_vector_store(
    environ: Mapping[str, str] | None = None,
) -> FileSystemCxVectorStore:
    env = os.environ if environ is None else environ
    root = env.get(
        PRIVATE_VECTOR_STORAGE_ROOT_ENV,
        str(DEFAULT_PRIVATE_VECTOR_STORAGE_ROOT),
    )
    return FileSystemCxVectorStore(root)


def link_private_vector_metadata(
    metadata: Mapping[str, object],
    receipt: CxPrivatePayloadReceipt,
) -> dict[str, object]:
    _assert_vector_key(receipt.key)
    if receipt.vector_dimension is None:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_VECTOR_RECEIPT_INVALID",
            detail="Private vector receipt is missing its dimension.",
        )
    content_field = (
        "chunk_id"
        if receipt.key.payload_kind == "chunk_embedding"
        else "document_summary_id"
    )
    existing_content_id = metadata.get(content_field)
    conflicts = (
        existing_content_id not in (None, receipt.key.content_id),
        metadata.get("embedding_sha256") not in (None, receipt.sha256),
        metadata.get("vector_dimension") not in (
            None,
            receipt.vector_dimension,
        ),
        metadata.get("embedding_storage_uri") not in (
            None,
            receipt.storage_uri,
        ),
    )
    if any(conflicts):
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_METADATA_CONFLICT",
            detail="Public vector metadata conflicts with the private payload receipt.",
        )
    return {
        **metadata,
        content_field: receipt.key.content_id,
        "embedding_sha256": receipt.sha256,
        "vector_dimension": receipt.vector_dimension,
        "embedding_storage_uri": receipt.storage_uri,
    }


def persist_and_link_private_vector(
    *,
    access_context: CxAccessContext,
    vector_store: CxVectorStore,
    payload_kind: str,
    content_id: str,
    vector: Sequence[float],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    expected_sha256 = metadata.get("embedding_sha256")
    if not isinstance(expected_sha256, str):
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_METADATA_INVALID",
            detail="Public vector metadata must include embedding_sha256.",
        )
    key = build_private_payload_key(
        access_context,
        payload_kind=payload_kind,
        content_id=content_id,
    )
    receipt = vector_store.put_vector(
        access_context=access_context,
        key=key,
        vector=vector,
        expected_sha256=expected_sha256,
    )
    return link_private_vector_metadata(metadata, receipt)


def _assert_vector_key(key: CxPrivatePayloadKey) -> None:
    if key.payload_kind not in PRIVATE_VECTOR_PAYLOAD_KINDS:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_KIND_INVALID",
            detail="The payload key is not valid for a private vector.",
        )


def _deserialize_vector(payload: bytes) -> object:
    try:
        decoded = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored private vector payload is not valid canonical JSON.",
        ) from exc
    if not isinstance(decoded, dict) or set(decoded) != {"embedding"}:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored private vector payload has an invalid envelope.",
        )
    return decoded["embedding"]
