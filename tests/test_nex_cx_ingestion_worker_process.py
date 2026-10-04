from __future__ import annotations

from types import SimpleNamespace

import pytest

from nex_runtime import InMemoryJobQueue, build_common_job, build_subject_ref
from nex_cx.ingestion_coordinator import IngestionStepResult
from nex_cx.ingestion_orchestration import (
    INGESTION_PIPELINE_STEPS,
    build_ingestion_run,
    claim_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
)
from nex_cx.ingestion_worker import CX_INGESTION_JOB_TYPE
from nex_cx.ingestion_worker_process import (
    IngestionWorkerProcess,
    IngestionWorkerProcessError,
    build_default_ingestion_worker_process,
)


NOW = "2026-10-05T02:00:00Z"


def _dependencies():
    queue = InMemoryJobQueue()
    repository = InMemoryIngestionRunRepository()
    queue.enqueue(
        build_common_job(
            job_id="job-1349",
            job_type=CX_INGESTION_JOB_TYPE,
            trace_id="trace-1349",
            request_id="request-1349",
            subject_ref=build_subject_ref("cx.document", "document-1349"),
            idempotency_key="upload-1349",
            created_at=NOW,
        )
    )
    run = repository.create(
        build_ingestion_run(
            document_id="document-1349",
            job_id="job-1349",
            idempotency_key="upload-1349",
            tenant_ref={"type": "oa.tenant", "id": "tenant-1349"},
            owner_subject_ref={"type": "oa.user", "id": "owner-1349"},
            trace_id="trace-1349",
            request_id="request-1349",
            created_at=NOW,
        )
    )
    handlers = {
        step_id: (
            lambda value, selected=step_id: IngestionStepResult(
                output_ref=f"cx.{selected}:{value['document_id']}"
            )
        )
        for step_id in INGESTION_PIPELINE_STEPS
    }
    return queue, repository, run, handlers


def test_process_hydrates_restart_plan_then_claims_durable_work() -> None:
    queue, repository, _, handlers = _dependencies()
    process = IngestionWorkerProcess(
        queue,
        repository,
        handlers,
        profile="test",
        clock=lambda: NOW,
    )

    startup = process.startup()
    repeated = process.startup()
    result = process.run_once()

    assert startup == repeated
    assert startup["restart_action_counts"] == {"READY": 1}
    assert startup["recovered_lease_count"] == 0
    assert result["status"] == "SUCCEEDED"
    assert process.metadata()["work_claiming_enabled"] is True
    process.close()


def test_process_recovers_expired_lease_before_claiming() -> None:
    queue, repository, run, handlers = _dependencies()
    queue.claim_next_job("dead-worker", updated_at=NOW)
    repository.save(
        claim_ingestion_run(
            run,
            worker_id="dead-worker",
            lease_expires_at="2026-10-05T02:00:01Z",
            observed_at=NOW,
        ),
        expected_checkpoint_version=0,
    )
    process = IngestionWorkerProcess(
        queue,
        repository,
        handlers,
        profile="test",
        clock=lambda: "2026-10-05T02:00:02Z",
    )

    startup = process.startup()
    result = process.run_once()

    assert startup["restart_action_counts"] == {"RECOVER_EXPIRED_LEASE": 1}
    assert startup["recovered_lease_count"] == 1
    assert startup["recovered_job_ids"] == ["job-1349"]
    assert result["status"] == "IDLE"


def test_disabled_process_is_idle_and_cleanup_is_idempotent() -> None:
    queue, repository, _, handlers = _dependencies()
    cleaned: list[bool] = []
    process = IngestionWorkerProcess(
        queue,
        repository,
        handlers,
        profile="local_mock",
        work_claiming_enabled=False,
        clock=lambda: NOW,
        cleanup=lambda: cleaned.append(True),
    )

    assert process.run_once()["work_claiming_enabled"] is False
    assert process.metadata()["pool_workload"] is None
    process.close()
    process.close()
    assert cleaned == [True]
    with pytest.raises(IngestionWorkerProcessError, match="already closed"):
        process.startup()


class _Engine:
    def __init__(self) -> None:
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1


@pytest.mark.parametrize(
    ("profile", "composition_present", "enabled"),
    [("local_mock", False, False), ("test", True, True)],
)
def test_default_process_builder_uses_main_runtime(
    monkeypatch,
    profile,
    composition_present,
    enabled,
) -> None:
    queue, repository, _, handlers = _dependencies()
    worker_engine = _Engine()
    api_engine = _Engine()
    fake_main = SimpleNamespace(
        CX_MVP_RUNTIME=(
            SimpleNamespace(ingestion_step_handlers=handlers)
            if composition_present
            else None
        ),
        SERVICE_PERSISTENCE=SimpleNamespace(
            job_queue=queue,
            worker_engine=worker_engine,
            api_engine=api_engine,
        ),
        CX_INGESTION_RUN_REPOSITORY=repository,
    )
    monkeypatch.setitem(__import__("sys").modules, "nex_cx.main", fake_main)

    process = build_default_ingestion_worker_process(profile)

    assert process.work_claiming_enabled is enabled
    process.close()
    assert worker_engine.dispose_count == 1
    assert api_engine.dispose_count == 1


def test_default_process_builder_rejects_profile_and_missing_runtime(monkeypatch) -> None:
    with pytest.raises(IngestionWorkerProcessError, match="profile"):
        build_default_ingestion_worker_process("production")

    fake_main = SimpleNamespace(CX_MVP_RUNTIME=None)
    monkeypatch.setitem(__import__("sys").modules, "nex_cx.main", fake_main)
    with pytest.raises(IngestionWorkerProcessError, match="runtime is unavailable"):
        build_default_ingestion_worker_process("test")


def test_process_default_clock_and_builder_cleanup_deduplicate_engines(
    monkeypatch,
) -> None:
    process = IngestionWorkerProcess(
        InMemoryJobQueue(),
        InMemoryIngestionRunRepository(),
        {},
        profile="local_mock",
        work_claiming_enabled=False,
    )
    assert process.startup()["observed_at"].endswith("Z")

    engine = _Engine()
    fake_main = SimpleNamespace(
        CX_MVP_RUNTIME=None,
        SERVICE_PERSISTENCE=SimpleNamespace(
            job_queue=InMemoryJobQueue(),
            worker_engine=engine,
            api_engine=engine,
        ),
        CX_INGESTION_RUN_REPOSITORY=InMemoryIngestionRunRepository(),
    )
    monkeypatch.setitem(__import__("sys").modules, "nex_cx.main", fake_main)
    built = build_default_ingestion_worker_process("local_mock")
    built.close()
    assert engine.dispose_count == 1
