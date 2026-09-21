from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from nex_cx.access_context import CxAccessContext
from nex_cx.private_file_storage import (
    ImmutableOwnerScopedFileStorage,
    PrivateFileErrorCodes,
)
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivatePayloadKey,
    CxPrivatePayloadReceipt,
    assert_private_payload_access,
    build_private_payload_receipt,
    sha256_private_text,
    validate_private_text,
)


DEFAULT_PRIVATE_TEXT_STORAGE_ROOT = Path(
    "/data/nex-platform/cx/private-text"
)
PRIVATE_TEXT_STORAGE_ROOT_ENV = "NEX_CX_PRIVATE_TEXT_STORAGE_ROOT"
PRIVATE_TEXT_STORAGE_BACKEND = "filesystem-text-v1"
_PRIVATE_TEXT_FILE_ERRORS = PrivateFileErrorCodes(
    root_invalid="CX_PRIVATE_TEXT_ROOT_INVALID",
    storage_unsafe="CX_PRIVATE_TEXT_STORAGE_UNSAFE",
    storage_unavailable="CX_PRIVATE_TEXT_STORAGE_UNAVAILABLE",
    immutable_conflict="CX_PRIVATE_TEXT_IMMUTABLE_CONFLICT",
)


class FileSystemCxPrivateTextStore:
    """Immutable owner-scoped private text storage for a local filesystem."""

    def __init__(self, root: str | Path) -> None:
        self._storage = ImmutableOwnerScopedFileStorage(
            root,
            backend=PRIVATE_TEXT_STORAGE_BACKEND,
            suffix=".utf8",
            errors=_PRIVATE_TEXT_FILE_ERRORS,
        )

    @property
    def root(self) -> Path:
        return self._storage.root

    def put_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        text: str,
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        assert_private_payload_access(access_context, key)
        verified_text = validate_private_text(
            key=key,
            text=text,
            expected_sha256=expected_sha256,
        )
        payload = verified_text.encode("utf-8")
        self._storage.publish(
            key=key,
            payload=payload,
            expected_sha256=expected_sha256,
        )
        return self._receipt(key, expected_sha256, len(payload))

    def get_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
    ) -> str | None:
        assert_private_payload_access(access_context, key)
        payload = self._storage.read(key)
        if payload is None:
            return None
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_PRIVATE_TEXT_ENCODING_INVALID",
                detail="Stored private text is not valid UTF-8.",
            ) from exc
        return validate_private_text(
            key=key,
            text=text,
            expected_sha256=expected_sha256,
        )

    def delete_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        assert_private_payload_access(access_context, key)
        return self._storage.delete(key)

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        return self._storage.storage_uri(key)

    def _payload_path(self, key: CxPrivatePayloadKey) -> Path:
        return self._storage.payload_path(key)

    def _receipt(
        self,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
        size_bytes: int,
    ) -> CxPrivatePayloadReceipt:
        return build_private_payload_receipt(
            key=key,
            storage_backend=PRIVATE_TEXT_STORAGE_BACKEND,
            storage_uri=self.storage_uri(key),
            sha256=expected_sha256,
            size_bytes=size_bytes,
        )

def build_private_text_store(
    environ: Mapping[str, str] | None = None,
) -> FileSystemCxPrivateTextStore:
    env = os.environ if environ is None else environ
    root = env.get(
        PRIVATE_TEXT_STORAGE_ROOT_ENV,
        str(DEFAULT_PRIVATE_TEXT_STORAGE_ROOT),
    )
    return FileSystemCxPrivateTextStore(root)
