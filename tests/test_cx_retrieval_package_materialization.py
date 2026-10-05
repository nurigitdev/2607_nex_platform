from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
import run_cx_retrieval_package_materialization as smoke

from nex_cx.access_context import CxAccessContext
from nex_cx.repository import (
    InMemoryCxContentRepository,
    build_retrieval_package_persistence_record,
)
from nex_cx.retrieval_materialization import (
    RestartSafeRetrievalPackageStore,
    RetrievalPackageMaterializationError,
    materialize_retrieval_package,
)


PACKAGE_ID = "11111111-1111-4111-8111-111111111111"
CONTENT_ID = "22222222-2222-4222-8222-222222222222"
CHUNK_ID = "33333333-3333-4333-8333-333333333333"
EVIDENCE_ID = "44444444-4444-4444-8444-444444444444"
EVIDENCE_TEXT = "Owner-private grounded evidence."


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _access_context(*, tenant_id: str = "tenant-a", subject_id: str = "user-a") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-1363",
        trace_id="1" * 32,
        scopes=("service.invoke",),
    )


def _runtime_package(*, status: str = "READY") -> dict[str, Any]:
    evidence = [] if status == "NO_ANSWER" else [
        {
            "evidence_id": EVIDENCE_ID,
            "rank": 1,
            "content_object_id": CONTENT_ID,
            "content_version_id": _sha256(EVIDENCE_TEXT),
            "chunk_id": CHUNK_ID,
            "chunk_policy_id": "chunk_1000_100",
            "source_anchor": {"type": "character_range", "start_offset": 0, "end_offset": 34},
            "citation_label": "[1]",
            "text": EVIDENCE_TEXT,
            "scores": {"final_score": 0.91},
            "matched_terms": ["grounded"],
            "permission_result": {"visible": True},
            "neighbor_context": [],
            "quality_flags": [],
        }
    ]
    return {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_runtime_schema_version": "cx_permission_hybrid_runtime.v1",
        "retrieval_package_id": PACKAGE_ID,
        "package_hash": "a" * 64,
        "status": status,
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "tenant-a",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "user-a",
        "trace_id": "1" * 32,
        "request_id": "request-1363",
        "query_text": "private query",
        "persistence_payload_policy": "hash_only_private_owner",
        "query_embedding_snapshot": {
            "provided": True,
            "embedding_sha256": "b" * 64,
            "vector_dimension": 3,
        },
        "purpose": "grounded_answer",
        "retrieval_profile": {
            "search_strategy": "permission_filtered_hybrid",
            "confidence_policy": {"low_confidence_threshold": 0.42},
            "quality_policy": {
                "policy_id": "weighted_rrf_vector_bm25_v1",
                "policy_version": "0001",
                "policy_hash": "c" * 64,
                "policy_source": "cx_permission_filtered_hybrid_runtime",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
            },
        },
        "permission_snapshot": {
            "permission_snapshot_schema_version": "cx_retrieval_permission_snapshot.v1",
            "actor_type": "oa.user",
            "actor_id": "user-a",
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "scope_applied": {"type": "document_ids", "document_ids": [CONTENT_ID]},
            "policy_version": "cx.private_owner_active.v1",
        },
        "evidence_items": evidence,
        "source_summary": {
            "source_count": len(evidence),
            "document_count": len(evidence),
            "chunk_count": len(evidence),
        },
        "score_summary": {
            "best_score": 0.91 if evidence else 0.0,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "rerank_state": "APPLIED",
        },
        "warnings": ["calibration_profile_applied"],
        "no_answer_reason": "no_visible_candidates" if not evidence else None,
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
    }


def _record(*, status: str = "READY") -> dict[str, Any]:
    return build_retrieval_package_persistence_record(
        _runtime_package(status=status)
    )


@dataclass
class FakePrivateEvidenceSource:
    text: str = EVIDENCE_TEXT
    text_sha256: str | None = None
    returned_items: list[dict[str, Any]] | None = None
    failure: Exception | None = None
    calls: list[tuple[CxAccessContext, list[Mapping[str, str]]]] = field(
        default_factory=list
    )

    def load_private_evidence(
        self,
        *,
        access_context: CxAccessContext,
        chunk_refs: Sequence[Mapping[str, str]],
    ) -> list[dict[str, Any]]:
        self.calls.append((access_context, list(chunk_refs)))
        if self.failure is not None:
            raise self.failure
        if self.returned_items is not None:
            return self.returned_items
        return [
            {
                "content_object_id": CONTENT_ID,
                "chunk_id": CHUNK_ID,
                "chunk_text": self.text,
                "text_sha256": self.text_sha256 or _sha256(self.text),
            }
        ]


def test_persistence_record_carries_restore_metadata_without_private_text() -> None:
    record = _record()

    assert record["tenant_ref_id"] == "tenant-a"
    assert record["owner_subject_ref_id"] == "user-a"
    assert record["retrieval_runtime_schema_version"] == (
        "cx_permission_hybrid_runtime.v1"
    )
    assert record["persistence_payload_policy"] == "hash_only_private_owner"
    assert record["retrieval_profile"]["search_strategy"] == (
        "permission_filtered_hybrid"
    )
    assert record["permission_snapshot"]["actor_id"] == "user-a"
    assert record["warnings"] == ["calibration_profile_applied"]
    assert EVIDENCE_TEXT not in str(record)
    assert "private query" not in str(record)


def test_restart_safe_store_materializes_owner_private_evidence() -> None:
    repository = InMemoryCxContentRepository()
    repository.save_retrieval_package_record(_record())
    source = FakePrivateEvidenceSource()
    store = RestartSafeRetrievalPackageStore(repository, source)

    package = store.get_retrieval_package(
        PACKAGE_ID,
        access_context=_access_context(),
    )

    assert package is not None
    assert package["retrieval_package_schema_version"] == (
        "cx_retrieval_context_package.v1"
    )
    assert package["owner_subject_ref_id"] == "user-a"
    assert package["evidence_items"][0]["text"] == EVIDENCE_TEXT
    assert package["evidence_items"][0]["citation_label"] == "[1]"
    assert package["retrieval_profile"]["confidence_policy"] == {
        "low_confidence_threshold": 0.42
    }
    assert source.calls[0][1] == [
        {"content_object_id": CONTENT_ID, "chunk_id": CHUNK_ID}
    ]


def test_restart_safe_store_hides_missing_and_cross_owner_packages_before_private_read() -> None:
    repository = InMemoryCxContentRepository()
    repository.save_retrieval_package_record(_record())
    source = FakePrivateEvidenceSource()
    store = RestartSafeRetrievalPackageStore(repository, source)

    assert store.get_retrieval_package(
        "missing", access_context=_access_context()
    ) is None
    assert store.get_retrieval_package(
        PACKAGE_ID,
        access_context=_access_context(subject_id="user-b"),
    ) is None
    assert source.calls == []


def test_no_answer_package_materializes_without_private_read() -> None:
    source = FakePrivateEvidenceSource()

    package = materialize_retrieval_package(
        _record(status="NO_ANSWER"),
        access_context=_access_context(),
        private_evidence_source=source,
    )

    assert package["status"] == "NO_ANSWER"
    assert package["evidence_items"] == []
    assert source.calls == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda record: record.update(permission_snapshot_hash="0" * 64), "snapshot hash"),
        (lambda record: record.update(evidence_count=2), "evidence count"),
        (lambda record: record.update(warnings="invalid"), "string list"),
        (lambda record: record["evidence_items"][0].update(rank=0), "positive"),
        (lambda record: record.update(retrieval_profile=[]), "retrieval_profile"),
    ],
)
def test_materialization_rejects_corrupt_persisted_metadata(mutate, expected: str) -> None:
    record = deepcopy(_record())
    mutate(record)

    with pytest.raises(RetrievalPackageMaterializationError, match=expected):
        materialize_retrieval_package(
            record,
            access_context=_access_context(),
            private_evidence_source=FakePrivateEvidenceSource(),
        )


def test_materialization_rejects_permission_owner_mismatch() -> None:
    record = deepcopy(_record())
    record["permission_snapshot"]["actor_id"] = "user-b"
    from nex_cx.retrieval_persistence import sha256_json

    record["permission_snapshot_hash"] = sha256_json(
        record["permission_snapshot"]
    )

    with pytest.raises(RetrievalPackageMaterializationError, match="owner lineage"):
        materialize_retrieval_package(
            record,
            access_context=_access_context(),
            private_evidence_source=FakePrivateEvidenceSource(),
        )


@pytest.mark.parametrize(
    "field, value",
    [
        ("actor_type", "service"),
        ("actor_id", "user-b"),
        ("tenant_ref.type", "tenant"),
        ("tenant_ref.id", "tenant-b"),
    ],
)
def test_materialization_rejects_each_permission_owner_dimension(
    field: str,
    value: str,
) -> None:
    record = deepcopy(_record())
    if field.startswith("tenant_ref."):
        record["permission_snapshot"]["tenant_ref"][field.rsplit(".", 1)[1]] = value
    else:
        record["permission_snapshot"][field] = value
    from nex_cx.retrieval_persistence import sha256_json

    record["permission_snapshot_hash"] = sha256_json(
        record["permission_snapshot"]
    )

    with pytest.raises(RetrievalPackageMaterializationError, match="owner lineage"):
        materialize_retrieval_package(
            record,
            access_context=_access_context(),
            private_evidence_source=FakePrivateEvidenceSource(),
        )


@pytest.mark.parametrize(
    "source, expected",
    [
        (FakePrivateEvidenceSource(text="tampered"), "hash does not match"),
        (
            FakePrivateEvidenceSource(text_sha256="0" * 64),
            "chunk lineage hash",
        ),
        (FakePrivateEvidenceSource(returned_items=[]), "could not be materialized"),
        (
            FakePrivateEvidenceSource(
                returned_items=[
                    {
                        "content_object_id": CONTENT_ID,
                        "chunk_id": CHUNK_ID,
                        "chunk_text": EVIDENCE_TEXT,
                        "text_sha256": _sha256(EVIDENCE_TEXT),
                    },
                    {
                        "content_object_id": CONTENT_ID,
                        "chunk_id": CHUNK_ID,
                        "chunk_text": EVIDENCE_TEXT,
                        "text_sha256": _sha256(EVIDENCE_TEXT),
                    },
                ]
            ),
            "duplicate",
        ),
    ],
)
def test_materialization_rejects_private_evidence_drift(
    source: FakePrivateEvidenceSource,
    expected: str,
) -> None:
    with pytest.raises(RetrievalPackageMaterializationError, match=expected):
        materialize_retrieval_package(
            _record(),
            access_context=_access_context(),
            private_evidence_source=source,
        )


def test_materialization_wraps_private_evidence_failures_as_retryable() -> None:
    source = FakePrivateEvidenceSource(failure=RuntimeError("storage offline"))

    with pytest.raises(RetrievalPackageMaterializationError) as captured:
        materialize_retrieval_package(
            _record(),
            access_context=_access_context(),
            private_evidence_source=source,
        )

    assert captured.value.status_code == 503
    assert captured.value.retryable is True
    assert captured.value.error_code == (
        "cx.retrieval_package_private_evidence_unavailable"
    )


def test_materialization_preserves_domain_private_evidence_failure() -> None:
    failure = RetrievalPackageMaterializationError(
        status_code=409,
        error_code="cx.test_private_evidence_invalid",
        detail="private evidence invalid",
    )

    with pytest.raises(RetrievalPackageMaterializationError) as captured:
        materialize_retrieval_package(
            _record(),
            access_context=_access_context(),
            private_evidence_source=FakePrivateEvidenceSource(failure=failure),
        )

    assert captured.value is failure


def test_materialization_accepts_private_source_without_redundant_hash() -> None:
    source = FakePrivateEvidenceSource(
        returned_items=[
            {
                "content_object_id": CONTENT_ID,
                "chunk_id": CHUNK_ID,
                "chunk_text": EVIDENCE_TEXT,
            }
        ]
    )

    package = materialize_retrieval_package(
        _record(),
        access_context=_access_context(),
        private_evidence_source=source,
    )

    assert package["evidence_items"][0]["text"] == EVIDENCE_TEXT


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda record: record.update(tenant_ref_id="tenant-b"), "owner lineage"),
        (lambda record: record.update(evidence_items="invalid"), "must be a list"),
        (lambda record: record.update(evidence_items=[None]), "item is invalid"),
        (
            lambda record: (
                record["evidence_items"].append(
                    deepcopy(record["evidence_items"][0])
                ),
                record.update(evidence_count=2),
            ),
            "ranks must be unique",
        ),
        (
            lambda record: record["evidence_items"][0].update(
                content_object_id=""
            ),
            "non-empty string",
        ),
        (lambda record: record.update(package_hash="z" * 64), "SHA-256"),
        (lambda record: record.update(evidence_count=True), "non-negative integer"),
        (lambda record: record.update(evidence_count=-1), "non-negative integer"),
        (lambda record: record.update(warnings=[1]), "string list"),
    ],
)
def test_materialization_rejects_invalid_structural_values(mutate, expected: str) -> None:
    record = deepcopy(_record())
    mutate(record)

    with pytest.raises(RetrievalPackageMaterializationError, match=expected):
        materialize_retrieval_package(
            record,
            access_context=_access_context(),
            private_evidence_source=FakePrivateEvidenceSource(),
        )


def test_materialization_rejects_non_mapping_private_item() -> None:
    source = FakePrivateEvidenceSource(returned_items=[None])  # type: ignore[list-item]

    with pytest.raises(RetrievalPackageMaterializationError, match="invalid item"):
        materialize_retrieval_package(
            _record(),
            access_context=_access_context(),
            private_evidence_source=source,
        )


def test_materialization_migration_is_owner_scoped_and_hash_only() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "database/nex-cx/migrations/1363_cx_retrieval_materialization.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())

    assert "tenant_ref_id" in compact
    assert "owner_subject_ref_id" in compact
    assert "idx_cx_ret_pkg_owner_created" in compact
    assert "1363_cx_retrieval_materialization" in compact
    assert "evidence_text" not in compact
    assert "query_text" not in compact


def test_deterministic_materialization_evidence_passes() -> None:
    result = smoke.run_cx_retrieval_package_materialization()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 5,
        "passed_count": 5,
        "private_read_count": 1,
        "materialized_evidence_count": 1,
    }
    assert result["decision"]["next_slice"] == "1364"
    assert smoke.summary_line(result) == (
        "cx_retrieval_materialization=pass checks=5/5 private_reads=1 next=1364"
    )


def test_materialization_evidence_main_outputs_json_and_summary(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_retrieval_package_materialization()
    monkeypatch.setattr(
        smoke,
        "run_cx_retrieval_package_materialization",
        lambda: passing,
    )

    assert smoke.main(["--summary"]) == 0
    assert "checks=5/5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_cx_retrieval_package_materialization",
        lambda: {"status": "FAIL", "summary": {}, "decision": {}},
    )
    assert smoke.main([]) == 1
