from __future__ import annotations

from dataclasses import dataclass

import pytest

from nex_cx.ingestion_coordinator import (
    IngestionCheckpointExecutionError,
    IngestionStepResult,
    _existing_or_execute,
    _metadata_output_ref,
    build_default_ingestion_step_handlers,
    execute_all_ingestion_checkpoints,
    execute_ingestion_checkpoint,
)
from nex_cx.ingestion_orchestration import (
    INGESTION_PIPELINE_STEPS,
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepositoryError,
)


NOW = "2026-09-21T00:00:00Z"
LATER = "2026-09-21T00:02:00Z"


def claimed_run():
    repository = InMemoryIngestionRunRepository()
    run = repository.create(
        build_ingestion_run(
            document_id="document-1",
            job_id="job-1",
            idempotency_key="upload-1",
            tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
            owner_subject_ref={"type": "oa.user", "id": "user-a"},
            trace_id="trace-1",
            request_id="request-1",
            created_at=NOW,
        )
    )
    claimed = claim_ingestion_run(
        run,
        worker_id="worker-1",
        lease_expires_at=LATER,
        observed_at=NOW,
    )
    return repository, repository.save(claimed, expected_checkpoint_version=0)


def handlers(*, skipped_step: str | None = None):
    return {
        step_id: (
            lambda run, selected=step_id: IngestionStepResult(
                output_ref=f"cx.{selected}:{run['document_id']}",
                skipped=selected == skipped_step,
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }


def test_execute_checkpoint_persists_exactly_one_step() -> None:
    repository, run = claimed_run()
    saved = execute_ingestion_checkpoint(
        run,
        run_repository=repository,
        worker_id="worker-1",
        step_handlers=handlers(),
        observed_at=LATER,
    )
    assert saved["checkpoint_version"] == 2
    assert saved["step_states"]["extraction"]["status"] == "SUCCEEDED"
    assert saved["current_step"] == "chunking"
    assert repository.get(
        saved["run_id"], tenant_id="tenant-a", owner_subject_id="user-a"
    ) == saved


def test_execute_all_checkpoints_completes_and_marks_skip() -> None:
    repository, run = claimed_run()
    saved = execute_all_ingestion_checkpoints(
        run,
        run_repository=repository,
        worker_id="worker-1",
        step_handlers=handlers(skipped_step="summary"),
        observed_at=LATER,
    )
    assert saved["status"] == "SUCCEEDED"
    assert saved["checkpoint_version"] == 7
    assert saved["step_states"]["summary"]["status"] == "SKIPPED"
    assert saved["lease_owner"] is None


def test_inactive_run_and_missing_handler_fail_closed() -> None:
    repository, run = claimed_run()
    queued = build_ingestion_run(
        document_id="document-2",
        job_id="job-2",
        idempotency_key="upload-2",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id="trace-2",
        request_id="request-2",
        created_at=NOW,
    )
    with pytest.raises(IngestionCheckpointExecutionError) as inactive:
        execute_ingestion_checkpoint(
            queued,
            run_repository=repository,
            worker_id="worker-1",
            step_handlers=handlers(),
        )
    assert inactive.value.error_code == "cx.ingestion_checkpoint.run_not_active"

    with pytest.raises(IngestionCheckpointExecutionError) as missing:
        execute_ingestion_checkpoint(
            run,
            run_repository=repository,
            worker_id="worker-1",
            step_handlers={},
        )
    assert missing.value.error_code == "cx.ingestion_checkpoint.handler_missing"


@dataclass(frozen=True)
class RetryableStepError(Exception):
    error_code: str = "provider.timeout"
    detail: str = "provider timeout"
    retryable: bool = True
    status_code: int = 503


def test_step_and_invalid_result_errors_are_metadata_only() -> None:
    repository, run = claimed_run()

    def fail(_run):
        raise RetryableStepError()

    with pytest.raises(IngestionCheckpointExecutionError) as failed:
        execute_ingestion_checkpoint(
            run,
            run_repository=repository,
            worker_id="worker-1",
            step_handlers={"extraction": fail},
        )
    assert failed.value.error_code == "provider.timeout"
    assert failed.value.retryable is True
    assert failed.value.failed_step == "extraction"
    assert str(failed.value) == "provider timeout"

    with pytest.raises(IngestionCheckpointExecutionError) as invalid:
        execute_ingestion_checkpoint(
            run,
            run_repository=repository,
            worker_id="worker-1",
            step_handlers={"extraction": lambda _: {}},
        )
    assert invalid.value.error_code == "cx.ingestion_checkpoint.step_failed"


def test_checkpoint_error_from_handler_is_preserved() -> None:
    repository, run = claimed_run()
    expected = IngestionCheckpointExecutionError(
        error_code="cx.ingestion_checkpoint.already_normalized",
        detail="already normalized",
        retryable=False,
        failed_step="extraction",
        status_code=409,
    )

    def fail(_run):
        raise expected

    with pytest.raises(IngestionCheckpointExecutionError) as failed:
        execute_ingestion_checkpoint(
            run,
            run_repository=repository,
            worker_id="worker-1",
            step_handlers={"extraction": fail},
        )
    assert failed.value is expected


class FailingSaveRepository(InMemoryIngestionRunRepository):
    def save(self, run, *, expected_checkpoint_version):
        raise IngestionRunRepositoryError("repository.failed", "offline", 503)


def test_repository_failure_maps_to_checkpoint_error() -> None:
    _, run = claimed_run()
    with pytest.raises(IngestionCheckpointExecutionError) as failed:
        execute_ingestion_checkpoint(
            run,
            run_repository=FailingSaveRepository(),
            worker_id="worker-1",
            step_handlers=handlers(),
        )
    assert failed.value.error_code == "repository.failed"
    assert failed.value.retryable is True


@pytest.mark.parametrize(
    ("step_id", "output", "expected"),
    [
        ("extraction", {"document_id": "doc-1"}, "cx.extraction:doc-1"),
        ("summary", {"document_summary_id": "sum-1"}, "cx.document_summary:sum-1"),
        (
            "summary_embedding",
            {"document_summary_id": "sum-1"},
            "cx.document_summary_embedding:sum-1",
        ),
    ],
)
def test_metadata_output_refs(step_id: str, output: dict, expected: str) -> None:
    assert _metadata_output_ref(step_id, "doc-1", output) == expected


def test_existing_output_is_skipped_without_execution() -> None:
    result = _existing_or_execute(
        step_id="chunking",
        document_id="doc-1",
        existing={"document_id": "doc-1"},
        execute=lambda: pytest.fail("execute should not run"),
    )
    assert result.skipped is True
    assert result.output_ref == "cx.chunking:doc-1"


class MaterializedStore:
    def get_extraction_result(self, document_id):
        return {"document_id": document_id}

    def get_chunk_set(self, document_id):
        return {"document_id": document_id}

    def get_lexical_index(self, document_id):
        return {"document_id": document_id}

    def get_embedding_index(self, document_id):
        return {"document_id": document_id}

    def get_document_summary(self, _document_id):
        return {"document_summary_id": "summary-1"}

    def get_summary_embedding_index(self, _document_id):
        return {"document_summary_id": "summary-1"}


def test_default_handlers_reuse_all_materialized_outputs() -> None:
    default_handlers = build_default_ingestion_step_handlers(
        store=MaterializedStore(),
        storage_config=object(),
        mo_client=object(),
        embedding_alias="embedding-main",
    )
    run = {
        "document_id": "doc-1",
        "job_id": "job-1",
        "request_id": "request-1",
        "trace_id": "trace-1",
    }
    results = {step_id: handler(run) for step_id, handler in default_handlers.items()}
    assert tuple(results) == INGESTION_PIPELINE_STEPS
    assert all(result.skipped for result in results.values())
    assert results["summary"].output_ref == "cx.document_summary:summary-1"
    assert results["summary_embedding"].output_ref == (
        "cx.document_summary_embedding:summary-1"
    )


def test_execute_all_returns_an_inactive_run_without_dispatch() -> None:
    repository = InMemoryIngestionRunRepository()
    queued = build_ingestion_run(
        document_id="document-2",
        job_id="job-2",
        idempotency_key="upload-2",
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "user-a"},
        trace_id="trace-2",
        request_id="request-2",
        created_at=NOW,
    )
    assert execute_all_ingestion_checkpoints(
        queued,
        run_repository=repository,
        worker_id="worker-1",
        step_handlers={},
    ) == queued


def test_missing_output_identity_and_empty_result_ref_are_rejected() -> None:
    with pytest.raises(ValueError):
        _metadata_output_ref("summary", "doc-1", {})
    with pytest.raises(ValueError):
        IngestionStepResult(" ")
