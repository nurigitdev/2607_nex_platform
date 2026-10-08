from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Protocol

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
    object_storage_settings,
)


DOCUMENT_BLOB_BACKEND = "s3-document-v1"
DOCUMENT_BLOB_URI_PREFIX = f"cx-private://{DOCUMENT_BLOB_BACKEND}/"
MAX_EXTRACTED_MARKDOWN_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KEY = re.compile(r"^v1/source/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}(?:\.[a-z0-9_-]{1,31})?$")


@dataclass(frozen=True)
class CxDocumentBlobError(RuntimeError):
    error_code: str
    detail: str
    status_code: int
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CxDocumentBlobReceipt:
    storage_backend: str
    storage_key: str
    storage_uri: str
    sha256: str
    size_bytes: int
    version_id: str | None


class CxDocumentBlobStore(Protocol):
    def put_source(
        self,
        *,
        storage_key: str,
        payload: bytes,
        expected_sha256: str,
        content_type: str,
    ) -> CxDocumentBlobReceipt: ...

    def get_source(
        self,
        *,
        storage_key: str,
        expected_sha256: str,
        expected_size_bytes: int,
        max_size_bytes: int,
    ) -> bytes | None: ...

    def put_markdown(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        document_id: str,
        markdown_text: str,
        expected_sha256: str,
    ) -> CxDocumentBlobReceipt: ...

    def get_markdown(
        self,
        *,
        storage_uri: str,
        tenant_id: str,
        subject_id: str,
        document_id: str,
        expected_sha256: str,
    ) -> str | None: ...


class S3CxDocumentBlobStore:
    def __init__(self, object_store: S3ObjectStore) -> None:
        self.object_store = object_store

    def put_source(
        self,
        *,
        storage_key: str,
        payload: bytes,
        expected_sha256: str,
        content_type: str,
    ) -> CxDocumentBlobReceipt:
        _validate_source_key(storage_key, expected_sha256)
        try:
            metadata = self.object_store.put_immutable(
                key=storage_key,
                payload=payload,
                expected_sha256=expected_sha256,
                content_type=content_type,
            )
        except ObjectStorageError as exc:
            raise _blob_error(exc) from exc
        return _receipt(metadata, storage_key)

    def get_source(
        self,
        *,
        storage_key: str,
        expected_sha256: str,
        expected_size_bytes: int,
        max_size_bytes: int,
    ) -> bytes | None:
        _validate_source_key(storage_key, expected_sha256)
        try:
            return self.object_store.get_bytes(
                key=storage_key,
                expected_sha256=expected_sha256,
                expected_size_bytes=expected_size_bytes,
                max_size_bytes=max_size_bytes,
            )
        except ObjectStorageError as exc:
            raise _blob_error(exc) from exc

    def put_markdown(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        document_id: str,
        markdown_text: str,
        expected_sha256: str,
    ) -> CxDocumentBlobReceipt:
        if not isinstance(markdown_text, str):
            raise _invalid("Extracted Markdown must be text.")
        payload = markdown_text.encode("utf-8")
        if len(payload) > MAX_EXTRACTED_MARKDOWN_BYTES:
            raise CxDocumentBlobError(
                "cx.document_blob.markdown_too_large",
                "Extracted Markdown exceeds its object-storage boundary.",
                413,
            )
        _verify(payload, expected_sha256)
        key = self.markdown_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            document_id=document_id,
        )
        try:
            metadata = self.object_store.put_immutable(
                key=key,
                payload=payload,
                expected_sha256=expected_sha256,
                content_type="text/markdown; charset=utf-8",
            )
        except ObjectStorageError as exc:
            raise _blob_error(exc) from exc
        return _receipt(metadata, key)

    def get_markdown(
        self,
        *,
        storage_uri: str,
        tenant_id: str,
        subject_id: str,
        document_id: str,
        expected_sha256: str,
    ) -> str | None:
        key = self.markdown_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            document_id=document_id,
        )
        if storage_uri != f"{DOCUMENT_BLOB_URI_PREFIX}{key}":
            raise _invalid("Extracted Markdown storage reference is invalid.", status_code=409)
        try:
            metadata = self.object_store.head(key)
            if metadata is None:
                return None
            payload = self.object_store.get_bytes(
                key=key,
                expected_sha256=expected_sha256,
                expected_size_bytes=metadata.size_bytes,
                max_size_bytes=MAX_EXTRACTED_MARKDOWN_BYTES,
            )
        except ObjectStorageError as exc:
            raise _blob_error(exc) from exc
        if payload is None:
            return None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _invalid("Stored extracted Markdown is not valid UTF-8.", status_code=409) from exc

    @staticmethod
    def markdown_key(*, tenant_id: str, subject_id: str, document_id: str) -> str:
        try:
            return build_owner_object_key(
                payload_family="extracted",
                tenant_id=tenant_id,
                subject_id=subject_id,
                content_id=document_id,
                suffix="md",
            )
        except ObjectStorageError as exc:
            raise _blob_error(exc) from exc


def build_document_blob_store(
    environ: Mapping[str, str] | None = None,
) -> CxDocumentBlobStore | None:
    env = os.environ if environ is None else environ
    mode = str(env.get("NEX_CX_PRIVATE_STORAGE_MODE", "FILESYSTEM")).strip().upper()
    if mode == "FILESYSTEM":
        return None
    if mode != "S3":
        raise _invalid("CX private storage mode is invalid.", status_code=500)
    allow_insecure = _allow_insecure(env)
    try:
        settings = object_storage_settings(
            "nex-cx", env, allow_insecure_endpoint=allow_insecure
        )
        return S3CxDocumentBlobStore(
            S3ObjectStore(build_s3_client(settings), settings)
        )
    except ObjectStorageError as exc:
        raise CxDocumentBlobError(
            "cx.document_blob.configuration_invalid",
            "CX document object-storage configuration is invalid.",
            500,
            exc.retryable,
        ) from exc


def source_object_key(source_sha256: str, filename: str) -> str:
    if not _SHA256.fullmatch(source_sha256):
        raise _invalid("Source SHA-256 is invalid.")
    suffix = Path(filename).suffix.lower().lstrip(".")
    safe_suffix = suffix if suffix and len(suffix) <= 31 and re.fullmatch(r"[a-z0-9_-]+", suffix) else ""
    extension = f".{safe_suffix}" if safe_suffix else ""
    return f"v1/source/{source_sha256[:2]}/{source_sha256[2:4]}/{source_sha256}{extension}"


def _validate_source_key(storage_key: str, expected_sha256: str) -> None:
    if not _SHA256.fullmatch(expected_sha256) or not _SOURCE_KEY.fullmatch(storage_key):
        raise _invalid("Source object key is invalid.")
    parts = storage_key.split("/")
    key_digest = Path(storage_key).name.split(".", 1)[0]
    if (
        key_digest != expected_sha256
        or parts[2] != expected_sha256[:2]
        or parts[3] != expected_sha256[2:4]
    ):
        raise _invalid("Source object key does not match its SHA-256.", status_code=409)


def _verify(payload: bytes, expected_sha256: str) -> None:
    if not _SHA256.fullmatch(expected_sha256) or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise _invalid("Document blob failed SHA-256 validation.", status_code=409)


def _receipt(metadata, storage_key: str) -> CxDocumentBlobReceipt:
    return CxDocumentBlobReceipt(
        storage_backend=DOCUMENT_BLOB_BACKEND,
        storage_key=storage_key,
        storage_uri=f"{DOCUMENT_BLOB_URI_PREFIX}{storage_key}",
        sha256=metadata.sha256,
        size_bytes=metadata.size_bytes,
        version_id=metadata.version_id,
    )


def _allow_insecure(environ: Mapping[str, str]) -> bool:
    raw = str(environ.get("NEX_CX_OBJECT_STORAGE_ALLOW_INSECURE", "false")).strip().lower()
    if raw not in {"true", "false"}:
        raise _invalid("CX object-storage insecure endpoint flag is invalid.", status_code=500)
    if raw == "false":
        return False
    profile = str(environ.get("NEX_RUNTIME_PROFILE", "")).strip().lower()
    if profile not in {"development", "local_mock", "test", "protected_test"}:
        raise CxDocumentBlobError(
            "cx.document_blob.insecure_endpoint_forbidden",
            "Insecure object-storage endpoints are forbidden for this profile.",
            500,
        )
    return True


def _blob_error(exc: ObjectStorageError) -> CxDocumentBlobError:
    if exc.retryable:
        return CxDocumentBlobError(
            "cx.document_blob.storage_unavailable",
            "CX document object storage is unavailable.",
            503,
            True,
        )
    if exc.code in {
        "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_METADATA_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
    }:
        return CxDocumentBlobError(
            "cx.document_blob.integrity_failed",
            "CX document object failed integrity validation.",
            409,
        )
    return _invalid("CX document object-storage operation failed.", status_code=500)


def _invalid(detail: str, *, status_code: int = 422) -> CxDocumentBlobError:
    return CxDocumentBlobError(
        "cx.document_blob.invalid",
        detail,
        status_code,
    )
