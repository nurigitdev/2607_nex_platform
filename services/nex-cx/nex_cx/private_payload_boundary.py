from __future__ import annotations

from typing import Any


CX_PRIVATE_PAYLOAD_BOUNDARY_SCHEMA_VERSION = "cx_private_payload_boundary.v1"

CX_PRIVATE_PAYLOAD_DECISIONS: tuple[dict[str, Any], ...] = (
    {
        "payload_id": "source_bytes",
        "current_runtime_holder": "ContentIngestionStore.source_bytes",
        "canonical_durable_owner": "local_source_file_adapter",
        "current_storage_root_env": "NEX_CX_SOURCE_STORAGE_ROOT",
        "future_storage_adapter": "object_storage",
        "restart_policy": "reload_and_verify_from_storage_uri",
        "durability_status": "DURABLE",
        "implementation_priority": "COMPLETE",
    },
    {
        "payload_id": "source_texts",
        "current_runtime_holder": "ContentIngestionStore.source_texts",
        "canonical_durable_owner": "none_ephemeral_decode_cache",
        "current_storage_root_env": None,
        "future_storage_adapter": "none",
        "restart_policy": "decode_again_from_verified_source_bytes",
        "durability_status": "RECONSTRUCTABLE",
        "implementation_priority": "COMPLETE",
    },
    {
        "payload_id": "chunk_texts",
        "current_runtime_holder": "ContentIngestionStore.chunk_texts",
        "canonical_durable_owner": "extracted_markdown_plus_chunk_offsets",
        "current_storage_root_env": "NEX_CX_EXTRACTED_MARKDOWN_ROOT",
        "future_storage_adapter": "private_chunk_text_reader",
        "restart_policy": "reconstruct_and_hash_verify_from_markdown_offsets",
        "durability_status": "ADAPTER_REQUIRED",
        "implementation_priority": "S92_HIGH",
    },
    {
        "payload_id": "embedding_vectors",
        "current_runtime_holder": "ContentIngestionStore.embedding_vectors",
        "canonical_durable_owner": "vector_store",
        "current_storage_root_env": "NEX_CX_VECTOR_DATABASE_URL",
        "future_storage_adapter": "pgvector_or_external_vector_database",
        "restart_policy": "load_by_chunk_id_and_verify_dimension_hash",
        "durability_status": "ADAPTER_REQUIRED",
        "implementation_priority": "S92_HIGH",
    },
    {
        "payload_id": "summary_texts",
        "current_runtime_holder": "ContentIngestionStore.summary_texts",
        "canonical_durable_owner": "private_summary_artifact_store",
        "current_storage_root_env": "NEX_CX_SUMMARY_STORAGE_ROOT",
        "future_storage_adapter": "local_then_object_storage",
        "restart_policy": "load_by_summary_storage_uri_and_verify_sha256",
        "durability_status": "ADAPTER_REQUIRED",
        "implementation_priority": "S92_HIGH",
    },
    {
        "payload_id": "summary_embedding_vectors",
        "current_runtime_holder": "ContentIngestionStore.summary_embedding_vectors",
        "canonical_durable_owner": "vector_store",
        "current_storage_root_env": "NEX_CX_VECTOR_DATABASE_URL",
        "future_storage_adapter": "pgvector_or_external_vector_database",
        "restart_policy": "load_by_summary_id_and_verify_dimension_hash",
        "durability_status": "ADAPTER_REQUIRED",
        "implementation_priority": "S92_HIGH",
    },
)


def build_cx_private_payload_boundary_decision() -> dict[str, Any]:
    decisions = [dict(item) for item in CX_PRIVATE_PAYLOAD_DECISIONS]
    adapter_required = [
        item["payload_id"]
        for item in decisions
        if item["durability_status"] == "ADAPTER_REQUIRED"
    ]
    return {
        "decision_schema_version": CX_PRIVATE_PAYLOAD_BOUNDARY_SCHEMA_VERSION,
        "slice": "0904",
        "requirement": "S91",
        "decision_status": "FROZEN",
        "owner": "nex-cx",
        "policies": {
            "public_postgres_payload_policy": "metadata_hash_uri_dimension_only",
            "missing_payload_policy": "fail_closed_and_mark_reprocessing_required",
            "hash_mismatch_policy": "fail_closed_and_emit_redacted_operational_event",
            "owner_scope_policy": "authorize_before_private_payload_read",
            "transaction_policy": "perform_payload_io_outside_database_transaction",
            "adapter_policy": "local_first_object_and_vector_store_replaceable",
        },
        "payloads": decisions,
        "summary": {
            "payload_count": len(decisions),
            "durable_count": sum(
                item["durability_status"] == "DURABLE" for item in decisions
            ),
            "reconstructable_count": sum(
                item["durability_status"] == "RECONSTRUCTABLE"
                for item in decisions
            ),
            "adapter_required_count": len(adapter_required),
            "adapter_required_payloads": adapter_required,
        },
        "next_slice": "0905",
        "next_requirement": "S92",
    }
