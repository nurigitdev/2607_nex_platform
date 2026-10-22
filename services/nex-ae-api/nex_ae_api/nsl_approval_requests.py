from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import (
    canonical_json,
    hash_ref_from_sha256,
    sha256_text,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

PROTECTED_APPROVAL_REQUEST_SCHEMA_VERSION = "ae_nsl_approval_request.v2"
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


def build_protected_approval_request_payload(
    approval_request: object,
) -> dict[str, Any]:
    request = canonical_approval_request_data(approval_request)
    return _build_payload_from_request(request)


def _build_payload_from_request(request: Mapping[str, Any]) -> dict[str, Any]:
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
        "content_bytes": encoded,
        "content_sha256": digest,
        "size_bytes": len(encoded),
        "storage_ref": (
            f"{PROTECTED_APPROVAL_REQUEST_STORAGE_SCHEME}"
            f"{identity_digest[:2]}/{identity_digest}.json"
        ),
    }


def canonical_approval_request_data(value: object) -> dict[str, Any]:
    to_data = getattr(value, "to_data", None)
    if not callable(to_data):
        raise _invalid("NSL ApprovalRequest must expose its canonical to_data API.")
    try:
        raw = to_data()
    except Exception as exc:
        raise _invalid("NSL ApprovalRequest canonical serialization failed.") from exc
    return _canonicalize_request_mapping(raw)


def _canonicalize_request_mapping(raw: object) -> dict[str, Any]:
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


class SqlAlchemyProtectedApprovalRequestStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def persist(self, approval_request: object) -> dict[str, Any]:
        request = canonical_approval_request_data(approval_request)
        payload = _build_payload_from_request(request)
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
            "_approval_request_bytes": payload["content_bytes"],
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
                return _public_record(saved)
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
                record = _load_record(
                    session,
                    tenant_id=tenant_id,
                    approval_request_id=approval_request_id,
                )
                return None if record is None else _public_record(record)
        except ProtectedApprovalRequestError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def load_request(
        self, *, tenant_id: str, approval_request_id: str
    ) -> dict[str, Any] | None:
        tenant_id = _required_text("tenant_id", tenant_id, 128)
        approval_request_id = _required_text(
            "approval_request_id", approval_request_id, 256
        )
        try:
            with self._session_factory() as session:
                record = _load_record(
                    session,
                    tenant_id=tenant_id,
                    approval_request_id=approval_request_id,
                )
        except ProtectedApprovalRequestError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        if record is None:
            return None
        return _request_from_record(record)


def _load_record(
    session: Session, *, tenant_id: str, approval_request_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, approval_request_id, nsl_execution_id, "
                "business_operation_id, protected_request_ref, "
                "approval_request_hash, request_size_bytes, content_type, "
                "data_classification, created_at, approval_request_bytes "
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
    raw_body = row["approval_request_bytes"]
    if not isinstance(raw_body, (bytes, bytearray, memoryview)):
        raise _integrity_error()
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
        "_approval_request_bytes": bytes(raw_body),
    }
    if (
        _STORAGE_REF.fullmatch(record["protected_request_ref"]) is None
        or record["content_type"] != PROTECTED_APPROVAL_REQUEST_CONTENT_TYPE
        or record["data_classification"] not in _CLASSIFICATIONS
        or not 1 <= record["request_size_bytes"] <= MAX_PROTECTED_APPROVAL_REQUEST_BYTES
    ):
        raise _integrity_error()
    _request_from_record(record)
    return record


def _request_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("_approval_request_bytes")
    if not isinstance(payload, bytes):
        raise _integrity_error()
    request = _decode_request(
        payload,
        approval_request_id=str(record["approval_request_id"]),
        digest=str(record["approval_request_hash"]).removeprefix("sha256:"),
        size=int(record["request_size_bytes"]),
    )
    if (
        request["tenant_id"] != record["tenant_id"]
        or request["execution_id"] != record["nsl_execution_id"]
        or request["business_operation_id"] != record["business_operation_id"]
        or request["data_classification"] != record["data_classification"]
    ):
        raise _integrity_error()
    return request


def _decode_request(
    payload: bytes, *, approval_request_id: str, digest: str, size: int
) -> dict[str, Any]:
    _verify_payload(payload, digest=digest, size=size)
    try:
        content = payload.decode("utf-8")
        raw = json.loads(content)
        request = _canonicalize_request_mapping(raw)
    except (UnicodeDecodeError, ValueError, ProtectedApprovalRequestError) as exc:
        raise _integrity_error() from exc
    if (
        canonical_json(request) != content
        or request["approval_request_id"] != approval_request_id
    ):
        raise _integrity_error()
    return request


def _verify_payload(payload: bytes, *, digest: str, size: int) -> None:
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise _integrity_error()


def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _same_immutable_record(
    saved: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    fields = set(expected) - {"created_at"}
    return all(saved.get(field) == expected.get(field) for field in fields)


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
        data_classification, created_at, approval_request_bytes
    ) VALUES (
        :tenant_id, :approval_request_id, :nsl_execution_id,
        :business_operation_id, :protected_request_ref,
        :approval_request_hash, :request_size_bytes, :content_type,
        :data_classification, :created_at, :_approval_request_bytes
    ) ON CONFLICT (tenant_id, approval_request_id) DO NOTHING
"""
