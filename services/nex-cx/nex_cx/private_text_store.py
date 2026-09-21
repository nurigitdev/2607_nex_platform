from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import tempfile

from nex_cx.access_context import CxAccessContext
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


class FileSystemCxPrivateTextStore:
    """Immutable owner-scoped private text storage for a local filesystem."""

    def __init__(self, root: str | Path) -> None:
        raw_root = str(root).strip()
        if not raw_root:
            raise CxPrivateContentError(
                status_code=500,
                error_code="CX_PRIVATE_TEXT_ROOT_INVALID",
                detail="Private text storage root must not be empty.",
            )
        self.root = Path(raw_root).expanduser().resolve(strict=False)

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
        path = self._payload_path(key)
        self._ensure_safe_parent(path.parent)

        if path.exists() or path.is_symlink():
            self._assert_existing_payload(path, expected_sha256)
            return self._receipt(key, expected_sha256, len(payload))

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".cx-private-text-",
            dir=path.parent,
        )
        try:
            with os.fdopen(temp_fd, "wb", closefd=True) as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp_name, path)
            except FileExistsError:
                self._assert_existing_payload(path, expected_sha256)
            self._fsync_directory(path.parent)
        except CxPrivateContentError:
            raise
        except OSError as exc:
            raise CxPrivateContentError(
                status_code=503,
                error_code="CX_PRIVATE_TEXT_STORAGE_UNAVAILABLE",
                detail="Private text storage is unavailable.",
                retryable=True,
            ) from exc
        finally:
            Path(temp_name).unlink(missing_ok=True)

        return self._receipt(key, expected_sha256, len(payload))

    def get_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
    ) -> str | None:
        assert_private_payload_access(access_context, key)
        path = self._payload_path(key)
        if not path.exists() and not path.is_symlink():
            return None
        payload = self._read_payload(path)
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
        path = self._payload_path(key)
        if not path.exists() and not path.is_symlink():
            return False
        self._assert_regular_file(path)
        path.unlink()
        self._fsync_directory(path.parent)
        return True

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        owner_scope = _owner_scope_digest(key)
        content_digest = _content_digest(key)
        return (
            f"cx-private://{PRIVATE_TEXT_STORAGE_BACKEND}/"
            f"{owner_scope}/{key.payload_kind}/{content_digest}"
        )

    def _payload_path(self, key: CxPrivatePayloadKey) -> Path:
        owner_scope = _owner_scope_digest(key)
        content_digest = _content_digest(key)
        return (
            self.root
            / owner_scope[:2]
            / owner_scope
            / key.payload_kind
            / f"{content_digest}.utf8"
        )

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

    def _assert_existing_payload(self, path: Path, expected_sha256: str) -> None:
        payload = self._read_payload(path)
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != expected_sha256:
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_PRIVATE_TEXT_IMMUTABLE_CONFLICT",
                detail="Private text content id is already bound to another payload.",
            )

    def _read_payload(self, path: Path) -> bytes:
        self._assert_regular_file(path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise CxPrivateContentError(
                status_code=503,
                error_code="CX_PRIVATE_TEXT_STORAGE_UNAVAILABLE",
                detail="Private text storage is unavailable.",
                retryable=True,
            ) from exc

    def _assert_regular_file(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise CxPrivateContentError(
                status_code=500,
                error_code="CX_PRIVATE_TEXT_STORAGE_UNSAFE",
                detail="Private text storage entry is not a regular file.",
            )

    def _ensure_safe_parent(self, parent: Path) -> None:
        if self.root.exists() or self.root.is_symlink():
            root_is_safe = not self.root.is_symlink() and self.root.is_dir()
        else:
            self.root.mkdir(mode=0o700, parents=True)
            root_is_safe = True
        if not root_is_safe:
            raise CxPrivateContentError(
                status_code=500,
                error_code="CX_PRIVATE_TEXT_STORAGE_UNSAFE",
                detail="Private text storage root is not a safe directory.",
            )
        relative = parent.relative_to(self.root)
        current = self.root
        for segment in relative.parts:
            current = current / segment
            current.mkdir(mode=0o700, exist_ok=True)
            if current.is_symlink() or not current.is_dir():
                raise CxPrivateContentError(
                    status_code=500,
                    error_code="CX_PRIVATE_TEXT_STORAGE_UNSAFE",
                    detail="Private text storage path is not a safe directory.",
                )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def build_private_text_store(
    environ: Mapping[str, str] | None = None,
) -> FileSystemCxPrivateTextStore:
    env = os.environ if environ is None else environ
    root = env.get(
        PRIVATE_TEXT_STORAGE_ROOT_ENV,
        str(DEFAULT_PRIVATE_TEXT_STORAGE_ROOT),
    )
    return FileSystemCxPrivateTextStore(root)


def _owner_scope_digest(key: CxPrivatePayloadKey) -> str:
    return hashlib.sha256(
        f"{key.tenant_id}\0{key.subject_id}".encode("utf-8")
    ).hexdigest()


def _content_digest(key: CxPrivatePayloadKey) -> str:
    return hashlib.sha256(key.content_id.encode("utf-8")).hexdigest()
