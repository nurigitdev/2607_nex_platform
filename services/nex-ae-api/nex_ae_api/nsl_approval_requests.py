from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from nex_runtime.object_storage import (
    ObjectStorageError,
    S3ObjectStore,
    build_owner_object_key,
)
from nex_runtime.semantic_hashes import (
    canonical_json,
    hash_ref_from_sha256,
    sha256_text,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    ae_private_storage_mode,
    build_ae_private_object_store,
)

PROTECTED_APPROVAL_REQUEST_SCHEMA_VERSION = "ae_nsl_approval_request.v1"
PROTECTED_APPROVAL_REQUEST_STORAGE_ENV = "NEX_AE_NSL_APPROVAL_REQUEST_STORAGE_ROOT"
PROTECTED_APPROVAL_REQUEST_STORAGE_SCHEME = "ae://nsl-approval-requests/"
PROTECTED_APPROVAL_REQUEST_CONTENT_TYPE = "application/json"
MAX_PROTECTED_APPROVAL_REQUEST_BYTES = 1024 * 1024

_REQUEST_FIELDS = frozenset(
    {
        "tenant_id",
        "execution_id",
        "business_operation_id",
        "approval_id",
        "approval_request_id",
        "skill_id",
        "skill_version",
        "skill_semantic_hash",
        "write_node_id",
        "tool_id",
        "payload_hash",
        "write_intent_hash",
        "risk_level",
        "message",
        "expires_at",
        "display_safe_summary",
        "protected_payload_ref",
        "data_classification",
    }
)
_RISK_LEVELS = frozenset({"R0", "R1", "R2", "R3", "R4", "R5"})
_CLASSIFICATIONS = frozenset({"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
_STORAGE_REF = re.compile(
    r"^ae://nsl-approval-requests/[0-9a-f]{2}/[0-9a-f]{64}\.json$"
)


@dataclass(frozen=True)
class ProtectedApprovalRequestError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ProtectedApprovalRequestStorage(Protocol):
    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> str: ...

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> dict[str, Any] | None: ...


def build_protected_approval_request_payload(
    approval_request: object,
) -> dict[str, Any]:
    request = canonical_approval_request_data(approval_request)
    content = canonical_json(request)
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > MAX_PROTECTED_APPROVAL_REQUEST_BYTES:
        raise _invalid("NSL ApprovalRequest size is outside the protected boundary.")
    digest = sha256_text(content)
    identity_digest = sha256_text(
        canonical_json(
            {
                "tenant_id": request["tenant_id"],
                "approval_request_id": request["approval_request_id"],
            }
        )
    )
    return {
        "approval_request_id": request["approval_request_id"],
        "content": content,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": (
            f"{PROTECTED_APPROVAL_REQUEST_STORAGE_SCHEME}"
            f"{identity_digest[:2]}/{identity_digest}.json"
        ),
    }


def protected_approval_request_payload_metadata(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _validate_payload(payload, require_content=True)
    return {key: value for key, value in normalized.items() if key != "content"}


def canonical_approval_request_data(value: object) -> dict[str, Any]:
    to_data = getattr(value, "to_data", None)
    if not callable(to_data):
        raise _invalid("NSL ApprovalRequest must expose its canonical to_data API.")
    try:
        raw = to_data()
    except Exception as exc:
        raise _invalid("NSL ApprovalRequest canonical serialization failed.") from exc
    if not isinstance(raw, Mapping) or set(raw) != _REQUEST_FIELDS:
        raise _invalid("NSL ApprovalRequest fields do not match the admitted API.")
    try:
        request = json.loads(canonical_json(dict(raw)))
    except (TypeError, ValueError) as exc:
        raise _invalid("NSL ApprovalRequest is not canonical JSON.") from exc
    for field_name, maximum in (
        ("tenant_id", 128),
        ("execution_id", 256),
        ("business_operation_id", 256),
        ("approval_id", 256),
        ("approval_request_id", 256),
        ("skill_id", 256),
        ("skill_version", 128),
        ("write_node_id", 256),
        ("tool_id", 256),
        ("write_intent_hash", 256),
        ("message", 4096),
    ):
        _required_text(field_name, request[field_name], maximum)
    for field_name in ("skill_semantic_hash", "payload_hash"):
        try:
            validate_hash_ref(request[field_name])
        except ValueError as exc:
            raise _invalid(f"NSL ApprovalRequest {field_name} is invalid.") from exc
    if request["risk_level"] not in _RISK_LEVELS:
        raise _invalid("NSL ApprovalRequest risk level is invalid.")
    if request["data_classification"] not in _CLASSIFICATIONS:
        raise _invalid("NSL ApprovalRequest data classification is invalid.")
    if not isinstance(request["display_safe_summary"], dict):
        raise _invalid("NSL ApprovalRequest display summary must be an object.")
    _optional_text("protected_payload_ref", request["protected_payload_ref"], 1024)
    _optional_timestamp("expires_at", request["expires_at"])
    return request


@dataclass
class InMemoryProtectedApprovalRequestStorage:
    payloads: dict[tuple[str, str, str], bytes] = field(default_factory=dict)

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        _required_text("execution_id", execution_id, 256)
        key = _owner_key(
            tenant_id,
            normalized["approval_request_id"],
            normalized["storage_ref"],
        )
        encoded = str(normalized["content"]).encode("utf-8")
        existing = self.payloads.get(key)
        if existing is not None and existing != encoded:
            raise _conflict()
        self.payloads[key] = encoded
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        _required_text("execution_id", execution_id, 256)
        payload = self.payloads.get(
            _owner_key(
                tenant_id,
                normalized["approval_request_id"],
                normalized["storage_ref"],
            )
        )
        return None if payload is None else _decode_request(payload, normalized)


@dataclass(frozen=True)
class LocalProtectedApprovalRequestStorage:
    root: Path

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        _required_text("execution_id", execution_id, 256)
        path = self._path(
            tenant_id,
            normalized["approval_request_id"],
            normalized["storage_ref"],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = str(normalized["content"]).encode("utf-8")
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise _unavailable() from exc
            if existing != encoded:
                raise _conflict()
            return str(normalized["storage_ref"])
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
            raise _unavailable() from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        _required_text("execution_id", execution_id, 256)
        path = self._path(
            tenant_id,
            normalized["approval_request_id"],
            normalized["storage_ref"],
        )
        if not path.exists():
            return None
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise _unavailable() from exc
        return _decode_request(payload, normalized)

    def _path(
        self, tenant_id: str, approval_request_id: str, storage_ref: object
    ) -> Path:
        owner_digest = sha256_text(
            f"{_required_text('tenant_id', tenant_id, 128)}\0"
            f"{_required_text('approval_request_id', approval_request_id, 256)}"
        )
        relative = _storage_ref_relative_path(storage_ref)
        root = self.root.resolve()
        path = root.joinpath(
            owner_digest[:2], owner_digest, *relative.split("/")
        ).resolve(strict=False)
        if not path.is_relative_to(root):
            raise _invalid("Protected ApprovalRequest reference escapes its root.")
        return path


@dataclass(frozen=True)
class S3ProtectedApprovalRequestStorage:
    object_store: S3ObjectStore

    def save(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> str:
        normalized = _validate_payload(payload, require_content=True)
        _required_text("execution_id", execution_id, 256)
        encoded = str(normalized["content"]).encode("utf-8")
        try:
            self.object_store.put_immutable(
                key=self._key(
                    tenant_id,
                    normalized["approval_request_id"],
                    normalized["approval_request_id"],
                ),
                payload=encoded,
                expected_sha256=str(normalized["content_sha256"]),
                content_type=PROTECTED_APPROVAL_REQUEST_CONTENT_TYPE,
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return str(normalized["storage_ref"])

    def load(
        self,
        metadata: Mapping[str, Any],
        *,
        tenant_id: str,
        execution_id: str,
    ) -> dict[str, Any] | None:
        normalized = _validate_payload(metadata, require_content=False)
        _required_text("execution_id", execution_id, 256)
        try:
            payload = self.object_store.get_bytes(
                key=self._key(
                    tenant_id,
                    normalized["approval_request_id"],
                    normalized["approval_request_id"],
                ),
                expected_sha256=str(normalized["content_sha256"]),
                expected_size_bytes=int(normalized["size_bytes"]),
                max_size_bytes=MAX_PROTECTED_APPROVAL_REQUEST_BYTES,
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc
        return None if payload is None else _decode_request(payload, normalized)

    @staticmethod
    def _key(tenant_id: str, approval_request_id: str, request_id: object) -> str:
        try:
            return build_owner_object_key(
                payload_family="approval-request",
                tenant_id=_required_text("tenant_id", tenant_id, 128),
                subject_id=_required_text(
                    "approval_request_id", approval_request_id, 256
                ),
                content_id=_required_text("approval_request_id", request_id, 256),
                suffix="json",
            )
        except ObjectStorageError as exc:
            raise _object_storage_error(exc) from exc


def build_default_protected_approval_request_storage(
    environ: Mapping[str, str] | None = None,
) -> ProtectedApprovalRequestStorage:
    env = os.environ if environ is None else environ
    try:
        mode = ae_private_storage_mode(env)
        if mode == "S3":
            return S3ProtectedApprovalRequestStorage(build_ae_private_object_store(env))
    except AePrivateObjectStorageError as exc:
        raise ProtectedApprovalRequestError(
            exc.error_code, exc.detail, exc.retryable
        ) from exc
    root = env.get(PROTECTED_APPROVAL_REQUEST_STORAGE_ENV)
    if mode == "FILESYSTEM" and (not isinstance(root, str) or not root.strip()):
        raise _invalid("AE protected ApprovalRequest filesystem root is required.")
    if not isinstance(root, str) or not root.strip():
        return InMemoryProtectedApprovalRequestStorage()
    return LocalProtectedApprovalRequestStorage(Path(root.strip()))


class SqlAlchemyProtectedApprovalRequestStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        storage: ProtectedApprovalRequestStorage,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))

    def persist(self, approval_request: object) -> dict[str, Any]:
        request = canonical_approval_request_data(approval_request)
        payload = build_protected_approval_request_payload(approval_request)
        self._storage.save(
            payload,
            tenant_id=request["tenant_id"],
            execution_id=request["execution_id"],
        )
        record = {
            "schema_version": PROTECTED_APPROVAL_REQUEST_SCHEMA_VERSION,
            "tenant_id": request["tenant_id"],
            "approval_request_id": request["approval_request_id"],
            "nsl_execution_id": request["execution_id"],
            "business_operation_id": request["business_operation_id"],
            "protected_request_ref": payload["storage_ref"],
            "approval_request_hash": hash_ref_from_sha256(payload["content_sha256"]),
            "request_size_bytes": payload["size_bytes"],
            "content_type": PROTECTED_APPROVAL_REQUEST_CONTENT_TYPE,
            "data_classification": request["data_classification"],
            "created_at": _time(self._clock()),
        }
        try:
            with self._session_factory() as session:
                session.execute(text(_INSERT_SQL), record)
                saved = _load_record(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_request_id=record["approval_request_id"],
                )
                if saved is None:
                    raise _unavailable()
                if not _same_immutable_record(saved, record):
                    raise _conflict()
                session.commit()
                return saved
        except ProtectedApprovalRequestError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(self, *, tenant_id: str, approval_request_id: str) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        approval_request_id = _required_text(
            "approval_request_id", approval_request_id, 256
        )
        try:
            with self._session_factory() as session:
                return _load_record(
                    session,
                    tenant_id=tenant_id,
                    approval_request_id=approval_request_id,
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def load_request(
        self, *, tenant_id: str, approval_request_id: str
    ) -> dict[str, Any] | None:
        record = self.get(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
        )
        if record is None:
            return None
        metadata = {
            "approval_request_id": record["approval_request_id"],
            "content_sha256": str(record["approval_request_hash"]).removeprefix(
                "sha256:"
            ),
            "size_bytes": record["request_size_bytes"],
            "storage_ref": record["protected_request_ref"],
        }
        request = self._storage.load(
            metadata,
            tenant_id=record["tenant_id"],
            execution_id=record["nsl_execution_id"],
        )
        if request is None:
            raise _integrity_error()
        if (
            request["tenant_id"] != record["tenant_id"]
            or request["approval_request_id"] != record["approval_request_id"]
            or request["execution_id"] != record["nsl_execution_id"]
            or request["business_operation_id"] != record["business_operation_id"]
            or request["data_classification"] != record["data_classification"]
        ):
            raise _integrity_error()
        return request


def _validate_payload(
    value: Mapping[str, Any], *, require_content: bool
) -> dict[str, Any]:
    fields = {
        "approval_request_id",
        "content_sha256",
        "size_bytes",
        "storage_ref",
    }
    if require_content:
        fields.add("content")
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Protected ApprovalRequest payload shape is invalid.")
    request_id = _required_text(
        "approval_request_id", value.get("approval_request_id"), 256
    )
    digest = value.get("content_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise _invalid("Protected ApprovalRequest digest is invalid.")
    size = value.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= MAX_PROTECTED_APPROVAL_REQUEST_BYTES
    ):
        raise _invalid("Protected ApprovalRequest size is invalid.")
    storage_ref = value.get("storage_ref")
    if not isinstance(storage_ref, str) or _STORAGE_REF.fullmatch(storage_ref) is None:
        raise _invalid("Protected ApprovalRequest storage reference is invalid.")
    normalized = {
        "approval_request_id": request_id,
        "content_sha256": digest,
        "size_bytes": size,
        "storage_ref": storage_ref,
    }
    if require_content:
        content = value.get("content")
        if not isinstance(content, str):
            raise _invalid("Protected ApprovalRequest content must be JSON text.")
        _verify_payload(content.encode("utf-8"), digest=digest, size=size)
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise _invalid("Protected ApprovalRequest content is not JSON.") from exc
        if not isinstance(parsed, dict) or canonical_json(parsed) != content:
            raise _invalid("Protected ApprovalRequest content is not canonical JSON.")
        if parsed.get("approval_request_id") != request_id:
            raise _invalid("Protected ApprovalRequest identity is inconsistent.")
        normalized["content"] = content
    return normalized


def _decode_request(payload: bytes, metadata: Mapping[str, Any]) -> dict[str, Any]:
    _verify_payload(
        payload,
        digest=str(metadata["content_sha256"]),
        size=int(metadata["size_bytes"]),
    )
    try:
        content = payload.decode("utf-8")
        request = json.loads(content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise _integrity_error() from exc
    if (
        not isinstance(request, dict)
        or canonical_json(request) != content
        or set(request) != _REQUEST_FIELDS
        or request.get("approval_request_id") != metadata["approval_request_id"]
    ):
        raise _integrity_error()
    return request


def _verify_payload(payload: bytes, *, digest: str, size: int) -> None:
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise _integrity_error()


def _storage_ref_relative_path(value: object) -> str:
    if not isinstance(value, str) or _STORAGE_REF.fullmatch(value) is None:
        raise _invalid("Protected ApprovalRequest storage reference is invalid.")
    return value.removeprefix(PROTECTED_APPROVAL_REQUEST_STORAGE_SCHEME)


def _owner_key(
    tenant_id: str, approval_request_id: str, storage_ref: object
) -> tuple[str, str, str]:
    return (
        _required_text("tenant_id", tenant_id, 128),
        _required_text("approval_request_id", approval_request_id, 256),
        _storage_ref_relative_path(storage_ref),
    )


def _load_record(
    session: Session, *, tenant_id: str, approval_request_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, approval_request_id, nsl_execution_id, "
                "business_operation_id, protected_request_ref, "
                "approval_request_hash, request_size_bytes, content_type, "
                "data_classification, created_at "
                "FROM ae_nsl_approval_request "
                "WHERE tenant_id = :tenant_id "
                "AND approval_request_id = :approval_request_id"
            ),
            {
                "tenant_id": tenant_id,
                "approval_request_id": approval_request_id,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    try:
        approval_hash = validate_hash_ref(row["approval_request_hash"])
    except ValueError as exc:
        raise _integrity_error() from exc
    record = {
        "schema_version": PROTECTED_APPROVAL_REQUEST_SCHEMA_VERSION,
        "tenant_id": str(row["tenant_id"]),
        "approval_request_id": str(row["approval_request_id"]),
        "nsl_execution_id": str(row["nsl_execution_id"]),
        "business_operation_id": str(row["business_operation_id"]),
        "protected_request_ref": str(row["protected_request_ref"]),
        "approval_request_hash": approval_hash,
        "request_size_bytes": int(row["request_size_bytes"]),
        "content_type": str(row["content_type"]),
        "data_classification": str(row["data_classification"]),
        "created_at": _time(row["created_at"]),
    }
    if (
        _STORAGE_REF.fullmatch(record["protected_request_ref"]) is None
        or record["content_type"] != PROTECTED_APPROVAL_REQUEST_CONTENT_TYPE
        or record["data_classification"] not in _CLASSIFICATIONS
        or not 1 <= record["request_size_bytes"] <= MAX_PROTECTED_APPROVAL_REQUEST_BYTES
    ):
        raise _integrity_error()
    return record


def _same_immutable_record(
    saved: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    fields = set(expected) - {"created_at"}
    return all(saved.get(field) == expected.get(field) for field in fields)


def _object_storage_error(
    exc: ObjectStorageError,
) -> ProtectedApprovalRequestError:
    if exc.retryable:
        return _unavailable()
    if exc.code in {
        "OBJECT_STORAGE_IMMUTABLE_CONFLICT",
        "OBJECT_STORAGE_INTEGRITY_MISMATCH",
        "OBJECT_STORAGE_METADATA_INVALID",
        "OBJECT_STORAGE_SIZE_MISMATCH",
    }:
        return _integrity_error()
    return _invalid("Protected ApprovalRequest object-storage operation failed.")


def _required_text(field_name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field_name} must be a bounded non-empty string.")
    return value.strip()


def _optional_text(field_name: str, value: object, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(field_name, value, maximum)


def _optional_timestamp(field_name: str, value: object) -> str | None:
    if value is None:
        return None
    normalized = _required_text(field_name, value, 64)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field_name} must include a timezone.")
    return normalized


def _time(value: object) -> str:
    if not isinstance(value, datetime):
        return str(value)
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value
    return normalized.isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> ProtectedApprovalRequestError:
    return ProtectedApprovalRequestError("ae.nsl_approval_request_invalid", detail)


def _conflict() -> ProtectedApprovalRequestError:
    return ProtectedApprovalRequestError(
        "ae.nsl_approval_request_idempotency_conflict",
        "ApprovalRequest identity is already bound to different semantics.",
    )


def _integrity_error() -> ProtectedApprovalRequestError:
    return ProtectedApprovalRequestError(
        "ae.nsl_approval_request_integrity_failed",
        "Protected ApprovalRequest failed integrity verification.",
    )


def _unavailable() -> ProtectedApprovalRequestError:
    return ProtectedApprovalRequestError(
        "ae.nsl_approval_request_store_unavailable",
        "AE protected ApprovalRequest store is unavailable.",
        True,
    )


_INSERT_SQL = """
    INSERT INTO ae_nsl_approval_request (
        tenant_id, approval_request_id, nsl_execution_id,
        business_operation_id, protected_request_ref,
        approval_request_hash, request_size_bytes, content_type,
        data_classification, created_at
    ) VALUES (
        :tenant_id, :approval_request_id, :nsl_execution_id,
        :business_operation_id, :protected_request_ref,
        :approval_request_hash, :request_size_bytes, :content_type,
        :data_classification, :created_at
    ) ON CONFLICT (tenant_id, approval_request_id) DO NOTHING
"""
