from __future__ import annotations

from nex_cx.retrieval_persistence import (
    CX_RETRIEVAL_EVIDENCE_ITEM_TABLE,
    CX_RETRIEVAL_PACKAGE_TABLE,
    TEXT_PREVIEW_MAX_CHARS,
    bounded_text_preview,
    build_retrieval_package_persistence_preview,
    build_retrieval_runtime_persistence_decision,
    sha256_json,
    sha256_text,
)


def test_retrieval_runtime_persistence_decision_freezes_target_mapping() -> None:
    decision = build_retrieval_runtime_persistence_decision()

    assert decision["decision_slice"] == "0171"
    assert decision["decision_status"] == "postgres_adapter_ready"
    assert decision["migration_version"] == "0172_cx_retrieval_package_persistence"
    assert decision["adapter_slice"] == "0173"
    assert decision["write_through_slice"] == "0174"
    assert decision["postgres_smoke_slice"] == "0175"
    assert decision["target_tables"] == [
        CX_RETRIEVAL_PACKAGE_TABLE,
        CX_RETRIEVAL_EVIDENCE_ITEM_TABLE,
    ]
    assert decision["unique_keys"][CX_RETRIEVAL_PACKAGE_TABLE] == [
        ["retrieval_package_id"],
        ["package_hash"],
    ]
    assert ["retrieval_package_id", "rank"] in decision["unique_keys"][
        CX_RETRIEVAL_EVIDENCE_ITEM_TABLE
    ]
    assert "query_text_sha256" in decision["header_metadata_fields"]
    assert "evidence_text_sha256" in decision["evidence_metadata_fields"]
    assert decision["private_payload_exclusions"] == [
        "query_text",
        "query_embedding_raw_vector",
        "evidence_items[].text",
    ]
    assert decision["next_slice"] == (
        "0176_ag_retrieval_package_operations_projection"
    )


def test_retrieval_package_persistence_preview_hashes_private_runtime_text() -> None:
    query_text = "  민감한 query " + ("x" * 400)
    evidence_text = "민감한 evidence " + ("y" * 400)
    permission_snapshot = {
        "actor_claims_ref": {"actor_id": "user-001", "actor_type": "user"},
        "document_scope": {"document_ids": ["doc-001"]},
        "authorized_document_ids": ["doc-001"],
    }
    package = {
        "retrieval_package_id": "retrieval-001",
        "package_hash": "package-hash-001",
        "status": "READY",
        "trace_id": "trace-001",
        "request_id": "request-001",
        "query_text": query_text,
        "query_embedding_snapshot": {
            "provided": True,
            "embedding_sha256": "e" * 64,
            "vector_dimension": 3,
        },
        "purpose": "grounded_answer",
        "retrieval_profile": {
            "quality_policy": {
                "policy_id": "weighted_rrf_vector_bm25_v1",
                "policy_version": "2026-08-09",
                "policy_hash": "p" * 64,
                "policy_source": "ag_registry_active",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
            }
        },
        "permission_snapshot": permission_snapshot,
        "evidence_items": [
            {
                "evidence_id": "evidence-001",
                "rank": 1,
                "content_object_id": "doc-001",
                "content_version_id": "version-001",
                "chunk_id": "chunk-001",
                "chunk_policy_id": "chunk_1000_100",
                "source_anchor": {"offset_start": 0, "offset_end": 30},
                "citation_label": "source.md#chunk-001",
                "text": evidence_text,
                "neighbor_context": {"previous_chunk_id": None, "next_chunk_id": None},
                "scores": {"final_score": 0.91},
                "matched_terms": ["query"],
                "permission_result": {"allowed": True},
                "quality_flags": [],
            }
        ],
        "source_summary": {"document_count": 1},
        "score_summary": {
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "rerank_state": "NOT_APPLIED",
        },
        "warnings": [{"code": "cx.mock_warning"}],
        "no_answer_reason": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
    }

    preview = build_retrieval_package_persistence_preview(package)
    header = preview["header"]
    evidence = preview["evidence_items"][0]

    assert "query_text" not in header
    assert header["query_text_sha256"] == sha256_text(query_text.strip())
    assert len(header["query_text_preview"]) <= TEXT_PREVIEW_MAX_CHARS
    assert query_text.strip() not in str(preview)
    assert header["query_embedding_provided"] is True
    assert header["query_embedding_sha256"] == "e" * 64
    assert header["query_embedding_dimension"] == 3
    assert header["permission_snapshot_hash"] == sha256_json(permission_snapshot)
    assert header["retrieval_policy_id"] == "weighted_rrf_vector_bm25_v1"
    assert header["ranker_mix"] == "weighted_rrf_vector_bm25_v1"
    assert header["warning_count"] == 1
    assert header["evidence_count"] == 1
    assert "text" not in evidence
    assert evidence["evidence_text_sha256"] == sha256_text(evidence_text)
    assert len(evidence["evidence_text_preview"]) <= TEXT_PREVIEW_MAX_CHARS
    assert evidence["final_score"] == 0.91
    assert evidence_text not in str(preview)
    assert evidence["target_table"] == CX_RETRIEVAL_EVIDENCE_ITEM_TABLE


def test_retrieval_package_persistence_preview_handles_sparse_runtime_package() -> None:
    package = {
        "retrieval_package_id": "retrieval-empty",
        "evidence_items": [
            {
                "evidence_id": "evidence-without-text",
                "rank": 1,
                "text": None,
            },
            "not-a-mapping",
        ],
        "warnings": "not-a-list",
    }

    preview = build_retrieval_package_persistence_preview(package)

    assert preview["header"]["query_text_sha256"] is None
    assert preview["header"]["query_text_preview"] is None
    assert preview["header"]["query_embedding_provided"] is False
    assert preview["header"]["permission_snapshot_hash"] == sha256_json({})
    assert preview["header"]["warning_count"] == 0
    assert preview["header"]["evidence_count"] == 1
    assert preview["evidence_items"][0]["evidence_text_sha256"] is None
    assert preview["evidence_items"][0]["evidence_text_preview"] is None
    assert preview["evidence_items"][0]["final_score"] == 0.0


def test_bounded_text_preview_covers_empty_short_long_and_tiny_limits() -> None:
    assert bounded_text_preview(None) is None
    assert bounded_text_preview("") is None
    assert bounded_text_preview(" short text ") == "short text"
    assert bounded_text_preview("abcdef", max_chars=0) == ""
    assert bounded_text_preview("abcdef", max_chars=2) == "ab"
    assert bounded_text_preview("abcdef", max_chars=5) == "ab..."
