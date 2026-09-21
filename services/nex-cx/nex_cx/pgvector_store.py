from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    CxPrivatePayloadKey,
    CxPrivatePayloadReceipt,
    CxVectorStore,
    assert_private_payload_access,
    build_private_payload_receipt,
    normalize_private_vector,
    serialize_private_vector,
    sha256_private_vector,
)
from nex_cx.vector_index_freshness import validate_vector_index_manifest
from nex_runtime import (
    build_engine,
    build_session_factory,
    database_pool_settings,
    service_database_settings,
)


PGVECTOR_STORAGE_BACKEND = "postgresql-pgvector-v1"
_VECTOR_TEXT_PATTERN = re.compile(r"^\[(.*)]$")


@dataclass(frozen=True)
class PgVectorIndexBinding:
    vector_index_id: UUID
    content_object_id: UUID
    chunk_set_id: UUID
    tenant_id: str
    owner_subject_id: str
    chunk_ids: frozenset[UUID]
    vector_dimension: int
    status: str


class PgVectorCxVectorStore:
    """PostgreSQL/pgvector backend that binds writes to one manifest."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        redacted_database_url: str,
        uses_primary_database: bool,
    ) -> None:
        self._session_factory = session_factory
        self.redacted_database_url = redacted_database_url
        self.uses_primary_database = uses_primary_database

    def bind_index(
        self,
        manifest: Mapping[str, Any],
    ) -> BoundPgVectorCxVectorStore:
        return BoundPgVectorCxVectorStore(
            self._session_factory,
            binding=build_pgvector_index_binding(manifest),
        )


class BoundPgVectorCxVectorStore:
    """Existing CxVectorStore capability bound to one owner-scoped index."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        binding: PgVectorIndexBinding,
    ) -> None:
        self._session_factory = session_factory
        self.binding = binding

    def put_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        vector: Sequence[float],
        expected_sha256: str,
    ) -> CxPrivatePayloadReceipt:
        self._assert_bound_key(access_context, key, write=True)
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=expected_sha256,
        )
        if len(normalized) != self.binding.vector_dimension:
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
                detail="Private vector dimension does not match the bound index.",
            )
        vector_id = self._vector_id(key)
        vector_text = _serialize_pgvector(normalized)
        try:
            with self._session_factory.begin() as session:
                existing = session.execute(
                    text(
                        """
                        SELECT embedding_sha256, vector_dimension
                        FROM cx_vectors
                        WHERE vector_index_id = :vector_index_id
                          AND chunk_id = :chunk_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(key),
                ).mappings().one_or_none()
                if existing is not None:
                    if (
                        existing["embedding_sha256"] != expected_sha256
                        or existing["vector_dimension"] != len(normalized)
                    ):
                        raise CxPrivateContentError(
                            status_code=409,
                            error_code="CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT",
                            detail="The pgvector payload already exists with different content.",
                        )
                else:
                    session.execute(
                        text(
                            """
                            INSERT INTO cx_vectors (
                                vector_id,
                                vector_index_id,
                                content_object_id,
                                chunk_set_id,
                                chunk_id,
                                tenant_ref_type,
                                tenant_ref_id,
                                owner_subject_ref_type,
                                owner_subject_ref_id,
                                embedding_sha256,
                                vector_dimension,
                                embedding,
                                created_at
                            ) VALUES (
                                :vector_id,
                                :vector_index_id,
                                :content_object_id,
                                :chunk_set_id,
                                :chunk_id,
                                'oa.tenant',
                                :tenant_id,
                                'oa.user',
                                :owner_subject_id,
                                :embedding_sha256,
                                :vector_dimension,
                                CAST(:embedding AS vector),
                                CURRENT_TIMESTAMP
                            )
                            """
                        ),
                        {
                            **self._identity_parameters(key),
                            "vector_id": str(vector_id),
                            "content_object_id": str(self.binding.content_object_id),
                            "chunk_set_id": str(self.binding.chunk_set_id),
                            "embedding_sha256": expected_sha256,
                            "vector_dimension": len(normalized),
                            "embedding": vector_text,
                        },
                    )
        except CxPrivateContentError:
            raise
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        return build_private_payload_receipt(
            key=key,
            storage_backend=PGVECTOR_STORAGE_BACKEND,
            storage_uri=self.storage_uri(key),
            sha256=expected_sha256,
            size_bytes=len(serialize_private_vector(normalized)),
            vector_dimension=len(normalized),
        )

    def get_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        expected_sha256: str,
        expected_dimension: int,
    ) -> tuple[float, ...] | None:
        self._assert_bound_key(access_context, key)
        _positive_dimension(expected_dimension)
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        """
                        SELECT embedding::text AS embedding,
                               embedding_sha256,
                               vector_dimension
                        FROM cx_vectors
                        WHERE vector_index_id = :vector_index_id
                          AND chunk_id = :chunk_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(key),
                ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        if row is None:
            return None
        vector = _parse_pgvector(row["embedding"])
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=expected_sha256,
        )
        if (
            row["embedding_sha256"] != expected_sha256
            or row["vector_dimension"] != expected_dimension
            or len(normalized) != expected_dimension
        ):
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
                detail="Stored pgvector payload verification failed.",
            )
        return normalized

    def delete_vector(
        self,
        *,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> bool:
        self._assert_bound_key(access_context, key)
        try:
            with self._session_factory.begin() as session:
                result = session.execute(
                    text(
                        """
                        DELETE FROM cx_vectors
                        WHERE vector_index_id = :vector_index_id
                          AND chunk_id = :chunk_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(key),
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc

    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        self._assert_context(access_context)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_VECTOR_SEARCH_LIMIT_INVALID",
                detail="Vector search limit must be between 1 and 100.",
            )
        probe_key = CxPrivatePayloadKey(
            tenant_id=self.binding.tenant_id,
            subject_id=self.binding.owner_subject_id,
            payload_kind="chunk_embedding",
            content_id=str(next(iter(self.binding.chunk_ids))),
        )
        normalized = normalize_private_vector(
            key=probe_key,
            vector=query_vector,
            expected_sha256=sha256_private_vector(query_vector),
        )
        if len(normalized) != self.binding.vector_dimension:
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
                detail="Query vector dimension does not match the bound index.",
            )
        distance = (
            "embedding::halfvec(2560) <=> CAST(:embedding AS halfvec(2560))"
            if self.binding.vector_dimension == 2560
            else "embedding <=> CAST(:embedding AS vector)"
        )
        statement = text(
            f"""
            SELECT chunk_id, embedding_sha256, {distance} AS distance
            FROM cx_vectors
            WHERE vector_index_id = :vector_index_id
              AND tenant_ref_id = :tenant_id
              AND owner_subject_ref_id = :owner_subject_id
              AND vector_dimension = :vector_dimension
            ORDER BY distance, chunk_id
            LIMIT :limit
            """
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    statement,
                    {
                        "vector_index_id": str(self.binding.vector_index_id),
                        "tenant_id": self.binding.tenant_id,
                        "owner_subject_id": self.binding.owner_subject_id,
                        "vector_dimension": self.binding.vector_dimension,
                        "embedding": _serialize_pgvector(normalized),
                        "limit": limit,
                    },
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        return [
            {
                "chunk_id": str(row["chunk_id"]),
                "embedding_sha256": row["embedding_sha256"],
                "distance": float(row["distance"]),
                "score": 1.0 - float(row["distance"]),
            }
            for row in rows
        ]

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        self._assert_key_shape(key)
        return f"cx-private://pgvector/{self._vector_id(key)}"

    def _assert_bound_key(
        self,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
        *,
        write: bool = False,
    ) -> None:
        assert_private_payload_access(access_context, key)
        self._assert_context(access_context)
        self._assert_key_shape(key)
        if write and self.binding.status != "BUILDING":
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_VECTOR_INDEX_NOT_BUILDING",
                detail="Vector payload writes require a BUILDING index.",
            )

    def _assert_context(self, access_context: CxAccessContext) -> None:
        if (
            access_context.tenant_id != self.binding.tenant_id
            or access_context.subject_id != self.binding.owner_subject_id
        ):
            raise CxPrivateContentError(
                status_code=404,
                error_code="CX_PRIVATE_PAYLOAD_NOT_FOUND",
                detail="Private payload was not found for the owner scope.",
            )

    def _assert_key_shape(self, key: CxPrivatePayloadKey) -> None:
        if key.payload_kind != "chunk_embedding":
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_PGVECTOR_KIND_INVALID",
                detail="The bound pgvector index accepts chunk embeddings only.",
            )
        chunk_id = _uuid(key.content_id, "chunk_id")
        if chunk_id not in self.binding.chunk_ids:
            raise CxPrivateContentError(
                status_code=404,
                error_code="CX_PRIVATE_PAYLOAD_NOT_FOUND",
                detail="Chunk is not part of the bound vector index.",
            )

    def _identity_parameters(self, key: CxPrivatePayloadKey) -> dict[str, str]:
        return {
            "vector_index_id": str(self.binding.vector_index_id),
            "chunk_id": str(_uuid(key.content_id, "chunk_id")),
            "tenant_id": self.binding.tenant_id,
            "owner_subject_id": self.binding.owner_subject_id,
        }

    def _vector_id(self, key: CxPrivatePayloadKey) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"nex-cx-pgvector:{self.binding.vector_index_id}:{key.content_id}",
        )


def build_pgvector_index_binding(
    manifest: Mapping[str, Any],
) -> PgVectorIndexBinding:
    value = validate_vector_index_manifest(manifest)
    source = value["source_snapshot"]
    return PgVectorIndexBinding(
        vector_index_id=_uuid(value["vector_index_id"], "vector_index_id"),
        content_object_id=_uuid(value["content_object_id"], "content_object_id"),
        chunk_set_id=_uuid(source["chunk_set_id"], "chunk_set_id"),
        tenant_id=value["tenant_ref"]["id"],
        owner_subject_id=value["owner_subject_ref"]["id"],
        chunk_ids=frozenset(
            _uuid(item["chunk_id"], "chunk_id") for item in source["chunk_refs"]
        ),
        vector_dimension=value["embedding_profile"]["vector_dimension"],
        status=value["status"],
    )


def build_pgvector_cx_vector_store(
    *,
    database_env: str = "NEX_CX_DATABASE_URL",
    environ: Mapping[str, str] | None = None,
    workload: str = "worker",
) -> PgVectorCxVectorStore:
    settings = service_database_settings(
        service_id="nex-cx",
        database_env=database_env,
        environ=environ,
    )
    if settings.vector_database_url is None or settings.redacted_vector_database_url is None:
        raise CxPrivateContentError(
            status_code=500,
            error_code="CX_VECTOR_DATABASE_CONFIG_INVALID",
            detail="CX vector database routing is unavailable.",
        )
    pool = database_pool_settings("nex-cx", workload=workload, environ=environ)
    engine = build_engine(settings.vector_database_url, pool_settings=pool)
    return PgVectorCxVectorStore(
        build_session_factory(engine),
        redacted_database_url=settings.redacted_vector_database_url,
        uses_primary_database=settings.vector_uses_primary,
    )


def _parse_pgvector(value: Any) -> tuple[float, ...]:
    if not isinstance(value, str):
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored pgvector payload has an invalid representation.",
        )
    match = _VECTOR_TEXT_PATTERN.fullmatch(value.strip())
    if match is None:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored pgvector payload has an invalid representation.",
        )
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored pgvector payload has an invalid representation.",
        ) from exc
    return tuple(decoded)


def _serialize_pgvector(vector: Sequence[float]) -> str:
    return json.dumps(list(vector), ensure_ascii=True, separators=(",", ":"))


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_VECTOR_IDENTIFIER_INVALID",
            detail=f"{field} must be a UUID.",
        ) from exc


def _positive_dimension(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_DIMENSION_INVALID",
            detail="Expected vector dimension must be a positive integer.",
        )
    return value


def _storage_unavailable() -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=503,
        error_code="CX_PGVECTOR_STORAGE_UNAVAILABLE",
        detail="CX pgvector storage is unavailable.",
        retryable=True,
    )
