from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from nex_cx.chunking import build_and_store_chunk_set
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.ingestion_hydration import (
    IngestionHydrationError,
    hydrate_ingestion_runtime,
)
from nex_cx.ingestion_orchestration import build_ingestion_run
from nex_cx.lexical_index import build_and_store_lexical_index
from nex_cx.repository import InMemoryCxContentRepository


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "request-1346"


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source-files",
        extracted_markdown_root=tmp_path / "extracted-markdown",
        extraction_temp_root=tmp_path / "temp",
        chunk_policy="chunk_20_5",
        chunk_size=20,
        chunk_overlap=5,
        bm25_tokenizer="korean_mixed_v1",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def persisted_runtime(tmp_path: Path):
    config = storage_config(tmp_path)
    repository = InMemoryCxContentRepository()
    store = ContentIngestionStore(content_repository=repository)
    registration = build_upload_registration(
        {
            "filename": "restart.md",
            "content_type": "text/markdown",
            "content_text": "restart durable markdown with several chunks and BM25 terms",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    saved = store.save_upload_registration(
        registration,
        source_text="restart durable markdown with several chunks and BM25 terms",
    )
    extraction = run_text_extraction_job(
        saved["ingestion_job"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    chunk_set = build_and_store_chunk_set(
        saved["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    lexical = build_and_store_lexical_index(
        saved["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    run = build_ingestion_run(
        document_id=saved["document_id"],
        job_id=saved["ingestion_job"]["job_id"],
        idempotency_key=saved["upload_id"],
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        created_at=saved["created_at"],
    )
    return config, repository, store, run, extraction, chunk_set, lexical


def test_hydrates_source_extraction_chunks_private_text_and_lexical_index(
    tmp_path: Path,
) -> None:
    config, repository, original, run, extraction, chunk_set, lexical = (
        persisted_runtime(tmp_path)
    )
    restarted = ContentIngestionStore(content_repository=repository)

    evidence = hydrate_ingestion_runtime(run, store=restarted, storage_config=config)

    assert evidence == {
        "hydration_schema_version": "cx_ingestion_hydration.v1",
        "document_id": run["document_id"],
        "upload_id": run["idempotency_key"],
        "job_id": run["job_id"],
        "source_file_hydrated": True,
        "extraction_hydrated": True,
        "chunk_set_hydrated": True,
        "private_chunk_count": chunk_set["chunk_count"],
        "lexical_index_hydrated": True,
        "private_payload_in_evidence": False,
    }
    assert restarted.get_document(run["document_id"])["upload_id"] == run["idempotency_key"]
    assert restarted.get_extraction_result(run["document_id"])[
        "extracted_markdown_sha256"
    ] == extraction["extracted_markdown_sha256"]
    assert restarted.get_chunk_set(run["document_id"])["chunks"] == repository.find_latest_chunk_set(
        content_object_id=run["document_id"]
    )["chunks"]
    assert restarted.get_lexical_index(run["document_id"])["postings"] == lexical["postings"]
    for chunk in chunk_set["chunks"]:
        assert restarted.get_chunk_text(chunk["chunk_id"]) == original.get_chunk_text(
            chunk["chunk_id"]
        )


def test_hydrates_source_only_before_extraction(tmp_path: Path) -> None:
    config = storage_config(tmp_path)
    repository = InMemoryCxContentRepository()
    store = ContentIngestionStore(content_repository=repository)
    saved = store.save_upload_registration(
        build_upload_registration(
            {
                "filename": "pending.md",
                "content_text": "pending source",
                "tenant_id": "tenant-a",
                "owner_user_id": "user-a",
            },
            storage_config=config,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        source_text="pending source",
    )
    run = build_ingestion_run(
        document_id=saved["document_id"],
        job_id=saved["ingestion_job"]["job_id"],
        idempotency_key=saved["upload_id"],
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        created_at=saved["created_at"],
    )

    evidence = hydrate_ingestion_runtime(
        run,
        store=ContentIngestionStore(content_repository=repository),
        storage_config=config,
    )

    assert evidence["source_file_hydrated"] is True
    assert evidence["extraction_hydrated"] is False
    assert evidence["chunk_set_hydrated"] is False
    assert evidence["lexical_index_hydrated"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        (
            lambda run, repository: run.update(
                owner_subject_ref={"type": "oa.user", "id": "user-b"}
            ),
            409,
        ),
        (lambda run, repository: run.update(idempotency_key="other-upload"), 409),
        (lambda run, repository: run.update(job_id="other-job"), 409),
        (
            lambda run, repository: repository.source_files.clear(),
            409,
        ),
        (
            lambda run, repository: run.update(document_id="missing-document"),
            404,
        ),
        (lambda run, repository: run.pop("request_id"), 422),
    ],
)
def test_hydration_rejects_broken_durable_lineage(
    tmp_path: Path,
    mutation,
    expected_status: int,
) -> None:
    config, repository, _, original_run, *_ = persisted_runtime(tmp_path)
    run = deepcopy(original_run)
    mutation(run, repository)

    with pytest.raises(IngestionHydrationError) as exc:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert exc.value.status_code == expected_status
    assert "private" not in exc.value.detail.lower()
    assert str(exc.value) == exc.value.detail


def test_hydration_rejects_missing_tampered_or_unsafe_markdown(tmp_path: Path) -> None:
    config, repository, _, run, extraction, *_ = persisted_runtime(tmp_path)
    artifact = repository.find_latest_extraction_artifact(
        content_object_id=run["document_id"]
    )
    assert artifact is not None

    Path(extraction["extracted_markdown_path"]).unlink()
    with pytest.raises(IngestionHydrationError) as missing:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert missing.value.retryable is True
    assert missing.value.status_code == 503

    Path(extraction["extracted_markdown_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(extraction["extracted_markdown_path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(IngestionHydrationError) as tampered:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert tampered.value.error_code == "cx.ingestion_hydration.lineage_conflict"

    artifact["markdown_storage_uri"] = "local://cx/extracted-markdown/../escape.md"
    with pytest.raises(IngestionHydrationError) as unsafe:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "escapes" in unsafe.value.detail


def test_hydration_rejects_tampered_chunk_offsets_and_hash(tmp_path: Path) -> None:
    config, repository, _, run, *_ = persisted_runtime(tmp_path)
    chunk_set = repository.find_latest_chunk_set(content_object_id=run["document_id"])
    assert chunk_set is not None
    chunk_set["chunks"][0]["end_offset"] = 999999

    with pytest.raises(IngestionHydrationError) as offsets:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "offsets" in offsets.value.detail

    chunk_set["chunks"][0]["end_offset"] = 20
    chunk_set["chunks"][0]["text_sha256"] = "0" * 64
    with pytest.raises(IngestionHydrationError) as digest:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "integrity" in digest.value.detail


def test_hydration_requires_artifact_for_chunks_and_allows_missing_lexical(
    tmp_path: Path,
) -> None:
    config, repository, _, run, *_ = persisted_runtime(tmp_path)
    repository.extraction_artifacts.clear()
    repository.extraction_artifact_ids_by_content_hash.clear()
    with pytest.raises(IngestionHydrationError) as missing_artifact:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "no extraction artifact" in missing_artifact.value.detail

    config, repository, _, run, *_ = persisted_runtime(tmp_path / "no-lexical")
    repository.lexical_indexes.clear()
    evidence = hydrate_ingestion_runtime(
        run,
        store=ContentIngestionStore(content_repository=repository),
        storage_config=replace(
            config,
            bm25_tokenizer="mecab_ko",
            bm25_tokenizer_fallback="korean_mixed_v1",
        ),
    )
    assert evidence["chunk_set_hydrated"] is True
    assert evidence["lexical_index_hydrated"] is False


def test_hydration_uses_fallback_lexical_and_rejects_broken_artifact_links(
    tmp_path: Path,
) -> None:
    config, repository, _, run, *_ = persisted_runtime(tmp_path)
    fallback_config = replace(
        config,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )
    evidence = hydrate_ingestion_runtime(
        run,
        store=ContentIngestionStore(content_repository=repository),
        storage_config=fallback_config,
    )
    assert evidence["lexical_index_hydrated"] is True

    artifact = repository.find_latest_extraction_artifact(
        content_object_id=run["document_id"]
    )
    chunk_set = repository.find_latest_chunk_set(content_object_id=run["document_id"])
    assert artifact is not None and chunk_set is not None
    chunk_set["extraction_artifact_id"] = "other-artifact"
    with pytest.raises(IngestionHydrationError) as broken_chunk:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "does not match" in broken_chunk.value.detail

    chunk_set["extraction_artifact_id"] = artifact["extraction_artifact_id"]
    artifact["markdown_storage_uri"] = "https://example.invalid/private.md"
    with pytest.raises(IngestionHydrationError) as invalid_uri:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "URI is invalid" in invalid_uri.value.detail


def test_hydration_rejects_markdown_symlink_escape(tmp_path: Path) -> None:
    config, repository, _, run, *_ = persisted_runtime(tmp_path)
    artifact = repository.find_latest_extraction_artifact(
        content_object_id=run["document_id"]
    )
    assert artifact is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    link = config.extracted_markdown_root / "linked"
    link.symlink_to(outside, target_is_directory=True)
    artifact["markdown_storage_uri"] = (
        "local://cx/extracted-markdown/linked/private.md"
    )

    with pytest.raises(IngestionHydrationError) as escaped:
        hydrate_ingestion_runtime(
            run,
            store=ContentIngestionStore(content_repository=repository),
            storage_config=config,
        )
    assert "escapes" in escaped.value.detail
