from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Protocol

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
)
from nex_runtime.object_storage_migration import (
    ObjectMigrationError,
    configured_migration_read_mode,
    read_with_migration_policy,
)
from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    ae_private_storage_mode,
    build_ae_private_object_store,
)


GENERATED_RESPONSE_STORAGE_ENV = "NEX_AE_CHAT_RESPONSE_STORAGE_ROOT"
GENERATED_RESPONSE_STORAGE_SCHEME = "ae://chat-responses/"
MAX_GENERATED_RESPONSE_BYTES = 16 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GeneratedResponseStorageError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class GeneratedResponseStorage(Protocol):
    def save(self, payload: Mapping[str, Any]) -> str:
        ...

    def load(self, metadata: Mapping[str, Any]) -> str | None:
        ...

    def delete(self, metadata: Mapping[str, Any]) -> bool:
        ...


def build_generated_response_payload(
    *,
    response_id: str,
    content: str,
    content_type: str = "text/plain; charset=utf-8",
) -> dict[str, Any]:
    normalized_id = _required_safe_id(response_id)
    normalized_type = _required_content_type(content_type)
    if not isinstance(content, str):
        raise _invalid("Generated response content must be a string.")
    encoded = content.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "response_id": normalized_id,
        "content_type": normalized_type,
        "content": content,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": build_generated_response_storage_ref(
            normalized_id,
            digest,
        ),
    }


def generated_response_storage_metadata(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_generated_response_payload(payload, require_content=True)
    return {key: value for key, value in normalized.items() if key != "content"}


def validate_generated_response_payload(
    value: object,
    *,
    require_content: bool,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Generated response storage payload must be an object.")
    required = {
        "response_id",
        "content_type",
        "content_sha256",
        "size_bytes",
        "storage_ref",
    }
    if require_content:
        required.add("content")
    if set(value) != required:
        raise _invalid("Generated response storage payload has an invalid shape.")
    response_id = _required_safe_id(value.get("response_id"))
    content_type = _required_content_type(value.get("content_type"))
    digest = value.get("content_sha256")
    size_bytes = value.get("size_bytes")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise _invalid("Generated response content digest is invalid.")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise _invalid("Generated response content size is invalid.")
    expected_ref = build_generated_response_storage_ref(response_id, digest)
    if value.get("storage_ref") != expected_ref:
        raise _invalid("Generated response storage reference is inconsistent.")
    normalized = {
        "response_id": response_id,
        "content_type": content_type,
        "content_sha256": digest,
        "size_bytes": size_bytes,
        "storage_ref": expected_ref,
    }
    if require_content:
        content = value.get("content")
        if not isinstance(content, str):
            raise _invalid("Generated response content must be a string.")
        _verify_content(content, digest=digest, size_bytes=size_bytes)
        normalized["content"] = content
    return normalized


def build_generated_response_storage_ref(
    response_id: str,
    content_sha256: str,
) -> str:
    normalized_id = _required_safe_id(response_id)
    if (
        not isinstance(content_sha256, str)
        or _SHA256.fullmatch(content_sha256) is None
    ):
        raise _invalid("Generated response content digest is invalid.")
    return (
        f"{GENERATED_RESPONSE_STORAGE_SCHEME}{content_sha256[:2]}/"
        f"{content_sha256[2:4]}/{normalized_id}.txt"
    )


@dataclass
class InMemoryGeneratedResponseStorage:
    payloads: dict[str, bytes] = field(default_factory=dict)

    def save(self, payload: Mapping[str, Any]) -> str:
        normalized = validate_generated_response_payload(
            payload,
            require_content=True,
        )
        storage_ref = str(normalized["storage_ref"])
        self.payloads[storage_ref] = str(normalized["content"]).encode("utf-8")
        return storage_ref

    def load(self, metadata: Mapping[str, Any]) -> str | None:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        payload = self.payloads.get(str(normalized["storage_ref"]))
        if payload is None:
            return None
        return _verified_decoded_content(payload, normalized)

    def delete(self, metadata: Mapping[str, Any]) -> bool:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        return self.payloads.pop(str(normalized["storage_ref"]), None) is not None


@dataclass(frozen=True)
class LocalGeneratedResponseStorage:
    root: Path

    def save(self, payload: Mapping[str, Any]) -> str:
        normalized = validate_generated_response_payload(
            payload,
            require_content=True,
        )
        storage_ref = str(normalized["storage_ref"])
        path = self.path_for_storage_ref(storage_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = str(normalized["content"]).encode("utf-8")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
            path.chmod(0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise GeneratedResponseStorageError(
                error_code="ae.generated_response_storage_unavailable",
                detail="AE generated response storage is unavailable.",
                retryable=True,
            ) from exc
        return storage_ref

    def load(self, metadata: Mapping[str, Any]) -> str | None:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        path = self.path_for_storage_ref(str(normalized["storage_ref"]))
        if not path.exists():
            return None
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise GeneratedResponseStorageError(
                error_code="ae.generated_response_storage_unavailable",
                detail="AE generated response storage is unavailable.",
                retryable=True,
            ) from exc
        return _verified_decoded_content(payload, normalized)

    def delete(self, metadata: Mapping[str, Any]) -> bool:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        path = self.path_for_storage_ref(str(normalized["storage_ref"]))
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise GeneratedResponseStorageError(
                error_code="ae.generated_response_storage_unavailable",
                detail="AE generated response storage is unavailable.",
                retryable=True,
            ) from exc
        return True

    def path_for_storage_ref(self, storage_ref: str) -> Path:
        relative = _storage_ref_relative_path(storage_ref)
        root = self.root.resolve()
        path = root.joinpath(*relative.split("/")).resolve(strict=False)
        if not path.is_relative_to(root):
            raise _invalid("Generated response storage reference escapes its root.")
        return path


@dataclass(frozen=True)
class S3GeneratedResponseStorage:
    object_store: S3ObjectStore

    def save_for_owner(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> str:
        normalized = validate_generated_response_payload(
            payload,
            require_content=True,
        )
        encoded = str(normalized["content"]).encode("utf-8")
        if len(encoded) > MAX_GENERATED_RESPONSE_BYTES:
            raise _invalid("Generated response exceeds its storage boundary.")
        key = self._key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            response_id=str(normalized["response_id"]),
        )
        try:
            self.object_store.put_immutable(
                key=key,
                payload=encoded,
                expected_sha256=str(normalized["content_sha256"]),
                content_type=str(normalized["content_type"]),
            )
        except ObjectStorageError as exc:
            raise _s3_storage_error(exc) from exc
        return str(normalized["storage_ref"])

    def load_for_owner(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> str | None:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        key = self._key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            response_id=str(normalized["response_id"]),
        )
        try:
            payload = self.object_store.get_bytes(
                key=key,
                expected_sha256=str(normalized["content_sha256"]),
                expected_size_bytes=int(normalized["size_bytes"]),
                max_size_bytes=MAX_GENERATED_RESPONSE_BYTES,
            )
        except ObjectStorageError as exc:
            raise _s3_storage_error(exc) from exc
        if payload is None:
            return None
        return _verified_decoded_content(payload, normalized)

    def delete_for_owner(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> bool:
        normalized = validate_generated_response_payload(
            metadata,
            require_content=False,
        )
        key = self._key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            response_id=str(normalized["response_id"]),
        )
        try:
            if self.object_store.head(key) is None:
                return False
            self.object_store.delete(key)
        except ObjectStorageError as exc:
            raise _s3_storage_error(exc) from exc
        return True

    @staticmethod
    def _key(*, tenant_id: str, subject_id: str, response_id: str) -> str:
        try:
            return build_owner_object_key(
                payload_family="chat-response",
                tenant_id=tenant_id,
                subject_id=subject_id,
                content_id=response_id,
                suffix="txt",
            )
        except ObjectStorageError as exc:
            raise _s3_storage_error(exc) from exc


@dataclass(frozen=True)
class MigratingGeneratedResponseStorage:
    target: S3GeneratedResponseStorage
    legacy: LocalGeneratedResponseStorage
    read_mode: str

    def save_for_owner(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> str:
        return self.target.save_for_owner(
            payload,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )

    def load_for_owner(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> str | None:
        return read_with_migration_policy(
            self.read_mode,
            object_read=lambda: self.target.load_for_owner(
                metadata,
                tenant_id=tenant_id,
                subject_id=subject_id,
            ),
            filesystem_read=lambda: self.legacy.load(metadata),
        )

    def delete_for_owner(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        subject_id: str,
    ) -> bool:
        return self.target.delete_for_owner(
            metadata,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )


def save_generated_response_for_record(
    storage: GeneratedResponseStorage,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> str:
    owner_method = getattr(storage, "save_for_owner", None)
    if callable(owner_method):
        tenant_id, subject_id = _record_owner_scope(record)
        return owner_method(
            payload,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
    return storage.save(payload)


def load_generated_response_for_record(
    storage: GeneratedResponseStorage,
    metadata: Mapping[str, Any],
    record: Mapping[str, Any],
) -> str | None:
    owner_method = getattr(storage, "load_for_owner", None)
    if callable(owner_method):
        tenant_id, subject_id = _record_owner_scope(record)
        return owner_method(
            metadata,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
    return storage.load(metadata)


def delete_generated_response_for_record(
    storage: GeneratedResponseStorage,
    metadata: Mapping[str, Any],
    record: Mapping[str, Any],
) -> bool:
    owner_method = getattr(storage, "delete_for_owner", None)
    if callable(owner_method):
        tenant_id, subject_id = _record_owner_scope(record)
        return owner_method(
            metadata,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
    return storage.delete(metadata)


def build_default_generated_response_storage(
    environ: Mapping[str, str] | None = None,
) -> GeneratedResponseStorage:
    env = environ if environ is not None else os.environ
    try:
        mode = ae_private_storage_mode(env)
        if mode == "S3":
            target = S3GeneratedResponseStorage(build_ae_private_object_store(env))
            read_mode = configured_migration_read_mode("nex-ae-api", env)
            if read_mode == "OBJECT_ONLY":
                return target
            root = env.get(GENERATED_RESPONSE_STORAGE_ENV)
            if not isinstance(root, str) or not root.strip():
                raise _invalid(
                    "AE generated response migration requires its filesystem root."
                )
            return MigratingGeneratedResponseStorage(
                target=target,
                legacy=LocalGeneratedResponseStorage(Path(root.strip())),
                read_mode=read_mode,
            )
    except (AePrivateObjectStorageError, ObjectMigrationError) as exc:
        raise GeneratedResponseStorageError(
            error_code=getattr(exc, "error_code", None)
            or "ae.generated_response_migration_invalid",
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc
    root = env.get(GENERATED_RESPONSE_STORAGE_ENV)
    if mode == "FILESYSTEM" and (not isinstance(root, str) or not root.strip()):
        raise _invalid("AE generated response filesystem root is required.")
    if not isinstance(root, str) or not root.strip():
        return InMemoryGeneratedResponseStorage()
    return LocalGeneratedResponseStorage(Path(root.strip()))


def _record_owner_scope(record: Mapping[str, Any]) -> tuple[str, str]:
    tenant_id = record.get("tenant_id")
    subject_id = record.get("owner_user_id") or record.get("user_id")
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or not isinstance(subject_id, str)
        or not subject_id.strip()
    ):
        raise _invalid("Generated response owner scope is invalid.")
    return tenant_id.strip(), subject_id.strip()


def _s3_storage_error(exc: ObjectStorageError) -> GeneratedResponseStorageError:
    if exc.retryable:
        return GeneratedResponseStorageError(
            "ae.generated_response_storage_unavailable",
            "AE generated response storage is unavailable.",
            True,
        )
    if exc.code in {
        "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_METADATA_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
    }:
        return _integrity_error()
    return _invalid("AE generated response object-storage operation failed.")


def _storage_ref_relative_path(storage_ref: object) -> str:
    if not isinstance(storage_ref, str) or not storage_ref.startswith(
        GENERATED_RESPONSE_STORAGE_SCHEME
    ):
        raise _invalid("Generated response storage reference is invalid.")
    relative = storage_ref.removeprefix(GENERATED_RESPONSE_STORAGE_SCHEME)
    parts = relative.split("/")
    if (
        len(parts) != 3
        or any(part in {"", ".", ".."} for part in parts)
        or not _SAFE_ID.fullmatch(parts[0])
        or not _SAFE_ID.fullmatch(parts[1])
        or not parts[2].endswith(".txt")
        or not _SAFE_ID.fullmatch(parts[2][:-4])
    ):
        raise _invalid("Generated response storage reference is invalid.")
    return relative


def _verified_decoded_content(
    payload: bytes,
    metadata: Mapping[str, Any],
) -> str:
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _integrity_error() from exc
    _verify_content(
        content,
        digest=str(metadata["content_sha256"]),
        size_bytes=int(metadata["size_bytes"]),
    )
    return content


def _verify_content(content: str, *, digest: str, size_bytes: int) -> None:
    encoded = content.encode("utf-8")
    if len(encoded) != size_bytes or hashlib.sha256(encoded).hexdigest() != digest:
        raise _integrity_error()


def _required_safe_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value.strip()) is None:
        raise _invalid("Generated response identifier is invalid.")
    return value.strip()


def _required_content_type(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip().startswith("text/")
        or len(value.strip()) > 120
    ):
        raise _invalid("Generated response content type is invalid.")
    return value.strip()


def _invalid(detail: str) -> GeneratedResponseStorageError:
    return GeneratedResponseStorageError(
        error_code="ae.generated_response_storage_invalid",
        detail=detail,
    )


def _integrity_error() -> GeneratedResponseStorageError:
    return GeneratedResponseStorageError(
        error_code="ae.generated_response_integrity_failed",
        detail="AE generated response content integrity verification failed.",
    )
