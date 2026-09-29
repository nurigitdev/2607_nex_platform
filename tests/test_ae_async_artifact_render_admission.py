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
