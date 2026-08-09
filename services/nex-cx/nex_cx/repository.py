from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_OWNER_USER_ID = "local-user"


class CxContentRepository(Protocol):
    def save_source_file(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_source_file(self, source_file_id: str) -> dict[str, Any] | None:
        ...

    def get_source_file_by_sha256(self, source_sha256: str) -> dict[str, Any] | None:
        ...

    def save_content_object(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def mark_source_file_checksum_verified(
        self,
        source_file_id: str,
        *,
        verified_at: str,
    ) -> dict[str, Any]:
        ...

    def get_content_object(self, content_object_id: str) -> dict[str, Any] | None:
        ...

    def find_active_content_object(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class CxContentRepositoryError(Exception):
    error_code: str
    detail: str
    status_code: int = 503


@dataclass
class InMemoryCxContentRepository:
    source_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_file_ids_by_sha256: dict[str, str] = field(default_factory=dict)
    content_objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_content_object_ids_by_owner_sha: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )

    def save_source_file(self, record: dict[str, Any]) -> dict[str, Any]:
        existing_id = self.source_file_ids_by_sha256.get(record["source_sha256"])
        if existing_id is not None:
            return self.source_files[existing_id]

        stored = dict(record)
        self.source_files[stored["source_file_id"]] = stored
        self.source_file_ids_by_sha256[stored["source_sha256"]] = stored["source_file_id"]
        return stored

    def get_source_file(self, source_file_id: str) -> dict[str, Any] | None:
        return self.source_files.get(source_file_id)

    def get_source_file_by_sha256(self, source_sha256: str) -> dict[str, Any] | None:
        source_file_id = self.source_file_ids_by_sha256.get(source_sha256)
        if source_file_id is None:
            return None
        return self.source_files[source_file_id]

    def mark_source_file_checksum_verified(
        self,
        source_file_id: str,
        *,
        verified_at: str,
    ) -> dict[str, Any]:
        source_file = self.source_files[source_file_id]
        source_file["checksum_verified_at"] = verified_at
        return source_file

    def save_content_object(self, record: dict[str, Any]) -> dict[str, Any]:
        stored = dict(record)
        self.content_objects[stored["content_object_id"]] = stored
        if stored["lifecycle_status"] == "ACTIVE":
            self.active_content_object_ids_by_owner_sha[
                (
                    stored["tenant_id"],
                    stored["owner_user_id"],
                    stored["source_sha256"],
                )
            ] = stored["content_object_id"]
        return stored

    def get_content_object(self, content_object_id: str) -> dict[str, Any] | None:
        return self.content_objects.get(content_object_id)

    def find_active_content_object(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        content_object_id = self.active_content_object_ids_by_owner_sha.get(
            (tenant_id, owner_user_id, source_sha256)
        )
        if content_object_id is None:
            return None
        return self.content_objects[content_object_id]


class SqlAlchemyCxContentRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        local_source_root: str | Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._local_source_root = (
            Path(local_source_root) if local_source_root is not None else None
        )

    def save_source_file(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_source_file(session, record_to_store)
            )
        except IntegrityError as exc:
            existing = self.get_source_file_by_sha256(str(record_to_store["source_sha256"]))
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_source_file(self, source_file_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_source_file(session, source_file_id)
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_source_file_by_sha256(self, source_sha256: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_source_file_by_sha256(session, source_sha256)
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_content_object(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_content_object(session, record_to_store)
            )
        except IntegrityError as exc:
            existing = self.find_active_content_object(
                tenant_id=str(record_to_store["tenant_id"]),
                owner_user_id=str(record_to_store["owner_user_id"]),
                source_sha256=str(record_to_store["source_sha256"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def mark_source_file_checksum_verified(
        self,
        source_file_id: str,
        *,
        verified_at: str,
    ) -> dict[str, Any]:
        try:
            return self._run_in_transaction(
                lambda session: self._mark_source_file_checksum_verified(
                    session,
                    source_file_id=source_file_id,
                    verified_at=verified_at,
                )
            )
        except CxContentRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_content_object(self, content_object_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_content_object(session, content_object_id)
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_active_content_object(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_active_content_object(
                    session,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    source_sha256=source_sha256,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def _run_in_transaction(self, operation: Any) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()

    def _save_source_file(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_source_file_by_sha256(session, str(record["source_sha256"]))
        if existing is not None:
            return existing
        self._insert_source_file(session, record)
        stored = self._select_source_file(session, str(record["source_file_id"]))
        assert stored is not None
        return stored

    def _save_content_object(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_content_object(session, str(record["content_object_id"]))
        if existing is not None:
            return existing
        active = self._select_active_content_object(
            session,
            tenant_id=str(record["tenant_id"]),
            owner_user_id=str(record["owner_user_id"]),
            source_sha256=str(record["source_sha256"]),
        )
        if active is not None:
            return active
        self._insert_content_object(session, record)
        self._insert_owner_acl_entry(session, record)
        stored = self._select_content_object(session, str(record["content_object_id"]))
        assert stored is not None
        return stored

    def _mark_source_file_checksum_verified(
        self,
        session: Session,
        *,
        source_file_id: str,
        verified_at: str,
    ) -> dict[str, Any]:
        existing = self._select_source_file(session, source_file_id)
        if existing is None:
            raise CxContentRepositoryError(
                error_code="cx_content.source_file_not_found",
                detail=f"source file was not found: {source_file_id}",
                status_code=404,
            )
        session.execute(
            text(
                """
                UPDATE cx_source_files
                SET checksum_verified_at = :checksum_verified_at
                WHERE source_file_id = :source_file_id
                """
            ),
            {
                "source_file_id": source_file_id,
                "checksum_verified_at": verified_at,
            },
        )
        stored = self._select_source_file(session, source_file_id)
        assert stored is not None
        return stored

    def _select_source_file(
        self,
        session: Session,
        source_file_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_SOURCE_FILE_SELECT_COLUMNS}
                FROM cx_source_files
                WHERE source_file_id = :source_file_id
                """
            ),
            {"source_file_id": source_file_id},
        ).mappings().first()
        return self._source_file_from_row(row) if row is not None else None

    def _select_source_file_by_sha256(
        self,
        session: Session,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_SOURCE_FILE_SELECT_COLUMNS}
                FROM cx_source_files
                WHERE source_sha256 = :source_sha256
                """
            ),
            {"source_sha256": source_sha256},
        ).mappings().first()
        return self._source_file_from_row(row) if row is not None else None

    def _select_content_object(
        self,
        session: Session,
        content_object_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_CONTENT_OBJECT_SELECT_COLUMNS}
                FROM cx_content_objects
                WHERE content_object_id = :content_object_id
                """
            ),
            {"content_object_id": content_object_id},
        ).mappings().first()
        return _content_object_from_row(row) if row is not None else None

    def _select_active_content_object(
        self,
        session: Session,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_CONTENT_OBJECT_SELECT_COLUMNS}
                FROM cx_content_objects
                WHERE tenant_id = :tenant_id
                  AND owner_user_id = :owner_user_id
                  AND source_sha256 = :source_sha256
                  AND lifecycle_status = 'ACTIVE'
                """
            ),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "source_sha256": source_sha256,
            },
        ).mappings().first()
        return _content_object_from_row(row) if row is not None else None

    def _insert_source_file(self, session: Session, record: dict[str, Any]) -> None:
        session.execute(
            text(
                """
                INSERT INTO cx_source_files (
                    source_file_id,
                    source_sha256,
                    size_bytes,
                    content_type,
                    storage_uri,
                    first_seen_trace_id,
                    storage_backend,
                    storage_key,
                    stored_filename,
                    stored_extension,
                    checksum_verified_at,
                    created_at
                )
                VALUES (
                    :source_file_id,
                    :source_sha256,
                    :size_bytes,
                    :content_type,
                    :storage_uri,
                    :first_seen_trace_id,
                    :storage_backend,
                    :storage_key,
                    :stored_filename,
                    :stored_extension,
                    :checksum_verified_at,
                    :created_at
                )
                """
            ),
            _source_file_insert_params(record),
        )

    def _insert_content_object(self, session: Session, record: dict[str, Any]) -> None:
        retrieval_policy_expression = _json_sql_expression(session, "retrieval_policy")
        session.execute(
            text(
                f"""
                INSERT INTO cx_content_objects (
                    content_object_id,
                    tenant_id,
                    owner_user_id,
                    source_file_id,
                    source_sha256,
                    upload_id,
                    original_filename,
                    content_type,
                    size_bytes,
                    classification,
                    lifecycle_status,
                    retrieval_policy,
                    created_trace_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    :content_object_id,
                    :tenant_id,
                    :owner_user_id,
                    :source_file_id,
                    :source_sha256,
                    :upload_id,
                    :original_filename,
                    :content_type,
                    :size_bytes,
                    :classification,
                    :lifecycle_status,
                    {retrieval_policy_expression},
                    :created_trace_id,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _content_object_insert_params(record),
        )

    def _insert_owner_acl_entry(self, session: Session, record: dict[str, Any]) -> None:
        content_object_id = str(record["content_object_id"])
        owner_user_id = str(record["owner_user_id"])
        existing = session.execute(
            text(
                """
                SELECT acl_entry_id
                FROM cx_content_acl_entries
                WHERE content_object_id = :content_object_id
                  AND principal_type = 'user'
                  AND principal_id = :principal_id
                  AND permission = 'owner'
                """
            ),
            {
                "content_object_id": content_object_id,
                "principal_id": owner_user_id,
            },
        ).mappings().first()
        if existing is not None:
            return
        session.execute(
            text(
                """
                INSERT INTO cx_content_acl_entries (
                    acl_entry_id,
                    content_object_id,
                    principal_type,
                    principal_id,
                    permission,
                    granted_by_user_id,
                    created_at
                )
                VALUES (
                    :acl_entry_id,
                    :content_object_id,
                    'user',
                    :principal_id,
                    'owner',
                    :granted_by_user_id,
                    :created_at
                )
                """
            ),
            {
                "acl_entry_id": _owner_acl_entry_id(content_object_id, owner_user_id),
                "content_object_id": content_object_id,
                "principal_id": owner_user_id,
                "granted_by_user_id": owner_user_id,
                "created_at": record["created_at"],
            },
        )

    def _source_file_from_row(self, row: Any) -> dict[str, Any]:
        record = {
            "source_file_id": str(row["source_file_id"]),
            "source_sha256": row["source_sha256"],
            "size_bytes": int(row["size_bytes"]),
            "content_type": row["content_type"],
            "storage_uri": row["storage_uri"],
            "storage_backend": row["storage_backend"],
            "storage_key": row["storage_key"],
            "stored_filename": row["stored_filename"],
            "stored_extension": row["stored_extension"],
            "first_seen_trace_id": row["first_seen_trace_id"],
            "checksum_verified_at": _timestamp_to_wire_optional(
                row["checksum_verified_at"]
            ),
            "created_at": _timestamp_to_wire(row["created_at"]),
        }
        if (
            self._local_source_root is not None
            and record["storage_backend"] == "local_filesystem"
        ):
            record["source_storage_path"] = str(
                self._local_source_root / record["storage_key"]
            )
        return record


def build_source_file_record(upload_registration: dict[str, Any]) -> dict[str, Any]:
    storage = upload_registration["storage"]
    source_sha256 = upload_registration["source_sha256"]
    source_file_id = str(uuid5(NAMESPACE_URL, f"cx-source-file:{source_sha256}"))
    return {
        "source_file_id": source_file_id,
        "source_sha256": source_sha256,
        "size_bytes": upload_registration["size_bytes"],
        "content_type": upload_registration["content_type"],
        "storage_uri": f"local://cx/source-files/{storage['source_storage_key']}",
        "storage_backend": storage["source_storage_backend"],
        "storage_key": storage["source_storage_key"],
        "source_storage_path": storage["source_storage_path"],
        "stored_filename": storage["stored_filename"],
        "stored_extension": storage["stored_extension"],
        "first_seen_trace_id": upload_registration["trace_id"],
        "checksum_verified_at": None,
        "created_at": upload_registration["created_at"],
    }


def build_content_object_record(
    upload_registration: dict[str, Any],
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    owner_user_id: str = DEFAULT_OWNER_USER_ID,
    source_file_id: str,
) -> dict[str, Any]:
    now = upload_registration["created_at"]
    return {
        "content_object_id": upload_registration["document_id"],
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "source_file_id": source_file_id,
        "source_sha256": upload_registration["source_sha256"],
        "upload_id": upload_registration["upload_id"],
        "original_filename": upload_registration["original_filename"],
        "content_type": upload_registration["content_type"],
        "size_bytes": upload_registration["size_bytes"],
        "classification": "internal",
        "lifecycle_status": "ACTIVE",
        "retrieval_policy": dict(upload_registration["retrieval_policy"]),
        "created_trace_id": upload_registration["trace_id"],
        "created_at": now,
        "updated_at": upload_registration["updated_at"],
    }


_SOURCE_FILE_SELECT_COLUMNS = """
    source_file_id,
    source_sha256,
    size_bytes,
    content_type,
    storage_uri,
    first_seen_trace_id,
    storage_backend,
    storage_key,
    stored_filename,
    stored_extension,
    checksum_verified_at,
    created_at
"""

_CONTENT_OBJECT_SELECT_COLUMNS = """
    content_object_id,
    tenant_id,
    owner_user_id,
    source_file_id,
    source_sha256,
    upload_id,
    original_filename,
    content_type,
    size_bytes,
    classification,
    lifecycle_status,
    retrieval_policy,
    created_trace_id,
    created_at,
    updated_at
"""


def _source_file_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file_id": record["source_file_id"],
        "source_sha256": record["source_sha256"],
        "size_bytes": record["size_bytes"],
        "content_type": record["content_type"],
        "storage_uri": record["storage_uri"],
        "first_seen_trace_id": record.get("first_seen_trace_id"),
        "storage_backend": record.get("storage_backend", "local_filesystem"),
        "storage_key": record["storage_key"],
        "stored_filename": record["stored_filename"],
        "stored_extension": record.get("stored_extension", ""),
        "checksum_verified_at": record.get("checksum_verified_at"),
        "created_at": record["created_at"],
    }


def _content_object_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_object_id": record["content_object_id"],
        "tenant_id": record["tenant_id"],
        "owner_user_id": record["owner_user_id"],
        "source_file_id": record["source_file_id"],
        "source_sha256": record["source_sha256"],
        "upload_id": record["upload_id"],
        "original_filename": record["original_filename"],
        "content_type": record["content_type"],
        "size_bytes": record["size_bytes"],
        "classification": record["classification"],
        "lifecycle_status": record["lifecycle_status"],
        "retrieval_policy": _json_dumps(record["retrieval_policy"]),
        "created_trace_id": record.get("created_trace_id"),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _content_object_from_row(row: Any) -> dict[str, Any]:
    return {
        "content_object_id": str(row["content_object_id"]),
        "tenant_id": row["tenant_id"],
        "owner_user_id": row["owner_user_id"],
        "source_file_id": str(row["source_file_id"]),
        "source_sha256": row["source_sha256"],
        "upload_id": str(row["upload_id"]),
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "size_bytes": int(row["size_bytes"]),
        "classification": row["classification"],
        "lifecycle_status": row["lifecycle_status"],
        "retrieval_policy": _json_loads(row["retrieval_policy"], default={}),
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _owner_acl_entry_id(content_object_id: str, owner_user_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"cx-content-acl:{content_object_id}:user:{owner_user_id}:owner",
        )
    )


def _json_sql_expression(session: Session, param_name: str) -> str:
    if _dialect_name(session) == "postgresql":
        return f"CAST(:{param_name} AS JSONB)"
    return f":{param_name}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _timestamp_to_wire_optional(value: Any) -> str | None:
    if value is None:
        return None
    return _timestamp_to_wire(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _content_repository_unavailable() -> CxContentRepositoryError:
    return CxContentRepositoryError(
        error_code="cx_content.repository_unavailable",
        detail="CX content repository is unavailable.",
        status_code=503,
    )
