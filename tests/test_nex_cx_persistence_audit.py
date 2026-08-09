from __future__ import annotations

from pathlib import Path

import pytest

from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig, build_upload_registration
from nex_cx.persistence_audit import (
    CX_DEFERRED_SCHEMA_DECISIONS,
    CX_PERSISTENCE_GAP_AUDIT_SCHEMA_VERSION,
    build_cx_persistence_gap_audit,
    normalize_cx_persistence_audit_mode,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def upload_registration(tmp_path: Path, *, content_text: str) -> dict[str, object]:
    return build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": content_text,
        },
        storage_config=storage_config(tmp_path),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )


def test_cx_persistence_gap_audit_defaults_to_empty_memory_checkpoint() -> None:
    audit = build_cx_persistence_gap_audit()

    assert audit["audit_schema_version"] == CX_PERSISTENCE_GAP_AUDIT_SCHEMA_VERSION
    assert audit["service_id"] == "nex-cx"
    assert audit["checkpoint_slice"] == "0181"
    assert audit["persistence_mode"] == "memory"
    assert audit["checkpoint_status"] == "ACTION_REQUIRED"
    assert audit["store_type"] is None
    assert audit["content_repository_type"] is None
    assert audit["summary"] == {
        "surface_count": 10,
        "postgres_adapter_gap_count": 1,
        "schema_deferred_count": 0,
        "migration_pending_count": 0,
        "deferred_schema_decision_count": 3,
        "private_payload_boundary_count": 6,
        "next_recommended_slice": "0184_cx_processing_run_write_through_integration",
    }
    assert all(count == 0 for count in audit["observed_store_counts"].values())
    processing_surface = {
        surface["surface_id"]: surface for surface in audit["surfaces"]
    }["processing_runs"]
    assert processing_surface["target_table_status"] == "migration_present"
    assert processing_surface["current_adapter_status"] == (
        "repository_adapter_ready_write_through_pending"
    )
    closed_surfaces = {
        surface["surface_id"]: surface
        for surface in audit["surfaces"]
        if not surface["postgres_adapter_required"]
    }
    assert set(closed_surfaces) == {
        "chunk_embeddings",
        "chunks",
        "content_objects",
        "document_summaries",
        "extraction_artifacts",
        "lexical_index",
        "retrieval_packages",
        "source_files",
        "summary_embeddings",
    }
    assert all(
        surface["current_adapter_status"] == "sqlalchemy_repository_ready"
        for surface in closed_surfaces.values()
    )
    assert {
        decision["decision_id"] for decision in audit["deferred_schema_decisions"]
    } == {
        "chunk_embedding_index_header",
        "lexical_index_header",
        "processing_runs",
    }
    assert (
        audit["retrieval_runtime_persistence_decision"]["decision_status"]
        == "postgres_adapter_ready"
    )
    assert audit["retrieval_runtime_persistence_decision"]["postgres_smoke_slice"] == (
        "0175"
    )
    assert (
        audit["processing_run_persistence_decision"]["decision_status"]
        == "repository_adapter_ready_write_through_pending"
    )
    assert audit["processing_run_persistence_decision"]["next_slice"] == (
        "0184_cx_processing_run_write_through_integration"
    )
    assert audit["latest_processing_run_persistence_preview"] is None


def test_cx_persistence_gap_audit_counts_seeded_store_without_private_leak(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore()
    document = upload_registration(tmp_path, content_text="SECRET_SOURCE_PAYLOAD")
    store.save_upload_registration(document, source_text="SECRET_SOURCE_PAYLOAD")
    document_id = str(document["document_id"])
    store.extraction_results[document_id] = {"document_id": document_id}
    store.chunk_sets[document_id] = {"document_id": document_id}
    store.chunk_texts["chunk-001"] = "SECRET_CHUNK_PAYLOAD"
    store.embedding_indexes[document_id] = {"document_id": document_id}
    store.embedding_vectors["chunk-001"] = [0.1, 0.2]
    store.lexical_indexes[document_id] = {"document_id": document_id}
    store.retrieval_packages["retrieval-001"] = {
        "retrieval_package_id": "retrieval-001"
    }
    store.document_summaries[document_id] = {
        "document_id": document_id,
        "document_summary_id": "summary-001",
    }
    store.summary_texts["summary-001"] = "SECRET_SUMMARY_PAYLOAD"
    store.summary_embedding_indexes[document_id] = {
        "document_id": document_id,
        "document_summary_id": "summary-001",
    }
    store.summary_embedding_vectors["summary-001"] = [0.3, 0.4]
    store.document_processing_runs["pipeline-001"] = {
        "document_id": document_id,
        "pipeline_run_id": "pipeline-001",
        "status": "FAILED",
        "steps": [
            {
                "step_id": "summary",
                "status": "FAILED",
                "output_ref": {"type": "cx.summary", "id": "summary-001"},
                "error": {
                    "error_code": "cx.summary_failed",
                    "detail": "SECRET_ERROR_DETAIL",
                    "retryable": False,
                },
            }
        ],
    }

    audit = build_cx_persistence_gap_audit(
        store=store,
        persistence_mode="POSTGRES",
    )

    assert audit["persistence_mode"] == "postgres"
    assert audit["store_type"] == "ContentIngestionStore"
    assert audit["content_repository_type"] == "InMemoryCxContentRepository"
    assert audit["observed_store_counts"]["document_count"] == 1
    assert audit["observed_store_counts"]["source_file_count"] == 1
    assert audit["observed_store_counts"]["content_object_count"] == 1
    assert audit["observed_store_counts"]["private_chunk_text_count"] == 1
    assert audit["observed_store_counts"]["private_embedding_vector_count"] == 1
    assert audit["observed_store_counts"]["private_summary_text_count"] == 1
    assert audit["observed_store_counts"][
        "private_summary_embedding_vector_count"
    ] == 1
    surface_counts = {
        surface["surface_id"]: surface["observed_count"]
        for surface in audit["surfaces"]
    }
    assert surface_counts["source_files"] == 1
    assert surface_counts["chunks"] == 1
    assert surface_counts["processing_runs"] == 1
    assert "SECRET_SOURCE_PAYLOAD" not in str(audit)
    assert "SECRET_CHUNK_PAYLOAD" not in str(audit)
    assert "SECRET_SUMMARY_PAYLOAD" not in str(audit)
    assert "SECRET_ERROR_DETAIL" not in str(audit)
    assert audit["latest_processing_run_persistence_preview"]["header"][
        "pipeline_run_id"
    ] == "pipeline-001"
    assert audit["latest_processing_run_persistence_preview"]["steps"][0][
        "error_code"
    ] == "cx.summary_failed"


def test_cx_persistence_gap_audit_records_deferred_schema_decisions() -> None:
    audit = build_cx_persistence_gap_audit()
    decisions = {
        decision["decision_id"]: decision
        for decision in audit["deferred_schema_decisions"]
    }

    processing = decisions["processing_runs"]
    lexical_header = decisions["lexical_index_header"]
    chunk_embedding_header = decisions["chunk_embedding_index_header"]

    assert processing["candidate_tables"] == [
        "cx_document_processing_runs",
        "cx_document_processing_steps",
    ]
    assert (
        processing["decision_status"]
        == "repository_adapter_ready_write_through_pending"
    )
    assert "step_total" in processing["minimum_persisted_metadata"]
    assert "steps[].error_detail_sha256" in processing["minimum_persisted_metadata"]
    assert lexical_header["decision_status"] == "header_table_deferred"
    assert chunk_embedding_header["decision_status"] == "header_table_deferred"
    assert len(CX_DEFERRED_SCHEMA_DECISIONS) == 3

    processing["candidate_tables"].append("mutated")
    fresh = build_cx_persistence_gap_audit()
    fresh_processing = {
        decision["decision_id"]: decision
        for decision in fresh["deferred_schema_decisions"]
    }["processing_runs"]
    assert "mutated" not in fresh_processing["candidate_tables"]


def test_cx_persistence_gap_audit_accepts_repository_without_public_dicts() -> None:
    class AdapterOnlyRepository:
        pass

    store = ContentIngestionStore(content_repository=AdapterOnlyRepository())

    audit = build_cx_persistence_gap_audit(store=store)

    assert audit["content_repository_type"] == "AdapterOnlyRepository"
    assert audit["observed_store_counts"]["source_file_count"] == 0
    assert audit["observed_store_counts"]["content_object_count"] == 0


def test_normalize_cx_persistence_audit_mode_rejects_unknown_value() -> None:
    assert normalize_cx_persistence_audit_mode(None) == "memory"
    assert normalize_cx_persistence_audit_mode(" POSTGRES ") == "postgres"

    with pytest.raises(ValueError, match="CX persistence audit mode"):
        normalize_cx_persistence_audit_mode("sqlite")
