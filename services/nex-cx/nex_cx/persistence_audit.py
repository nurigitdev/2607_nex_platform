from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.ingestion import ContentIngestionStore
from nex_cx.processing_persistence import (
    CX_DOCUMENT_PROCESSING_RUN_TABLE,
    CX_DOCUMENT_PROCESSING_STEP_TABLE,
    build_processing_run_persistence_decision,
    build_processing_run_persistence_preview,
)
from nex_cx.retrieval_persistence import build_retrieval_runtime_persistence_decision


CX_PERSISTENCE_GAP_AUDIT_SCHEMA_VERSION = "cx_persistence_gap_audit.v1"
CX_PERSISTENCE_AUDIT_MODES = ("memory", "postgres")

CX_CONTENT_PERSISTENCE_SURFACES: tuple[dict[str, Any], ...] = (
    {
        "surface_id": "source_files",
        "owned_records": ["source_file"],
        "current_boundary": "CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_source_files"],
        "postgres_adapter_required": False,
        "private_payload_policy": "metadata_only",
        "observed_count_key": "source_file_count",
    },
    {
        "surface_id": "content_objects",
        "owned_records": ["content_object", "content_acl_entry"],
        "current_boundary": "CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_content_objects", "cx_content_acl_entries"],
        "postgres_adapter_required": False,
        "private_payload_policy": "metadata_only",
        "observed_count_key": "content_object_count",
    },
    {
        "surface_id": "extraction_artifacts",
        "owned_records": ["text_extraction"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_extraction_artifacts"],
        "postgres_adapter_required": False,
        "private_payload_policy": "markdown_uri_hash_preview_only",
        "observed_count_key": "extraction_result_count",
    },
    {
        "surface_id": "chunks",
        "owned_records": ["chunk_set", "chunk"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_chunk_sets", "cx_chunks"],
        "postgres_adapter_required": False,
        "private_payload_policy": "text_hash_preview_only",
        "observed_count_key": "chunk_set_count",
    },
    {
        "surface_id": "lexical_index",
        "owned_records": ["lexical_term", "lexical_posting"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_lexical_terms", "cx_lexical_postings"],
        "postgres_adapter_required": False,
        "private_payload_policy": "token_counts_only",
        "observed_count_key": "lexical_index_count",
    },
    {
        "surface_id": "chunk_embeddings",
        "owned_records": ["chunk_embedding"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_chunk_embeddings"],
        "postgres_adapter_required": False,
        "private_payload_policy": "vector_hash_dimension_uri_only",
        "observed_count_key": "embedding_index_count",
    },
    {
        "surface_id": "document_summaries",
        "owned_records": ["document_summary"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_document_summaries"],
        "postgres_adapter_required": False,
        "private_payload_policy": "summary_hash_limit_uri_only",
        "observed_count_key": "document_summary_count",
    },
    {
        "surface_id": "summary_embeddings",
        "owned_records": ["document_summary_embedding"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_document_summary_embeddings"],
        "postgres_adapter_required": False,
        "private_payload_policy": "vector_hash_dimension_uri_only",
        "observed_count_key": "summary_embedding_index_count",
    },
    {
        "surface_id": "retrieval_packages",
        "owned_records": ["retrieval_context_package"],
        "current_boundary": "ContentIngestionStore + CxContentRepository",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": ["cx_retrieval_packages", "cx_retrieval_evidence_items"],
        "postgres_adapter_required": False,
        "private_payload_policy": "query_hash_preview_and_evidence_hash_preview_only",
        "observed_count_key": "retrieval_package_count",
    },
    {
        "surface_id": "processing_runs",
        "owned_records": ["document_processing_run"],
        "current_boundary": "ContentIngestionStore",
        "current_adapter_status": "sqlalchemy_repository_ready",
        "target_tables": [
            CX_DOCUMENT_PROCESSING_RUN_TABLE,
            CX_DOCUMENT_PROCESSING_STEP_TABLE,
        ],
        "target_table_status": "migration_present",
        "postgres_adapter_required": False,
        "private_payload_policy": (
            "run_header_step_status_output_ref_hash_and_error_hash_only"
        ),
        "observed_count_key": "processing_run_count",
    },
)

CX_PRIVATE_PAYLOAD_BOUNDARIES: tuple[dict[str, str], ...] = (
    {
        "payload_id": "source_bytes",
        "current_holder": "ContentIngestionStore.source_bytes",
        "future_owner": "local filesystem or object storage",
        "public_record_policy": "sha256_size_storage_uri_only",
    },
    {
        "payload_id": "source_texts",
        "current_holder": "ContentIngestionStore.source_texts",
        "future_owner": "extractor input cache only",
        "public_record_policy": "do_not_persist_raw_text",
    },
    {
        "payload_id": "chunk_texts",
        "current_holder": "ContentIngestionStore.chunk_texts",
        "future_owner": "private chunk text store or markdown offset reconstruction",
        "public_record_policy": "hash_preview_offsets_only",
    },
    {
        "payload_id": "embedding_vectors",
        "current_holder": "ContentIngestionStore.embedding_vectors",
        "future_owner": "pgvector or external vector store",
        "public_record_policy": "hash_dimension_storage_uri_only",
    },
    {
        "payload_id": "summary_texts",
        "current_holder": "ContentIngestionStore.summary_texts",
        "future_owner": "private summary artifact store",
        "public_record_policy": "hash_preview_limit_uri_only",
    },
    {
        "payload_id": "summary_embedding_vectors",
        "current_holder": "ContentIngestionStore.summary_embedding_vectors",
        "future_owner": "pgvector or external vector store",
        "public_record_policy": "hash_dimension_storage_uri_only",
    },
)

CX_DEFERRED_SCHEMA_DECISIONS: tuple[dict[str, Any], ...] = (
    {
        "decision_id": "processing_runs",
        "surface_id": "processing_runs",
        "decision_status": "postgres_smoke_ready",
        "candidate_tables": [
            CX_DOCUMENT_PROCESSING_RUN_TABLE,
            CX_DOCUMENT_PROCESSING_STEP_TABLE,
        ],
        "minimum_persisted_metadata": [
            "pipeline_run_id",
            "pipeline_schema_version",
            "document_id",
            "trace_id",
            "request_id",
            "status",
            "job_id",
            "job_status",
            "step_total",
            "step_succeeded",
            "step_skipped",
            "step_failed",
            "queued_at",
            "started_at",
            "completed_at",
            "updated_at",
            "steps[].step_order",
            "steps[].step_id",
            "steps[].status",
            "steps[].output_ref_hash",
            "steps[].error_code",
            "steps[].error_detail_sha256",
        ],
        "private_payload_policy": (
            "run_header_step_status_output_ref_hash_and_error_hash_only"
        ),
        "decision_trigger": "slice_0186_persisted_read_model_query_foundation",
    },
    {
        "decision_id": "lexical_index_header",
        "surface_id": "lexical_index",
        "decision_status": "header_table_deferred",
        "candidate_tables": ["cx_lexical_indexes"],
        "minimum_persisted_metadata": [
            "chunk_set_id",
            "tokenizer_requested",
            "tokenizer_used",
            "fallback_used",
            "chunk_count",
            "unique_token_count",
        ],
        "private_payload_policy": "token_counts_only",
        "decision_trigger": "only if zero-token lexical index history must be durable",
    },
    {
        "decision_id": "chunk_embedding_index_header",
        "surface_id": "chunk_embeddings",
        "decision_status": "header_table_deferred",
        "candidate_tables": ["cx_chunk_embedding_indexes"],
        "minimum_persisted_metadata": [
            "chunk_set_id",
            "provider_alias",
            "model_profile_id",
            "model_revision",
            "deployment_id",
            "chunk_count",
            "vector_dimension",
        ],
        "private_payload_policy": "vector_hash_dimension_uri_only",
        "decision_trigger": "only if zero-chunk embedding index history must be durable",
    },
)


def normalize_cx_persistence_audit_mode(value: str | None) -> str:
    normalized = "memory" if value is None or not value.strip() else value.strip().lower()
    if normalized not in CX_PERSISTENCE_AUDIT_MODES:
        raise ValueError(
            "CX persistence audit mode must be one of: "
            f"{', '.join(CX_PERSISTENCE_AUDIT_MODES)}"
        )
    return normalized


def build_cx_persistence_gap_audit(
    *,
    store: ContentIngestionStore | None = None,
    persistence_mode: str | None = None,
) -> dict[str, Any]:
    mode = normalize_cx_persistence_audit_mode(persistence_mode)
    counts = _observed_store_counts(store)
    surfaces = [
        {
            **surface,
            "observed_count": counts[surface["observed_count_key"]],
            "target_table_status": (
                surface.get("target_table_status")
                or ("migration_present" if surface["target_tables"] else "schema_deferred")
            ),
        }
        for surface in CX_CONTENT_PERSISTENCE_SURFACES
    ]
    postgres_gap_count = sum(
        1 for surface in surfaces if surface["postgres_adapter_required"]
    )
    schema_deferred_count = sum(
        1 for surface in surfaces if surface["target_table_status"] == "schema_deferred"
    )
    migration_pending_count = sum(
        1
        for surface in surfaces
        if surface["target_table_status"] == "schema_ready_pending_migration"
    )
    latest_processing_run = _latest_processing_run(store)
    return {
        "audit_schema_version": CX_PERSISTENCE_GAP_AUDIT_SCHEMA_VERSION,
        "service_id": "nex-cx",
        "checkpoint_slice": "0181",
        "persistence_mode": mode,
        "store_type": type(store).__name__ if store is not None else None,
        "content_repository_type": (
            type(store.content_repository).__name__ if store is not None else None
        ),
        "checkpoint_status": "ACTION_REQUIRED",
        "summary": {
            "surface_count": len(surfaces),
            "postgres_adapter_gap_count": postgres_gap_count,
            "schema_deferred_count": schema_deferred_count,
            "migration_pending_count": migration_pending_count,
            "deferred_schema_decision_count": len(CX_DEFERRED_SCHEMA_DECISIONS),
            "private_payload_boundary_count": len(CX_PRIVATE_PAYLOAD_BOUNDARIES),
            "next_recommended_slice": (
                "0186_cx_processing_persisted_read_model_query_foundation"
            ),
        },
        "observed_store_counts": counts,
        "surfaces": surfaces,
        "private_payload_boundaries": [
            dict(boundary) for boundary in CX_PRIVATE_PAYLOAD_BOUNDARIES
        ],
        "deferred_schema_decisions": [
            deepcopy_decision(decision) for decision in CX_DEFERRED_SCHEMA_DECISIONS
        ],
        "retrieval_runtime_persistence_decision": (
            build_retrieval_runtime_persistence_decision()
        ),
        "processing_run_persistence_decision": (
            build_processing_run_persistence_decision()
        ),
        "latest_processing_run_persistence_preview": (
            build_processing_run_persistence_preview(latest_processing_run)
            if latest_processing_run is not None
            else None
        ),
        "refactoring_checkpoints": [
            "Keep file IO and provider calls outside database transactions.",
            "Persist metadata, hashes, previews, lineage, and storage URIs only.",
            "Keep raw source bytes, chunk text, summaries, and vectors outside public records.",
            "Preserve owner-scoped duplicate detection on tenant_id + owner_user_id + source_sha256.",
            "Add PostgreSQL write-through behind existing store/repository ports before changing routes.",
        ],
    }


def deepcopy_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in decision.items()
    }


def _observed_store_counts(store: ContentIngestionStore | None) -> dict[str, int]:
    if store is None:
        return {
            "document_count": 0,
            "job_count": 0,
            "source_file_count": 0,
            "content_object_count": 0,
            "extraction_result_count": 0,
            "chunk_set_count": 0,
            "private_chunk_text_count": 0,
            "embedding_index_count": 0,
            "private_embedding_vector_count": 0,
            "lexical_index_count": 0,
            "retrieval_package_count": 0,
            "document_summary_count": 0,
            "private_summary_text_count": 0,
            "summary_embedding_index_count": 0,
            "private_summary_embedding_vector_count": 0,
            "processing_run_count": 0,
        }
    return {
        "document_count": len(store.documents),
        "job_count": len(store.jobs),
        "source_file_count": _mapping_count(
            getattr(store.content_repository, "source_files", None)
        ),
        "content_object_count": _mapping_count(
            getattr(store.content_repository, "content_objects", None)
        ),
        "extraction_result_count": len(store.extraction_results),
        "chunk_set_count": len(store.chunk_sets),
        "private_chunk_text_count": len(store.chunk_texts),
        "embedding_index_count": len(store.embedding_indexes),
        "private_embedding_vector_count": len(store.embedding_vectors),
        "lexical_index_count": len(store.lexical_indexes),
        "retrieval_package_count": len(store.retrieval_packages),
        "document_summary_count": len(store.document_summaries),
        "private_summary_text_count": len(store.summary_texts),
        "summary_embedding_index_count": len(store.summary_embedding_indexes),
        "private_summary_embedding_vector_count": len(store.summary_embedding_vectors),
        "processing_run_count": len(store.document_processing_runs),
    }


def _latest_processing_run(store: ContentIngestionStore | None) -> dict[str, Any] | None:
    if store is None or not store.document_processing_runs:
        return None
    return next(reversed(store.document_processing_runs.values()))


def _mapping_count(value: object) -> int:
    return len(value) if isinstance(value, Mapping) else 0
