from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ae_api.async_artifact_rendering import (
    AE_ASYNC_ARTIFACT_RENDER_ADMISSION_SCHEMA_VERSION,
    ASYNC_ARTIFACT_RENDER_JOB_TYPE,
    AeAsyncArtifactRenderError,
    admit_async_artifact_render,
    build_async_artifact_render_queue_job,
    build_async_artifact_render_request,
    cancel_async_artifact_render,
    get_async_artifact_render_projection,
    validate_async_artifact_render_admission,
    validate_async_artifact_render_queue_job,
)
from nex_ae_api.artifacts import ArtifactHandoffError, ArtifactRecordStore
from nex_runtime import InMemoryJobQueue, JobQueueError


NOW = "2026-09-29T01:00:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _artifact() -> dict:
    return {
        "artifact_id": "artifact-1",
        "artifact_status": "DRAFT",
        "interaction_id": "interaction-1",
        "owner_actor_ref": {"tenant_id": "tenant-1", "actor_id": "owner-1"},
        "workspace_ref": {"workspace_id": "workspace-1"},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": DIGEST_A,
                "citation_claims_hash": DIGEST_B,
            }
        ],
        "render_jobs": [],
        "updated_at": NOW,
    }


def _request() -> dict:
    return build_async_artifact_render_request(
        artifact_record=_artifact(),
        render_request_id="render-request-1",
        target_formats=["MD", "PDF"],
        request_id="request-1",
        trace_id="trace-1",
        response_id="response-1",
        requested_at=NOW,
    )


def _store() -> ArtifactRecordStore:
    store = ArtifactRecordStore()
    store.create(_artifact())
    return store


def test_build_queue_job_is_durable_content_free_and_bound() -> None:
    request = _request()
    result = build_async_artifact_render_queue_job(request)

    assert result["job_id"] == request["render_job_id"]
    assert result["job_type"] == ASYNC_ARTIFACT_RENDER_JOB_TYPE
    assert result["subject_ref"] == {"type": "artifact", "id": "artifact-1"}
    assert result["idempotency_key"] == request["render_job_id"]
    assert result["payload"] == {"render_request": request}
    assert not {
        "content",
        "raw_text",
        "rendered_payloads",
        "storage_ref",
    }.intersection(result["payload"]["render_request"])


def test_admission_persists_render_and_queue_jobs() -> None:
    store = _store()
    queue = InMemoryJobQueue()

    result = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )

    assert result["render_admission_schema_version"] == (
        AE_ASYNC_ARTIFACT_RENDER_ADMISSION_SCHEMA_VERSION
    )
    assert result["admission_status"] == "ENQUEUED"
    assert result["render"]["lifecycle_status"] == "PENDING"
    assert store.get("artifact-1")["artifact_status"] == "RENDERING"
    assert len(store.get("artifact-1")["render_jobs"]) == 1
    assert queue.get_job(_request()["render_job_id"])["status"] == "QUEUED"


def test_admission_replay_joins_without_duplicate_render_job() -> None:
    store = _store()
    queue = InMemoryJobQueue()
    first = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    second = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )

    assert first["admission_status"] == "ENQUEUED"
    assert second["admission_status"] == "JOINED"
    assert len(store.get("artifact-1")["render_jobs"]) == 1
    assert len(queue.jobs) == 1


class FailingOnceQueue(InMemoryJobQueue):
    failed = False

    def enqueue(self, job: dict) -> dict:
        if not self.failed:
            self.failed = True
            raise JobQueueError("job.store_unavailable", "down", status_code=503)
        return super().enqueue(job)


def test_admission_recovers_render_job_after_queue_failure() -> None:
    store = _store()
    queue = FailingOnceQueue()

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        admit_async_artifact_render(
            request=_request(), artifact_store=store, job_queue=queue
        )
    assert exc_info.value.error_code.endswith("queue_unavailable")
    assert exc_info.value.retryable is True
    assert len(store.get("artifact-1")["render_jobs"]) == 1

    recovered = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    assert recovered["admission_status"] == "RECOVERED"
    assert len(store.get("artifact-1")["render_jobs"]) == 1


def test_admission_joins_preexisting_queue_and_restores_render_job() -> None:
    store = _store()
    queue = InMemoryJobQueue()
    queue.enqueue(build_async_artifact_render_queue_job(_request()))

    result = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )

    assert result["admission_status"] == "JOINED"
    assert store.get_render_job(_request()["render_job_id"]) is not None


def test_projection_read_and_cancel_are_idempotent() -> None:
    store = _store()
    queue = InMemoryJobQueue()
    admitted = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    job_id = admitted["render"]["render_job_id"]

    pending = get_async_artifact_render_projection(
        render_job_id=job_id, artifact_store=store, job_queue=queue
    )
    cancelled = cancel_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
        cancelled_at="2026-09-29T02:00:00Z",
    )
    repeated = cancel_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
        cancelled_at="2026-09-29T02:01:00Z",
    )

    assert pending["lifecycle_status"] == "PENDING"
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert repeated == cancelled
    assert store.get_render_job(job_id)["completed_at"] == "2026-09-29T02:00:00Z"


def test_running_render_can_be_cancelled() -> None:
    store = _store()
    queue = InMemoryJobQueue()
    admitted = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    job_id = admitted["render"]["render_job_id"]
    queue.start_job(job_id, updated_at="2026-09-29T01:30:00Z")
    render_job = store.get_render_job(job_id)
    store.save_render_job_state(
        {
            **render_job,
            "job_status": "RUNNING",
            "current_stage": "MARKDOWN_RENDERING",
            "progress_percent": 20,
            "started_at": "2026-09-29T01:30:00Z",
            "updated_at": "2026-09-29T01:30:00Z",
        }
    )

    result = cancel_async_artifact_render(
        render_job_id=job_id, artifact_store=store, job_queue=queue
    )
    assert result["queue_job_status"] == "CANCELLED"
    assert result["render_job_status"] == "CANCELLED"


@pytest.mark.parametrize("terminal_status", ["SUCCEEDED", "FAILED"])
def test_terminal_queue_job_cannot_be_cancelled(terminal_status: str) -> None:
    store = _store()
    queue = InMemoryJobQueue()
    admitted = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    job_id = admitted["render"]["render_job_id"]
    queue.start_job(job_id)
    if terminal_status == "SUCCEEDED":
        queue.complete_job(job_id)
    else:
        queue.fail_job(job_id)

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        cancel_async_artifact_render(
            render_job_id=job_id, artifact_store=store, job_queue=queue
        )
    assert exc_info.value.status_code == 409


def test_projection_and_cancel_report_missing_durable_state() -> None:
    store = _store()
    queue = InMemoryJobQueue()
    with pytest.raises(AeAsyncArtifactRenderError) as missing:
        get_async_artifact_render_projection(
            render_job_id="missing", artifact_store=store, job_queue=queue
        )
    assert missing.value.status_code == 404
    with pytest.raises(AeAsyncArtifactRenderError) as cancel_missing:
        cancel_async_artifact_render(
            render_job_id="missing", artifact_store=store, job_queue=queue
        )
    assert cancel_missing.value.status_code == 404

    admitted = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )
    job_id = admitted["render"]["render_job_id"]
    queue.jobs.pop(job_id)
    with pytest.raises(AeAsyncArtifactRenderError) as queue_missing:
        get_async_artifact_render_projection(
            render_job_id=job_id, artifact_store=store, job_queue=queue
        )
    assert queue_missing.value.retryable is True
    with pytest.raises(AeAsyncArtifactRenderError) as cancel_queue_missing:
        cancel_async_artifact_render(
            render_job_id=job_id, artifact_store=store, job_queue=queue
        )
    assert cancel_queue_missing.value.retryable is True


def test_queue_replay_allows_new_trace_and_time_but_not_identity_drift() -> None:
    stored_request = _request()
    job = build_async_artifact_render_queue_job(stored_request)
    replay = {
        **stored_request,
        "request_id": "request-2",
        "trace_id": "trace-2",
        "requested_at": "2026-09-29T03:00:00Z",
    }

    assert validate_async_artifact_render_queue_job(job, replay)["job_id"] == (
        stored_request["render_job_id"]
    )
    drifted = {**replay, "target_formats": ["MD"]}
    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_queue_job(job, drifted)


class FailingCancelQueue(InMemoryJobQueue):
    def cancel_job(self, job_id: str, *, updated_at: str | None = None) -> dict:
        raise JobQueueError("job.store_unavailable", "down", status_code=503)


def test_cancel_wraps_queue_failure() -> None:
    store = _store()
    queue = FailingCancelQueue()
    admitted = admit_async_artifact_render(
        request=_request(), artifact_store=store, job_queue=queue
    )

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        cancel_async_artifact_render(
            render_job_id=admitted["render"]["render_job_id"],
            artifact_store=store,
            job_queue=queue,
        )
    assert exc_info.value.error_code.endswith("cancel_failed")
    assert exc_info.value.retryable is True


def test_admission_rejects_missing_or_changed_artifact() -> None:
    request = _request()
    with pytest.raises(AeAsyncArtifactRenderError) as missing:
        admit_async_artifact_render(
            request=request,
            artifact_store=ArtifactRecordStore(),
            job_queue=InMemoryJobQueue(),
        )
    assert missing.value.status_code == 404

    store = _store()
    store.records["artifact-1"]["owner_actor_ref"]["actor_id"] = "other"
    with pytest.raises(AeAsyncArtifactRenderError):
        admit_async_artifact_render(
            request=request, artifact_store=store, job_queue=InMemoryJobQueue()
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(job_type="other"),
        lambda value: value.update(payload={}),
        lambda value: value["payload"].update(render_request={}),
        lambda value: value["payload"]["render_request"].update(trace_id="other"),
        lambda value: value.update(job_id="other"),
        lambda value: value.update(idempotency_key="other"),
        lambda value: value.update(subject_ref={"type": "artifact", "id": "other"}),
        lambda value: value.update(request_id="other"),
        lambda value: value.update(max_attempts=2),
        lambda value: value.update(links={}),
    ],
)
def test_validate_queue_job_rejects_contract_drift(mutation) -> None:
    request = _request()
    job = build_async_artifact_render_queue_job(request)
    mutation(job)

    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_queue_job(job, request)


def test_validate_queue_job_wraps_common_job_errors() -> None:
    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_queue_job([])
    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_queue_job({"job_type": ASYNC_ARTIFACT_RENDER_JOB_TYPE})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("render"),
        lambda value: value.update(render_admission_schema_version="v2"),
        lambda value: value.update(admission_status="UNKNOWN"),
        lambda value: value.update(render={}),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(content_included=True),
    ],
)
def test_validate_admission_rejects_invalid_shape(mutation) -> None:
    result = admit_async_artifact_render(
        request=_request(), artifact_store=_store(), job_queue=InMemoryJobQueue()
    )
    mutation(result)

    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_admission(result)


def test_memory_store_initial_render_is_idempotent_and_missing_safe() -> None:
    store = _store()
    request = _request()
    from nex_ae_api.async_artifact_rendering import build_initial_render_job

    render_job = build_initial_render_job(request)
    first = store.save_initial_render_job(render_job)
    second = store.save_initial_render_job(deepcopy(render_job))
    assert first == second
    assert len(store.records["artifact-1"]["render_jobs"]) == 1

    render_job["artifact_id"] = "missing"
    render_job["render_job_id"] = "missing-job"
    with pytest.raises(ArtifactHandoffError) as exc_info:
        store.save_initial_render_job(render_job)
    assert exc_info.value.status_code == 404

    with pytest.raises(ArtifactHandoffError):
        store.save_render_job_state(render_job)
