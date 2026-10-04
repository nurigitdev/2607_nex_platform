from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime.prompts import PromptRegistryStore

from nex_cx.access_context import CxAccessContext
from nex_cx.embedding_index import MoEmbeddingClient
from nex_cx.hybrid_ranking import PermissionAwareRerankClient
from nex_cx.hybrid_retrieval_package import PermissionFilteredHybridPackageRuntime
from nex_cx.hybrid_retrieval_runtime import (
    HybridRetrievalSource,
    build_permission_hardened_hybrid_runtime,
)
from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig
from nex_cx.ingestion_coordinator import (
    IngestionStepHandler,
    build_default_ingestion_step_handlers,
)
from nex_cx.ingestion_hydration import hydrate_ingestion_runtime
from nex_cx.lexical_candidates import PostgresLexicalCandidateStore
from nex_cx.mvp_ingestion_indexing import MvpIngestionVectorIndexer
from nex_cx.pgvector_store import PgVectorCxVectorStore
from nex_cx.private_content import CxPrivateTextStore, build_private_payload_key
from nex_cx.repository import CxContentRepository
from nex_cx.retrieval_permissions import evaluate_retrieval_permission
from nex_cx.vector_index_repository import VectorIndexRepository
from nex_cx.vector_index_freshness import build_source_snapshot


@dataclass(frozen=True)
class CxMvpRuntimeError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class PostgresHybridRetrievalSource(HybridRetrievalSource):
    session_factory: sessionmaker[Session]
    content_repository: CxContentRepository
    vector_repository: VectorIndexRepository
    private_text_store: CxPrivateTextStore

    def load_content_objects(
        self,
        document_ids: Sequence[str],
    ) -> Mapping[str, object]:
        identifiers = _identifiers(document_ids, field="document_ids")
        try:
            return {
                document_id: content
                for document_id in identifiers
                if (
                    content := self.content_repository.get_content_object(
                        document_id
                    )
                )
                is not None
            }
        except Exception as exc:
            raise _unavailable("content metadata") from exc

    def load_vector_targets(
        self,
        *,
        access_context: CxAccessContext,
        document_ids: Sequence[str],
    ) -> Mapping[str, Mapping[str, Any]]:
        identifiers = _identifiers(document_ids, field="document_ids")
        if not identifiers:
            return {}
        statement = text(
            """
            SELECT vector_index_id, content_object_id
            FROM cx_vector_indexes
            WHERE content_object_id IN :document_ids
              AND tenant_ref_type = 'oa.tenant'
              AND tenant_ref_id = :tenant_id
              AND owner_subject_ref_type = 'oa.user'
              AND owner_subject_ref_id = :owner_subject_id
              AND status = 'READY'
            ORDER BY content_object_id,
                     (ready_at IS NULL), ready_at DESC,
                     updated_at DESC, vector_index_id DESC
            """
        ).bindparams(bindparam("document_ids", expanding=True))
        chunk_set_statement = text(
            """
            SELECT chunk_set_id, content_object_id
            FROM cx_chunk_sets
            WHERE content_object_id IN :document_ids
            ORDER BY content_object_id, created_at DESC, chunk_set_id DESC
            """
        ).bindparams(bindparam("document_ids", expanding=True))
        try:
            with self.session_factory() as session:
                rows = session.execute(
                    statement,
                    {
                        "document_ids": identifiers,
                        "tenant_id": access_context.tenant_id,
                        "owner_subject_id": access_context.subject_id,
                    },
                ).mappings().all()
                chunk_set_rows = session.execute(
                    chunk_set_statement,
                    {"document_ids": identifiers},
                ).mappings().all()
            latest_by_document: dict[str, str] = {}
            for row in rows:
                latest_by_document.setdefault(
                    str(row["content_object_id"]),
                    str(row["vector_index_id"]),
                )
            current_chunk_set_by_document: dict[str, str] = {}
            for row in chunk_set_rows:
                current_chunk_set_by_document.setdefault(
                    str(row["content_object_id"]),
                    str(row["chunk_set_id"]),
                )
            content_objects = self.load_content_objects(identifiers)
            targets: dict[str, Mapping[str, Any]] = {}
            for document_id, vector_index_id in latest_by_document.items():
                permission = evaluate_retrieval_permission(
                    access_context,
                    content_objects.get(document_id),
                )
                if permission["visible"] is not True:
                    continue
                manifest = self.vector_repository.get(
                    vector_index_id,
                    tenant_id=access_context.tenant_id,
                    owner_subject_id=access_context.subject_id,
                )
                if manifest is None or manifest.get("status") != "READY":
                    continue
                chunk_set_id = current_chunk_set_by_document.get(document_id)
                chunk_set = (
                    self.content_repository.get_chunk_set(chunk_set_id)
                    if chunk_set_id is not None
                    else None
                )
                if chunk_set is None:
                    continue
                targets[document_id] = {
                    "content_object_id": document_id,
                    "vector_index_id": vector_index_id,
                    "source_snapshot": build_source_snapshot(
                        chunk_set_id=str(chunk_set["chunk_set_id"]),
                        chunk_policy_id=str(chunk_set["chunk_policy_id"]),
                        source_markdown_sha256=str(
                            chunk_set["source_markdown_sha256"]
                        ),
                        chunks=chunk_set["chunks"],
                    ),
                    "embedding_profile": manifest["embedding_profile"],
                    "permission_decision": permission,
                }
            return targets
        except CxMvpRuntimeError:
            raise
        except Exception as exc:
            raise _unavailable("vector metadata") from exc

    def load_private_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        refs = _chunk_references(chunk_refs)
        if not refs:
            return []
        statement = text(
            """
            SELECT chunk.content_object_id,
                   chunk.chunk_id,
                   chunk_set.chunk_policy_id,
                   chunk.start_offset,
                   chunk.end_offset,
                   chunk.text_sha256
            FROM cx_chunks AS chunk
            JOIN cx_chunk_sets AS chunk_set
              ON chunk_set.chunk_set_id = chunk.chunk_set_id
            JOIN cx_content_objects AS content
              ON content.content_object_id = chunk.content_object_id
            WHERE chunk.chunk_id IN :chunk_ids
              AND content.lifecycle_status = 'ACTIVE'
              AND content.tenant_ref_type = 'oa.tenant'
              AND content.tenant_ref_id = :tenant_id
              AND content.owner_subject_ref_type = 'oa.user'
              AND content.owner_subject_ref_id = :owner_subject_id
            """
        ).bindparams(bindparam("chunk_ids", expanding=True))
        try:
            with self.session_factory() as session:
                rows = session.execute(
                    statement,
                    {
                        "chunk_ids": [item["chunk_id"] for item in refs],
                        "tenant_id": access_context.tenant_id,
                        "owner_subject_id": access_context.subject_id,
                    },
                ).mappings().all()
            by_key = {
                (str(row["content_object_id"]), str(row["chunk_id"])): row
                for row in rows
            }
            records: list[dict[str, Any]] = []
            for ref in refs:
                key = (ref["content_object_id"], ref["chunk_id"])
                row = by_key.get(key)
                if row is None:
                    raise CxMvpRuntimeError(
                        error_code="cx.mvp_runtime.evidence_not_found",
                        detail="Private retrieval evidence was not found.",
                    )
                expected_sha256 = str(row["text_sha256"])
                chunk_text = self.private_text_store.get_text(
                    access_context=access_context,
                    key=build_private_payload_key(
                        access_context,
                        payload_kind="chunk_text",
                        content_id=ref["chunk_id"],
                    ),
                    expected_sha256=expected_sha256,
                )
                if chunk_text is None:
                    raise CxMvpRuntimeError(
                        error_code="cx.mvp_runtime.private_text_unavailable",
                        detail="Private retrieval evidence is unavailable.",
                        retryable=True,
                    )
                records.append(
                    {
                        **ref,
                        "chunk_policy_id": str(row["chunk_policy_id"]),
                        "chunk_text": chunk_text,
                        "text_sha256": expected_sha256,
                        "start_offset": int(row["start_offset"]),
                        "end_offset": int(row["end_offset"]),
                        "matched_terms": [],
                    }
                )
            return records
        except CxMvpRuntimeError:
            raise
        except Exception as exc:
            raise _unavailable("private evidence") from exc


@dataclass(frozen=True)
class CxMvpRuntimeComposition:
    source: PostgresHybridRetrievalSource
    hybrid_retrieval_runtime: PermissionFilteredHybridPackageRuntime
    ingestion_vector_indexer: MvpIngestionVectorIndexer
    ingestion_step_handlers: Mapping[str, IngestionStepHandler]

    def to_safe_summary(self) -> dict[str, object]:
        return {
            "runtime": "cx_mvp_postgres",
            "retrieval": "permission_hardened_hybrid",
            "vector_publish": "fresh_owner_scoped_pgvector",
            "private_text": "owner_scoped_external_payload",
            "ingestion_step_count": len(self.ingestion_step_handlers),
        }


def build_cx_mvp_runtime(
    *,
    session_factory: sessionmaker[Session],
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    content_repository: CxContentRepository,
    vector_repository: VectorIndexRepository,
    retrieval_vector_store: PgVectorCxVectorStore,
    ingestion_vector_store: PgVectorCxVectorStore,
    private_text_store: CxPrivateTextStore,
    embedding_client: MoEmbeddingClient,
    embedding_alias: str,
    rerank_client: PermissionAwareRerankClient | None,
    reranker_alias: str,
    prompt_store: PromptRegistryStore | None = None,
) -> CxMvpRuntimeComposition:
    source = PostgresHybridRetrievalSource(
        session_factory=session_factory,
        content_repository=content_repository,
        vector_repository=vector_repository,
        private_text_store=private_text_store,
    )
    hybrid_runtime = build_permission_hardened_hybrid_runtime(
        source=source,
        lexical_store=PostgresLexicalCandidateStore(session_factory),
        vector_repository=vector_repository,
        vector_store=retrieval_vector_store,
        embedding_client=embedding_client,
        embedding_alias=embedding_alias,
        rerank_client=rerank_client,
        reranker_alias=reranker_alias,
    )
    runtime_hydrator = lambda run: hydrate_ingestion_runtime(
        run,
        store=store,
        storage_config=storage_config,
    )
    vector_indexer = MvpIngestionVectorIndexer(
        store=store,
        private_text_store=private_text_store,
        embedding_client=embedding_client,
        embedding_alias=embedding_alias,
        vector_repository=vector_repository,
        vector_store=ingestion_vector_store,
        runtime_hydrator=runtime_hydrator,
    )
    handlers = build_default_ingestion_step_handlers(
        store=store,
        storage_config=storage_config,
        mo_client=embedding_client,
        embedding_alias=embedding_alias,
        prompt_store=prompt_store,
        mvp_embedding_handler=vector_indexer,
        runtime_hydrator=runtime_hydrator,
    )
    return CxMvpRuntimeComposition(
        source=source,
        hybrid_retrieval_runtime=hybrid_runtime,
        ingestion_vector_indexer=vector_indexer,
        ingestion_step_handlers=handlers,
    )


def _identifiers(values: Sequence[str], *, field: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CxMvpRuntimeError(
            error_code=f"cx.mvp_runtime.{field}_invalid",
            detail=f"{field} must be a list of non-empty identifiers.",
        )
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CxMvpRuntimeError(
                error_code=f"cx.mvp_runtime.{field}_invalid",
                detail=f"{field} must be a list of non-empty identifiers.",
            )
        identifier = value.strip()
        if identifier not in seen:
            result.append(identifier)
            seen.add(identifier)
    return result


def _chunk_references(
    values: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CxMvpRuntimeError(
            error_code="cx.mvp_runtime.chunk_refs_invalid",
            detail="Chunk references must be a list of owner-scoped identities.",
        )
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise _invalid_chunk_refs()
        content_id = value.get("content_object_id")
        chunk_id = value.get("chunk_id")
        if (
            not isinstance(content_id, str)
            or not content_id.strip()
            or not isinstance(chunk_id, str)
            or not chunk_id.strip()
        ):
            raise _invalid_chunk_refs()
        key = (content_id.strip(), chunk_id.strip())
        if key in seen:
            raise _invalid_chunk_refs()
        refs.append({"content_object_id": key[0], "chunk_id": key[1]})
        seen.add(key)
    return refs


def _invalid_chunk_refs() -> CxMvpRuntimeError:
    return CxMvpRuntimeError(
        error_code="cx.mvp_runtime.chunk_refs_invalid",
        detail="Chunk references must contain unique document and chunk identities.",
    )


def _unavailable(capability: str) -> CxMvpRuntimeError:
    return CxMvpRuntimeError(
        error_code="cx.mvp_runtime.dependency_unavailable",
        detail=f"CX MVP {capability} is unavailable.",
        retryable=True,
    )
