from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from typing import Any, Protocol

from nex_cx.access_context import CxAccessContext
from nex_cx.api_ownership import record_visible_to_owner
from nex_cx.repository import CxContentRepository
from nex_cx.retrieval_persistence import sha256_json


class PrivateEvidenceSource(Protocol):
    def load_private_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class RetrievalPackageMaterializationError(RuntimeError):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class RestartSafeRetrievalPackageStore:
    repository: CxContentRepository
    private_evidence_source: PrivateEvidenceSource

    def get_retrieval_package(
        self,
        retrieval_package_id: str,
        *,
        access_context: CxAccessContext | None = None,
    ) -> dict[str, Any] | None:
        if access_context is None:
            return None
        record = self.repository.get_retrieval_package_record(
            retrieval_package_id
        )
        if record is None or not record_visible_to_owner(access_context, record):
            return None
        return materialize_retrieval_package(
            record,
            access_context=access_context,
            private_evidence_source=self.private_evidence_source,
        )


def materialize_retrieval_package(
    record: Mapping[str, Any],
    *,
    access_context: CxAccessContext,
    private_evidence_source: PrivateEvidenceSource,
) -> dict[str, Any]:
    if not record_visible_to_owner(access_context, record):
        raise _corrupt("Retrieval package owner lineage does not match the request.")

    permission_snapshot = _mapping(record.get("permission_snapshot"), "permission_snapshot")
    _validate_permission_snapshot(
        permission_snapshot,
        expected_hash=record.get("permission_snapshot_hash"),
        access_context=access_context,
    )
    retrieval_profile = _mapping(record.get("retrieval_profile"), "retrieval_profile")
    evidence_records = _evidence_records(record.get("evidence_items"))
    evidence_count = _non_negative_int(record.get("evidence_count"), "evidence_count")
    if evidence_count != len(evidence_records):
        raise _corrupt("Retrieval package evidence count does not match persisted items.")

    materialized_evidence = _materialize_evidence(
        evidence_records,
        access_context=access_context,
        private_evidence_source=private_evidence_source,
    )
    return {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_runtime_schema_version": record.get(
            "retrieval_runtime_schema_version"
        ),
        "retrieval_package_id": _required_text(
            record.get("retrieval_package_id"), "retrieval_package_id"
        ),
        "package_hash": _sha256(record.get("package_hash"), "package_hash"),
        "status": _required_text(record.get("status"), "status"),
        "tenant_ref_type": record["tenant_ref_type"],
        "tenant_ref_id": record["tenant_ref_id"],
        "owner_subject_ref_type": record["owner_subject_ref_type"],
        "owner_subject_ref_id": record["owner_subject_ref_id"],
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "persistence_payload_policy": record.get("persistence_payload_policy"),
        "query_embedding_snapshot": {
            "provided": bool(record.get("query_embedding_provided", False)),
            "embedding_sha256": record.get("query_embedding_sha256"),
            "vector_dimension": record.get("query_embedding_dimension", 0),
        },
        "purpose": record.get("purpose"),
        "retrieval_profile": dict(retrieval_profile),
        "permission_snapshot": dict(permission_snapshot),
        "evidence_items": materialized_evidence,
        "source_summary": dict(_mapping(record.get("source_summary"), "source_summary")),
        "score_summary": dict(_mapping(record.get("score_summary"), "score_summary")),
        "warnings": _string_list(record.get("warnings"), "warnings"),
        "no_answer_reason": record.get("no_answer_reason"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _materialize_evidence(
    evidence_records: list[dict[str, Any]],
    *,
    access_context: CxAccessContext,
    private_evidence_source: PrivateEvidenceSource,
) -> list[dict[str, Any]]:
    if not evidence_records:
        return []
    refs = [
        {
            "content_object_id": _required_text(
                item.get("content_object_id"), "content_object_id"
            ),
            "chunk_id": _required_text(item.get("chunk_id"), "chunk_id"),
        }
        for item in evidence_records
    ]
    try:
        private_items = private_evidence_source.load_private_evidence(
            access_context=access_context,
            chunk_refs=refs,
        )
    except RetrievalPackageMaterializationError:
        raise
    except Exception as exc:
        raise RetrievalPackageMaterializationError(
            status_code=503,
            error_code="cx.retrieval_package_private_evidence_unavailable",
            detail="Private retrieval evidence could not be loaded.",
            retryable=bool(getattr(exc, "retryable", True)),
        ) from exc

    private_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in private_items:
        if not isinstance(item, Mapping):
            raise _corrupt("Private evidence materialization returned an invalid item.")
        key = (
            _required_text(item.get("content_object_id"), "content_object_id"),
            _required_text(item.get("chunk_id"), "chunk_id"),
        )
        if key in private_by_key:
            raise _corrupt("Private evidence materialization returned duplicate items.")
        private_by_key[key] = item

    result: list[dict[str, Any]] = []
    for persisted in evidence_records:
        key = (str(persisted["content_object_id"]), str(persisted["chunk_id"]))
        private = private_by_key.get(key)
        if private is None:
            raise _corrupt("Persisted retrieval evidence could not be materialized.")
        text = _required_text(private.get("chunk_text"), "chunk_text")
        expected_hash = _sha256(
            persisted.get("evidence_text_sha256"), "evidence_text_sha256"
        )
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected_hash:
            raise _corrupt("Private retrieval evidence hash does not match metadata.")
        private_hash = private.get("text_sha256")
        if private_hash is not None and private_hash != expected_hash:
            raise _corrupt("Private chunk lineage hash does not match retrieval evidence.")
        result.append(
            {
                **persisted,
                "retrieval_evidence_schema_version": "cx_retrieval_evidence_item.v1",
                "text": text,
            }
        )
    return result


def _validate_permission_snapshot(
    snapshot: Mapping[str, Any],
    *,
    expected_hash: object,
    access_context: CxAccessContext,
) -> None:
    if sha256_json(snapshot) != _sha256(expected_hash, "permission_snapshot_hash"):
        raise _corrupt("Retrieval permission snapshot hash does not match metadata.")
    tenant_ref = _mapping(snapshot.get("tenant_ref"), "permission_snapshot.tenant_ref")
    if (
        snapshot.get("actor_type") != "oa.user"
        or snapshot.get("actor_id") != access_context.subject_id
        or tenant_ref.get("type") != "oa.tenant"
        or tenant_ref.get("id") != access_context.tenant_id
    ):
        raise _corrupt("Retrieval permission snapshot does not match owner lineage.")


def _evidence_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _corrupt("Retrieval package evidence items must be a list.")
    records: list[dict[str, Any]] = []
    ranks: set[int] = set()
    for item in value:
        if not isinstance(item, dict):
            raise _corrupt("Retrieval package evidence item is invalid.")
        rank = _positive_int(item.get("rank"), "rank")
        if rank in ranks:
            raise _corrupt("Retrieval package evidence ranks must be unique.")
        ranks.add(rank)
        records.append(dict(item))
    return sorted(records, key=lambda item: int(item["rank"]))


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _corrupt(f"{field} must be an object.")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _corrupt(f"{field} must be a string list.")
    return list(value)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _corrupt(f"{field} must be a non-empty string.")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _required_text(value, field).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise _corrupt(f"{field} must be a SHA-256 value.")
    return text


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _corrupt(f"{field} must be a non-negative integer.")
    return value


def _positive_int(value: object, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise _corrupt(f"{field} must be positive.")
    return result


def _corrupt(detail: str) -> RetrievalPackageMaterializationError:
    return RetrievalPackageMaterializationError(
        status_code=409,
        error_code="cx.retrieval_package_materialization_invalid",
        detail=detail,
    )
