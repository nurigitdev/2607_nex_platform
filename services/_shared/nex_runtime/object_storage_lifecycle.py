from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Protocol

from nex_runtime.object_storage import ObjectStorageError, S3ObjectStore


DEFAULT_NONCURRENT_RETENTION_DAYS = 30
DEFAULT_MULTIPART_ABORT_DAYS = 7
PURGE_TAG_KEY = "nex-purge"
PURGE_TAG_VALUE = "eligible"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION_ID = re.compile(r"^[A-Za-z0-9._~+/=-]{1,256}$")


@dataclass(frozen=True)
class ObjectLifecycleError(RuntimeError):
    code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class PrivateBucketLifecyclePolicy:
    noncurrent_retention_days: int = DEFAULT_NONCURRENT_RETENTION_DAYS
    multipart_abort_days: int = DEFAULT_MULTIPART_ABORT_DAYS


@dataclass(frozen=True)
class BucketBootstrapReceipt:
    bucket: str
    created: bool
    versioning_enabled: bool
    encryption_algorithm: str
    lifecycle_rule_count: int
    policy_digest: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "private_bucket_bootstrap.v1",
            "status": "VERIFIED",
            "bucket_ref": hashlib.sha256(self.bucket.encode("utf-8")).hexdigest(),
            "created": self.created,
            "versioning_enabled": self.versioning_enabled,
            "encryption_algorithm": self.encryption_algorithm,
            "lifecycle_rule_count": self.lifecycle_rule_count,
            "policy_digest": self.policy_digest,
        }


@dataclass(frozen=True)
class PurgeAdmission:
    admitted: bool
    reason_codes: tuple[str, ...]

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_version_purge_admission.v1",
            "admitted": self.admitted,
            "reason_codes": list(self.reason_codes),
            "destructive_delete_performed": False,
        }


@dataclass(frozen=True)
class PurgeTagReceipt:
    version_count: int
    version_set_digest: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_version_purge_tag.v1",
            "status": "TAGGED",
            "version_count": self.version_count,
            "version_set_digest": self.version_set_digest,
            "destructive_delete_performed": False,
        }


@dataclass(frozen=True)
class ObjectRestoreReceipt:
    restored_from_version_ref: str
    restored_version_ref: str
    sha256: str
    size_bytes: int
    content_type: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "object_version_restore.v1",
            "status": "VERIFIED",
            "restored_from_version_ref": self.restored_from_version_ref,
            "restored_version_ref": self.restored_version_ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "payload_disclosed": False,
            "object_key_disclosed": False,
        }


class ObjectLifecycleClient(Protocol):
    def head_bucket(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def create_bucket(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_bucket_versioning(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_bucket_versioning(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_bucket_encryption(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_bucket_encryption(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_bucket_lifecycle_configuration(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def get_bucket_lifecycle_configuration(
        self, **kwargs: Any
    ) -> Mapping[str, Any]: ...

    def get_object_tagging(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object_tagging(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


def lifecycle_configuration(
    policy: PrivateBucketLifecyclePolicy = PrivateBucketLifecyclePolicy(),
) -> dict[str, Any]:
    _validate_policy(policy)
    return {
        "Rules": [
            {
                "ID": "abort-incomplete-multipart",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "AbortIncompleteMultipartUpload": {
                    "DaysAfterInitiation": policy.multipart_abort_days
                },
            },
            {
                "ID": "purge-eligible-noncurrent-versions",
                "Status": "Enabled",
                "Filter": {
                    "Tag": {"Key": PURGE_TAG_KEY, "Value": PURGE_TAG_VALUE}
                },
                "NoncurrentVersionExpiration": {
                    "NoncurrentDays": policy.noncurrent_retention_days
                },
            },
            {
                "ID": "remove-expired-delete-markers",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"ExpiredObjectDeleteMarker": True},
            },
        ]
    }


def bootstrap_private_bucket(
    client: ObjectLifecycleClient,
    *,
    bucket: str,
    policy: PrivateBucketLifecyclePolicy = PrivateBucketLifecyclePolicy(),
) -> BucketBootstrapReceipt:
    _validate_bucket(bucket)
    lifecycle = lifecycle_configuration(policy)
    created = False
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        if not _not_found(exc):
            raise _client_error("BUCKET_READINESS_FAILED", exc) from exc
        try:
            client.create_bucket(Bucket=bucket)
        except Exception as create_exc:
            raise _client_error("BUCKET_CREATE_FAILED", create_exc) from create_exc
        created = True
    try:
        client.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )
        client.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration=lifecycle,
        )
        versioning = client.get_bucket_versioning(Bucket=bucket)
        encryption = client.get_bucket_encryption(Bucket=bucket)
        observed_lifecycle = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except Exception as exc:
        raise _client_error("BUCKET_POLICY_APPLY_FAILED", exc) from exc
    _verify_bucket_policy(versioning, encryption, observed_lifecycle, lifecycle)
    return BucketBootstrapReceipt(
        bucket=bucket,
        created=created,
        versioning_enabled=True,
        encryption_algorithm="AES256",
        lifecycle_rule_count=len(lifecycle["Rules"]),
        policy_digest=_digest_json(lifecycle),
    )


def assess_purge_admission(
    *,
    active_reference_count: int,
    legal_hold: bool,
    purge_decision_recorded: bool,
    rollback_window_elapsed: bool,
) -> PurgeAdmission:
    if (
        isinstance(active_reference_count, bool)
        or not isinstance(active_reference_count, int)
        or active_reference_count < 0
    ):
        raise _error(
            "PURGE_REFERENCE_COUNT_INVALID",
            "Object reference count is invalid.",
        )
    reasons: list[str] = []
    if active_reference_count:
        reasons.append("active_references_present")
    if legal_hold:
        reasons.append("legal_hold_active")
    if not purge_decision_recorded:
        reasons.append("purge_decision_missing")
    if not rollback_window_elapsed:
        reasons.append("rollback_window_open")
    return PurgeAdmission(admitted=not reasons, reason_codes=tuple(reasons))


def mark_versions_purge_eligible(
    client: ObjectLifecycleClient,
    *,
    bucket: str,
    key: str,
    version_ids: Sequence[str],
    admission: PurgeAdmission,
) -> PurgeTagReceipt:
    _validate_bucket(bucket)
    _validate_key(key)
    versions = tuple(_validate_version_id(value) for value in version_ids)
    if not admission.admitted:
        raise _error("PURGE_NOT_ADMITTED", "Object version purge is not admitted.")
    if not versions or len(versions) != len(set(versions)):
        raise _error("PURGE_VERSION_SET_INVALID", "Object version set is invalid.")
    for version_id in versions:
        try:
            observed = client.get_object_tagging(
                Bucket=bucket,
                Key=key,
                VersionId=version_id,
            )
            tags = _merged_purge_tags(observed)
            client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                VersionId=version_id,
                Tagging={"TagSet": tags},
            )
        except ObjectLifecycleError:
            raise
        except Exception as exc:
            raise _client_error("PURGE_TAGGING_FAILED", exc) from exc
    return PurgeTagReceipt(
        version_count=len(versions),
        version_set_digest=_digest_json(sorted(versions)),
    )


def restore_object_version(
    client: ObjectLifecycleClient,
    store: S3ObjectStore,
    *,
    key: str,
    version_id: str,
    expected_key_prefix: str,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_content_type: str,
    max_size_bytes: int,
) -> ObjectRestoreReceipt:
    _validate_key(key)
    source_version = _validate_version_id(version_id)
    if not expected_key_prefix or not key.startswith(expected_key_prefix):
        raise _error("RESTORE_OWNER_SCOPE_INVALID", "Restore owner scope is invalid.")
    if (
        not _SHA256.fullmatch(expected_sha256)
        or isinstance(expected_size_bytes, bool)
        or not isinstance(expected_size_bytes, int)
        or expected_size_bytes < 0
        or max_size_bytes < 1
        or expected_size_bytes > max_size_bytes
        or not expected_content_type.strip()
    ):
        raise _error("RESTORE_METADATA_INVALID", "Restore metadata is invalid.")
    try:
        if store.head(key) is not None:
            raise _error(
                "RESTORE_ACTIVE_VERSION_CONFLICT",
                "Restore target already has an active version.",
            )
        response = client.get_object(
            Bucket=store.settings.bucket,
            Key=key,
            VersionId=source_version,
        )
    except ObjectLifecycleError:
        raise
    except ObjectStorageError as exc:
        raise _storage_error("RESTORE_TARGET_READ_FAILED", exc) from exc
    except Exception as exc:
        raise _client_error("RESTORE_SOURCE_READ_FAILED", exc) from exc
    payload = _read_version_payload(response, max_size_bytes)
    _verify_restore_source(
        response,
        payload,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        expected_content_type=expected_content_type.strip(),
    )
    try:
        metadata = store.put_immutable(
            key=key,
            payload=payload,
            expected_sha256=expected_sha256,
            content_type=expected_content_type.strip(),
        )
        readable = store.get_bytes(
            key=key,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            max_size_bytes=max_size_bytes,
        )
    except ObjectStorageError as exc:
        raise _storage_error("RESTORE_PUBLICATION_FAILED", exc) from exc
    if readable != payload or metadata.version_id is None:
        raise _error(
            "RESTORE_VERIFICATION_FAILED",
            "Restored object failed current-version verification.",
        )
    return ObjectRestoreReceipt(
        restored_from_version_ref=_version_ref(source_version),
        restored_version_ref=_version_ref(metadata.version_id),
        sha256=metadata.sha256,
        size_bytes=metadata.size_bytes,
        content_type=metadata.content_type,
    )


def _verify_bucket_policy(
    versioning: Mapping[str, Any],
    encryption: Mapping[str, Any],
    observed_lifecycle: Mapping[str, Any],
    expected_lifecycle: Mapping[str, Any],
) -> None:
    if versioning.get("Status") != "Enabled":
        raise _error("BUCKET_VERSIONING_INVALID", "Bucket versioning is not enabled.")
    encryption_config = encryption.get("ServerSideEncryptionConfiguration")
    rules = encryption_config.get("Rules") if isinstance(encryption_config, Mapping) else None
    algorithms: set[str] = set()
    for rule in rules or []:
        if not isinstance(rule, Mapping):
            continue
        default = rule.get("ApplyServerSideEncryptionByDefault")
        if isinstance(default, Mapping):
            algorithms.add(str(default.get("SSEAlgorithm")))
    if algorithms != {"AES256"}:
        raise _error("BUCKET_ENCRYPTION_INVALID", "Bucket encryption policy is invalid.")
    observed_rules = observed_lifecycle.get("Rules")
    if not isinstance(observed_rules, list):
        raise _error("BUCKET_LIFECYCLE_INVALID", "Bucket lifecycle policy is invalid.")
    expected_by_id = {
        str(rule["ID"]): rule for rule in expected_lifecycle["Rules"]
    }
    observed_by_id = {
        str(rule.get("ID")): rule
        for rule in observed_rules
        if isinstance(rule, Mapping)
    }
    if set(observed_by_id) != set(expected_by_id):
        raise _error("BUCKET_LIFECYCLE_INVALID", "Bucket lifecycle policy is invalid.")
    for rule_id, expected in expected_by_id.items():
        observed = observed_by_id[rule_id]
        if any(observed.get(field) != expected.get(field) for field in expected):
            raise _error("BUCKET_LIFECYCLE_INVALID", "Bucket lifecycle policy is invalid.")


def _read_version_payload(response: Mapping[str, Any], max_size_bytes: int) -> bytes:
    body = response.get("Body")
    try:
        payload = body.read(max_size_bytes + 1)
    except Exception as exc:
        raise _client_error("RESTORE_SOURCE_READ_FAILED", exc) from exc
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    if not isinstance(payload, bytes) or len(payload) > max_size_bytes:
        raise _error("RESTORE_SIZE_MISMATCH", "Restore source exceeds its size boundary.")
    return payload


def _verify_restore_source(
    response: Mapping[str, Any],
    payload: bytes,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_content_type: str,
) -> None:
    metadata = response.get("Metadata")
    metadata = (
        {str(name).lower(): value for name, value in metadata.items()}
        if isinstance(metadata, Mapping)
        else {}
    )
    if (
        response.get("DeleteMarker") is True
        or response.get("ContentLength") != expected_size_bytes
        or len(payload) != expected_size_bytes
        or metadata.get("sha256") != expected_sha256
        or hashlib.sha256(payload).hexdigest() != expected_sha256
        or response.get("ContentType") != expected_content_type
        or response.get("ServerSideEncryption") != "AES256"
    ):
        raise _error("RESTORE_INTEGRITY_MISMATCH", "Restore source failed integrity verification.")


def _merged_purge_tags(response: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = response.get("TagSet", [])
    if not isinstance(raw, list):
        raise _error("PURGE_TAG_SET_INVALID", "Object version tag set is invalid.")
    tags: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise _error("PURGE_TAG_SET_INVALID", "Object version tag set is invalid.")
        key = item.get("Key")
        value = item.get("Value")
        if not isinstance(key, str) or not isinstance(value, str):
            raise _error("PURGE_TAG_SET_INVALID", "Object version tag set is invalid.")
        tags[key] = value
    tags[PURGE_TAG_KEY] = PURGE_TAG_VALUE
    return [{"Key": key, "Value": tags[key]} for key in sorted(tags)]


def _validate_policy(policy: PrivateBucketLifecyclePolicy) -> None:
    if (
        isinstance(policy.noncurrent_retention_days, bool)
        or not 1 <= policy.noncurrent_retention_days <= 3650
        or isinstance(policy.multipart_abort_days, bool)
        or not 1 <= policy.multipart_abort_days <= 30
    ):
        raise _error("BUCKET_LIFECYCLE_INVALID", "Bucket lifecycle policy is invalid.")


def _validate_bucket(bucket: str) -> None:
    if (
        not isinstance(bucket, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
        or ".." in bucket
    ):
        raise _error("BUCKET_NAME_INVALID", "Bucket name is invalid.")


def _validate_key(key: str) -> None:
    if (
        not isinstance(key, str)
        or not key.startswith("v1/")
        or ".." in key
        or "//" in key
        or len(key) > 512
    ):
        raise _error("OBJECT_KEY_INVALID", "Object key is invalid.")


def _validate_version_id(value: str) -> str:
    if not isinstance(value, str) or _VERSION_ID.fullmatch(value) is None:
        raise _error("OBJECT_VERSION_INVALID", "Object version identifier is invalid.")
    return value


def _version_ref(version_id: str) -> str:
    return hashlib.sha256(version_id.encode("utf-8")).hexdigest()


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _not_found(exc: Exception) -> bool:
    return _status_code(exc) == 404 or _error_code(exc) in {"NoSuchBucket", "NotFound"}


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


def _client_error(code: str, exc: Exception) -> ObjectLifecycleError:
    status = _status_code(exc)
    return ObjectLifecycleError(
        code,
        "Object lifecycle operation failed.",
        status == 0 or status == 429 or status >= 500,
    )


def _storage_error(code: str, exc: ObjectStorageError) -> ObjectLifecycleError:
    return ObjectLifecycleError(code, "Object restore operation failed.", exc.retryable)


def _error(code: str, detail: str) -> ObjectLifecycleError:
    return ObjectLifecycleError(code, detail)
