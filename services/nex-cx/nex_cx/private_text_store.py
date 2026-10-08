from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path

from nex_runtime.object_storage import (
    ObjectStorageError,
    ObjectMetadata,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
    object_storage_settings,
)
from nex_runtime.object_storage_migration import (
    ObjectMigrationError,
    configured_migration_read_mode,
    read_with_migration_policy,
)

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
S3_PRIVATE_TEXT_STORAGE_BACKEND = "s3-text-v1"
PRIVATE_STORAGE_MODE_ENV = "NEX_CX_PRIVATE_STORAGE_MODE"
PRIVATE_STORAGE_FILESYSTEM_MODE = "FILESYSTEM"
PRIVATE_STORAGE_S3_MODE = "S3"
MAX_PRIVATE_TEXT_BYTES = 32 * 1024 * 1024
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


class S3CxPrivateTextStore:
    """Owner-scoped CX text adapter over the product-neutral S3 port."""

    def __init__(self, object_store: S3ObjectStore) -> None:
        self.object_store = object_store

    def put_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        text: str,
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        assert_private_payload_access(access_context, key)
        verified = validate_private_text(
            key=key,
            text=text,
            expected_sha256=expected_sha256,
        )
        payload = verified.encode("utf-8")
        if len(payload) > MAX_PRIVATE_TEXT_BYTES:
            raise CxPrivateContentError(
                status_code=413,
                error_code="CX_PRIVATE_TEXT_TOO_LARGE",
                detail="Private text exceeds the object-storage size boundary.",
            )
        try:
            metadata = self.object_store.put_immutable(
                key=self.object_key(key),
                payload=payload,
                expected_sha256=expected_sha256,
                content_type="text/plain; charset=utf-8",
            )
        except ObjectStorageError as exc:
            raise _cx_storage_error(exc) from exc
        return self._receipt(key, metadata)

    def get_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
    ) -> str | None:
        assert_private_payload_access(access_context, key)
        object_key = self.object_key(key)
        try:
            metadata = self.object_store.head(object_key)
            if metadata is None:
                return None
            payload = self.object_store.get_bytes(
                key=object_key,
                expected_sha256=expected_sha256,
                expected_size_bytes=metadata.size_bytes,
                max_size_bytes=MAX_PRIVATE_TEXT_BYTES,
            )
        except ObjectStorageError as exc:
            raise _cx_storage_error(exc) from exc
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
        object_key = self.object_key(key)
        try:
            if self.object_store.head(object_key) is None:
                return False
            self.object_store.delete(object_key)
        except ObjectStorageError as exc:
            raise _cx_storage_error(exc) from exc
        return True

    def object_key(self, key: CxPrivatePayloadKey) -> str:
        return build_owner_object_key(
            payload_family=_payload_family(key.payload_kind),
            tenant_id=key.tenant_id,
            subject_id=key.subject_id,
            content_id=key.content_id,
            suffix="utf8",
        )

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        return f"cx-private://{S3_PRIVATE_TEXT_STORAGE_BACKEND}/{self.object_key(key)}"

    def _receipt(
        self,
        key: CxPrivatePayloadKey,
        metadata: ObjectMetadata,
    ) -> CxPrivatePayloadReceipt:
        return build_private_payload_receipt(
            key=key,
            storage_backend=S3_PRIVATE_TEXT_STORAGE_BACKEND,
            storage_uri=self.storage_uri(key),
            sha256=metadata.sha256,
            size_bytes=metadata.size_bytes,
        )


@dataclass(frozen=True)
class MigratingCxPrivateTextStore:
    target: S3CxPrivateTextStore
    legacy: FileSystemCxPrivateTextStore
    read_mode: str

    def put_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        text: str,
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        return self.target.put_text(
            access_context=access_context,
            key=key,
            text=text,
            expected_sha256=expected_sha256,
        )

    def get_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
    ) -> str | None:
        return read_with_migration_policy(
            self.read_mode,
            object_read=lambda: self.target.get_text(
                access_context=access_context,
                key=key,
                expected_sha256=expected_sha256,
            ),
            filesystem_read=lambda: self.legacy.get_text(
                access_context=access_context,
                key=key,
                expected_sha256=expected_sha256,
            ),
        )

    def delete_text(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        return self.target.delete_text(access_context=access_context, key=key)


def build_private_text_store(
    environ: Mapping[str, str] | None = None,
) -> CxPrivateTextStore:
    env = os.environ if environ is None else environ
    return build_cx_private_text_store(
        env,
        filesystem_root_env=PRIVATE_TEXT_STORAGE_ROOT_ENV,
        default_root=DEFAULT_PRIVATE_TEXT_STORAGE_ROOT,
    )


def build_cx_private_text_store(
    environ: Mapping[str, str],
    *,
    filesystem_root_env: str,
    default_root: Path,
) -> CxPrivateTextStore:
    mode = environ.get(
        PRIVATE_STORAGE_MODE_ENV,
        PRIVATE_STORAGE_FILESYSTEM_MODE,
    ).strip().upper()
    if mode == PRIVATE_STORAGE_FILESYSTEM_MODE:
        return FileSystemCxPrivateTextStore(
            environ.get(filesystem_root_env, str(default_root))
        )
    if mode != PRIVATE_STORAGE_S3_MODE:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_STORAGE_MODE_INVALID",
            detail="CX private storage mode is invalid.",
        )
    allow_insecure = _allow_insecure_object_endpoint(environ)
    try:
        settings = object_storage_settings(
            "nex-cx",
            environ,
            allow_insecure_endpoint=allow_insecure,
        )
        target = S3CxPrivateTextStore(
            S3ObjectStore(build_s3_client(settings), settings)
        )
        read_mode = configured_migration_read_mode("nex-cx", environ)
        if read_mode == "OBJECT_ONLY":
            return target
        return MigratingCxPrivateTextStore(
            target=target,
            legacy=FileSystemCxPrivateTextStore(
                environ.get(filesystem_root_env, str(default_root))
            ),
            read_mode=read_mode,
        )
    except (ObjectStorageError, ObjectMigrationError) as exc:
        raise _cx_storage_error(exc, configuration=True) from exc


def _payload_family(payload_kind: str) -> str:
    if payload_kind in {"chunk_text", "summary_text"}:
        return "text"
    if payload_kind == "generation_request":
        return "generation-request"
    if payload_kind in {"generation_output", "structured_draft"}:
        return "generation-output"
    raise CxPrivateContentError(
        status_code=422,
        error_code="CX_PRIVATE_TEXT_KIND_INVALID",
        detail="The payload key is not valid for private text object storage.",
    )


def _allow_insecure_object_endpoint(environ: Mapping[str, str]) -> bool:
    raw = str(environ.get("NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE", "false")).strip().lower()
    if raw not in {"true", "false"}:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_STORAGE_MODE_INVALID",
            detail="CX object-storage insecure endpoint flag is invalid.",
        )
    if raw == "false":
        return False
    profile = str(environ.get("NEX_RUNTIME_PROFILE", "")).strip().lower()
    if profile not in {"development", "local_mock", "test", "protected_test"}:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_PRIVATE_STORAGE_INSECURE_FORBIDDEN",
            detail="Insecure object-storage endpoints are forbidden for this profile.",
        )
    return True


def _cx_storage_error(
    exc: ObjectStorageError | ObjectMigrationError,
    *,
    configuration: bool = False,
) -> CxPrivateContentError:
    if configuration:
        status_code = 500
        error_code = "CX_PRIVATE_STORAGE_CONFIGURATION_INVALID"
    elif exc.retryable:
        status_code = 503
        error_code = "CX_PRIVATE_TEXT_STORAGE_UNAVAILABLE"
    elif exc.code in {
        "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_METADATA_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
    }:
        status_code = 409
        error_code = "CX_PRIVATE_TEXT_INTEGRITY_FAILED"
    else:
        status_code = 500
        error_code = "CX_PRIVATE_TEXT_STORAGE_INVALID"
    return CxPrivateContentError(
        status_code=status_code,
        error_code=error_code,
        detail="CX private text object storage operation failed.",
        retryable=exc.retryable,
    )
