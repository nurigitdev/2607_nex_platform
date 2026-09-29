from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    ArtifactRecordStore,
    build_markdown_render_result,
)
from nex_ae_api.async_artifact_render_worker import (
    AE_ASYNC_ARTIFACT_RENDER_WORKER_RESULT_SCHEMA_VERSION,
    AsyncArtifactRenderWorkerHandler,
    AsyncArtifactRenderWorkerError,
    build_async_artifact_render_worker_config,
    run_async_artifact_render_worker_batch,
    run_async_artifact_render_worker_once,
)
from nex_ae_api.async_artifact_rendering import (
    admit_async_artifact_render,
    build_async_artifact_render_request,
    get_async_artifact_render_projection,
)
from nex_runtime import InMemoryJobQueue

NOW = "2026-09-29T03:00:00Z"
TRACE_ID = "1" * 32
CONTENT_HASH = "c" * 64
CITATION_HASH = "d" * 64


def _artifact(artifact_id: str = "artifact-worker-1") -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_status": "DRAFT",
        "display_title": "Async grounded report",
        "interaction_id": "interaction-1",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "owner-1",
            "tenant_id": "tenant-1",
        },
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "target_formats": ["MD", "HTML_PREVIEW", "PDF"],
        "template_ref": {"template_id": "template-1", "template_version": "1"},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": CONTENT_HASH,
                "citation_claims_hash": CITATION_HASH,
                "quality_summary": {"citation_status": "VALIDATED"},
            }
        ],
        "versions": [],
        "render_jobs": [],
        "files": [],
        "links": [],
        "updated_at": NOW,
    }


def _draft(**overrides: Any) -> dict[str, Any]:
    draft = {
        "structured_draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_id": "draft-1",
        "cx_generation_id": "generation-1",
        "status": "VALIDATED",
        "trace_id": TRACE_ID,
        "request_id": "request-1",
        "title": "Grounded report",
        "summary": "Safe summary.",
        "content_hash": CONTENT_HASH,
        "sections": [
            {
                "section_id": "section-1",
                "ordinal": 1,
                "heading": "Overview",
                "blocks": [
                    {
                        "block_id": "block-1",
                        "block_type": "paragraph",
                        "text_hash": "e" * 64,
                        "text_preview": "Grounded answer [1].",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_label": "[1]",
                "evidence_id": "evidence-1",
                "retrieval_package_id": "retrieval-1",
                "valid": True,
                "validation_error": None,
            }
        ],
        "validation": {
            "validator_profile_id": "validator-1",
            "citation_status": "VALIDATED",
            "errors": [],
            "warnings": [],
        },
    }
    draft.update(overrides)
    return draft


@dataclass
class StubCxClient:
    draft: dict[str, Any] = field(default_factory=_draft)
    error: Exception | None = None
    callback: Callable[[], None] | None = None
    calls: list[dict[str, str]] = field(default_factory=list)

    def get_structured_draft(
        self,
        cx_generation_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "cx_generation_id": cx_generation_id,
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        if self.callback is not None:
            self.callback()
        if self.error is not None:
            raise self.error
        return deepcopy(self.draft)


def _admitted(
    *,
    artifact_id: str = "artifact-worker-1",
    target_formats: list[str] | None = None,
    max_attempts: int = 3,
) -> tuple[ArtifactRecordStore, InMemoryJobQueue, dict[str, Any]]:
    store = ArtifactRecordStore()
    artifact = store.create(_artifact(artifact_id))
    request = build_async_artifact_render_request(
        artifact_record=artifact,
        render_request_id=f"render-{artifact_id}",
        target_formats=target_formats or ["MD", "HTML_PREVIEW"],
        request_id="request-1",
        trace_id=TRACE_ID,
        response_id="response-1",
        max_attempts=max_attempts,
        requested_at=NOW,
    )
    queue = InMemoryJobQueue()
    admit_async_artifact_render(
        request=request,
        artifact_store=store,
        job_queue=queue,
    )
    return store, queue, request


def test_worker_renders_owner_scoped_artifact_and_completes_queue() -> None:
    store, queue, request = _admitted()
    cx_client = StubCxClient()

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )

    assert execution.status == "SUCCEEDED"
    assert execution.handler_result == {
        "worker_result_schema_version": (
            AE_ASYNC_ARTIFACT_RENDER_WORKER_RESULT_SCHEMA_VERSION
        ),
        "outcome": "SUCCEEDED",
        "render_job_id": request["render_job_id"],
        "artifact_id": request["artifact_id"],
        "artifact_version_id": store.get(request["artifact_id"])["current_version_id"],
        "render_job_status": "COMPLETED",
        "queue_job_status": "SUCCEEDED",
        "rendered_formats": ["MD", "HTML_PREVIEW"],
        "file_count": 2,
        "owner_scope_enforced": True,
        "content_included": False,
    }
    assert cx_client.calls == [
        {
            "cx_generation_id": "generation-1",
            "tenant_id": "tenant-1",
            "owner_user_id": "owner-1",
            "request_id": "request-1",
            "trace_id": TRACE_ID,
        }
    ]
    artifact = store.get(request["artifact_id"])
    assert artifact["artifact_status"] == "READY"
    assert len(artifact["render_jobs"]) == 1
    assert len(artifact["versions"]) == 1
    assert queue.get_job(request["render_job_id"])["status"] == "SUCCEEDED"
    assert (
        get_async_artifact_render_projection(
            render_job_id=request["render_job_id"],
            artifact_store=store,
            job_queue=queue,
        )["lifecycle_status"]
        == "READY"
    )
    assert "storage_ref" not in str(execution.handler_result)


def test_worker_retryable_failure_requeues_without_exposing_failure_projection() -> (
    None
):
    store, queue, request = _admitted()
    cx_client = StubCxClient(
        error=ArtifactHandoffError(
            status_code=503,
            error_code="cx.structured_draft_unavailable",
            detail="CX is unavailable.",
            retryable=True,
        )
    )

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )

    assert execution.status == "FAILED"
    assert execution.error_code == "cx.structured_draft_unavailable"
    queue_job = queue.get_job(request["render_job_id"])
    assert queue_job["status"] == "QUEUED"
    assert queue_job["error"]["retryable"] is True
    assert store.get_render_job(request["render_job_id"])["job_status"] == "QUEUED"
    projection = get_async_artifact_render_projection(
        render_job_id=request["render_job_id"],
        artifact_store=store,
        job_queue=queue,
    )
    assert projection["lifecycle_status"] == "PENDING"
    assert projection["failure"] is None


def test_worker_non_retryable_failure_dead_letters_and_marks_artifact_failed() -> None:
    store, queue, request = _admitted(max_attempts=1)
    cx_client = StubCxClient(draft=_draft(cx_generation_id="other-generation"))

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )

    assert execution.status == "FAILED"
    assert execution.error_code == "ae.source_generation_mismatch"
    assert queue.get_job(request["render_job_id"])["status"] == "FAILED"
    assert store.get_render_job(request["render_job_id"])["job_status"] == "FAILED"
    assert store.get(request["artifact_id"])["artifact_status"] == "FAILED"
    projection = get_async_artifact_render_projection(
        render_job_id=request["render_job_id"],
        artifact_store=store,
        job_queue=queue,
    )
    assert projection["lifecycle_status"] == "BLOCKED"
    assert projection["failure"] == {
        "error_code": "ae.source_generation_mismatch",
        "retryable": False,
        "dead_lettered": True,
    }


def test_worker_observes_cancellation_before_publishing_rendered_content() -> None:
    store, queue, request = _admitted()
    cx_client = StubCxClient(
        callback=lambda: queue.cancel_job(request["render_job_id"], updated_at=NOW)
    )

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )

    assert execution.status == "CANCELLED"
    assert execution.handler_result["outcome"] == "CANCELLED"
    assert execution.handler_result["artifact_version_id"] is None
    assert execution.handler_result["file_count"] == 0
    assert store.get(request["artifact_id"])["versions"] == []
    assert store.get_render_job(request["render_job_id"])["job_status"] == "CANCELLED"


def test_worker_observes_preexisting_cancellation_without_cx_call() -> None:
    store, queue, request = _admitted()
    claimed = queue.claim_next_job("worker-cancelled", updated_at=NOW)
    queue.cancel_job(request["render_job_id"], updated_at=NOW)
    render_job = store.get_render_job(request["render_job_id"])
    store.save_render_job_state(
        {
            **render_job,
            "job_status": "CANCELLED",
            "current_stage": "CANCELLED",
            "retryable": False,
            "completed_at": NOW,
            "updated_at": NOW,
        }
    )
    cx_client = StubCxClient()

    result = AsyncArtifactRenderWorkerHandler(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )(claimed)

    assert result["outcome"] == "CANCELLED"
    assert cx_client.calls == []


def test_worker_rejects_artifact_binding_drift() -> None:
    store, queue, request = _admitted(max_attempts=1)
    artifact = store.get(request["artifact_id"])
    artifact["owner_actor_ref"]["actor_id"] = "other-owner"
    store.save(artifact)

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=StubCxClient(),
        clock=lambda: NOW,
    )

    assert execution.status == "FAILED"
    assert execution.error_code == "ae.async_artifact_render.contract_invalid"
    assert queue.get_job(request["render_job_id"])["status"] == "FAILED"


def test_worker_fails_orphaned_queue_job_without_private_state() -> None:
    store, queue, request = _admitted(max_attempts=1)
    store.records.pop(request["artifact_id"])
    store.render_jobs.pop(request["render_job_id"])

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=StubCxClient(),
        clock=lambda: NOW,
    )

    assert execution.status == "FAILED"
    assert execution.error_code == "ae.async_artifact_render.artifact_not_found"
    assert queue.get_job(request["render_job_id"])["status"] == "FAILED"


def test_worker_reports_missing_render_state_as_retryable_dependency_failure() -> None:
    store, queue, request = _admitted(max_attempts=2)
    store.render_jobs.pop(request["render_job_id"])

    execution = run_async_artifact_render_worker_once(
        job_queue=queue,
        artifact_store=store,
        cx_client=StubCxClient(),
        clock=lambda: NOW,
    )

    assert execution.status == "FAILED"
    assert execution.error_code == "ae.async_artifact_render.state_missing"
    assert queue.get_job(request["render_job_id"])["status"] == "QUEUED"


def test_worker_recovers_completed_render_without_duplicate_metadata() -> None:
    store, queue, request = _admitted(target_formats=["MD"])
    claimed = queue.claim_next_job("worker-crash", updated_at=NOW)
    artifact = store.get(request["artifact_id"])
    result = build_markdown_render_result(
        artifact_record=artifact,
        structured_draft=_draft(),
        target_formats=["MD"],
        render_request_id=request["render_request_id"],
        render_job_id=request["render_job_id"],
    )
    store.apply_markdown_render(
        artifact_id=request["artifact_id"],
        artifact_version=result["artifact_version"],
        render_job=result["render_job"],
        markdown=result["markdown"],
        artifact_files=result["artifact_files"],
        artifact_links=result["artifact_links"],
        rendered_payloads=result["rendered_payloads"],
    )
    cx_client = StubCxClient()

    replayed = AsyncArtifactRenderWorkerHandler(
        job_queue=queue,
        artifact_store=store,
        cx_client=cx_client,
        clock=lambda: NOW,
    )(claimed)

    artifact = store.get(request["artifact_id"])
    assert replayed["outcome"] == "REPLAYED"
    assert queue.get_job(request["render_job_id"])["status"] == "SUCCEEDED"
    assert len(artifact["render_jobs"]) == 1
    assert len(artifact["versions"]) == 1
    assert len(artifact["files"]) == 1
    assert cx_client.calls == []


def test_worker_batch_processes_job_then_reports_idle() -> None:
    store, queue, _ = _admitted(target_formats=["MD"])

    batch = run_async_artifact_render_worker_batch(
        job_queue=queue,
        artifact_store=store,
        cx_client=StubCxClient(),
        max_jobs=2,
        stop_on_failure=False,
        clock=lambda: NOW,
    )

    assert batch.claimed_count == 1
    assert batch.succeeded_count == 1
    assert batch.idle_count == 1
    assert len(batch.executions) == 2


def test_worker_config_uses_dedicated_artifact_render_identity() -> None:
    config = build_async_artifact_render_worker_config(
        worker_id="worker-custom",
        max_jobs=3,
    )

    assert config.service_id == "nex-ae-api"
    assert config.worker_id == "worker-custom"
    assert config.worker_type == "ae.async_artifact_render.worker"
    assert config.job_type == "ae.artifact.render"
    assert config.max_jobs == 3


def test_worker_default_clock_and_error_string_are_available() -> None:
    execution = run_async_artifact_render_worker_once(
        job_queue=InMemoryJobQueue(),
        artifact_store=ArtifactRecordStore(),
        cx_client=StubCxClient(),
    )
    error = AsyncArtifactRenderWorkerError("worker.test", "worker failed")

    assert execution.status == "IDLE"
    assert str(error) == "worker failed"
