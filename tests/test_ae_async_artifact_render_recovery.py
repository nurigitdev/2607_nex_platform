from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.artifacts import ArtifactRecordStore, register_artifact_handoff_routes
from nex_ae_api.async_artifact_render_recovery import (
    AE_ASYNC_ARTIFACT_RENDER_RECONCILIATION_SCHEMA_VERSION,
    AE_ASYNC_ARTIFACT_RENDER_RECOVERY_SCHEMA_VERSION,
    MANUAL_REVIEW,
    MARK_RENDER_CANCELLED,
    MARK_RENDER_FAILED,
    MARK_RENDER_RUNNING,
    NO_ACTION,
    REPEAT_ADMISSION,
    RESET_RENDER_TO_QUEUED,
    WAIT_FOR_RETRY,
    WAIT_FOR_WORKER,
    _apply_recovery_action,
    build_async_artifact_render_recovery_plan,
    inspect_async_artifact_render_recovery,
    reconcile_async_artifact_render,
)
from nex_ae_api.async_artifact_rendering import (
    AeAsyncArtifactRenderError,
    admit_async_artifact_render,
    build_async_artifact_render_request,
)
from nex_runtime import (
    InMemoryJobQueue,
    JobQueueError,
    SERVICE_SPECS,
    build_job_error,
    build_service_app,
    issue_mock_user_token,
)


NOW = "2026-09-29T06:00:00Z"
LATER = "2026-09-29T06:01:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _artifact() -> dict:
    return {
        "artifact_id": "artifact-1",
        "artifact_status": "DRAFT",
        "chat_document_id": "chat-document-1",
        "interaction_id": "interaction-1",
        "display_title": "Grounded report",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "owner-1",
            "tenant_id": "tenant-1",
        },
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "target_formats": ["MD"],
        "template_ref": {"template_id": "template-1", "template_version": "1"},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": DIGEST_A,
                "citation_claims_hash": DIGEST_B,
                "quality_summary": {"citation_status": "VALIDATED"},
            }
        ],
        "versions": [],
        "render_jobs": [],
        "files": [],
        "links": [],
        "updated_at": NOW,
    }


def _admitted(
    *, max_attempts: int = 3
) -> tuple[ArtifactRecordStore, InMemoryJobQueue, str]:
    store = ArtifactRecordStore()
    store.create(_artifact())
    queue = InMemoryJobQueue()
    request = build_async_artifact_render_request(
        artifact_record=_artifact(),
        render_request_id="render-request-1",
        target_formats=["MD"],
        request_id="request-1",
        trace_id="trace-1",
        max_attempts=max_attempts,
        requested_at=NOW,
    )
    admit_async_artifact_render(
        request=request,
        artifact_store=store,
        job_queue=queue,
    )
    return store, queue, request["render_job_id"]


def _set_render_running(store: ArtifactRecordStore, job_id: str) -> None:
    render = store.get_render_job(job_id)
    store.save_render_job_state(
        {
            **render,
            "job_status": "RUNNING",
            "current_stage": "HANDOFF_VALIDATING",
            "progress_percent": 10,
            "started_at": NOW,
            "updated_at": NOW,
        }
    )


def _error() -> dict:
    return build_job_error(
        error_code="ae.render_dependency_unavailable",
        detail="private dependency detail",
        retryable=True,
    )


def test_recovery_plan_projects_healthy_queued_state_without_content() -> None:
    store, queue, job_id = _admitted()

    result = inspect_async_artifact_render_recovery(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
    )

    assert result["recovery_schema_version"] == (
        AE_ASYNC_ARTIFACT_RENDER_RECOVERY_SCHEMA_VERSION
    )
    assert result["action"] == WAIT_FOR_WORKER
    assert result["recovery_status"] == "HEALTHY"
    assert result["attempts_remaining"] == 3
    assert result["owner_scope_enforced"] is True
    assert result["content_included"] is False
    assert "private dependency detail" not in str(result)


def test_recovery_plan_reports_bounded_retry_metadata() -> None:
    store, queue, job_id = _admitted()
    queue.start_job(job_id, updated_at=NOW)
    _set_render_running(store, job_id)
    queue.retry_job(job_id, error=_error(), failed_at=NOW)
    render = store.get_render_job(job_id)
    store.save_render_job_state(
        {
            **render,
            "job_status": "QUEUED",
            "current_stage": "QUEUED",
            "progress_percent": 0,
            "updated_at": NOW,
        }
    )

    result = inspect_async_artifact_render_recovery(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
    )

    assert result["action"] == WAIT_FOR_RETRY
    assert result["recovery_status"] == "RETRY_SCHEDULED"
    assert result["attempt_count"] == 1
    assert result["attempts_remaining"] == 2
    assert result["next_retry_at"] == "2026-09-29T06:00:30Z"
    assert result["failure_code"] == "ae.render_dependency_unavailable"
    assert result["dead_lettered"] is False


@pytest.mark.parametrize(
    ("queue_status", "render_status", "expected_action", "expected_status"),
    [
        ("RUNNING", "RUNNING", WAIT_FOR_WORKER, "HEALTHY"),
        ("SUCCEEDED", "COMPLETED", NO_ACTION, "TERMINAL"),
        ("CANCELLED", "CANCELLED", NO_ACTION, "TERMINAL"),
        ("FAILED", "FAILED", MANUAL_REVIEW, "BLOCKED"),
        ("QUEUED", "RUNNING", RESET_RENDER_TO_QUEUED, "RECOVERY_REQUIRED"),
        ("QUEUED", "FAILED", RESET_RENDER_TO_QUEUED, "RECOVERY_REQUIRED"),
        ("RUNNING", "QUEUED", MARK_RENDER_RUNNING, "RECOVERY_REQUIRED"),
        ("CANCELLED", "QUEUED", MARK_RENDER_CANCELLED, "RECOVERY_REQUIRED"),
        ("CANCELLED", "RUNNING", MARK_RENDER_CANCELLED, "RECOVERY_REQUIRED"),
        ("FAILED", "QUEUED", MARK_RENDER_FAILED, "RECOVERY_REQUIRED"),
        ("FAILED", "RUNNING", MARK_RENDER_FAILED, "RECOVERY_REQUIRED"),
        ("SUCCEEDED", "QUEUED", MANUAL_REVIEW, "BLOCKED"),
    ],
)
def test_recovery_plan_decision_matrix(
    queue_status: str,
    render_status: str,
    expected_action: str,
    expected_status: str,
) -> None:
    render = {
        "render_job_id": "render-1",
        "artifact_id": "artifact-1",
        "job_status": render_status,
    }
    queue = {
        "job_id": "render-1",
        "job_type": "ae.artifact.render",
        "subject_ref": {"type": "artifact", "id": "artifact-1"},
        "status": queue_status,
        "attempt_count": 1,
        "max_attempts": 3,
        "error": (
            {
                "error_code": "ae.render_failed",
                "retryable": False,
                "dead_lettered": True,
            }
            if queue_status == "FAILED"
            else None
        ),
        "available_at": NOW,
    }

    result = build_async_artifact_render_recovery_plan(
        render_job_id="render-1",
        render_job=render,
        queue_job=queue,
    )

    assert result["action"] == expected_action
    assert result["recovery_status"] == expected_status
    assert result["mutation_required"] is (expected_action in {
        RESET_RENDER_TO_QUEUED,
        MARK_RENDER_RUNNING,
        MARK_RENDER_CANCELLED,
        MARK_RENDER_FAILED,
    })


def test_recovery_plan_distinguishes_missing_queue_and_render_state() -> None:
    render = {
        "render_job_id": "render-1",
        "artifact_id": "artifact-1",
        "job_status": "QUEUED",
    }
    queue = {
        "job_id": "render-1",
        "job_type": "ae.artifact.render",
        "subject_ref": {"type": "artifact", "id": "artifact-1"},
        "status": "QUEUED",
        "attempt_count": 0,
        "max_attempts": 3,
    }

    repeat = build_async_artifact_render_recovery_plan(
        render_job_id="render-1", render_job=render, queue_job=None
    )
    review = build_async_artifact_render_recovery_plan(
        render_job_id="render-1", render_job=None, queue_job=queue
    )

    assert repeat["action"] == REPEAT_ADMISSION
    assert repeat["attempt_count"] == 0
    assert repeat["max_attempts"] == 0
    assert review["action"] == MANUAL_REVIEW
    assert review["artifact_id"] == "artifact-1"


def test_reconcile_resets_retry_drift_idempotently() -> None:
    store, queue, job_id = _admitted()
    queue.start_job(job_id, updated_at=NOW)
    _set_render_running(store, job_id)
    queue.retry_job(job_id, error=_error(), failed_at=NOW)

    result = reconcile_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
        observed_at=LATER,
    )
    repeated = reconcile_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
        observed_at=LATER,
    )

    assert result["reconciliation_schema_version"] == (
        AE_ASYNC_ARTIFACT_RENDER_RECONCILIATION_SCHEMA_VERSION
    )
    assert result["result"] == "RECONCILED"
    assert result["applied_action"] == RESET_RENDER_TO_QUEUED
    assert result["after"]["action"] == WAIT_FOR_RETRY
    assert repeated["result"] == "NO_ACTION"
    assert repeated["applied_action"] is None
    assert store.get_render_job(job_id)["progress_percent"] == 0


def test_reconcile_marks_claimed_cancelled_and_failed_states() -> None:
    running_store, running_queue, running_id = _admitted()
    running_queue.start_job(running_id, updated_at=NOW)
    running = reconcile_async_artifact_render(
        render_job_id=running_id,
        artifact_store=running_store,
        job_queue=running_queue,
        observed_at=LATER,
    )
    assert running["applied_action"] == MARK_RENDER_RUNNING
    assert running_store.get_render_job(running_id)["started_at"] == LATER

    cancel_store, cancel_queue, cancel_id = _admitted()
    cancel_queue.cancel_job(cancel_id, updated_at=NOW)
    cancelled = reconcile_async_artifact_render(
        render_job_id=cancel_id,
        artifact_store=cancel_store,
        job_queue=cancel_queue,
        observed_at=LATER,
    )
    assert cancelled["applied_action"] == MARK_RENDER_CANCELLED
    assert cancel_store.get_render_job(cancel_id)["completed_at"] == LATER

    failed_store, failed_queue, failed_id = _admitted(max_attempts=1)
    failed_queue.start_job(failed_id, updated_at=NOW)
    failed_queue.dead_letter_job(failed_id, error=_error(), failed_at=NOW)
    failed = reconcile_async_artifact_render(
        render_job_id=failed_id,
        artifact_store=failed_store,
        job_queue=failed_queue,
        observed_at=LATER,
    )
    assert failed["applied_action"] == MARK_RENDER_FAILED
    assert failed_store.get_render_job(failed_id)["failure_code"] == (
        "ae.render_dependency_unavailable"
    )
    assert failed_store.get("artifact-1")["artifact_status"] == "FAILED"


def test_reconcile_never_mutates_manual_or_readmission_state() -> None:
    store, queue, job_id = _admitted()
    queue.start_job(job_id, updated_at=NOW)
    queue.complete_job(job_id, updated_at=NOW)
    manual = reconcile_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=queue,
    )
    assert manual["result"] == "MANUAL_REVIEW_REQUIRED"
    assert store.get_render_job(job_id)["job_status"] == "QUEUED"

    missing_queue = InMemoryJobQueue()
    readmission = reconcile_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=missing_queue,
    )
    assert readmission["result"] == "READMISSION_REQUIRED"


def test_reconcile_handles_concurrent_settlement_and_second_read_failure() -> None:
    store, queue, job_id = _admitted()

    class ConcurrentlySettledQueue(InMemoryJobQueue):
        reads = 0

        def get_job(self, requested_job_id: str) -> dict | None:
            self.reads += 1
            job = super().get_job(requested_job_id)
            if self.reads == 1 and job is not None:
                return {**job, "status": "RUNNING", "attempt_count": 1}
            return job

    settled_queue = ConcurrentlySettledQueue(
        jobs=deepcopy(queue.jobs),
        idempotency_index=deepcopy(queue.idempotency_index),
    )
    settled = reconcile_async_artifact_render(
        render_job_id=job_id,
        artifact_store=store,
        job_queue=settled_queue,
        observed_at=LATER,
    )
    assert settled["result"] == "ALREADY_SETTLED"
    assert settled["after"]["action"] == WAIT_FOR_WORKER

    class SecondReadBrokenQueue(ConcurrentlySettledQueue):
        def get_job(self, requested_job_id: str) -> dict | None:
            job = super().get_job(requested_job_id)
            if self.reads == 2:
                raise JobQueueError("job.store_unavailable", "offline", 503)
            return job

    broken_queue = SecondReadBrokenQueue(
        jobs=deepcopy(queue.jobs),
        idempotency_index=deepcopy(queue.idempotency_index),
    )
    with pytest.raises(AeAsyncArtifactRenderError) as unavailable:
        reconcile_async_artifact_render(
            render_job_id=job_id,
            artifact_store=store,
            job_queue=broken_queue,
        )
    assert unavailable.value.retryable is True


def test_recovery_action_guards_incomplete_unknown_and_missing_artifact_state() -> None:
    queue_job = {
        "error": {
            "error_code": "ae.render_failed",
            "retryable": False,
            "dead_lettered": True,
        }
    }
    with pytest.raises(AeAsyncArtifactRenderError):
        _apply_recovery_action(
            action=MARK_RENDER_FAILED,
            render_job=None,
            queue_job=queue_job,
            artifact_store=ArtifactRecordStore(),
            observed_at=NOW,
        )
    with pytest.raises(AeAsyncArtifactRenderError):
        _apply_recovery_action(
            action="UNKNOWN",
            render_job={"artifact_id": "missing"},
            queue_job=queue_job,
            artifact_store=ArtifactRecordStore(),
            observed_at=NOW,
        )

    class OrphanedArtifactStore:
        saved_render: dict | None = None

        def save_render_job_state(self, render_job: dict) -> dict:
            self.saved_render = deepcopy(render_job)
            return render_job

        def get(self, artifact_id: str) -> None:
            return None

        def save(self, record: dict) -> dict:
            raise AssertionError("missing artifact must not be synthesized")

    orphaned_store = OrphanedArtifactStore()
    _apply_recovery_action(
        action=MARK_RENDER_FAILED,
        render_job={
            "render_job_id": "render-1",
            "artifact_id": "missing-artifact",
            "job_status": "RUNNING",
        },
        queue_job=queue_job,
        artifact_store=orphaned_store,  # type: ignore[arg-type]
        observed_at=NOW,
    )
    assert orphaned_store.saved_render["job_status"] == "FAILED"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda render, queue: render.update(render_job_id="other"),
        lambda render, queue: render.update(job_status="UNKNOWN"),
        lambda render, queue: queue.update(job_id="other"),
        lambda render, queue: queue.update(job_type="other"),
        lambda render, queue: queue.update(status="UNKNOWN"),
        lambda render, queue: queue.update(attempt_count=True),
        lambda render, queue: queue.update(attempt_count=4),
        lambda render, queue: queue.update(available_at=" "),
    ],
)
def test_recovery_plan_rejects_invalid_state(mutation) -> None:
    render = {
        "render_job_id": "render-1",
        "artifact_id": "artifact-1",
        "job_status": "QUEUED",
    }
    queue = {
        "job_id": "render-1",
        "job_type": "ae.artifact.render",
        "subject_ref": {"type": "artifact", "id": "artifact-1"},
        "status": "QUEUED",
        "attempt_count": 0,
        "max_attempts": 3,
        "available_at": NOW,
    }
    mutation(render, queue)

    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_recovery_plan(
            render_job_id="render-1",
            render_job=render,
            queue_job=queue,
        )


def test_recovery_rejects_invalid_shapes_and_missing_identity() -> None:
    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_recovery_plan(
            render_job_id="render-1", render_job=[], queue_job=None  # type: ignore[arg-type]
        )
    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_recovery_plan(
            render_job_id="render-1", render_job=None, queue_job=[]  # type: ignore[arg-type]
        )
    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_recovery_plan(
            render_job_id="render-1", render_job=None, queue_job=None
        )
    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_recovery_plan(
            render_job_id="render-1",
            render_job=None,
            queue_job={
                "job_id": "render-1",
                "job_type": "ae.artifact.render",
                "subject_ref": {"type": "document", "id": "artifact-1"},
                "status": "QUEUED",
                "attempt_count": 0,
                "max_attempts": 3,
            },
        )


def test_inspection_maps_missing_and_queue_dependency_failures() -> None:
    class BrokenQueue(InMemoryJobQueue):
        def get_job(self, job_id: str) -> dict | None:
            raise JobQueueError("job.store_unavailable", "offline", 503)

    with pytest.raises(AeAsyncArtifactRenderError) as missing:
        inspect_async_artifact_render_recovery(
            render_job_id="missing",
            artifact_store=ArtifactRecordStore(),
            job_queue=InMemoryJobQueue(),
        )
    assert missing.value.status_code == 404

    with pytest.raises(AeAsyncArtifactRenderError) as unavailable:
        inspect_async_artifact_render_recovery(
            render_job_id="render-1",
            artifact_store=ArtifactRecordStore(),
            job_queue=BrokenQueue(),
        )
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def _headers(user_id: str = "owner-1") -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="tenant-1", user_id=user_id)
    return {"Authorization": f"Bearer {token.access_token}"}


def _route_client() -> tuple[TestClient, ArtifactRecordStore, InMemoryJobQueue, str]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store, queue, job_id = _admitted()
    register_artifact_handoff_routes(app, artifact_store=store, job_queue=queue)
    return TestClient(app), store, queue, job_id


def test_owner_scoped_recovery_routes_inspect_and_reconcile() -> None:
    client, store, queue, job_id = _route_client()
    queue.start_job(job_id, updated_at=NOW)

    visible = client.get(
        f"/api/v1/async-artifact-render-jobs/{job_id}/recovery",
        headers=_headers(),
    )
    hidden = client.get(
        f"/api/v1/async-artifact-render-jobs/{job_id}/recovery",
        headers=_headers("other-owner"),
    )
    reconciled = client.post(
        f"/api/v1/async-artifact-render-jobs/{job_id}/reconcile",
        headers=_headers(),
    )

    assert visible.status_code == 200
    assert visible.json()["action"] == MARK_RENDER_RUNNING
    assert hidden.status_code == 404
    assert reconciled.status_code == 200
    assert reconciled.json()["result"] == "RECONCILED"
    assert store.get_render_job(job_id)["job_status"] == "RUNNING"


def test_recovery_routes_hide_missing_jobs_and_require_authentication() -> None:
    client, _, _, _ = _route_client()

    missing_get = client.get(
        "/api/v1/async-artifact-render-jobs/missing/recovery",
        headers=_headers(),
    )
    missing_post = client.post(
        "/api/v1/async-artifact-render-jobs/missing/reconcile",
        headers=_headers(),
    )
    unauthenticated = client.get(
        "/api/v1/async-artifact-render-jobs/missing/recovery"
    )

    assert missing_get.status_code == 404
    assert missing_post.status_code == 404
    assert unauthenticated.status_code == 401


def test_recovery_plan_does_not_mutate_inputs() -> None:
    store, queue, job_id = _admitted()
    render = store.get_render_job(job_id)
    queued = queue.get_job(job_id)
    original_render = deepcopy(render)
    original_queue = deepcopy(queued)

    build_async_artifact_render_recovery_plan(
        render_job_id=job_id,
        render_job=render,
        queue_job=queued,
    )

    assert render == original_render
    assert queued == original_queue
