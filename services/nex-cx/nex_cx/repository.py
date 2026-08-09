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

    def save_extraction_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_extraction_artifact(
        self,
        extraction_artifact_id: str,
    ) -> dict[str, Any] | None:
        ...

    def find_extraction_artifact(
        self,
        *,
        content_object_id: str,
        extractor_name: str,
        extractor_version: str,
        markdown_sha256: str,
    ) -> dict[str, Any] | None:
        ...

    def save_chunk_set(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_chunk_set(self, chunk_set_id: str) -> dict[str, Any] | None:
        ...

    def find_chunk_set(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        chunk_policy_id: str,
        source_markdown_sha256: str,
    ) -> dict[str, Any] | None:
        ...

    def save_lexical_index(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def find_lexical_index(
        self,
        *,
        chunk_set_id: str,
        tokenizer_used: str,
    ) -> dict[str, Any] | None:
        ...

    def save_chunk_embedding_index(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def find_chunk_embedding_index(
        self,
        *,
        chunk_set_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        ...

    def save_document_summary_record(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_document_summary_record(
        self,
        document_summary_id: str,
    ) -> dict[str, Any] | None:
        ...

    def find_document_summary_record(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        summary_text_sha256: str,
    ) -> dict[str, Any] | None:
        ...

    def save_summary_embedding_record(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_summary_embedding_record(
        self,
        summary_embedding_id: str,
    ) -> dict[str, Any] | None:
        ...

    def find_summary_embedding_record(
        self,
        *,
        document_summary_id: str,
        model_profile_id: str,
        model_revision: str,
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
    extraction_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    extraction_artifact_ids_by_content_hash: dict[tuple[str, str, str, str], str] = field(
        default_factory=dict
    )
    chunk_sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_set_ids_by_unique_key: dict[tuple[str, str, str, str], str] = field(
        default_factory=dict
    )
    lexical_indexes: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    chunk_embedding_indexes: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    document_summary_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_summary_ids_by_unique_key: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )
    summary_embedding_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary_embedding_ids_by_unique_key: dict[tuple[str, str, str], str] = field(
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

    def save_extraction_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _extraction_artifact_unique_key(record)
        existing_id = self.extraction_artifact_ids_by_content_hash.get(key)
        if existing_id is not None:
            return self.extraction_artifacts[existing_id]
        stored = dict(record)
        self.extraction_artifacts[stored["extraction_artifact_id"]] = stored
        self.extraction_artifact_ids_by_content_hash[key] = stored[
            "extraction_artifact_id"
        ]
        return stored

    def get_extraction_artifact(
        self,
        extraction_artifact_id: str,
    ) -> dict[str, Any] | None:
        return self.extraction_artifacts.get(extraction_artifact_id)

    def find_extraction_artifact(
        self,
        *,
        content_object_id: str,
        extractor_name: str,
        extractor_version: str,
        markdown_sha256: str,
    ) -> dict[str, Any] | None:
        extraction_artifact_id = self.extraction_artifact_ids_by_content_hash.get(
            (content_object_id, extractor_name, extractor_version, markdown_sha256)
        )
        if extraction_artifact_id is None:
            return None
        return self.extraction_artifacts[extraction_artifact_id]

    def save_chunk_set(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _chunk_set_unique_key(record)
        existing_id = self.chunk_set_ids_by_unique_key.get(key)
        if existing_id is not None:
            return self.chunk_sets[existing_id]
        stored = deepcopy(record)
        self.chunk_sets[stored["chunk_set_id"]] = stored
        self.chunk_set_ids_by_unique_key[key] = stored["chunk_set_id"]
        return stored

    def get_chunk_set(self, chunk_set_id: str) -> dict[str, Any] | None:
        return self.chunk_sets.get(chunk_set_id)

    def find_chunk_set(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        chunk_policy_id: str,
        source_markdown_sha256: str,
    ) -> dict[str, Any] | None:
        chunk_set_id = self.chunk_set_ids_by_unique_key.get(
            (
                content_object_id,
                extraction_artifact_id,
                chunk_policy_id,
                source_markdown_sha256,
            )
        )
        if chunk_set_id is None:
            return None
        return self.chunk_sets[chunk_set_id]

    def save_lexical_index(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _lexical_index_unique_key(record)
        existing = self.lexical_indexes.get(key)
        if existing is not None:
            return existing
        stored = deepcopy(record)
        self.lexical_indexes[key] = stored
        return stored

    def find_lexical_index(
        self,
        *,
        chunk_set_id: str,
        tokenizer_used: str,
    ) -> dict[str, Any] | None:
        return self.lexical_indexes.get((chunk_set_id, tokenizer_used))

    def save_chunk_embedding_index(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _chunk_embedding_index_unique_key(record)
        existing = self.chunk_embedding_indexes.get(key)
        if existing is not None:
            return existing
        stored = deepcopy(record)
        self.chunk_embedding_indexes[key] = stored
        return stored

    def find_chunk_embedding_index(
        self,
        *,
        chunk_set_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        return self.chunk_embedding_indexes.get(
            (chunk_set_id, model_profile_id, model_revision)
        )

    def save_document_summary_record(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _document_summary_unique_key(record)
        existing_id = self.document_summary_ids_by_unique_key.get(key)
        if existing_id is not None:
            return self.document_summary_records[existing_id]
        stored = deepcopy(record)
        self.document_summary_records[stored["document_summary_id"]] = stored
        self.document_summary_ids_by_unique_key[key] = stored["document_summary_id"]
        return stored

    def get_document_summary_record(
        self,
        document_summary_id: str,
    ) -> dict[str, Any] | None:
        return self.document_summary_records.get(document_summary_id)

    def find_document_summary_record(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        summary_text_sha256: str,
    ) -> dict[str, Any] | None:
        document_summary_id = self.document_summary_ids_by_unique_key.get(
            (content_object_id, extraction_artifact_id, summary_text_sha256)
        )
        if document_summary_id is None:
            return None
        return self.document_summary_records[document_summary_id]

    def save_summary_embedding_record(self, record: dict[str, Any]) -> dict[str, Any]:
        key = _summary_embedding_unique_key(record)
        existing_id = self.summary_embedding_ids_by_unique_key.get(key)
        if existing_id is not None:
            return self.summary_embedding_records[existing_id]
        stored = deepcopy(record)
        self.summary_embedding_records[stored["summary_embedding_id"]] = stored
        self.summary_embedding_ids_by_unique_key[key] = stored["summary_embedding_id"]
        return stored

    def get_summary_embedding_record(
        self,
        summary_embedding_id: str,
    ) -> dict[str, Any] | None:
        return self.summary_embedding_records.get(summary_embedding_id)

    def find_summary_embedding_record(
        self,
        *,
        document_summary_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        summary_embedding_id = self.summary_embedding_ids_by_unique_key.get(
            (document_summary_id, model_profile_id, model_revision)
        )
        if summary_embedding_id is None:
            return None
        return self.summary_embedding_records[summary_embedding_id]


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

    def save_extraction_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_extraction_artifact(
                    session,
                    record_to_store,
                )
            )
        except IntegrityError as exc:
            existing = self.find_extraction_artifact(
                content_object_id=str(record_to_store["content_object_id"]),
                extractor_name=str(record_to_store["extractor_name"]),
                extractor_version=str(record_to_store["extractor_version"]),
                markdown_sha256=str(record_to_store["markdown_sha256"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_extraction_artifact(
        self,
        extraction_artifact_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_extraction_artifact(
                    session,
                    extraction_artifact_id,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_extraction_artifact(
        self,
        *,
        content_object_id: str,
        extractor_name: str,
        extractor_version: str,
        markdown_sha256: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_extraction_artifact_by_unique_key(
                    session,
                    content_object_id=content_object_id,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                    markdown_sha256=markdown_sha256,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_chunk_set(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_chunk_set(session, record_to_store)
            )
        except IntegrityError as exc:
            existing = self.find_chunk_set(
                content_object_id=str(record_to_store["content_object_id"]),
                extraction_artifact_id=str(record_to_store["extraction_artifact_id"]),
                chunk_policy_id=str(record_to_store["chunk_policy_id"]),
                source_markdown_sha256=str(record_to_store["source_markdown_sha256"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_chunk_set(self, chunk_set_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_chunk_set(session, chunk_set_id)
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_chunk_set(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        chunk_policy_id: str,
        source_markdown_sha256: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_chunk_set_by_unique_key(
                    session,
                    content_object_id=content_object_id,
                    extraction_artifact_id=extraction_artifact_id,
                    chunk_policy_id=chunk_policy_id,
                    source_markdown_sha256=source_markdown_sha256,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_lexical_index(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_lexical_index(session, record_to_store)
            )
        except IntegrityError as exc:
            existing = self.find_lexical_index(
                chunk_set_id=str(record_to_store["chunk_set_id"]),
                tokenizer_used=str(record_to_store["tokenizer_used"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_lexical_index(
        self,
        *,
        chunk_set_id: str,
        tokenizer_used: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_lexical_index(
                    session,
                    chunk_set_id=chunk_set_id,
                    tokenizer_used=tokenizer_used,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_chunk_embedding_index(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_chunk_embedding_index(
                    session,
                    record_to_store,
                )
            )
        except IntegrityError as exc:
            existing = self.find_chunk_embedding_index(
                chunk_set_id=str(record_to_store["chunk_set_id"]),
                model_profile_id=str(record_to_store["model_profile_id"]),
                model_revision=str(record_to_store["model_revision"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_chunk_embedding_index(
        self,
        *,
        chunk_set_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_chunk_embedding_index(
                    session,
                    chunk_set_id=chunk_set_id,
                    model_profile_id=model_profile_id,
                    model_revision=model_revision,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_document_summary_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_document_summary_record(
                    session,
                    record_to_store,
                )
            )
        except IntegrityError as exc:
            existing = self.find_document_summary_record(
                content_object_id=str(record_to_store["content_object_id"]),
                extraction_artifact_id=str(record_to_store["extraction_artifact_id"]),
                summary_text_sha256=str(record_to_store["summary_text_sha256"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_document_summary_record(
        self,
        document_summary_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_document_summary_record(
                    session,
                    document_summary_id,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_document_summary_record(
        self,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        summary_text_sha256: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_document_summary_record_by_unique_key(
                    session,
                    content_object_id=content_object_id,
                    extraction_artifact_id=extraction_artifact_id,
                    summary_text_sha256=summary_text_sha256,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def save_summary_embedding_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = deepcopy(record)
        try:
            return self._run_in_transaction(
                lambda session: self._save_summary_embedding_record(
                    session,
                    record_to_store,
                )
            )
        except IntegrityError as exc:
            existing = self.find_summary_embedding_record(
                document_summary_id=str(record_to_store["document_summary_id"]),
                model_profile_id=str(record_to_store["model_profile_id"]),
                model_revision=str(record_to_store["model_revision"]),
            )
            if existing is not None:
                return existing
            raise _content_repository_unavailable() from exc
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def get_summary_embedding_record(
        self,
        summary_embedding_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_summary_embedding_record(
                    session,
                    summary_embedding_id,
                )
        except SQLAlchemyError as exc:
            raise _content_repository_unavailable() from exc

    def find_summary_embedding_record(
        self,
        *,
        document_summary_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return self._select_summary_embedding_record_by_unique_key(
                    session,
                    document_summary_id=document_summary_id,
                    model_profile_id=model_profile_id,
                    model_revision=model_revision,
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

    def _save_extraction_artifact(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_extraction_artifact_by_unique_key(
            session,
            content_object_id=str(record["content_object_id"]),
            extractor_name=str(record["extractor_name"]),
            extractor_version=str(record["extractor_version"]),
            markdown_sha256=str(record["markdown_sha256"]),
        )
        if existing is not None:
            return existing
        self._insert_extraction_artifact(session, record)
        stored = self._select_extraction_artifact(
            session,
            str(record["extraction_artifact_id"]),
        )
        assert stored is not None
        return stored

    def _save_chunk_set(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_chunk_set_by_unique_key(
            session,
            content_object_id=str(record["content_object_id"]),
            extraction_artifact_id=str(record["extraction_artifact_id"]),
            chunk_policy_id=str(record["chunk_policy_id"]),
            source_markdown_sha256=str(record["source_markdown_sha256"]),
        )
        if existing is not None:
            return existing
        self._insert_chunk_set(session, record)
        self._insert_chunks(session, record)
        stored = self._select_chunk_set(session, str(record["chunk_set_id"]))
        assert stored is not None
        return stored

    def _save_lexical_index(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_lexical_index(
            session,
            chunk_set_id=str(record["chunk_set_id"]),
            tokenizer_used=str(record["tokenizer_used"]),
        )
        if existing is not None:
            return existing
        self._insert_lexical_terms(session, record)
        stored = self._select_lexical_index(
            session,
            chunk_set_id=str(record["chunk_set_id"]),
            tokenizer_used=str(record["tokenizer_used"]),
        )
        if stored is None:
            return deepcopy(record)
        return stored

    def _save_chunk_embedding_index(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_chunk_embedding_index(
            session,
            chunk_set_id=str(record["chunk_set_id"]),
            model_profile_id=str(record["model_profile_id"]),
            model_revision=str(record["model_revision"]),
        )
        if existing is not None:
            return existing
        self._insert_chunk_embeddings(session, record)
        stored = self._select_chunk_embedding_index(
            session,
            chunk_set_id=str(record["chunk_set_id"]),
            model_profile_id=str(record["model_profile_id"]),
            model_revision=str(record["model_revision"]),
        )
        if stored is None:
            return deepcopy(record)
        return stored

    def _save_document_summary_record(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_document_summary_record_by_unique_key(
            session,
            content_object_id=str(record["content_object_id"]),
            extraction_artifact_id=str(record["extraction_artifact_id"]),
            summary_text_sha256=str(record["summary_text_sha256"]),
        )
        if existing is not None:
            return existing
        self._insert_document_summary_record(session, record)
        stored = self._select_document_summary_record(
            session,
            str(record["document_summary_id"]),
        )
        assert stored is not None
        return stored

    def _save_summary_embedding_record(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._select_summary_embedding_record_by_unique_key(
            session,
            document_summary_id=str(record["document_summary_id"]),
            model_profile_id=str(record["model_profile_id"]),
            model_revision=str(record["model_revision"]),
        )
        if existing is not None:
            return existing
        self._insert_summary_embedding_record(session, record)
        stored = self._select_summary_embedding_record(
            session,
            str(record["summary_embedding_id"]),
        )
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

    def _select_extraction_artifact(
        self,
        session: Session,
        extraction_artifact_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_EXTRACTION_ARTIFACT_SELECT_COLUMNS}
                FROM cx_extraction_artifacts
                WHERE extraction_artifact_id = :extraction_artifact_id
                """
            ),
            {"extraction_artifact_id": extraction_artifact_id},
        ).mappings().first()
        return _extraction_artifact_from_row(row) if row is not None else None

    def _select_extraction_artifact_by_unique_key(
        self,
        session: Session,
        *,
        content_object_id: str,
        extractor_name: str,
        extractor_version: str,
        markdown_sha256: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_EXTRACTION_ARTIFACT_SELECT_COLUMNS}
                FROM cx_extraction_artifacts
                WHERE content_object_id = :content_object_id
                  AND extractor_name = :extractor_name
                  AND extractor_version = :extractor_version
                  AND markdown_sha256 = :markdown_sha256
                """
            ),
            {
                "content_object_id": content_object_id,
                "extractor_name": extractor_name,
                "extractor_version": extractor_version,
                "markdown_sha256": markdown_sha256,
            },
        ).mappings().first()
        return _extraction_artifact_from_row(row) if row is not None else None

    def _select_chunk_set(
        self,
        session: Session,
        chunk_set_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_CHUNK_SET_SELECT_COLUMNS}
                FROM cx_chunk_sets
                WHERE chunk_set_id = :chunk_set_id
                """
            ),
            {"chunk_set_id": chunk_set_id},
        ).mappings().first()
        if row is None:
            return None
        return _chunk_set_from_row(row, self._select_chunks(session, chunk_set_id))

    def _select_chunk_set_by_unique_key(
        self,
        session: Session,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        chunk_policy_id: str,
        source_markdown_sha256: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_CHUNK_SET_SELECT_COLUMNS}
                FROM cx_chunk_sets
                WHERE content_object_id = :content_object_id
                  AND extraction_artifact_id = :extraction_artifact_id
                  AND chunk_policy_id = :chunk_policy_id
                  AND source_markdown_sha256 = :source_markdown_sha256
                """
            ),
            {
                "content_object_id": content_object_id,
                "extraction_artifact_id": extraction_artifact_id,
                "chunk_policy_id": chunk_policy_id,
                "source_markdown_sha256": source_markdown_sha256,
            },
        ).mappings().first()
        if row is None:
            return None
        return _chunk_set_from_row(
            row,
            self._select_chunks(session, str(row["chunk_set_id"])),
        )

    def _select_chunks(self, session: Session, chunk_set_id: str) -> list[dict[str, Any]]:
        rows = session.execute(
            text(
                f"""
                SELECT {_CHUNK_SELECT_COLUMNS}
                FROM cx_chunks
                WHERE chunk_set_id = :chunk_set_id
                ORDER BY ordinal ASC
                """
            ),
            {"chunk_set_id": chunk_set_id},
        ).mappings().all()
        return [_chunk_from_row(row) for row in rows]

    def _select_lexical_index(
        self,
        session: Session,
        *,
        chunk_set_id: str,
        tokenizer_used: str,
    ) -> dict[str, Any] | None:
        rows = session.execute(
            text(
                f"""
                SELECT {_LEXICAL_TERM_SELECT_COLUMNS}
                FROM cx_lexical_terms
                WHERE chunk_set_id = :chunk_set_id
                  AND tokenizer_used = :tokenizer_used
                ORDER BY term ASC
                """
            ),
            {"chunk_set_id": chunk_set_id, "tokenizer_used": tokenizer_used},
        ).mappings().all()
        if not rows:
            return None
        terms = [
            _lexical_term_from_row(
                row,
                self._select_lexical_postings(session, str(row["lexical_term_id"])),
            )
            for row in rows
        ]
        chunk_set = self._select_chunk_set(session, chunk_set_id)
        chunk_count = chunk_set["chunk_count"] if chunk_set is not None else 0
        first = terms[0]
        return {
            "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
            "chunk_set_id": chunk_set_id,
            "tokenizer_requested": first["tokenizer_requested"],
            "tokenizer_used": first["tokenizer_used"],
            "tokenizer_fallback": first["tokenizer_fallback"],
            "fallback_used": first["fallback_used"],
            "chunk_count": chunk_count,
            "unique_token_count": len(terms),
            "terms": terms,
            "created_at": first["created_at"],
        }

    def _select_lexical_postings(
        self,
        session: Session,
        lexical_term_id: str,
    ) -> list[dict[str, Any]]:
        rows = session.execute(
            text(
                f"""
                SELECT {_LEXICAL_POSTING_SELECT_COLUMNS}
                FROM cx_lexical_postings
                WHERE lexical_term_id = :lexical_term_id
                ORDER BY chunk_id ASC
                """
            ),
            {"lexical_term_id": lexical_term_id},
        ).mappings().all()
        return [_lexical_posting_from_row(row) for row in rows]

    def _select_chunk_embedding_index(
        self,
        session: Session,
        *,
        chunk_set_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        rows = session.execute(
            text(
                f"""
                SELECT {_CHUNK_EMBEDDING_SELECT_COLUMNS}
                FROM cx_chunk_embeddings AS embedding
                JOIN cx_chunks AS chunk ON chunk.chunk_id = embedding.chunk_id
                WHERE chunk.chunk_set_id = :chunk_set_id
                  AND embedding.model_profile_id = :model_profile_id
                  AND embedding.model_revision = :model_revision
                ORDER BY chunk.ordinal ASC
                """
            ),
            {
                "chunk_set_id": chunk_set_id,
                "model_profile_id": model_profile_id,
                "model_revision": model_revision,
            },
        ).mappings().all()
        if not rows:
            return None
        embeddings = [_chunk_embedding_from_row(row) for row in rows]
        first = embeddings[0]
        return {
            "embedding_index_schema_version": "cx_embedding_index.persistence.v1",
            "chunk_set_id": chunk_set_id,
            "provider_alias": first["provider_alias"],
            "model_profile_id": first["model_profile_id"],
            "model_revision": first["model_revision"],
            "deployment_id": first["deployment_id"],
            "chunk_count": len(embeddings),
            "vector_dimension": first["vector_dimension"],
            "chunk_embeddings": embeddings,
            "created_trace_id": first["created_trace_id"],
            "created_at": first["created_at"],
        }

    def _select_document_summary_record(
        self,
        session: Session,
        document_summary_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_DOCUMENT_SUMMARY_SELECT_COLUMNS}
                FROM cx_document_summaries
                WHERE document_summary_id = :document_summary_id
                """
            ),
            {"document_summary_id": document_summary_id},
        ).mappings().first()
        return _document_summary_from_row(row) if row is not None else None

    def _select_document_summary_record_by_unique_key(
        self,
        session: Session,
        *,
        content_object_id: str,
        extraction_artifact_id: str,
        summary_text_sha256: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_DOCUMENT_SUMMARY_SELECT_COLUMNS}
                FROM cx_document_summaries
                WHERE content_object_id = :content_object_id
                  AND extraction_artifact_id = :extraction_artifact_id
                  AND summary_text_sha256 = :summary_text_sha256
                """
            ),
            {
                "content_object_id": content_object_id,
                "extraction_artifact_id": extraction_artifact_id,
                "summary_text_sha256": summary_text_sha256,
            },
        ).mappings().first()
        return _document_summary_from_row(row) if row is not None else None

    def _select_summary_embedding_record(
        self,
        session: Session,
        summary_embedding_id: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_SUMMARY_EMBEDDING_SELECT_COLUMNS}
                FROM cx_document_summary_embeddings
                WHERE summary_embedding_id = :summary_embedding_id
                """
            ),
            {"summary_embedding_id": summary_embedding_id},
        ).mappings().first()
        return _summary_embedding_from_row(row) if row is not None else None

    def _select_summary_embedding_record_by_unique_key(
        self,
        session: Session,
        *,
        document_summary_id: str,
        model_profile_id: str,
        model_revision: str,
    ) -> dict[str, Any] | None:
        row = session.execute(
            text(
                f"""
                SELECT {_SUMMARY_EMBEDDING_SELECT_COLUMNS}
                FROM cx_document_summary_embeddings
                WHERE document_summary_id = :document_summary_id
                  AND model_profile_id = :model_profile_id
                  AND model_revision = :model_revision
                """
            ),
            {
                "document_summary_id": document_summary_id,
                "model_profile_id": model_profile_id,
                "model_revision": model_revision,
            },
        ).mappings().first()
        return _summary_embedding_from_row(row) if row is not None else None

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

    def _insert_extraction_artifact(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO cx_extraction_artifacts (
                    extraction_artifact_id,
                    content_object_id,
                    source_file_id,
                    artifact_kind,
                    status,
                    extractor_name,
                    extractor_version,
                    markdown_sha256,
                    markdown_storage_uri,
                    markdown_char_count,
                    created_trace_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    :extraction_artifact_id,
                    :content_object_id,
                    :source_file_id,
                    :artifact_kind,
                    :status,
                    :extractor_name,
                    :extractor_version,
                    :markdown_sha256,
                    :markdown_storage_uri,
                    :markdown_char_count,
                    :created_trace_id,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _extraction_artifact_insert_params(record),
        )

    def _insert_chunk_set(self, session: Session, record: dict[str, Any]) -> None:
        session.execute(
            text(
                """
                INSERT INTO cx_chunk_sets (
                    chunk_set_id,
                    content_object_id,
                    extraction_artifact_id,
                    chunk_policy_id,
                    chunk_size,
                    chunk_overlap,
                    source_markdown_sha256,
                    chunk_count,
                    created_trace_id,
                    created_at
                )
                VALUES (
                    :chunk_set_id,
                    :content_object_id,
                    :extraction_artifact_id,
                    :chunk_policy_id,
                    :chunk_size,
                    :chunk_overlap,
                    :source_markdown_sha256,
                    :chunk_count,
                    :created_trace_id,
                    :created_at
                )
                """
            ),
            _chunk_set_insert_params(record),
        )

    def _insert_chunks(self, session: Session, record: dict[str, Any]) -> None:
        chunks = record.get("chunks", [])
        if not chunks:
            return
        session.execute(
            text(
                """
                INSERT INTO cx_chunks (
                    chunk_id,
                    chunk_set_id,
                    content_object_id,
                    ordinal,
                    start_offset,
                    end_offset,
                    char_count,
                    text_sha256,
                    text_preview,
                    created_at
                )
                VALUES (
                    :chunk_id,
                    :chunk_set_id,
                    :content_object_id,
                    :ordinal,
                    :start_offset,
                    :end_offset,
                    :char_count,
                    :text_sha256,
                    :text_preview,
                    :created_at
                )
                """
            ),
            [_chunk_insert_params(record, chunk) for chunk in chunks],
        )

    def _insert_lexical_terms(self, session: Session, record: dict[str, Any]) -> None:
        terms = record.get("terms", [])
        if not terms:
            return
        session.execute(
            text(
                """
                INSERT INTO cx_lexical_terms (
                    lexical_term_id,
                    chunk_set_id,
                    tokenizer_requested,
                    tokenizer_used,
                    tokenizer_fallback,
                    fallback_used,
                    term,
                    document_frequency,
                    created_at
                )
                VALUES (
                    :lexical_term_id,
                    :chunk_set_id,
                    :tokenizer_requested,
                    :tokenizer_used,
                    :tokenizer_fallback,
                    :fallback_used,
                    :term,
                    :document_frequency,
                    :created_at
                )
                """
            ),
            [_lexical_term_insert_params(record, term) for term in terms],
        )
        posting_params = [
            _lexical_posting_insert_params(term, posting)
            for term in terms
            for posting in term["postings"]
        ]
        if not posting_params:
            return
        session.execute(
            text(
                """
                INSERT INTO cx_lexical_postings (
                    lexical_posting_id,
                    lexical_term_id,
                    chunk_id,
                    occurrence_count,
                    created_at
                )
                VALUES (
                    :lexical_posting_id,
                    :lexical_term_id,
                    :chunk_id,
                    :occurrence_count,
                    :created_at
                )
                """
            ),
            posting_params,
        )

    def _insert_chunk_embeddings(self, session: Session, record: dict[str, Any]) -> None:
        embeddings = record.get("chunk_embeddings", [])
        if not embeddings:
            return
        session.execute(
            text(
                """
                INSERT INTO cx_chunk_embeddings (
                    chunk_embedding_id,
                    chunk_id,
                    provider_alias,
                    model_profile_id,
                    model_revision,
                    deployment_id,
                    vector_dimension,
                    embedding_sha256,
                    embedding_storage_uri,
                    status,
                    created_trace_id,
                    created_at
                )
                VALUES (
                    :chunk_embedding_id,
                    :chunk_id,
                    :provider_alias,
                    :model_profile_id,
                    :model_revision,
                    :deployment_id,
                    :vector_dimension,
                    :embedding_sha256,
                    :embedding_storage_uri,
                    :status,
                    :created_trace_id,
                    :created_at
                )
                """
            ),
            [_chunk_embedding_insert_params(record, item) for item in embeddings],
        )

    def _insert_document_summary_record(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO cx_document_summaries (
                    document_summary_id,
                    content_object_id,
                    extraction_artifact_id,
                    prompt_template_version_id,
                    summary_chunk_policy_id,
                    summary_text_sha256,
                    summary_storage_uri,
                    summary_char_count,
                    summary_max_chars,
                    summary_hard_limit_chars,
                    status,
                    language_code,
                    model_profile_id,
                    model_revision,
                    created_trace_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    :document_summary_id,
                    :content_object_id,
                    :extraction_artifact_id,
                    :prompt_template_version_id,
                    :summary_chunk_policy_id,
                    :summary_text_sha256,
                    :summary_storage_uri,
                    :summary_char_count,
                    :summary_max_chars,
                    :summary_hard_limit_chars,
                    :status,
                    :language_code,
                    :model_profile_id,
                    :model_revision,
                    :created_trace_id,
                    :created_at,
                    :updated_at
                )
                """
            ),
            _document_summary_insert_params(record),
        )

    def _insert_summary_embedding_record(
        self,
        session: Session,
        record: dict[str, Any],
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO cx_document_summary_embeddings (
                    summary_embedding_id,
                    document_summary_id,
                    provider_alias,
                    model_profile_id,
                    model_revision,
                    deployment_id,
                    vector_dimension,
                    embedding_sha256,
                    embedding_storage_uri,
                    status,
                    created_trace_id,
                    created_at
                )
                VALUES (
                    :summary_embedding_id,
                    :document_summary_id,
                    :provider_alias,
                    :model_profile_id,
                    :model_revision,
                    :deployment_id,
                    :vector_dimension,
                    :embedding_sha256,
                    :embedding_storage_uri,
                    :status,
                    :created_trace_id,
                    :created_at
                )
                """
            ),
            _summary_embedding_insert_params(record),
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


def build_extraction_artifact_record(
    extraction_result: dict[str, Any],
    *,
    content_object_id: str,
    source_file_id: str,
) -> dict[str, Any]:
    extractor = extraction_result["extractor"]
    extractor_name = str(extractor["provider"])
    extractor_version = str(extractor["version"])
    markdown_sha256 = str(extraction_result["extracted_markdown_sha256"])
    extraction_artifact_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-extraction-artifact:"
            f"{content_object_id}:{extractor_name}:{extractor_version}:{markdown_sha256}",
        )
    )
    return {
        "extraction_artifact_id": extraction_artifact_id,
        "content_object_id": content_object_id,
        "source_file_id": source_file_id,
        "artifact_kind": "markdown",
        "status": extraction_result["status"],
        "extractor_name": extractor_name,
        "extractor_version": extractor_version,
        "markdown_sha256": markdown_sha256,
        "markdown_storage_uri": markdown_storage_uri_from_path(
            str(extraction_result["extracted_markdown_path"])
        ),
        "markdown_char_count": extraction_result["markdown_char_count"],
        "created_trace_id": extraction_result["trace_id"],
        "created_at": extraction_result["created_at"],
        "updated_at": extraction_result["updated_at"],
    }


def build_chunk_set_record(
    chunk_set: dict[str, Any],
    *,
    content_object_id: str,
    extraction_artifact_id: str,
) -> dict[str, Any]:
    chunk_policy_id = str(chunk_set["chunk_policy"])
    source_markdown_sha256 = str(chunk_set["source_markdown_sha256"])
    chunk_set_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-chunk-set:"
            f"{content_object_id}:{extraction_artifact_id}:"
            f"{chunk_policy_id}:{source_markdown_sha256}",
        )
    )
    created_at = chunk_set["created_at"]
    return {
        "chunk_set_id": chunk_set_id,
        "content_object_id": content_object_id,
        "extraction_artifact_id": extraction_artifact_id,
        "chunk_policy_id": chunk_policy_id,
        "chunk_size": chunk_set["chunk_size"],
        "chunk_overlap": chunk_set["chunk_overlap"],
        "source_markdown_sha256": source_markdown_sha256,
        "chunk_count": chunk_set["chunk_count"],
        "created_trace_id": chunk_set.get("trace_id"),
        "created_at": created_at,
        "chunks": [
            {
                "chunk_id": str(chunk["chunk_id"]),
                "chunk_set_id": chunk_set_id,
                "content_object_id": content_object_id,
                "ordinal": chunk["ordinal"],
                "start_offset": chunk["start_offset"],
                "end_offset": chunk["end_offset"],
                "char_count": chunk["char_count"],
                "text_sha256": chunk["text_sha256"],
                "text_preview": chunk["text_preview"],
                "created_at": created_at,
            }
            for chunk in chunk_set["chunks"]
        ],
    }


def build_lexical_index_record(
    lexical_index: dict[str, Any],
    *,
    chunk_set_id: str,
) -> dict[str, Any]:
    created_at = lexical_index["created_at"]
    tokenizer_used = str(lexical_index["tokenizer_used"])
    terms = []
    for posting in lexical_index["postings"]:
        term_text = str(posting["term"])
        lexical_term_id = str(
            uuid5(
                NAMESPACE_URL,
                f"cx-lexical-term:{chunk_set_id}:{tokenizer_used}:{term_text}",
            )
        )
        terms.append(
            {
                "lexical_term_id": lexical_term_id,
                "chunk_set_id": chunk_set_id,
                "tokenizer_requested": lexical_index["tokenizer_requested"],
                "tokenizer_used": tokenizer_used,
                "tokenizer_fallback": lexical_index["tokenizer_fallback"],
                "fallback_used": lexical_index["fallback_used"],
                "term": term_text,
                "document_frequency": posting["document_frequency"],
                "postings": [
                    {
                        "lexical_posting_id": str(
                            uuid5(
                                NAMESPACE_URL,
                                "cx-lexical-posting:"
                                f"{lexical_term_id}:{occurrence['chunk_id']}",
                            )
                        ),
                        "lexical_term_id": lexical_term_id,
                        "chunk_id": occurrence["chunk_id"],
                        "occurrence_count": occurrence["count"],
                        "created_at": created_at,
                    }
                    for occurrence in posting["occurrences"]
                ],
                "created_at": created_at,
            }
        )
    return {
        "lexical_index_schema_version": "cx_lexical_index.persistence.v1",
        "chunk_set_id": chunk_set_id,
        "tokenizer_requested": lexical_index["tokenizer_requested"],
        "tokenizer_used": tokenizer_used,
        "tokenizer_fallback": lexical_index["tokenizer_fallback"],
        "fallback_used": lexical_index["fallback_used"],
        "chunk_count": lexical_index["chunk_count"],
        "unique_token_count": lexical_index["unique_token_count"],
        "terms": terms,
        "created_at": created_at,
    }


def build_chunk_embedding_index_record(
    embedding_index: dict[str, Any],
    *,
    chunk_set_id: str,
) -> dict[str, Any]:
    provider_alias = str(embedding_index["provider_alias"])
    model_profile_id = str(embedding_index.get("model_profile_id", provider_alias))
    model_revision = str(embedding_index["model_revision"])
    created_at = embedding_index["created_at"]
    created_trace_id = embedding_index.get("trace_id")
    return {
        "embedding_index_schema_version": "cx_embedding_index.persistence.v1",
        "chunk_set_id": chunk_set_id,
        "provider_alias": provider_alias,
        "model_profile_id": model_profile_id,
        "model_revision": model_revision,
        "deployment_id": embedding_index["deployment_id"],
        "chunk_count": embedding_index["chunk_count"],
        "vector_dimension": embedding_index["vector_dimension"],
        "chunk_embeddings": [
            {
                "chunk_embedding_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        "cx-chunk-embedding:"
                        f"{chunk['chunk_id']}:{model_profile_id}:{model_revision}",
                    )
                ),
                "chunk_id": chunk["chunk_id"],
                "provider_alias": provider_alias,
                "model_profile_id": model_profile_id,
                "model_revision": model_revision,
                "deployment_id": embedding_index["deployment_id"],
                "vector_dimension": chunk["vector_dimension"],
                "embedding_sha256": chunk["embedding_sha256"],
                "embedding_storage_uri": chunk.get("embedding_storage_uri"),
                "status": chunk.get("status", "READY"),
                "created_trace_id": created_trace_id,
                "created_at": created_at,
            }
            for chunk in embedding_index["chunk_embeddings"]
        ],
        "created_trace_id": created_trace_id,
        "created_at": created_at,
    }


def build_document_summary_persistence_record(
    summary: dict[str, Any],
    *,
    content_object_id: str,
    extraction_artifact_id: str,
) -> dict[str, Any]:
    summarizer = summary.get("summarizer")
    if not isinstance(summarizer, dict):
        summarizer = {}
    return {
        "document_summary_schema_version": "cx_document_summary.persistence.v1",
        "document_summary_id": summary["document_summary_id"],
        "content_object_id": content_object_id,
        "extraction_artifact_id": extraction_artifact_id,
        "prompt_template_version_id": summary.get("prompt_template_version_id"),
        "summary_chunk_policy_id": summary["summary_chunk_policy_id"],
        "summary_text_sha256": summary["summary_text_sha256"],
        "summary_storage_uri": summary["summary_storage_uri"],
        "summary_char_count": summary["summary_char_count"],
        "summary_max_chars": summary["summary_max_chars"],
        "summary_hard_limit_chars": summary["summary_hard_limit_chars"],
        "status": summary.get("status", "READY"),
        "language_code": summary.get("language_code"),
        "model_profile_id": summarizer.get("model_profile_id"),
        "model_revision": summarizer.get("model_revision"),
        "created_trace_id": summary.get("trace_id", summary.get("created_trace_id")),
        "created_at": summary["created_at"],
        "updated_at": summary["updated_at"],
    }


def build_summary_embedding_persistence_record(
    record: dict[str, Any],
    *,
    document_summary_id: str,
) -> dict[str, Any]:
    provider_alias = str(record["provider_alias"])
    model_profile_id = str(record.get("model_profile_id", provider_alias))
    model_revision = str(record["model_revision"])
    summary_embedding_id = str(
        uuid5(
            NAMESPACE_URL,
            "cx-document-summary-embedding:"
            f"{document_summary_id}:{model_profile_id}:{model_revision}",
        )
    )
    return {
        "summary_embedding_schema_version": (
            "cx_document_summary_embedding.persistence.v1"
        ),
        "summary_embedding_id": summary_embedding_id,
        "document_summary_id": document_summary_id,
        "provider_alias": provider_alias,
        "model_profile_id": model_profile_id,
        "model_revision": model_revision,
        "deployment_id": record["deployment_id"],
        "vector_dimension": record["vector_dimension"],
        "embedding_sha256": record["embedding_sha256"],
        "embedding_storage_uri": record.get("embedding_storage_uri"),
        "status": record.get("status", "READY"),
        "created_trace_id": record.get("trace_id", record.get("created_trace_id")),
        "created_at": record["created_at"],
    }


def markdown_storage_uri_from_path(extracted_markdown_path: str) -> str:
    path = Path(extracted_markdown_path)
    if len(path.parts) >= 2:
        suffix = "/".join(path.parts[-2:])
    else:
        suffix = path.name
    return f"local://cx/extracted-markdown/{suffix}"


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

_EXTRACTION_ARTIFACT_SELECT_COLUMNS = """
    extraction_artifact_id,
    content_object_id,
    source_file_id,
    artifact_kind,
    status,
    extractor_name,
    extractor_version,
    markdown_sha256,
    markdown_storage_uri,
    markdown_char_count,
    created_trace_id,
    created_at,
    updated_at
"""

_CHUNK_SET_SELECT_COLUMNS = """
    chunk_set_id,
    content_object_id,
    extraction_artifact_id,
    chunk_policy_id,
    chunk_size,
    chunk_overlap,
    source_markdown_sha256,
    chunk_count,
    created_trace_id,
    created_at
"""

_CHUNK_SELECT_COLUMNS = """
    chunk_id,
    chunk_set_id,
    content_object_id,
    ordinal,
    start_offset,
    end_offset,
    char_count,
    text_sha256,
    text_preview,
    created_at
"""

_LEXICAL_TERM_SELECT_COLUMNS = """
    lexical_term_id,
    chunk_set_id,
    tokenizer_requested,
    tokenizer_used,
    tokenizer_fallback,
    fallback_used,
    term,
    document_frequency,
    created_at
"""

_LEXICAL_POSTING_SELECT_COLUMNS = """
    lexical_posting_id,
    lexical_term_id,
    chunk_id,
    occurrence_count,
    created_at
"""

_CHUNK_EMBEDDING_SELECT_COLUMNS = """
    embedding.chunk_embedding_id,
    embedding.chunk_id,
    embedding.provider_alias,
    embedding.model_profile_id,
    embedding.model_revision,
    embedding.deployment_id,
    embedding.vector_dimension,
    embedding.embedding_sha256,
    embedding.embedding_storage_uri,
    embedding.status,
    embedding.created_trace_id,
    embedding.created_at
"""

_DOCUMENT_SUMMARY_SELECT_COLUMNS = """
    document_summary_id,
    content_object_id,
    extraction_artifact_id,
    prompt_template_version_id,
    summary_chunk_policy_id,
    summary_text_sha256,
    summary_storage_uri,
    summary_char_count,
    summary_max_chars,
    summary_hard_limit_chars,
    status,
    language_code,
    model_profile_id,
    model_revision,
    created_trace_id,
    created_at,
    updated_at
"""

_SUMMARY_EMBEDDING_SELECT_COLUMNS = """
    summary_embedding_id,
    document_summary_id,
    provider_alias,
    model_profile_id,
    model_revision,
    deployment_id,
    vector_dimension,
    embedding_sha256,
    embedding_storage_uri,
    status,
    created_trace_id,
    created_at
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


def _extraction_artifact_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "extraction_artifact_id": record["extraction_artifact_id"],
        "content_object_id": record["content_object_id"],
        "source_file_id": record["source_file_id"],
        "artifact_kind": record["artifact_kind"],
        "status": record["status"],
        "extractor_name": record["extractor_name"],
        "extractor_version": record["extractor_version"],
        "markdown_sha256": record["markdown_sha256"],
        "markdown_storage_uri": record["markdown_storage_uri"],
        "markdown_char_count": record["markdown_char_count"],
        "created_trace_id": record.get("created_trace_id"),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _chunk_set_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_set_id": record["chunk_set_id"],
        "content_object_id": record["content_object_id"],
        "extraction_artifact_id": record["extraction_artifact_id"],
        "chunk_policy_id": record["chunk_policy_id"],
        "chunk_size": record["chunk_size"],
        "chunk_overlap": record["chunk_overlap"],
        "source_markdown_sha256": record["source_markdown_sha256"],
        "chunk_count": record["chunk_count"],
        "created_trace_id": record.get("created_trace_id"),
        "created_at": record["created_at"],
    }


def _chunk_insert_params(
    record: dict[str, Any],
    chunk: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "chunk_set_id": record["chunk_set_id"],
        "content_object_id": record["content_object_id"],
        "ordinal": chunk["ordinal"],
        "start_offset": chunk["start_offset"],
        "end_offset": chunk["end_offset"],
        "char_count": chunk["char_count"],
        "text_sha256": chunk["text_sha256"],
        "text_preview": chunk["text_preview"],
        "created_at": chunk.get("created_at", record["created_at"]),
    }


def _lexical_term_insert_params(
    record: dict[str, Any],
    term: dict[str, Any],
) -> dict[str, Any]:
    return {
        "lexical_term_id": term["lexical_term_id"],
        "chunk_set_id": record["chunk_set_id"],
        "tokenizer_requested": term["tokenizer_requested"],
        "tokenizer_used": term["tokenizer_used"],
        "tokenizer_fallback": term["tokenizer_fallback"],
        "fallback_used": term["fallback_used"],
        "term": term["term"],
        "document_frequency": term["document_frequency"],
        "created_at": term.get("created_at", record["created_at"]),
    }


def _lexical_posting_insert_params(
    term: dict[str, Any],
    posting: dict[str, Any],
) -> dict[str, Any]:
    return {
        "lexical_posting_id": posting["lexical_posting_id"],
        "lexical_term_id": term["lexical_term_id"],
        "chunk_id": posting["chunk_id"],
        "occurrence_count": posting["occurrence_count"],
        "created_at": posting.get("created_at", term["created_at"]),
    }


def _chunk_embedding_insert_params(
    record: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "chunk_embedding_id": item["chunk_embedding_id"],
        "chunk_id": item["chunk_id"],
        "provider_alias": item["provider_alias"],
        "model_profile_id": item["model_profile_id"],
        "model_revision": item["model_revision"],
        "deployment_id": item["deployment_id"],
        "vector_dimension": item["vector_dimension"],
        "embedding_sha256": item["embedding_sha256"],
        "embedding_storage_uri": item.get("embedding_storage_uri"),
        "status": item.get("status", "READY"),
        "created_trace_id": item.get("created_trace_id", record.get("created_trace_id")),
        "created_at": item.get("created_at", record["created_at"]),
    }


def _document_summary_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_summary_id": record["document_summary_id"],
        "content_object_id": record["content_object_id"],
        "extraction_artifact_id": record["extraction_artifact_id"],
        "prompt_template_version_id": record.get("prompt_template_version_id"),
        "summary_chunk_policy_id": record["summary_chunk_policy_id"],
        "summary_text_sha256": record["summary_text_sha256"],
        "summary_storage_uri": record["summary_storage_uri"],
        "summary_char_count": record["summary_char_count"],
        "summary_max_chars": record["summary_max_chars"],
        "summary_hard_limit_chars": record["summary_hard_limit_chars"],
        "status": record.get("status", "READY"),
        "language_code": record.get("language_code"),
        "model_profile_id": record.get("model_profile_id"),
        "model_revision": record.get("model_revision"),
        "created_trace_id": record.get("created_trace_id"),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def _summary_embedding_insert_params(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary_embedding_id": record["summary_embedding_id"],
        "document_summary_id": record["document_summary_id"],
        "provider_alias": record["provider_alias"],
        "model_profile_id": record["model_profile_id"],
        "model_revision": record["model_revision"],
        "deployment_id": record["deployment_id"],
        "vector_dimension": record["vector_dimension"],
        "embedding_sha256": record["embedding_sha256"],
        "embedding_storage_uri": record.get("embedding_storage_uri"),
        "status": record.get("status", "READY"),
        "created_trace_id": record.get("created_trace_id"),
        "created_at": record["created_at"],
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


def _extraction_artifact_from_row(row: Any) -> dict[str, Any]:
    return {
        "extraction_artifact_id": str(row["extraction_artifact_id"]),
        "content_object_id": str(row["content_object_id"]),
        "source_file_id": str(row["source_file_id"]),
        "artifact_kind": row["artifact_kind"],
        "status": row["status"],
        "extractor_name": row["extractor_name"],
        "extractor_version": row["extractor_version"],
        "markdown_sha256": row["markdown_sha256"],
        "markdown_storage_uri": row["markdown_storage_uri"],
        "markdown_char_count": int(row["markdown_char_count"]),
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _chunk_set_from_row(
    row: Any,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "chunk_set_id": str(row["chunk_set_id"]),
        "content_object_id": str(row["content_object_id"]),
        "extraction_artifact_id": str(row["extraction_artifact_id"]),
        "chunk_policy_id": row["chunk_policy_id"],
        "chunk_size": int(row["chunk_size"]),
        "chunk_overlap": int(row["chunk_overlap"]),
        "source_markdown_sha256": row["source_markdown_sha256"],
        "chunk_count": int(row["chunk_count"]),
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
        "chunks": chunks,
    }


def _chunk_from_row(row: Any) -> dict[str, Any]:
    return {
        "chunk_id": str(row["chunk_id"]),
        "chunk_set_id": str(row["chunk_set_id"]),
        "content_object_id": str(row["content_object_id"]),
        "ordinal": int(row["ordinal"]),
        "start_offset": int(row["start_offset"]),
        "end_offset": int(row["end_offset"]),
        "char_count": int(row["char_count"]),
        "text_sha256": row["text_sha256"],
        "text_preview": row["text_preview"],
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _lexical_term_from_row(
    row: Any,
    postings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "lexical_term_id": str(row["lexical_term_id"]),
        "chunk_set_id": str(row["chunk_set_id"]),
        "tokenizer_requested": row["tokenizer_requested"],
        "tokenizer_used": row["tokenizer_used"],
        "tokenizer_fallback": row["tokenizer_fallback"],
        "fallback_used": _bool_from_database(row["fallback_used"]),
        "term": row["term"],
        "document_frequency": int(row["document_frequency"]),
        "postings": postings,
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _lexical_posting_from_row(row: Any) -> dict[str, Any]:
    return {
        "lexical_posting_id": str(row["lexical_posting_id"]),
        "lexical_term_id": str(row["lexical_term_id"]),
        "chunk_id": str(row["chunk_id"]),
        "occurrence_count": int(row["occurrence_count"]),
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _chunk_embedding_from_row(row: Any) -> dict[str, Any]:
    return {
        "chunk_embedding_id": str(row["chunk_embedding_id"]),
        "chunk_id": str(row["chunk_id"]),
        "provider_alias": row["provider_alias"],
        "model_profile_id": row["model_profile_id"],
        "model_revision": row["model_revision"],
        "deployment_id": row["deployment_id"],
        "vector_dimension": int(row["vector_dimension"]),
        "embedding_sha256": row["embedding_sha256"],
        "embedding_storage_uri": row["embedding_storage_uri"],
        "status": row["status"],
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _document_summary_from_row(row: Any) -> dict[str, Any]:
    return {
        "document_summary_schema_version": "cx_document_summary.persistence.v1",
        "document_summary_id": str(row["document_summary_id"]),
        "content_object_id": str(row["content_object_id"]),
        "extraction_artifact_id": str(row["extraction_artifact_id"]),
        "prompt_template_version_id": _optional_uuid_to_wire(
            row["prompt_template_version_id"]
        ),
        "summary_chunk_policy_id": row["summary_chunk_policy_id"],
        "summary_text_sha256": row["summary_text_sha256"],
        "summary_storage_uri": row["summary_storage_uri"],
        "summary_char_count": int(row["summary_char_count"]),
        "summary_max_chars": int(row["summary_max_chars"]),
        "summary_hard_limit_chars": int(row["summary_hard_limit_chars"]),
        "status": row["status"],
        "language_code": row["language_code"],
        "model_profile_id": row["model_profile_id"],
        "model_revision": row["model_revision"],
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _summary_embedding_from_row(row: Any) -> dict[str, Any]:
    return {
        "summary_embedding_schema_version": (
            "cx_document_summary_embedding.persistence.v1"
        ),
        "summary_embedding_id": str(row["summary_embedding_id"]),
        "document_summary_id": str(row["document_summary_id"]),
        "provider_alias": row["provider_alias"],
        "model_profile_id": row["model_profile_id"],
        "model_revision": row["model_revision"],
        "deployment_id": row["deployment_id"],
        "vector_dimension": int(row["vector_dimension"]),
        "embedding_sha256": row["embedding_sha256"],
        "embedding_storage_uri": row["embedding_storage_uri"],
        "status": row["status"],
        "created_trace_id": row["created_trace_id"],
        "created_at": _timestamp_to_wire(row["created_at"]),
    }


def _extraction_artifact_unique_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record["content_object_id"]),
        str(record["extractor_name"]),
        str(record["extractor_version"]),
        str(record["markdown_sha256"]),
    )


def _chunk_set_unique_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record["content_object_id"]),
        str(record["extraction_artifact_id"]),
        str(record["chunk_policy_id"]),
        str(record["source_markdown_sha256"]),
    )


def _lexical_index_unique_key(record: dict[str, Any]) -> tuple[str, str]:
    return (str(record["chunk_set_id"]), str(record["tokenizer_used"]))


def _chunk_embedding_index_unique_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["chunk_set_id"]),
        str(record["model_profile_id"]),
        str(record["model_revision"]),
    )


def _document_summary_unique_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["content_object_id"]),
        str(record["extraction_artifact_id"]),
        str(record["summary_text_sha256"]),
    )


def _summary_embedding_unique_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["document_summary_id"]),
        str(record["model_profile_id"]),
        str(record["model_revision"]),
    )


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


def _optional_uuid_to_wire(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _bool_from_database(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"1", "t", "true", "yes"}
    return bool(value)


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _content_repository_unavailable() -> CxContentRepositoryError:
    return CxContentRepositoryError(
        error_code="cx_content.repository_unavailable",
        detail="CX content repository is unavailable.",
        status_code=503,
    )
