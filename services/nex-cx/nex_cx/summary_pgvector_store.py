from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
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
    assert_private_payload_access,
    build_private_payload_receipt,
    normalize_private_vector,
    serialize_private_vector,
)
from nex_runtime import (
    build_engine,
    build_session_factory,
    database_pool_settings,
    service_database_settings,
)


SUMMARY_PGVECTOR_STORAGE_BACKEND = "postgresql-pgvector-summary-v1"
SUMMARY_VECTOR_FRESHNESS_SCHEMA_VERSION = "cx_summary_vector_freshness.v1"
_VECTOR_TEXT_PATTERN = re.compile(r"^\[(.*)]$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SummaryVectorBinding:
    summary_vector_id: UUID
    summary_embedding_id: UUID
    document_summary_id: UUID
    content_object_id: UUID
    tenant_id: str
    owner_subject_id: str
    content_status: str
    summary_status: str
    embedding_status: str
    summary_text_sha256: str
    provider_alias: str
    model_profile_id: str
    model_revision: str
    deployment_id: str
    profile_fingerprint: str
    embedding_sha256: str
    vector_dimension: int
    created_at: str


class SummaryPgVectorStore:
    """Owner-scoped PostgreSQL/pgvector backend for one-vector summaries."""

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

    def bind_summary(
        self,
        binding: SummaryVectorBinding,
    ) -> BoundSummaryPgVectorStore:
        return BoundSummaryPgVectorStore(self._session_factory, binding=binding)


class BoundSummaryPgVectorStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        binding: SummaryVectorBinding,
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
        self._assert_bound_key(access_context, key)
        self._assert_buildable()
        if expected_sha256 != self.binding.embedding_sha256:
            raise _immutable_conflict()
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=expected_sha256,
        )
        if len(normalized) != self.binding.vector_dimension:
            raise _dimension_mismatch()
        try:
            with self._session_factory.begin() as session:
                existing = session.execute(
                    text(
                        """
                        SELECT summary_vector_id, summary_text_sha256,
                               profile_fingerprint, embedding_sha256,
                               vector_dimension
                        FROM cx_summary_vectors
                        WHERE summary_embedding_id = :summary_embedding_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(),
                ).mappings().one_or_none()
                if existing is not None:
                    if not _stored_payload_matches(self.binding, existing):
                        raise _immutable_conflict()
                else:
                    session.execute(
                        text(
                            """
                            INSERT INTO cx_summary_vectors (
                                summary_vector_id,
                                summary_embedding_id,
                                document_summary_id,
                                content_object_id,
                                tenant_ref_type,
                                tenant_ref_id,
                                owner_subject_ref_type,
                                owner_subject_ref_id,
                                summary_text_sha256,
                                provider_alias,
                                model_profile_id,
                                model_revision,
                                deployment_id,
                                profile_fingerprint,
                                embedding_sha256,
                                vector_dimension,
                                embedding,
                                created_at
                            ) VALUES (
                                :summary_vector_id,
                                :summary_embedding_id,
                                :document_summary_id,
                                :content_object_id,
                                'oa.tenant',
                                :tenant_id,
                                'oa.user',
                                :owner_subject_id,
                                :summary_text_sha256,
                                :provider_alias,
                                :model_profile_id,
                                :model_revision,
                                :deployment_id,
                                :profile_fingerprint,
                                :embedding_sha256,
                                :vector_dimension,
                                CAST(:embedding AS vector),
                                :created_at
                            )
                            """
                        ),
                        {
                            **self._binding_parameters(),
                            "embedding": _serialize_pgvector(normalized),
                        },
                    )
        except CxPrivateContentError:
            raise
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        return build_private_payload_receipt(
            key=key,
            storage_backend=SUMMARY_PGVECTOR_STORAGE_BACKEND,
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
                        SELECT summary_vector_id, embedding::text AS embedding,
                               summary_text_sha256,
                               profile_fingerprint,
                               embedding_sha256,
                               vector_dimension
                        FROM cx_summary_vectors
                        WHERE summary_embedding_id = :summary_embedding_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(),
                ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        if row is None:
            return None
        if (
            expected_sha256 != self.binding.embedding_sha256
            or expected_dimension != self.binding.vector_dimension
            or not _stored_payload_matches(self.binding, row)
        ):
            raise _dimension_mismatch()
        vector = normalize_private_vector(
            key=key,
            vector=_parse_pgvector(row["embedding"]),
            expected_sha256=expected_sha256,
        )
        if len(vector) != expected_dimension:
            raise _dimension_mismatch()
        return vector

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
                        DELETE FROM cx_summary_vectors
                        WHERE summary_embedding_id = :summary_embedding_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(),
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc

    def freshness(
        self,
        *,
        access_context: CxAccessContext,
    ) -> dict[str, Any]:
        self._assert_context(access_context)
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        """
                        SELECT summary_vector_id, summary_embedding_id,
                               document_summary_id, content_object_id,
                               tenant_ref_id, owner_subject_ref_id,
                               summary_text_sha256, profile_fingerprint,
                               embedding_sha256, vector_dimension
                        FROM cx_summary_vectors
                        WHERE summary_embedding_id = :summary_embedding_id
                          AND tenant_ref_id = :tenant_id
                          AND owner_subject_ref_id = :owner_subject_id
                        """
                    ),
                    self._identity_parameters(),
                ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise _storage_unavailable() from exc
        return assess_summary_vector_freshness(self.binding, row)

    def storage_uri(self, key: CxPrivatePayloadKey) -> str:
        self._assert_key_shape(key)
        return f"cx-private://pgvector/summary/{self.binding.summary_vector_id}"

    def _assert_buildable(self) -> None:
        if (
            self.binding.content_status != "ACTIVE"
            or self.binding.summary_status != "READY"
            or self.binding.embedding_status != "READY"
        ):
            raise CxPrivateContentError(
                status_code=409,
                error_code="CX_SUMMARY_VECTOR_NOT_BUILDABLE",
                detail="Summary vector persistence requires active READY lineage.",
            )

    def _assert_bound_key(
        self,
        access_context: CxAccessContext,
        key: CxPrivatePayloadKey,
    ) -> None:
        assert_private_payload_access(access_context, key)
        self._assert_context(access_context)
        self._assert_key_shape(key)

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
        if key.payload_kind != "summary_embedding":
            raise CxPrivateContentError(
                status_code=422,
                error_code="CX_SUMMARY_PGVECTOR_KIND_INVALID",
                detail="The bound pgvector payload accepts summary embeddings only.",
            )
        if key.content_id != str(self.binding.document_summary_id):
            raise CxPrivateContentError(
                status_code=404,
                error_code="CX_PRIVATE_PAYLOAD_NOT_FOUND",
                detail="Summary vector was not found for the owner scope.",
            )

    def _identity_parameters(self) -> dict[str, str]:
        return {
            "summary_embedding_id": str(self.binding.summary_embedding_id),
            "tenant_id": self.binding.tenant_id,
            "owner_subject_id": self.binding.owner_subject_id,
        }

    def _binding_parameters(self) -> dict[str, Any]:
        return {
            **self._identity_parameters(),
            "summary_vector_id": str(self.binding.summary_vector_id),
            "document_summary_id": str(self.binding.document_summary_id),
            "content_object_id": str(self.binding.content_object_id),
            "summary_text_sha256": self.binding.summary_text_sha256,
            "provider_alias": self.binding.provider_alias,
            "model_profile_id": self.binding.model_profile_id,
            "model_revision": self.binding.model_revision,
            "deployment_id": self.binding.deployment_id,
            "profile_fingerprint": self.binding.profile_fingerprint,
            "embedding_sha256": self.binding.embedding_sha256,
            "vector_dimension": self.binding.vector_dimension,
            "created_at": self.binding.created_at,
        }


def build_summary_vector_binding(
    *,
    access_context: CxAccessContext,
    content_object: Mapping[str, Any],
    summary: Mapping[str, Any],
    embedding: Mapping[str, Any],
) -> SummaryVectorBinding:
    ownership = _mapping(content_object.get("ownership_ref"), "ownership_ref")
    tenant_ref = _mapping(ownership.get("tenant_ref"), "tenant_ref")
    owner_ref = _mapping(ownership.get("owner_subject_ref"), "owner_subject_ref")
    tenant_id = _required_text(tenant_ref.get("id"), "tenant_ref.id")
    owner_id = _required_text(owner_ref.get("id"), "owner_subject_ref.id")
    if tenant_ref.get("type") != "oa.tenant" or owner_ref.get("type") != "oa.user":
        raise _binding_invalid("Summary vector owner reference types are invalid.")
    if tenant_id != access_context.tenant_id or owner_id != access_context.subject_id:
        raise CxPrivateContentError(
            status_code=404,
            error_code="CX_PRIVATE_PAYLOAD_NOT_FOUND",
            detail="Private payload was not found for the owner scope.",
        )

    content_id = _uuid(content_object.get("content_object_id"), "content_object_id")
    summary_id = _uuid(summary.get("document_summary_id"), "document_summary_id")
    embedding_id = _uuid(embedding.get("summary_embedding_id"), "summary_embedding_id")
    if str(content_id) != str(summary.get("content_object_id")):
        raise _binding_invalid("Summary content lineage does not match.")
    if str(summary_id) != str(embedding.get("document_summary_id")):
        raise _binding_invalid("Summary embedding lineage does not match.")

    dimension = _positive_dimension(embedding.get("vector_dimension"))
    profile = {
        "provider_alias": _required_text(embedding.get("provider_alias"), "provider_alias"),
        "model_profile_id": _required_text(
            embedding.get("model_profile_id"), "model_profile_id"
        ),
        "model_revision": _required_text(embedding.get("model_revision"), "model_revision"),
        "deployment_id": _required_text(embedding.get("deployment_id"), "deployment_id"),
        "vector_dimension": dimension,
    }
    profile_fingerprint = hashlib.sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    vector_id = uuid5(NAMESPACE_URL, f"cx-summary-vector:{embedding_id}")
    return SummaryVectorBinding(
        summary_vector_id=vector_id,
        summary_embedding_id=embedding_id,
        document_summary_id=summary_id,
        content_object_id=content_id,
        tenant_id=tenant_id,
        owner_subject_id=owner_id,
        content_status=_required_text(
            content_object.get("lifecycle_status"), "lifecycle_status"
        ),
        summary_status=_required_text(summary.get("status"), "summary.status"),
        embedding_status=_required_text(embedding.get("status"), "embedding.status"),
        summary_text_sha256=_sha256(summary.get("summary_text_sha256"), "summary_text_sha256"),
        provider_alias=profile["provider_alias"],
        model_profile_id=profile["model_profile_id"],
        model_revision=profile["model_revision"],
        deployment_id=profile["deployment_id"],
        profile_fingerprint=profile_fingerprint,
        embedding_sha256=_sha256(embedding.get("embedding_sha256"), "embedding_sha256"),
        vector_dimension=dimension,
        created_at=_required_text(embedding.get("created_at"), "embedding.created_at"),
    )


def assess_summary_vector_freshness(
    binding: SummaryVectorBinding,
    stored: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if binding.content_status != "ACTIVE":
        reasons.append("CONTENT_NOT_ACTIVE")
    if binding.summary_status != "READY":
        reasons.append("SUMMARY_NOT_READY")
    if binding.embedding_status != "READY":
        reasons.append("EMBEDDING_NOT_READY")
    if stored is None:
        reasons.append("VECTOR_MISSING")
    else:
        comparisons = (
            (str(stored.get("document_summary_id")), str(binding.document_summary_id), "SUMMARY_LINEAGE_CHANGED"),
            (str(stored.get("content_object_id")), str(binding.content_object_id), "CONTENT_LINEAGE_CHANGED"),
            (stored.get("tenant_ref_id"), binding.tenant_id, "OWNER_SCOPE_CHANGED"),
            (stored.get("owner_subject_ref_id"), binding.owner_subject_id, "OWNER_SCOPE_CHANGED"),
            (stored.get("summary_text_sha256"), binding.summary_text_sha256, "SUMMARY_CHANGED"),
            (stored.get("profile_fingerprint"), binding.profile_fingerprint, "EMBEDDING_PROFILE_CHANGED"),
            (stored.get("embedding_sha256"), binding.embedding_sha256, "EMBEDDING_CHANGED"),
            (stored.get("vector_dimension"), binding.vector_dimension, "VECTOR_DIMENSION_CHANGED"),
        )
        reasons.extend(reason for actual, expected, reason in comparisons if actual != expected)
    unique_reasons = sorted(set(reasons))
    return {
        "freshness_schema_version": SUMMARY_VECTOR_FRESHNESS_SCHEMA_VERSION,
        "state": "READY" if not unique_reasons else "STALE",
        "usable": not unique_reasons,
        "reasons": unique_reasons,
        "document_summary_id": str(binding.document_summary_id),
        "summary_embedding_id": str(binding.summary_embedding_id),
        "profile_fingerprint": binding.profile_fingerprint,
    }


def build_summary_pgvector_store(
    *,
    database_env: str = "NEX_CX_DATABASE_URL",
    environ: Mapping[str, str] | None = None,
    workload: str = "worker",
) -> SummaryPgVectorStore:
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
    return SummaryPgVectorStore(
        build_session_factory(engine),
        redacted_database_url=settings.redacted_vector_database_url,
        uses_primary_database=settings.vector_uses_primary,
    )


def _stored_payload_matches(
    binding: SummaryVectorBinding,
    row: Mapping[str, Any],
) -> bool:
    return all(
        (
            str(row.get("summary_vector_id")) == str(binding.summary_vector_id),
            row.get("summary_text_sha256") == binding.summary_text_sha256,
            row.get("profile_fingerprint") == binding.profile_fingerprint,
            row.get("embedding_sha256") == binding.embedding_sha256,
            row.get("vector_dimension") == binding.vector_dimension,
        )
    )


def _parse_pgvector(value: Any) -> tuple[float, ...]:
    if not isinstance(value, str) or _VECTOR_TEXT_PATTERN.fullmatch(value.strip()) is None:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored summary pgvector payload has an invalid representation.",
        )
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CxPrivateContentError(
            status_code=409,
            error_code="CX_PRIVATE_VECTOR_ENCODING_INVALID",
            detail="Stored summary pgvector payload has an invalid representation.",
        ) from exc
    return tuple(decoded)


def _serialize_pgvector(vector: Sequence[float]) -> str:
    return json.dumps(list(vector), ensure_ascii=True, separators=(",", ":"))


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _binding_invalid(f"{field} must be an object.")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _binding_invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise _binding_invalid(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _binding_invalid(f"{field} must be a UUID.") from exc


def _positive_dimension(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CxPrivateContentError(
            status_code=422,
            error_code="CX_PRIVATE_VECTOR_DIMENSION_INVALID",
            detail="Expected vector dimension must be a positive integer.",
        )
    return value


def _binding_invalid(detail: str) -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=422,
        error_code="CX_SUMMARY_VECTOR_BINDING_INVALID",
        detail=detail,
    )


def _immutable_conflict() -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=409,
        error_code="CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT",
        detail="The summary pgvector payload already exists with different content.",
    )


def _dimension_mismatch() -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=409,
        error_code="CX_PRIVATE_VECTOR_DIMENSION_MISMATCH",
        detail="Stored summary pgvector payload verification failed.",
    )


def _storage_unavailable() -> CxPrivateContentError:
    return CxPrivateContentError(
        status_code=503,
        error_code="CX_SUMMARY_PGVECTOR_STORAGE_UNAVAILABLE",
        detail="CX summary pgvector storage is unavailable.",
        retryable=True,
    )
