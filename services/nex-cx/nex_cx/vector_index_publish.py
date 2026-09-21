from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.pgvector_store import PgVectorCxVectorStore
from nex_cx.private_content import (
    CxPrivateContentError,
    build_private_payload_key,
    normalize_private_vector,
    sha256_private_vector,
)
from nex_cx.vector_index_freshness import (
    VectorIndexContractError,
    mark_vector_index_ready,
    transition_vector_index_state,
    validate_vector_index_manifest,
)
from nex_cx.vector_index_repository import (
    VectorIndexRepository,
    VectorIndexRepositoryError,
)


class VectorIndexPublishError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


def publish_vector_index(
    *,
    access_context: CxAccessContext,
    manifest: Mapping[str, Any],
    vectors_by_chunk_id: Mapping[str, Sequence[float]],
    vector_store: PgVectorCxVectorStore,
    repository: VectorIndexRepository,
    observed_at: str,
) -> dict[str, Any]:
    current = validate_vector_index_manifest(manifest)
    _assert_owner(access_context, current)
    if current["status"] != "BUILDING":
        raise VectorIndexPublishError(
            "cx.vector_index.publish_status_invalid",
            "Vector index publish requires a BUILDING manifest.",
        )
    prepared = _prepare_vectors(current, vectors_by_chunk_id, access_context)
    persisted = repository.create(current)
    if persisted != current:
        raise VectorIndexPublishError(
            "cx.vector_index.publish_manifest_conflict",
            "Persisted vector index manifest differs from the publish request.",
            retryable=True,
        )

    bound_store = vector_store.bind_index(current)
    published: list[tuple[Any, Any]] = []
    try:
        receipts = []
        for key, vector, checksum in prepared:
            receipt = bound_store.put_vector(
                access_context=access_context,
                key=key,
                vector=vector,
                expected_sha256=checksum,
            )
            published.append((key, receipt))
            receipts.append(
                {
                    "chunk_id": key.content_id,
                    "embedding_sha256": receipt.sha256,
                    "vector_dimension": receipt.vector_dimension,
                    "storage_uri": receipt.storage_uri,
                }
            )
        ready = mark_vector_index_ready(
            current,
            payload_receipts=receipts,
            observed_at=observed_at,
        )
        return repository.save(
            ready,
            expected_checkpoint_version=current["checkpoint_version"],
        )
    except (CxPrivateContentError, VectorIndexContractError, VectorIndexRepositoryError) as exc:
        compensation_failed = _compensate(
            bound_store,
            access_context=access_context,
            published=published,
        )
        _record_failed_manifest(
            repository,
            current=current,
            observed_at=observed_at,
        )
        raise VectorIndexPublishError(
            "cx.vector_index.publish_failed",
            "Vector index publish failed and payload compensation was attempted.",
            retryable=not compensation_failed,
        ) from exc


def _prepare_vectors(
    manifest: Mapping[str, Any],
    vectors_by_chunk_id: Mapping[str, Sequence[float]],
    access_context: CxAccessContext,
) -> list[tuple[Any, tuple[float, ...], str]]:
    expected_ids = [
        item["chunk_id"] for item in manifest["source_snapshot"]["chunk_refs"]
    ]
    if set(vectors_by_chunk_id) != set(expected_ids):
        raise VectorIndexPublishError(
            "cx.vector_index.publish_payload_set_invalid",
            "Publish vectors must cover every source chunk exactly once.",
        )
    dimension = manifest["embedding_profile"]["vector_dimension"]
    prepared = []
    for chunk_id in expected_ids:
        key = build_private_payload_key(
            access_context,
            payload_kind="chunk_embedding",
            content_id=chunk_id,
        )
        vector = vectors_by_chunk_id[chunk_id]
        checksum = sha256_private_vector(vector)
        normalized = normalize_private_vector(
            key=key,
            vector=vector,
            expected_sha256=checksum,
        )
        if len(normalized) != dimension:
            raise VectorIndexPublishError(
                "cx.vector_index.publish_dimension_invalid",
                "Publish vector dimension does not match the embedding profile.",
            )
        prepared.append((key, normalized, checksum))
    return prepared


def _assert_owner(
    access_context: CxAccessContext,
    manifest: Mapping[str, Any],
) -> None:
    if (
        manifest["tenant_ref"]["id"] != access_context.tenant_id
        or manifest["owner_subject_ref"]["id"] != access_context.subject_id
    ):
        raise VectorIndexPublishError(
            "cx.vector_index.not_found",
            "Vector index was not found for the owner scope.",
        )


def _compensate(
    bound_store: Any,
    *,
    access_context: CxAccessContext,
    published: list[tuple[Any, Any]],
) -> bool:
    failed = False
    for key, _receipt in reversed(published):
        try:
            bound_store.delete_vector(access_context=access_context, key=key)
        except CxPrivateContentError:
            failed = True
    return failed


def _record_failed_manifest(
    repository: VectorIndexRepository,
    *,
    current: Mapping[str, Any],
    observed_at: str,
) -> None:
    try:
        failed = transition_vector_index_state(
            current,
            target_status="FAILED",
            reason="PAYLOAD_PUBLISH_FAILED",
            observed_at=observed_at,
        )
        repository.save(
            failed,
            expected_checkpoint_version=current["checkpoint_version"],
        )
    except (VectorIndexContractError, VectorIndexRepositoryError):
        return
