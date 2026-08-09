from __future__ import annotations

from pathlib import Path

import pytest

from nex_cx.ingestion import ContentIngestionStore, CxStorageConfig, build_upload_registration
from nex_cx.persistence_audit import (
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
    assert audit["checkpoint_slice"] == "0161"
    assert audit["persistence_mode"] == "memory"
    assert audit["checkpoint_status"] == "ACTION_REQUIRED"
    assert audit["store_type"] is None
    assert audit["content_repository_type"] is None
    assert audit["summary"] == {
        "surface_count": 10,
        "postgres_adapter_gap_count": 4,
        "schema_deferred_count": 2,
        "private_payload_boundary_count": 6,
        "next_recommended_slice": "0168_sqlalchemy_cx_document_summary_repository",
    }
    assert all(count == 0 for count in audit["observed_store_counts"].values())
    assert {
        surface["surface_id"]
        for surface in audit["surfaces"]
        if surface["target_table_status"] == "schema_deferred"
    } == {"processing_runs", "retrieval_packages"}
    closed_surfaces = {
        surface["surface_id"]: surface
        for surface in audit["surfaces"]
        if not surface["postgres_adapter_required"]
    }
    assert set(closed_surfaces) == {
        "chunk_embeddings",
        "chunks",
        "content_objects",
        "extraction_artifacts",
        "lexical_index",
        "source_files",
    }
    assert all(
        surface["current_adapter_status"] == "sqlalchemy_repository_ready"
        for surface in closed_surfaces.values()
    )


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
