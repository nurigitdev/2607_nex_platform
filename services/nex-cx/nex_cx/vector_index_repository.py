from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.vector_index_freshness import validate_vector_index_manifest


class VectorIndexRepositoryError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


@runtime_checkable
class VectorIndexRepository(Protocol):
    def create(self, manifest: Mapping[str, Any]) -> dict[str, Any]: ...

    def get(
        self,
        vector_index_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None: ...

    def save(
        self,
        manifest: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]: ...


class InMemoryVectorIndexRepository:
    def __init__(self) -> None:
        self._manifests: dict[str, dict[str, Any]] = {}

    def create(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        value = validate_vector_index_manifest(manifest)
        index_id = value["vector_index_id"]
        existing = self._manifests.get(index_id)
        if existing is not None and existing != value:
            raise VectorIndexRepositoryError(
                "cx.vector_index.create_conflict",
                "Vector index identity already exists with different metadata.",
            )
        self._manifests[index_id] = deepcopy(value)
        return deepcopy(value)

    def get(
        self,
        vector_index_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        value = self._manifests.get(vector_index_id)
        if value is None:
            return None
        if (
            value["tenant_ref"]["id"] != tenant_id
            or value["owner_subject_ref"]["id"] != owner_subject_id
        ):
            return None
        return deepcopy(value)

    def save(
        self,
        manifest: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        value = validate_vector_index_manifest(manifest)
        current = self._manifests.get(value["vector_index_id"])
        if (
            current is None
            or current["checkpoint_version"] != expected_checkpoint_version
            or value["checkpoint_version"] != expected_checkpoint_version + 1
            or current["tenant_ref"] != value["tenant_ref"]
            or current["owner_subject_ref"] != value["owner_subject_ref"]
        ):
            raise VectorIndexRepositoryError(
                "cx.vector_index.checkpoint_conflict",
                "Vector index checkpoint changed before persistence.",
                retryable=True,
            )
        self._manifests[value["vector_index_id"]] = deepcopy(value)
        return deepcopy(value)


class SqlAlchemyVectorIndexRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        value = validate_vector_index_manifest(manifest)
        parameters = _manifest_parameters(value)
        try:
            with self._session_factory.begin() as session:
                session.execute(
                    text(
                        """
                        INSERT INTO cx_vector_indexes (
                            vector_index_id, index_schema_version,
                            content_object_id, chunk_set_id,
                            tenant_ref_type, tenant_ref_id,
                            owner_subject_ref_type, owner_subject_ref_id,
                            chunk_policy_id, source_markdown_sha256,
                            source_fingerprint, source_chunk_count,
                            provider_alias, model_profile_id, model_revision,
                            deployment_id, vector_dimension, profile_fingerprint,
                            status, status_reason, payload_count,
                            payload_fingerprint, checkpoint_version,
                            trace_id, request_id, created_at, updated_at, ready_at
                        ) VALUES (
                            :vector_index_id, :index_schema_version,
                            :content_object_id, :chunk_set_id,
                            'oa.tenant', :tenant_id,
                            'oa.user', :owner_subject_id,
                            :chunk_policy_id, :source_markdown_sha256,
                            :source_fingerprint, :source_chunk_count,
                            :provider_alias, :model_profile_id, :model_revision,
                            :deployment_id, :vector_dimension, :profile_fingerprint,
                            :status, :status_reason, :payload_count,
                            :payload_fingerprint, :checkpoint_version,
                            :trace_id, :request_id, :created_at, :updated_at, :ready_at
                        )
                        ON CONFLICT (vector_index_id) DO NOTHING
                        """
                    ),
                    parameters,
                )
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        stored = self.get(
            value["vector_index_id"],
            tenant_id=value["tenant_ref"]["id"],
            owner_subject_id=value["owner_subject_ref"]["id"],
        )
        if stored is None or not _manifests_equivalent(stored, value):
            raise VectorIndexRepositoryError(
                "cx.vector_index.create_conflict",
                "Vector index identity already exists with different metadata.",
            )
        return deepcopy(value)

    def get(
        self,
        vector_index_id: str,
        *,
        tenant_id: str,
        owner_subject_id: str,
    ) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        """
                        SELECT * FROM cx_vector_indexes
                        WHERE vector_index_id = :vector_index_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    {
                        "vector_index_id": vector_index_id,
                        "tenant_id": tenant_id,
                        "owner_subject_id": owner_subject_id,
                    },
                ).mappings().one_or_none()
                if row is None:
                    return None
                chunks = session.execute(
                    text(
                        """
                        SELECT chunk_id, ordinal, text_sha256
                        FROM cx_chunks
                        WHERE chunk_set_id = :chunk_set_id
                        ORDER BY ordinal
                        """
                    ),
                    {"chunk_set_id": str(row["chunk_set_id"])},
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return validate_vector_index_manifest(_manifest_from_rows(row, chunks))

    def save(
        self,
        manifest: Mapping[str, Any],
        *,
        expected_checkpoint_version: int,
    ) -> dict[str, Any]:
        value = validate_vector_index_manifest(manifest)
        if value["checkpoint_version"] != expected_checkpoint_version + 1:
            raise VectorIndexRepositoryError(
                "cx.vector_index.checkpoint_conflict",
                "Vector index checkpoint must advance exactly once.",
                retryable=True,
            )
        parameters = {
            **_manifest_parameters(value),
            "expected_checkpoint_version": expected_checkpoint_version,
        }
        try:
            with self._session_factory.begin() as session:
                result = session.execute(
                    text(
                        """
                        UPDATE cx_vector_indexes
                        SET status = :status,
                            status_reason = :status_reason,
                            payload_count = :payload_count,
                            payload_fingerprint = :payload_fingerprint,
                            checkpoint_version = :checkpoint_version,
                            trace_id = :trace_id,
                            request_id = :request_id,
                            updated_at = :updated_at,
                            ready_at = :ready_at
                        WHERE vector_index_id = :vector_index_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                          AND checkpoint_version = :expected_checkpoint_version
                        """
                    ),
                    parameters,
                )
                if result.rowcount != 1:
                    raise VectorIndexRepositoryError(
                        "cx.vector_index.checkpoint_conflict",
                        "Vector index checkpoint changed before persistence.",
                        retryable=True,
                    )
        except VectorIndexRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return deepcopy(value)


def _manifest_parameters(value: Mapping[str, Any]) -> dict[str, Any]:
    source = value["source_snapshot"]
    profile = value["embedding_profile"]
    return {
        "vector_index_id": value["vector_index_id"],
        "index_schema_version": value["vector_index_schema_version"],
        "content_object_id": value["content_object_id"],
        "chunk_set_id": source["chunk_set_id"],
        "tenant_id": value["tenant_ref"]["id"],
        "owner_subject_id": value["owner_subject_ref"]["id"],
        "chunk_policy_id": source["chunk_policy_id"],
        "source_markdown_sha256": source["source_markdown_sha256"],
        "source_fingerprint": source["source_fingerprint"],
        "source_chunk_count": source["chunk_count"],
        "provider_alias": profile["provider_alias"],
        "model_profile_id": profile["model_profile_id"],
        "model_revision": profile["model_revision"],
        "deployment_id": profile["deployment_id"],
        "vector_dimension": profile["vector_dimension"],
        "profile_fingerprint": profile["profile_fingerprint"],
        "status": value["status"],
        "status_reason": value["status_reason"],
        "payload_count": value["payload_count"],
        "payload_fingerprint": value["payload_fingerprint"],
        "checkpoint_version": value["checkpoint_version"],
        "trace_id": value["trace_id"],
        "request_id": value["request_id"],
        "created_at": value["created_at"],
        "updated_at": value["updated_at"],
        "ready_at": value["ready_at"],
    }


def _manifest_from_rows(row: Mapping[str, Any], chunks: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "vector_index_schema_version": row["index_schema_version"],
        "vector_index_id": str(row["vector_index_id"]),
        "content_object_id": str(row["content_object_id"]),
        "tenant_ref": {"type": "oa.tenant", "id": row["tenant_ref_id"]},
        "owner_subject_ref": {
            "type": "oa.user",
            "id": row["owner_subject_ref_id"],
        },
        "source_snapshot": {
            "chunk_set_id": str(row["chunk_set_id"]),
            "chunk_policy_id": row["chunk_policy_id"],
            "source_markdown_sha256": row["source_markdown_sha256"],
            "chunk_count": row["source_chunk_count"],
            "chunk_refs": [
                {
                    "chunk_id": str(chunk["chunk_id"]),
                    "ordinal": chunk["ordinal"],
                    "text_sha256": chunk["text_sha256"],
                }
                for chunk in chunks
            ],
            "source_fingerprint": row["source_fingerprint"],
        },
        "embedding_profile": {
            "profile_schema_version": "cx_embedding_profile.v1",
            "provider_alias": row["provider_alias"],
            "model_profile_id": row["model_profile_id"],
            "model_revision": row["model_revision"],
            "deployment_id": row["deployment_id"],
            "vector_dimension": row["vector_dimension"],
            "profile_fingerprint": row["profile_fingerprint"],
        },
        "status": row["status"],
        "status_reason": row["status_reason"],
        "payload_count": row["payload_count"],
        "payload_fingerprint": row["payload_fingerprint"],
        "checkpoint_version": row["checkpoint_version"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "created_at": _timestamp(row["created_at"]),
        "updated_at": _timestamp(row["updated_at"]),
        "ready_at": _timestamp(row["ready_at"]) if row["ready_at"] is not None else None,
    }


def _timestamp(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _manifests_equivalent(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_value = deepcopy(dict(left))
    right_value = deepcopy(dict(right))
    for field in ("created_at", "updated_at", "ready_at"):
        if left_value.get(field) is not None and right_value.get(field) is not None:
            try:
                left_value[field] = datetime.fromisoformat(
                    str(left_value[field]).replace("Z", "+00:00")
                )
                right_value[field] = datetime.fromisoformat(
                    str(right_value[field]).replace("Z", "+00:00")
                )
            except ValueError:
                return False
    return left_value == right_value


def _unavailable() -> VectorIndexRepositoryError:
    return VectorIndexRepositoryError(
        "cx.vector_index.repository_unavailable",
        "Vector index repository is unavailable.",
        retryable=True,
    )
