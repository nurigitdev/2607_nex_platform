from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import importlib
import ipaddress
import re
from typing import Any, BinaryIO, Protocol
from urllib.parse import urlsplit


OBJECT_STORAGE_BACKENDS = frozenset({"S3"})
OBJECT_STORAGE_OWNERS = {
    "nex-cx": ("NEX_CX", "nex-cx-private"),
    "nex-ae-api": ("NEX_AE", "nex-ae-private"),
}
_BUCKET = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])$")
_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SUFFIX = re.compile(r"^[a-z0-9]{1,12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDERS = {"change-me", "changeme", "example", "placeholder", "secret"}


class ObjectStorageError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class S3Client(Protocol):
    def head_bucket(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ObjectStorageSettings:
    owner: str
    endpoint_url: str
    bucket: str
    access_key: str
    secret_key: str
    ca_bundle: str | None = None
    region: str = "us-east-1"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ObjectMetadata:
    bucket: str
    key: str
    sha256: str
    size_bytes: int
    content_type: str
    version_id: str | None
    server_side_encryption: str | None

    @property
    def storage_uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def object_storage_settings(
    owner: str,
    environ: Mapping[str, str],
    *,
    allow_insecure_endpoint: bool = False,
) -> ObjectStorageSettings:
    try:
        prefix, default_bucket = OBJECT_STORAGE_OWNERS[owner]
    except KeyError as exc:
        raise ObjectStorageError(
            "OBJECT_STORAGE_OWNER_UNSUPPORTED",
            "Object-storage owner is not supported.",
        ) from exc
    backend = _required(environ, f"{prefix}_OBJECT_STORAGE_BACKEND").upper()
    if backend not in OBJECT_STORAGE_BACKENDS:
        raise ObjectStorageError(
            "OBJECT_STORAGE_BACKEND_UNSUPPORTED",
            "Object-storage backend must use the S3-compatible port.",
        )
    endpoint = _valid_endpoint(
        _required(environ, f"{prefix}_OBJECT_STORAGE_ENDPOINT"),
        allow_insecure=allow_insecure_endpoint,
    )
    bucket = _valid_bucket(
        environ.get(f"{prefix}_OBJECT_STORAGE_BUCKET", default_bucket)
    )
    access_key = _required_secret(environ, f"{prefix}_OBJECT_STORAGE_ACCESS_KEY", 8)
    secret_key = _required_secret(environ, f"{prefix}_OBJECT_STORAGE_SECRET_KEY", 16)
    ca_bundle = _optional(environ.get(f"{prefix}_OBJECT_STORAGE_CA_BUNDLE"))
    region = _optional(environ.get(f"{prefix}_OBJECT_STORAGE_REGION")) or "us-east-1"
    return ObjectStorageSettings(
        owner=owner,
        endpoint_url=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        ca_bundle=ca_bundle,
        region=region,
    )


def build_s3_client(settings: ObjectStorageSettings) -> S3Client:
    boto3 = importlib.import_module("boto3")
    config_module = importlib.import_module("botocore.config")
    config = config_module.Config(
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        retries={"max_attempts": 3, "mode": "standard"},
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        region_name=settings.region,
        verify=settings.ca_bundle or True,
        config=config,
    )


def build_owner_object_key(
    *,
    payload_family: str,
    tenant_id: str,
    subject_id: str,
    content_id: str,
    suffix: str,
) -> str:
    family = payload_family.strip().lower()
    normalized_suffix = suffix.strip().lower().lstrip(".")
    if not _SEGMENT.fullmatch(family) or not _SUFFIX.fullmatch(normalized_suffix):
        raise ObjectStorageError(
            "OBJECT_STORAGE_KEY_INVALID",
            "Object-storage key family or suffix is invalid.",
        )
    owner_digest = hashlib.sha256(
        f"{_identity(tenant_id)}\0{_identity(subject_id)}".encode("utf-8")
    ).hexdigest()
    content_digest = hashlib.sha256(_identity(content_id).encode("utf-8")).hexdigest()
    return (
        f"v1/{family}/{owner_digest[:2]}/{owner_digest}/"
        f"{content_digest}.{normalized_suffix}"
    )


class S3ObjectStore:
    def __init__(self, client: S3Client, settings: ObjectStorageSettings) -> None:
        self.client = client
        self.settings = settings

    def check_ready(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.settings.bucket)
        except Exception as exc:
            raise _client_error("OBJECT_STORAGE_UNAVAILABLE", exc) from exc
        return True

    def head(self, key: str) -> ObjectMetadata | None:
        _validate_key(key)
        try:
            response = self.client.head_object(Bucket=self.settings.bucket, Key=key)
        except Exception as exc:
            if _not_found(exc):
                return None
            raise _client_error("OBJECT_STORAGE_HEAD_FAILED", exc) from exc
        return _metadata(self.settings.bucket, key, response)

    def put_immutable(
        self,
        *,
        key: str,
        payload: bytes,
        expected_sha256: str,
        content_type: str,
    ) -> ObjectMetadata:
        _validate_key(key)
        if not isinstance(payload, bytes):
            raise ObjectStorageError("OBJECT_STORAGE_PAYLOAD_INVALID", "Object payload must be bytes.")
        _verify_payload(payload, expected_sha256)
        existing = self.head(key)
        if existing is not None:
            return _assert_immutable(existing, expected_sha256, len(payload), content_type)
        try:
            self.client.put_object(
                Bucket=self.settings.bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
                Metadata={"sha256": expected_sha256},
                ServerSideEncryption="AES256",
                IfNoneMatch="*",
            )
        except Exception as exc:
            if _status_code(exc) != 412:
                raise _client_error("OBJECT_STORAGE_PUT_FAILED", exc) from exc
        published = self.head(key)
        if published is None:
            raise ObjectStorageError(
                "OBJECT_STORAGE_PUBLISH_INCOMPLETE",
                "Object was not visible after immutable publication.",
                retryable=True,
            )
        return _assert_immutable(published, expected_sha256, len(payload), content_type)

    def get_bytes(
        self,
        *,
        key: str,
        expected_sha256: str,
        expected_size_bytes: int,
        max_size_bytes: int,
    ) -> bytes | None:
        _validate_key(key)
        if expected_size_bytes < 0 or max_size_bytes < 1 or expected_size_bytes > max_size_bytes:
            raise ObjectStorageError("OBJECT_STORAGE_SIZE_INVALID", "Object size boundary is invalid.")
        try:
            response = self.client.get_object(Bucket=self.settings.bucket, Key=key)
        except Exception as exc:
            if _not_found(exc):
                return None
            raise _client_error("OBJECT_STORAGE_GET_FAILED", exc) from exc
        body = response.get("Body")
        try:
            payload = body.read(max_size_bytes + 1)
        except Exception as exc:
            raise _client_error("OBJECT_STORAGE_READ_FAILED", exc) from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, bytes) or len(payload) > max_size_bytes:
            raise ObjectStorageError("OBJECT_STORAGE_SIZE_MISMATCH", "Stored object exceeds its size boundary.")
        _verify_payload(payload, expected_sha256)
        if len(payload) != expected_size_bytes:
            raise ObjectStorageError("OBJECT_STORAGE_SIZE_MISMATCH", "Stored object size does not match metadata.")
        return payload

    def delete(self, key: str) -> str | None:
        _validate_key(key)
        try:
            response = self.client.delete_object(Bucket=self.settings.bucket, Key=key)
        except Exception as exc:
            raise _client_error("OBJECT_STORAGE_DELETE_FAILED", exc) from exc
        value = response.get("VersionId")
        return str(value) if value else None


def _metadata(bucket: str, key: str, response: Mapping[str, Any]) -> ObjectMetadata:
    metadata = response.get("Metadata")
    metadata = (
        {str(name).lower(): value for name, value in metadata.items()}
        if isinstance(metadata, Mapping)
        else {}
    )
    sha256 = str(metadata.get("sha256") or "")
    size = response.get("ContentLength")
    content_type = str(response.get("ContentType") or "application/octet-stream")
    if not _SHA256.fullmatch(sha256) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ObjectStorageError("OBJECT_STORAGE_METADATA_INVALID", "Stored object metadata is invalid.")
    version = response.get("VersionId")
    encryption = response.get("ServerSideEncryption")
    return ObjectMetadata(
        bucket=bucket,
        key=key,
        sha256=sha256,
        size_bytes=size,
        content_type=content_type,
        version_id=str(version) if version else None,
        server_side_encryption=str(encryption) if encryption else None,
    )


def _assert_immutable(
    metadata: ObjectMetadata,
    sha256: str,
    size: int,
    content_type: str,
) -> ObjectMetadata:
    if (
        metadata.sha256 != sha256
        or metadata.size_bytes != size
        or metadata.content_type != content_type
        or metadata.server_side_encryption != "AES256"
    ):
        raise ObjectStorageError(
            "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
            "Object key is already bound to different or unsafe content.",
        )
    return metadata


def _verify_payload(payload: bytes, expected_sha256: str) -> None:
    if not _SHA256.fullmatch(expected_sha256) or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ObjectStorageError("OBJECT_STORAGE_INTEGRITY_MISMATCH", "Object payload failed integrity validation.")


def _validate_key(key: str) -> None:
    if not key.startswith("v1/") or ".." in key or "//" in key or len(key) > 512:
        raise ObjectStorageError("OBJECT_STORAGE_KEY_INVALID", "Object-storage key is invalid.")


def _valid_bucket(value: str) -> str:
    bucket = str(value).strip()
    try:
        ipaddress.ip_address(bucket)
    except ValueError:
        pass
    else:
        raise ObjectStorageError("OBJECT_STORAGE_BUCKET_INVALID", "Object-storage bucket is invalid.")
    if not _BUCKET.fullmatch(bucket) or ".." in bucket or ".-" in bucket or "-." in bucket:
        raise ObjectStorageError("OBJECT_STORAGE_BUCKET_INVALID", "Object-storage bucket is invalid.")
    return bucket


def _valid_endpoint(value: str, *, allow_insecure: bool) -> str:
    endpoint = value.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    allowed_schemes = {"https"} | ({"http"} if allow_insecure else set())
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ObjectStorageError("OBJECT_STORAGE_ENDPOINT_INVALID", "Object-storage endpoint is invalid.")
    return endpoint


def _required(environ: Mapping[str, str], name: str) -> str:
    value = _optional(environ.get(name))
    if value is None:
        raise ObjectStorageError("OBJECT_STORAGE_CONFIGURATION_MISSING", f"{name} is required.")
    return value


def _required_secret(environ: Mapping[str, str], name: str, minimum: int) -> str:
    value = _required(environ, name)
    if len(value) < minimum or value.lower() in _PLACEHOLDERS:
        raise ObjectStorageError("OBJECT_STORAGE_CREDENTIAL_INVALID", f"{name} is invalid.")
    return value


def _optional(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _identity(value: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 256:
        raise ObjectStorageError("OBJECT_STORAGE_IDENTITY_INVALID", "Object owner or content identity is invalid.")
    return text


def _not_found(exc: Exception) -> bool:
    return _status_code(exc) == 404 or _error_code(exc) in {"NoSuchKey", "NotFound"}


def _status_code(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return 0
    metadata = response.get("ResponseMetadata")
    return int(metadata.get("HTTPStatusCode", 0)) if isinstance(metadata, Mapping) else 0


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return ""
    error = response.get("Error")
    return str(error.get("Code") or "") if isinstance(error, Mapping) else ""


def _client_error(code: str, exc: Exception) -> ObjectStorageError:
    status = _status_code(exc)
    return ObjectStorageError(
        code,
        "Object-storage operation failed.",
        retryable=status == 0 or status == 429 or status >= 500,
    )
