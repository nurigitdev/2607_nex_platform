from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


AG_ARCHIVE_RECEIPT_SCHEMA_VERSION = "ag_archive_receipt.v1"
AG_ARCHIVE_RECEIPT_TABLE = "ag_ret_archives"
ALLOWED_SOURCE_KINDS = frozenset({"operational_event", "evidence_export"})
ALLOWED_PROVIDER_MODES = frozenset({"mock", "external"})
ALLOWED_ARCHIVE_STATUSES = frozenset(
    {"REQUESTED", "MOCKED", "SEALED", "FAILED", "PURGED"}
)
IMMUTABLE_RECEIPT_FIELDS = (
    "archive_id",
    "source_kind",
    "source_id",
    "source_content_sha256",
    "archive_provider_mode",
    "archive_object_ref_hash",
    "archive_receipt_sha256",
    "archived_at",
)


@dataclass(frozen=True)
class AgArchiveReceiptError(RuntimeError):
    error_code: str
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail


class AgArchiveAdapter(Protocol):
    def archive(
        self,
        *,
        candidate: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class MockAgArchiveAdapter:
    def archive(
        self,
        *,
        candidate: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        source_hash = _sha256_json(payload)
        if source_hash != candidate.get("content_sha256"):
            raise AgArchiveReceiptError(
                error_code="ag.retention.archive_payload_hash_mismatch",
                detail="Archive payload does not match the retention candidate.",
            )
        source_kind = _required_text(candidate, "source_kind")
        source_id = _required_text(candidate, "source_id")
        object_ref = f"mock://nex-ag/{source_kind}/{_sha256_text(source_id)}"
        return {
            "provider_mode": "mock",
            "recoverable": False,
            "object_ref": object_ref,
            "content_sha256": source_hash,
            "receipt_sha256": _sha256_text(
                f"mock:{object_ref}:{source_hash}"
            ),
        }


class InMemoryAgArchiveReceiptStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _validate_receipt_record(record)
        existing = self.records.get(normalized["archive_id"])
        if existing is not None:
            _assert_idempotent_receipt(existing, normalized)
            return dict(existing)
        for item in self.records.values():
            if (
                item["source_kind"],
                item["source_id"],
            ) == (normalized["source_kind"], normalized["source_id"]):
                raise _receipt_conflict()
        self.records[normalized["archive_id"]] = dict(normalized)
        return dict(normalized)

    def get(self, archive_id: str) -> dict[str, Any] | None:
        record = self.records.get(archive_id)
        return dict(record) if record is not None else None

    def get_by_source(
        self,
        *,
        source_kind: str,
        source_id: str,
    ) -> dict[str, Any] | None:
        for record in self.records.values():
            if (record["source_kind"], record["source_id"]) == (
                source_kind,
                source_id,
            ):
                return dict(record)
        return None

    def list_receipts(
        self,
        *,
        archive_status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_status = _optional_status(archive_status)
        normalized_limit = _normalize_limit(limit)
        selected = [
            dict(record)
            for record in self.records.values()
            if normalized_status is None
            or record["archive_status"] == normalized_status
        ]
        selected.sort(
            key=lambda item: (item["updated_at"], item["archive_id"]),
            reverse=True,
        )
        return selected[:normalized_limit]


class SqlAlchemyAgArchiveReceiptStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _validate_receipt_record(record)
        try:
            with self._session_factory() as session:
                dialect = str(session.bind.dialect.name) if session.bind else ""
                session.execute(
                    text(_receipt_insert_sql(dialect)),
                    _receipt_params(normalized),
                )
                row = session.execute(
                    text(_receipt_select_sql("archive_id = :archive_id")),
                    {"archive_id": normalized["archive_id"]},
                ).mappings().first()
                if row is None:
                    row = session.execute(
                        text(
                            _receipt_select_sql(
                                "source_kind = :source_kind AND source_id = :source_id"
                            )
                        ),
                        {
                            "source_kind": normalized["source_kind"],
                            "source_id": normalized["source_id"],
                        },
                    ).mappings().first()
                existing = _receipt_from_row(row) if row is not None else None
                if existing is None:
                    raise _receipt_store_unavailable()
                _assert_idempotent_receipt(existing, normalized)
                session.commit()
                return existing
        except AgArchiveReceiptError:
            raise
        except SQLAlchemyError as exc:
            raise _receipt_store_unavailable() from exc

    def get(self, archive_id: str) -> dict[str, Any] | None:
        return self._get_one("archive_id = :archive_id", {"archive_id": archive_id})

    def get_by_source(
        self,
        *,
        source_kind: str,
        source_id: str,
    ) -> dict[str, Any] | None:
        return self._get_one(
            "source_kind = :source_kind AND source_id = :source_id",
            {"source_kind": source_kind, "source_id": source_id},
        )

    def list_receipts(
        self,
        *,
        archive_status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_status = _optional_status(archive_status)
        params: dict[str, Any] = {"limit": _normalize_limit(limit)}
        where_clause = "1 = 1"
        if normalized_status is not None:
            where_clause = "archive_status = :archive_status"
            params["archive_status"] = normalized_status
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        _receipt_select_sql(
                            where_clause
                            + " ORDER BY updated_at DESC, archive_id DESC LIMIT :limit"
                        )
                    ),
                    params,
                ).mappings().all()
            return [_receipt_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise _receipt_store_unavailable() from exc

    def _get_one(
        self,
        where_clause: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(_receipt_select_sql(where_clause)),
                    dict(params),
                ).mappings().first()
            return _receipt_from_row(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise _receipt_store_unavailable() from exc


def build_ag_archive_receipt(
    *,
    candidate: Mapping[str, Any],
    provider_result: Mapping[str, Any],
    archived_at: str,
    grace_days: int,
) -> dict[str, Any]:
    source_kind = _required_text(candidate, "source_kind")
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_source_kind_invalid",
            detail="Archive source kind is invalid.",
        )
    source_id = _required_text(candidate, "source_id")
    source_hash = _sha256_value(candidate.get("content_sha256"), "content_sha256")
    provider_mode = _required_text(provider_result, "provider_mode").lower()
    if provider_mode not in ALLOWED_PROVIDER_MODES:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_provider_mode_invalid",
            detail="Archive provider mode is invalid.",
        )
    provider_content_hash = _sha256_value(
        provider_result.get("content_sha256"),
        "content_sha256",
    )
    if provider_content_hash != source_hash:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_receipt_hash_mismatch",
            detail="Archive receipt does not match the source content hash.",
        )
    object_ref = _required_text(provider_result, "object_ref")
    receipt_hash = _sha256_value(
        provider_result.get("receipt_sha256"),
        "receipt_sha256",
    )
    recoverable = provider_result.get("recoverable")
    if not isinstance(recoverable, bool):
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_recoverability_invalid",
            detail="Archive recoverability must be explicit.",
        )
    if provider_mode == "external" and not recoverable:
        raise AgArchiveReceiptError(
            error_code="ag.retention.external_archive_not_recoverable",
            detail="External archive receipt must confirm recoverability.",
        )
    if provider_mode == "mock" and recoverable:
        raise AgArchiveReceiptError(
            error_code="ag.retention.mock_archive_recoverability_invalid",
            detail="Mock archive receipts cannot claim recoverability.",
        )
    if isinstance(grace_days, bool) or not isinstance(grace_days, int) or grace_days < 1:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_grace_invalid",
            detail="Archive grace days must be a positive integer.",
        )
    archived = _parse_timestamp(archived_at, field="archived_at")
    archive_status = "SEALED" if provider_mode == "external" else "MOCKED"
    purge_after = (
        _timestamp(archived + timedelta(days=grace_days))
        if archive_status == "SEALED"
        else None
    )
    archive_id = str(
        uuid5(NAMESPACE_URL, f"{source_kind}:{source_id}:{source_hash}")
    )
    now = _timestamp(archived)
    return {
        "receipt_schema_version": AG_ARCHIVE_RECEIPT_SCHEMA_VERSION,
        "archive_id": archive_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_content_sha256": source_hash,
        "archive_provider_mode": provider_mode,
        "archive_object_ref_hash": _sha256_text(object_ref),
        "archive_receipt_sha256": receipt_hash,
        "archive_status": archive_status,
        "archived_at": now,
        "purge_after": purge_after,
        "purged_at": None,
        "failure_code": None,
        "metadata": {
            "recoverable": recoverable,
            "raw_object_ref_included": False,
            "raw_payload_included": False,
        },
        "created_at": now,
        "updated_at": now,
    }


def _validate_receipt_record(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    if normalized.get("receipt_schema_version") != AG_ARCHIVE_RECEIPT_SCHEMA_VERSION:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_receipt_schema_invalid",
            detail="Archive receipt schema version is invalid.",
        )
    for field in (
        "archive_id",
        "source_id",
        "archive_provider_mode",
        "archive_status",
    ):
        normalized[field] = _required_text(normalized, field)
    if normalized.get("source_kind") not in ALLOWED_SOURCE_KINDS:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_source_kind_invalid",
            detail="Archive source kind is invalid.",
        )
    if normalized["archive_provider_mode"] not in ALLOWED_PROVIDER_MODES:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_provider_mode_invalid",
            detail="Archive provider mode is invalid.",
        )
    if normalized["archive_status"] not in ALLOWED_ARCHIVE_STATUSES:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_status_invalid",
            detail="Archive receipt status is invalid.",
        )
    for field in (
        "source_content_sha256",
        "archive_object_ref_hash",
        "archive_receipt_sha256",
    ):
        normalized[field] = _sha256_value(normalized.get(field), field)
    for field in ("archived_at", "purge_after", "purged_at", "created_at", "updated_at"):
        value = normalized.get(field)
        normalized[field] = (
            _timestamp(_parse_timestamp(value, field=field))
            if value is not None
            else None
        )
    metadata = normalized.get("metadata")
    if not isinstance(metadata, Mapping):
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_metadata_invalid",
            detail="Archive receipt metadata must be an object.",
        )
    normalized["metadata"] = dict(metadata)
    return normalized


def _assert_idempotent_receipt(
    existing: Mapping[str, Any],
    requested: Mapping[str, Any],
) -> None:
    if any(existing.get(field) != requested.get(field) for field in IMMUTABLE_RECEIPT_FIELDS):
        raise _receipt_conflict()


def _receipt_conflict() -> AgArchiveReceiptError:
    return AgArchiveReceiptError(
        error_code="ag.retention.archive_receipt_conflict",
        detail="Archive receipt conflicts with an immutable stored receipt.",
        status_code=409,
    )


def _receipt_store_unavailable() -> AgArchiveReceiptError:
    return AgArchiveReceiptError(
        error_code="ag.retention.archive_receipt_store_unavailable",
        detail="AG archive receipt store is unavailable.",
        status_code=503,
    )


def _optional_status(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().upper()
    if normalized not in ALLOWED_ARCHIVE_STATUSES:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_status_invalid",
            detail="Archive receipt status is invalid.",
        )
    return normalized


def _normalize_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 500:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_limit_invalid",
            detail="Archive receipt limit must be between 1 and 500.",
        )
    return value


def _required_text(value: Mapping[str, Any], field: str) -> str:
    raw = value.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_field_required",
            detail=f"{field} is required.",
        )
    return raw.strip()


def _sha256_value(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_hash_invalid",
            detail=f"{field} must be a lowercase SHA-256 value.",
        )
    return value


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgArchiveReceiptError(
                error_code="ag.retention.archive_timestamp_invalid",
                detail=f"{field} must be an ISO-8601 timestamp.",
            ) from exc
    else:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_timestamp_invalid",
            detail=f"{field} must be an ISO-8601 timestamp.",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgArchiveReceiptError(
            error_code="ag.retention.archive_timestamp_timezone_required",
            detail=f"{field} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return _timestamp(value)
    return value


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _receipt_insert_sql(dialect: str) -> str:
    metadata_value = "CAST(:metadata AS JSONB)" if dialect == "postgresql" else ":metadata"
    return f"""
        INSERT INTO ag_ret_archives (
            archive_id, receipt_schema_version, source_kind, source_id,
            source_content_sha256, archive_provider_mode,
            archive_object_ref_hash, archive_receipt_sha256, archive_status,
            archived_at, purge_after, purged_at, failure_code, metadata,
            created_at, updated_at
        ) VALUES (
            :archive_id, :receipt_schema_version, :source_kind, :source_id,
            :source_content_sha256, :archive_provider_mode,
            :archive_object_ref_hash, :archive_receipt_sha256, :archive_status,
            :archived_at, :purge_after, :purged_at, :failure_code,
            {metadata_value}, :created_at, :updated_at
        ) ON CONFLICT DO NOTHING
    """


def _receipt_select_sql(where_clause: str) -> str:
    return f"""
        SELECT archive_id, receipt_schema_version, source_kind, source_id,
               source_content_sha256, archive_provider_mode,
               archive_object_ref_hash, archive_receipt_sha256, archive_status,
               archived_at, purge_after, purged_at, failure_code, metadata,
               created_at, updated_at
        FROM ag_ret_archives
        WHERE {where_clause}
    """


def _receipt_params(record: Mapping[str, Any]) -> dict[str, Any]:
    params = dict(record)
    params["metadata"] = json.dumps(record["metadata"], sort_keys=True)
    return params


def _receipt_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return _validate_receipt_record(
        {
            **dict(row),
            "metadata": metadata,
        }
    )
