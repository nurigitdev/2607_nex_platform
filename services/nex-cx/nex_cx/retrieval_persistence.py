from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


CX_RETRIEVAL_RUNTIME_PERSISTENCE_DECISION_SCHEMA_VERSION = (
    "cx_retrieval_runtime_persistence_decision.v1"
)
CX_RETRIEVAL_PACKAGE_PERSISTENCE_PREVIEW_SCHEMA_VERSION = (
    "cx_retrieval_package_persistence_preview.v1"
)
CX_RETRIEVAL_PACKAGE_TABLE = "cx_retrieval_packages"
CX_RETRIEVAL_EVIDENCE_ITEM_TABLE = "cx_retrieval_evidence_items"
TEXT_PREVIEW_MAX_CHARS = 240


def build_retrieval_runtime_persistence_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": CX_RETRIEVAL_RUNTIME_PERSISTENCE_DECISION_SCHEMA_VERSION,
        "decision_slice": "0171",
        "surface_id": "retrieval_packages",
        "decision_status": "postgres_adapter_ready",
        "runtime_record_schema": "cx_retrieval_context_package.v1",
        "persistence_owner": "nex-cx",
        "repository_boundary": "CxContentRepository",
        "write_path": (
            "ContentIngestionStore.save_retrieval_package write-through after "
            "package materialization"
        ),
        "migration_version": "0172_cx_retrieval_package_persistence",
        "adapter_slice": "0173",
        "write_through_slice": "0174",
        "postgres_smoke_slice": "0175",
        "target_tables": [
            CX_RETRIEVAL_PACKAGE_TABLE,
            CX_RETRIEVAL_EVIDENCE_ITEM_TABLE,
        ],
        "unique_keys": {
            CX_RETRIEVAL_PACKAGE_TABLE: [
                ["retrieval_package_id"],
                ["package_hash"],
            ],
            CX_RETRIEVAL_EVIDENCE_ITEM_TABLE: [
                ["retrieval_package_id", "rank"],
                ["retrieval_package_id", "evidence_id"],
            ],
        },
        "header_metadata_fields": [
            "retrieval_package_id",
            "package_hash",
            "status",
            "trace_id",
            "request_id",
            "query_text_sha256",
            "query_text_preview",
            "query_embedding_provided",
            "query_embedding_sha256",
            "query_embedding_dimension",
            "purpose",
            "retrieval_policy_id",
            "retrieval_policy_version",
            "retrieval_policy_hash",
            "retrieval_policy_source",
            "ranker_mix",
            "rerank_state",
            "permission_snapshot_hash",
            "source_summary",
            "score_summary",
            "warning_count",
            "evidence_count",
            "no_answer_reason",
            "created_at",
            "updated_at",
        ],
        "evidence_metadata_fields": [
            "evidence_id",
            "retrieval_package_id",
            "rank",
            "content_object_id",
            "content_version_id",
            "chunk_id",
            "chunk_policy_id",
            "source_anchor",
            "citation_label",
            "evidence_text_sha256",
            "evidence_text_preview",
            "scores",
            "final_score",
            "matched_terms",
            "permission_result",
            "neighbor_context",
            "quality_flags",
        ],
        "private_payload_exclusions": [
            "query_text",
            "query_embedding_raw_vector",
            "evidence_items[].text",
        ],
        "private_payload_policy": "query_hash_preview_and_evidence_hash_preview_only",
        "migration_policy": "postgres_schema_and_adapter_write_through_ready",
        "next_slice": "0176_ag_retrieval_package_operations_projection",
    }


def build_retrieval_package_persistence_preview(
    package: Mapping[str, Any],
) -> dict[str, Any]:
    query_text = _string_value(package.get("query_text"))
    query_embedding_snapshot = _mapping_value(package.get("query_embedding_snapshot"))
    retrieval_profile = _mapping_value(package.get("retrieval_profile"))
    quality_policy = _mapping_value(retrieval_profile.get("quality_policy"))
    score_summary = _mapping_value(package.get("score_summary"))
    permission_snapshot = _mapping_value(package.get("permission_snapshot"))
    retrieval_package_id = package.get("retrieval_package_id")

    evidence_items = [
        _build_evidence_item_preview(
            item,
            retrieval_package_id=retrieval_package_id,
        )
        for item in _list_value(package.get("evidence_items"))
        if isinstance(item, Mapping)
    ]
    header = {
        "preview_schema_version": CX_RETRIEVAL_PACKAGE_PERSISTENCE_PREVIEW_SCHEMA_VERSION,
        "target_table": CX_RETRIEVAL_PACKAGE_TABLE,
        "retrieval_package_id": retrieval_package_id,
        "package_hash": package.get("package_hash"),
        "status": package.get("status"),
        "trace_id": package.get("trace_id"),
        "request_id": package.get("request_id"),
        "query_text_sha256": sha256_text(query_text) if query_text is not None else None,
        "query_text_preview": bounded_text_preview(query_text),
        "query_embedding_provided": bool(
            query_embedding_snapshot.get(
                "provided",
                query_embedding_snapshot.get("embedding_provided", False),
            )
        ),
        "query_embedding_sha256": query_embedding_snapshot.get("embedding_sha256"),
        "query_embedding_dimension": query_embedding_snapshot.get(
            "vector_dimension",
            query_embedding_snapshot.get("embedding_dimension"),
        ),
        "purpose": package.get("purpose"),
        "retrieval_policy_id": quality_policy.get("policy_id"),
        "retrieval_policy_version": quality_policy.get("policy_version"),
        "retrieval_policy_hash": quality_policy.get("policy_hash"),
        "retrieval_policy_source": quality_policy.get("policy_source"),
        "ranker_mix": score_summary.get("ranker_mix") or quality_policy.get("ranker_mix"),
        "rerank_state": score_summary.get("rerank_state"),
        "permission_snapshot_hash": sha256_json(permission_snapshot),
        "source_summary": package.get("source_summary"),
        "score_summary": package.get("score_summary"),
        "warning_count": len(_list_value(package.get("warnings"))),
        "evidence_count": len(evidence_items),
        "no_answer_reason": package.get("no_answer_reason"),
        "created_at": package.get("created_at"),
        "updated_at": package.get("updated_at"),
    }
    return {
        "preview_schema_version": CX_RETRIEVAL_PACKAGE_PERSISTENCE_PREVIEW_SCHEMA_VERSION,
        "decision": build_retrieval_runtime_persistence_decision(),
        "header": header,
        "evidence_items": evidence_items,
        "private_payload_exclusions": [
            "query_text",
            "query_embedding_raw_vector",
            "evidence_items[].text",
        ],
    }


def _build_evidence_item_preview(
    item: Mapping[str, Any],
    *,
    retrieval_package_id: object,
) -> dict[str, Any]:
    evidence_text = _string_value(item.get("text"))
    return {
        "target_table": CX_RETRIEVAL_EVIDENCE_ITEM_TABLE,
        "retrieval_package_id": retrieval_package_id,
        "evidence_id": item.get("evidence_id"),
        "rank": item.get("rank"),
        "content_object_id": item.get("content_object_id"),
        "content_version_id": item.get("content_version_id"),
        "chunk_id": item.get("chunk_id"),
        "chunk_policy_id": item.get("chunk_policy_id"),
        "source_anchor": item.get("source_anchor"),
        "citation_label": item.get("citation_label"),
        "evidence_text_sha256": (
            sha256_text(evidence_text) if evidence_text is not None else None
        ),
        "evidence_text_preview": bounded_text_preview(evidence_text),
        "scores": item.get("scores"),
        "final_score": _final_score(item.get("scores")),
        "matched_terms": item.get("matched_terms"),
        "permission_result": item.get("permission_result"),
        "neighbor_context": item.get("neighbor_context"),
        "quality_flags": item.get("quality_flags"),
    }


def bounded_text_preview(
    value: object,
    *,
    max_chars: int = TEXT_PREVIEW_MAX_CHARS,
) -> str | None:
    text = _string_value(value)
    if text is None:
        return None
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3].rstrip()}..."


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(canonical)


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _mapping_value(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _final_score(value: object) -> float:
    if not isinstance(value, Mapping):
        return 0.0
    score = value.get("final_score", 0.0)
    if isinstance(score, bool) or not isinstance(score, int | float):
        return 0.0
    return float(score)
