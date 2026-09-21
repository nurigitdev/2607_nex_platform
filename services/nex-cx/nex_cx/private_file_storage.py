from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

from nex_cx.private_content import CxPrivateContentError, CxPrivatePayloadKey


@dataclass(frozen=True)
class PrivateFileErrorCodes:
    root_invalid: str
    storage_unsafe: str
    storage_unavailable: str
    immutable_conflict: str


class ImmutableOwnerScopedFileStorage:
    def __init__(
        self,
        root: str | Path,
        *,
        backend: str,
        suffix: str,
        errors: PrivateFileErrorCodes,
    ) -> None:
        raw_root = str(root).strip()
        if not raw_root:
            raise CxPrivateContentError(
                status_code=500,
                error_code=errors.root_invalid,
                detail="Private payload storage root must not be empty.",
            )
        self.root = Path(raw_root).expanduser().resolve(strict=False)
        self.backend = backend
        self.suffix = suffix
        self.errors = errors

    def publish(
        self,
        *,
        key: CxPrivatePayloadKey,
        payload: bytes,
        expected_sha256: str,
    ) -> None:
        path = self.payload_path(key)
        self._ensure_safe_parent(path.parent)
        if path.exists() or path.is_symlink():
            self._assert_existing_payload(path, expected_sha256)
            return

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".cx-private-payload-",
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
            raise self._unavailable_error() from exc
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def read(self, key: CxPrivatePayloadKey) -> bytes | None:
        path = self.payload_path(key)
        if not path.exists() and not path.is_symlink():
            return None
        self._assert_regular_file(path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise self._unavailable_error() from exc

    def delete(self, key: CxPrivatePayloadKey) -> bool:
        path = self.payload_path(key)
        if not path.exists() and not path.is_symlink():
            return False
        self._assert_regular_file(path)
        try:
            path.unlink()
            self._fsync_directory(path.parent)
        except OSError as exc:
            raise self._unavailable_error() from exc
        return True

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        owner_scope = _owner_scope_digest(key)
        content_digest = _content_digest(key)
        return (
            f"cx-private://{self.backend}/"
            f"{owner_scope}/{key.payload_kind}/{content_digest}"
        )

    def payload_path(self, key: CxPrivatePayloadKey) -> Path:
        owner_scope = _owner_scope_digest(key)
        content_digest = _content_digest(key)
        return (
            self.root
            / owner_scope[:2]
            / owner_scope
            / key.payload_kind
            / f"{content_digest}{self.suffix}"
        )

    def _assert_existing_payload(self, path: Path, expected_sha256: str) -> None:
        payload = self._read_existing(path)
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise CxPrivateContentError(
                status_code=409,
                error_code=self.errors.immutable_conflict,
                detail="Private content id is already bound to another payload.",
            )

    def _read_existing(self, path: Path) -> bytes:
        self._assert_regular_file(path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise self._unavailable_error() from exc

    def _assert_regular_file(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise CxPrivateContentError(
                status_code=500,
                error_code=self.errors.storage_unsafe,
                detail="Private payload storage entry is not a regular file.",
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
                error_code=self.errors.storage_unsafe,
                detail="Private payload storage root is not a safe directory.",
            )
        relative = parent.relative_to(self.root)
        current = self.root
        for segment in relative.parts:
            current = current / segment
            current.mkdir(mode=0o700, exist_ok=True)
            if current.is_symlink() or not current.is_dir():
                raise CxPrivateContentError(
                    status_code=500,
                    error_code=self.errors.storage_unsafe,
                    detail="Private payload storage path is not a safe directory.",
                )

    def _unavailable_error(self) -> CxPrivateContentError:
        return CxPrivateContentError(
            status_code=503,
            error_code=self.errors.storage_unavailable,
            detail="Private payload storage is unavailable.",
            retryable=True,
        )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _owner_scope_digest(key: CxPrivatePayloadKey) -> str:
    return hashlib.sha256(
        f"{key.tenant_id}\0{key.subject_id}".encode("utf-8")
    ).hexdigest()


def _content_digest(key: CxPrivatePayloadKey) -> str:
    return hashlib.sha256(key.content_id.encode("utf-8")).hexdigest()
