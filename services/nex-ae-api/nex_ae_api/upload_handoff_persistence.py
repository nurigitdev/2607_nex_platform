from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chunk_text",
        "content_base64",
        "content_text",
        "embedding",
        "markdown",
        "password",
        "raw_token",
        "secret",
        "vector",
    }
)


@dataclass(frozen=True)
class UploadHandoffRepositoryError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyUploadHandoffStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        ensure_upload_handoff_metadata_only(record)
        params = _record_params(record)
        try:
            with self._session_factory() as session:
                inserted = session.execute(
                    text(_insert_sql(_dialect_name(session))),
                    params,
                )
                if int(inserted.rowcount or 0) == 0:
                    existing = _load_one(
                        session,
                        "upload_handoff_id = :upload_handoff_id",
                        {"upload_handoff_id": record["upload_handoff_id"]},
                    )
                    if existing is None:
                        raise UploadHandoffRepositoryError(
                            status_code=503,
                            error_code="ae.upload_handoff_write_conflict",
                            detail=(
                                "Upload handoff insert conflicted without a readable "
                                "record."
                            ),
                            retryable=True,
                        )
                    if _identity(existing) != _identity(record):
                        raise UploadHandoffRepositoryError(
                            status_code=409,
                            error_code="ae.upload_handoff_identity_conflict",
                            detail=(
                                "Upload handoff identifier is already bound to different "
                                "owner or CX lineage."
                            ),
                        )
                    return existing
                session.commit()
                return dict(record)
        except UploadHandoffRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(
        self,
        upload_handoff_id: str,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        clause, params = _owner_clause(
            "upload_handoff_id = :upload_handoff_id",
            {"upload_handoff_id": upload_handoff_id},
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        try:
            with self._session_factory() as session:
                return _load_one(session, clause, params)
        except UploadHandoffRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_by_document_id(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        clause, params = _owner_clause(
            "cx_document_id = :cx_document_id",
            {"cx_document_id": document_id},
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        try:
            with self._session_factory() as session:
                return _load_one(session, clause, params)
        except UploadHandoffRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def list_by_workspace(
        self,
        workspace_id: str,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clause, params = _owner_clause(
            "workspace_id = :workspace_id",
            {"workspace_id": workspace_id},
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(f"{_SELECT_SQL} WHERE {clause} "
                             "ORDER BY created_at ASC, upload_handoff_id ASC"),
                        params,
                    )
                    .mappings()
                    .all()
                )
                return [_record_from_row(row) for row in rows]
        except UploadHandoffRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def ensure_upload_handoff_metadata_only(value: object) -> None:
    if not isinstance(value, Mapping):
        raise _invalid("Upload handoff metadata must be an object.")
    forbidden = _forbidden_keys(value)
    if forbidden:
        raise _invalid(
            "Upload handoff metadata contains forbidden private payload fields: "
            + ", ".join(sorted(forbidden))
        )


def _forbidden_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        keys = {
            str(key).strip().lower()
            for key in value
            if str(key).strip().lower() in FORBIDDEN_PRIVATE_KEYS
        }
        for nested in value.values():
            keys.update(_forbidden_keys(nested))
        return keys
    if isinstance(value, (list, tuple)):
        keys: set[str] = set()
        for nested in value:
            keys.update(_forbidden_keys(nested))
        return keys
    return set()


_SELECT_SQL = """
SELECT upload_handoff_id, workspace_id, tenant_id, owner_user_id,
       source_sha256, cx_document_id, cx_upload_id, ingestion_job_id,
       status, record_payload, trace_id, request_id, created_at, updated_at
FROM ae_upload_handoffs
"""


def _insert_sql(dialect_name: str) -> str:
    payload = "CAST(:record_payload AS jsonb)" if dialect_name == "postgresql" else ":record_payload"
    return f"""
        INSERT INTO ae_upload_handoffs (
            upload_handoff_id, workspace_id, tenant_id, owner_user_id,
            source_sha256, cx_document_id, cx_upload_id, ingestion_job_id,
            status, record_payload, trace_id, request_id, created_at, updated_at
        ) VALUES (
            :upload_handoff_id, :workspace_id, :tenant_id, :owner_user_id,
            :source_sha256, :cx_document_id, :cx_upload_id, :ingestion_job_id,
            :status, {payload}, :trace_id, :request_id, :created_at, :updated_at
        ) ON CONFLICT (upload_handoff_id) DO NOTHING
    """


def _record_params(record: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(record.get("source"), "source")
    cx_ref = _mapping(record.get("cx_document_ref"), "cx_document_ref")
    return {
        "upload_handoff_id": _required(record, "upload_handoff_id"),
        "workspace_id": _required(record, "workspace_id"),
        "tenant_id": _required(record, "tenant_id"),
        "owner_user_id": _required(record, "owner_user_id"),
        "source_sha256": _required(source, "source_sha256"),
        "cx_document_id": _required(cx_ref, "document_id"),
        "cx_upload_id": _required(cx_ref, "upload_id"),
        "ingestion_job_id": _required(cx_ref, "ingestion_job_id"),
        "status": _required(record, "status"),
        "record_payload": json.dumps(record, sort_keys=True),
        "trace_id": _required(record, "trace_id"),
        "request_id": _required(record, "request_id"),
        "created_at": _required(record, "created_at"),
        "updated_at": _required(record, "updated_at"),
    }


def _load_one(
    session: Session,
    clause: str,
    params: Mapping[str, Any],
) -> dict[str, Any] | None:
    row = (
        session.execute(text(f"{_SELECT_SQL} WHERE {clause}"), dict(params))
        .mappings()
        .first()
    )
    return None if row is None else _record_from_row(row)


def _record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row["record_payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise _integrity_failed() from exc
    if not isinstance(payload, dict):
        raise _integrity_failed()
    ensure_upload_handoff_metadata_only(payload)
    indexed = _record_params(payload)
    for key in (
        "upload_handoff_id",
        "workspace_id",
        "tenant_id",
        "owner_user_id",
        "source_sha256",
        "cx_document_id",
        "cx_upload_id",
        "ingestion_job_id",
        "status",
        "trace_id",
        "request_id",
    ):
        if str(row[key]) != str(indexed[key]):
            raise _integrity_failed()
    return payload


def _owner_clause(
    clause: str,
    params: dict[str, Any],
    *,
    tenant_id: str | None,
    owner_user_id: str | None,
) -> tuple[str, dict[str, Any]]:
    if (tenant_id is None) != (owner_user_id is None):
        raise _invalid("Tenant and owner filters must be supplied together.")
    if tenant_id is None:
        return clause, params
    return (
        f"{clause} AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id",
        {**params, "tenant_id": tenant_id, "owner_user_id": owner_user_id},
    )


def _identity(record: Mapping[str, Any]) -> tuple[str, ...]:
    params = _record_params(record)
    return tuple(
        str(params[key])
        for key in (
            "tenant_id",
            "owner_user_id",
            "workspace_id",
            "source_sha256",
            "cx_document_id",
            "cx_upload_id",
        )
    )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"Upload handoff {field_name} must be an object.")
    return value


def _required(value: Mapping[str, Any], field_name: str) -> str:
    field = value.get(field_name)
    if not isinstance(field, str) or not field.strip():
        raise _invalid(f"Upload handoff {field_name} is required.")
    return field.strip()


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> UploadHandoffRepositoryError:
    return UploadHandoffRepositoryError(
        status_code=422,
        error_code="ae.upload_handoff_metadata_invalid",
        detail=detail,
    )


def _integrity_failed() -> UploadHandoffRepositoryError:
    return UploadHandoffRepositoryError(
        status_code=500,
        error_code="ae.upload_handoff_integrity_failed",
        detail="Persisted upload handoff metadata failed integrity validation.",
    )


def _unavailable() -> UploadHandoffRepositoryError:
    return UploadHandoffRepositoryError(
        status_code=503,
        error_code="ae.upload_handoff_store_unavailable",
        detail="AE upload handoff store is unavailable.",
        retryable=True,
    )
