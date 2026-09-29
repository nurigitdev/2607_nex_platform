from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol

from nex_runtime import (
    InMemoryWorkerHeartbeatStore,
    JobQueue,
    ServiceLogEmitter,
    WorkerBatchResult,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    build_job_error,
    run_worker_batch,
    run_worker_once,
)

from nex_ae_api.artifacts import (
    ArtifactHandoffError,
    CxArtifactSourceClient,
    build_markdown_render_result,
)
from nex_ae_api.async_artifact_rendering import (
    ASYNC_ARTIFACT_RENDER_JOB_TYPE,
    validate_async_artifact_render_artifact_binding,
    validate_async_artifact_render_queue_job,
)

AE_ASYNC_ARTIFACT_RENDER_WORKER_RESULT_SCHEMA_VERSION = (
    "ae_async_artifact_render_worker_result.v1"
)
AE_ASYNC_ARTIFACT_RENDER_WORKER_ID = "ae-async-artifact-render-worker"
AE_ASYNC_ARTIFACT_RENDER_WORKER_TYPE = "ae.async_artifact_render.worker"


class AsyncArtifactRenderStore(Protocol):
    def get(self, artifact_id: str) -> dict[str, Any] | None: ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]: ...

    def get_render_job(self, render_job_id: str) -> dict[str, Any] | None: ...

    def save_render_job_state(
        self,
        render_job: dict[str, Any],
    ) -> dict[str, Any]: ...

    def apply_markdown_render(
        self,
        *,
        artifact_id: str,
        artifact_version: dict[str, Any],
        render_job: dict[str, Any],
        markdown: str,
        artifact_files: list[dict[str, Any]],
        artifact_links: list[dict[str, Any]],
        rendered_payloads: dict[str, bytes] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AsyncArtifactRenderWorkerError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass
class AsyncArtifactRenderWorkerHandler:
    job_queue: JobQueue
    artifact_store: AsyncArtifactRenderStore
    cx_client: CxArtifactSourceClient
    clock: Callable[[], str] = lambda: _utc_now()

    def __call__(self, job: dict[str, Any]) -> dict[str, Any]:
        normalized_job = validate_async_artifact_render_queue_job(job)
        request = normalized_job["payload"]["render_request"]
        render_job_id = request["render_job_id"]
        artifact = self.artifact_store.get(request["artifact_id"])
        if artifact is None:
            return self._fail(
                normalized_job,
                ArtifactHandoffError(
                    status_code=404,
                    error_code="ae.async_artifact_render.artifact_not_found",
                    detail="Artifact was not found during asynchronous rendering.",
                ),
            )
        try:
            validate_async_artifact_render_artifact_binding(request, artifact)
        except Exception as exc:
            return self._fail(normalized_job, exc)

        render_job = self.artifact_store.get_render_job(render_job_id)
        if render_job is None:
            return self._fail(
                normalized_job,
                ArtifactHandoffError(
                    status_code=503,
                    error_code="ae.async_artifact_render.state_missing",
                    detail="Artifact render state is temporarily unavailable.",
                    retryable=True,
                ),
            )
        if render_job["job_status"] == "COMPLETED":
            completed_queue = self.job_queue.complete_job(
                render_job_id,
                updated_at=self.clock(),
            )
            return _worker_result(
                outcome="REPLAYED",
                request=request,
                render_job=render_job,
                queue_job=completed_queue,
                artifact=artifact,
            )

        cancelled = self._cancelled_result(request, render_job, artifact)
        if cancelled is not None:
            return cancelled

        observed_at = self.clock()
        running_render = self.artifact_store.save_render_job_state(
            {
                **render_job,
                "job_status": "RUNNING",
                "current_stage": "HANDOFF_VALIDATING",
                "progress_percent": 10,
                "retryable": True,
                "failure_code": None,
                "started_at": render_job.get("started_at") or observed_at,
                "completed_at": None,
                "updated_at": observed_at,
            }
        )
        try:
            structured_draft = self.cx_client.get_structured_draft(
                request["source_ref"]["cx_generation_id"],
                tenant_id=request["owner_scope"]["tenant_id"],
                owner_user_id=request["owner_scope"]["owner_user_id"],
                request_id=request["request_id"],
                trace_id=request["trace_id"],
            )
            if structured_draft.get("cx_generation_id") != (
                request["source_ref"]["cx_generation_id"]
            ):
                raise ArtifactHandoffError(
                    status_code=409,
                    error_code="ae.source_generation_mismatch",
                    detail="Structured draft generation does not match the artifact source.",
                )
            cancelled = self._cancelled_result(request, running_render, artifact)
            if cancelled is not None:
                return cancelled
            render_result = build_markdown_render_result(
                artifact_record=artifact,
                structured_draft=structured_draft,
                target_formats=request["target_formats"],
                render_request_id=request["render_request_id"],
                render_job_id=render_job_id,
            )
            completed_render = {
                **render_result["render_job"],
                "started_at": running_render["started_at"],
                "created_at": render_job.get("created_at") or request["requested_at"],
                "updated_at": render_result["render_job"]["completed_at"],
            }
            updated_artifact = self.artifact_store.apply_markdown_render(
                artifact_id=request["artifact_id"],
                artifact_version=render_result["artifact_version"],
                render_job=completed_render,
                markdown=render_result["markdown"],
                artifact_files=render_result["artifact_files"],
                artifact_links=render_result["artifact_links"],
                rendered_payloads=render_result["rendered_payloads"],
            )
        except Exception as exc:
            return self._fail(normalized_job, exc)

        completed_queue = self.job_queue.complete_job(
            render_job_id,
            updated_at=completed_render["completed_at"],
        )
        return _worker_result(
            outcome="SUCCEEDED",
            request=request,
            render_job=completed_render,
            queue_job=completed_queue,
            artifact=updated_artifact,
        )

    def _cancelled_result(
        self,
        request: Mapping[str, Any],
        render_job: Mapping[str, Any],
        artifact: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        queue_job = self.job_queue.get_job(str(request["render_job_id"]))
        if queue_job is None or queue_job["status"] != "CANCELLED":
            return None
        observed_at = self.clock()
        cancelled_render = dict(render_job)
        if cancelled_render["job_status"] != "CANCELLED":
            cancelled_render = self.artifact_store.save_render_job_state(
                {
                    **cancelled_render,
                    "job_status": "CANCELLED",
                    "current_stage": "CANCELLED",
                    "retryable": False,
                    "failure_code": None,
                    "completed_at": observed_at,
                    "updated_at": observed_at,
                }
            )
        return _worker_result(
            outcome="CANCELLED",
            request=request,
            render_job=cancelled_render,
            queue_job=queue_job,
            artifact=artifact,
        )

    def _fail(
        self,
        job: Mapping[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        error_code = str(
            getattr(exc, "error_code", "ae.async_artifact_render.worker_failed")
        )
        retryable = bool(getattr(exc, "retryable", True))
        failed_at = self.clock()
        error = build_job_error(
            error_code=error_code,
            detail="Asynchronous artifact rendering failed.",
            retryable=retryable,
        )
        if retryable:
            queue_job = self.job_queue.retry_job(
                str(job["job_id"]),
                error=error,
                failed_at=failed_at,
            )
        else:
            queue_job = self.job_queue.dead_letter_job(
                str(job["job_id"]),
                error=error,
                failed_at=failed_at,
            )
        render_job = self.artifact_store.get_render_job(str(job["job_id"]))
        if render_job is not None:
            terminal = queue_job["status"] == "FAILED"
            self.artifact_store.save_render_job_state(
                {
                    **render_job,
                    "job_status": "FAILED" if terminal else "QUEUED",
                    "current_stage": "FAILED" if terminal else "QUEUED",
                    "progress_percent": (
                        render_job["progress_percent"] if terminal else 0
                    ),
                    "retryable": not terminal,
                    "failure_code": error_code if terminal else None,
                    "completed_at": failed_at if terminal else None,
                    "updated_at": failed_at,
                }
            )
            if terminal:
                artifact = self.artifact_store.get(render_job["artifact_id"])
                if artifact is not None:
                    self.artifact_store.save(
                        {
                            **artifact,
                            "artifact_status": "FAILED",
                            "updated_at": failed_at,
                        }
                    )
        raise AsyncArtifactRenderWorkerError(
            error_code=error_code,
            detail="Asynchronous artifact rendering failed.",
            retryable=queue_job["status"] == "QUEUED",
        ) from exc


def build_async_artifact_render_worker_config(
    *,
    worker_id: str = AE_ASYNC_ARTIFACT_RENDER_WORKER_ID,
    max_jobs: int = 1,
) -> WorkerRunnerConfig:
    return WorkerRunnerConfig(
        service_id="nex-ae-api",
        worker_id=worker_id,
        worker_type=AE_ASYNC_ARTIFACT_RENDER_WORKER_TYPE,
        job_type=ASYNC_ARTIFACT_RENDER_JOB_TYPE,
        max_jobs=max_jobs,
    )


def run_async_artifact_render_worker_once(
    *,
    job_queue: JobQueue,
    artifact_store: AsyncArtifactRenderStore,
    cx_client: CxArtifactSourceClient,
    worker_id: str = AE_ASYNC_ARTIFACT_RENDER_WORKER_ID,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
    service_log_emitter: ServiceLogEmitter | None = None,
    clock: Callable[[], str] | None = None,
) -> WorkerJobExecution:
    observed_clock = clock or _utc_now
    heartbeat_emitter = worker_heartbeat_emitter or _default_heartbeat_emitter(
        worker_id
    )
    return run_worker_once(
        config=build_async_artifact_render_worker_config(worker_id=worker_id),
        queue=job_queue,
        heartbeat_emitter=heartbeat_emitter,
        handler=AsyncArtifactRenderWorkerHandler(
            job_queue=job_queue,
            artifact_store=artifact_store,
            cx_client=cx_client,
            clock=observed_clock,
        ),
        service_log_emitter=service_log_emitter,
        handler_finalizes_job=True,
        clock=observed_clock,
    )


def run_async_artifact_render_worker_batch(
    *,
    job_queue: JobQueue,
    artifact_store: AsyncArtifactRenderStore,
    cx_client: CxArtifactSourceClient,
    worker_id: str = AE_ASYNC_ARTIFACT_RENDER_WORKER_ID,
    max_jobs: int = 10,
    stop_on_failure: bool = True,
    worker_heartbeat_emitter: WorkerHeartbeatEmitter | None = None,
    service_log_emitter: ServiceLogEmitter | None = None,
    clock: Callable[[], str] | None = None,
) -> WorkerBatchResult:
    observed_clock = clock or _utc_now
    heartbeat_emitter = worker_heartbeat_emitter or _default_heartbeat_emitter(
        worker_id
    )
    return run_worker_batch(
        config=build_async_artifact_render_worker_config(
            worker_id=worker_id,
            max_jobs=max_jobs,
        ),
        queue=job_queue,
        heartbeat_emitter=heartbeat_emitter,
        handler=AsyncArtifactRenderWorkerHandler(
            job_queue=job_queue,
            artifact_store=artifact_store,
            cx_client=cx_client,
            clock=observed_clock,
        ),
        service_log_emitter=service_log_emitter,
        handler_finalizes_job=True,
        stop_on_failure=stop_on_failure,
        clock=observed_clock,
    )


def _worker_result(
    *,
    outcome: str,
    request: Mapping[str, Any],
    render_job: Mapping[str, Any],
    queue_job: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    version_id = render_job.get("artifact_version_id")
    version = next(
        (
            item
            for item in artifact.get("versions", [])
            if item.get("artifact_version_id") == version_id
        ),
        None,
    )
    file_count = sum(
        1
        for item in artifact.get("files", [])
        if item.get("artifact_version_id") == version_id
    )
    return {
        "worker_result_schema_version": (
            AE_ASYNC_ARTIFACT_RENDER_WORKER_RESULT_SCHEMA_VERSION
        ),
        "outcome": outcome,
        "render_job_id": request["render_job_id"],
        "artifact_id": request["artifact_id"],
        "artifact_version_id": version_id,
        "render_job_status": render_job["job_status"],
        "queue_job_status": queue_job["status"],
        "rendered_formats": (
            deepcopy(version.get("rendered_formats", [])) if version is not None else []
        ),
        "file_count": file_count,
        "owner_scope_enforced": True,
        "content_included": False,
    }


def _default_heartbeat_emitter(worker_id: str) -> WorkerHeartbeatEmitter:
    return WorkerHeartbeatEmitter(
        service_id="nex-ae-api",
        worker_id=worker_id,
        worker_type=AE_ASYNC_ARTIFACT_RENDER_WORKER_TYPE,
        store=InMemoryWorkerHeartbeatStore(),
        metadata={"job_type": ASYNC_ARTIFACT_RENDER_JOB_TYPE},
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
