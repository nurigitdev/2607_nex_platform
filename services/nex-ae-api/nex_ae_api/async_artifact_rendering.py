from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    JobQueue,
    JobQueueError,
    build_common_job,
    build_subject_ref,
    validate_common_job,
)
from nex_ae_api.generated_response_lineage import (
    AeGeneratedResponseLineageError,
    generated_response_lineage_from_record,
)


AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION = (
    "ae_async_artifact_render_request.v1"
)
AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION = (
    "ae_async_artifact_render_projection.v1"
)
AE_ASYNC_ARTIFACT_RENDER_ADMISSION_SCHEMA_VERSION = (
    "ae_async_artifact_render_admission.v1"
)
AE_ASYNC_ARTIFACT_RESPONSE_BINDING_SCHEMA_VERSION = (
    "ae_async_artifact_response_binding.v1"
)
ASYNC_ARTIFACT_RENDER_JOB_TYPE = "ae.artifact.render"
ASYNC_RENDER_ADMISSION_STATUSES = frozenset({"ENQUEUED", "JOINED", "RECOVERED"})
RENDER_JOB_STATUSES = frozenset(
    {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
)
QUEUE_JOB_STATUSES = frozenset(
    {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}
)
RENDER_LIFECYCLE_STATUSES = frozenset(
    {"PENDING", "RUNNING", "READY", "BLOCKED", "CANCELLED"}
)
RENDER_FORMATS = frozenset({"MD", "HTML_PREVIEW", "DOCX", "PDF"})
MAX_RENDER_ATTEMPTS = 5
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_REQUEST_FIELDS = frozenset(
    {
        "render_request_schema_version",
        "render_job_id",
        "artifact_id",
        "render_request_id",
        "target_formats",
        "owner_scope",
        "workspace_id",
        "interaction_id",
        "response_id",
        "source_ref",
        "request_id",
        "trace_id",
        "max_attempts",
        "requested_at",
        "links",
        "content_included",
    }
)
_PROJECTION_FIELDS = frozenset(
    {
        "render_projection_schema_version",
        "render_job_id",
        "artifact_id",
        "lifecycle_status",
        "render_job_status",
        "queue_job_status",
        "current_stage",
        "progress_percent",
        "attempt_count",
        "max_attempts",
        "retryable",
        "failure",
        "links",
        "owner_scope_enforced",
        "rendered_content_included",
    }
)


@dataclass(frozen=True)
class AeAsyncArtifactRenderError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class ArtifactRenderAdmissionStore(Protocol):
    def get(self, artifact_id: str) -> dict[str, Any] | None:
        ...

    def get_render_job(self, render_job_id: str) -> dict[str, Any] | None:
        ...

    def save_initial_render_job(
        self,
        render_job: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def save_render_job_state(
        self,
        render_job: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class GeneratedResponseLineageStore(Protocol):
    def get_for_owner(
        self,
        interaction_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        ...


def validate_async_artifact_response_lineage(
    *,
    artifact_record: Mapping[str, Any],
    response_id: str,
    lineage_store: GeneratedResponseLineageStore,
) -> dict[str, Any]:
    artifact = _required_mapping(artifact_record, "artifact_record")
    normalized_response_id = _required_text(response_id, "response_id")
    owner_ref = _required_mapping(artifact.get("owner_actor_ref"), "owner_actor_ref")
    workspace_ref = _required_mapping(artifact.get("workspace_ref"), "workspace_ref")
    tenant_id = _required_text(owner_ref.get("tenant_id"), "tenant_id")
    owner_user_id = _required_text(owner_ref.get("actor_id"), "owner_user_id")
    interaction_id = _required_text(
        artifact.get("interaction_id"), "interaction_id"
    )
    try:
        record = lineage_store.get_for_owner(
            interaction_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
    except Exception as exc:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.response_lineage_unavailable",
            detail="Generated response lineage is temporarily unavailable.",
            status_code=503,
            retryable=True,
        ) from exc
    if record is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.response_not_found",
            detail="Generated response was not found for asynchronous rendering.",
            status_code=404,
        )
    try:
        lineage = generated_response_lineage_from_record(record)
    except AeGeneratedResponseLineageError as exc:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.response_lineage_invalid",
            detail="Generated response lineage is invalid.",
            status_code=503,
        ) from exc
    if lineage is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.response_not_ready",
            detail="Generated response is not ready for asynchronous rendering.",
            status_code=409,
            retryable=True,
        )
    source_refs = artifact.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise _invalid("Artifact source_refs must contain a source reference.")
    source_ref = _required_mapping(source_refs[0], "source_ref")
    if (
        lineage["response_id"] != normalized_response_id
        or record.get("workspace_id")
        != _required_text(workspace_ref.get("workspace_id"), "workspace_id")
        or lineage["chat_document_id"] != artifact.get("chat_document_id")
        or lineage["cx_generation_id"] != source_ref.get("cx_generation_id")
        or lineage["structured_draft_id"]
        != source_ref.get("structured_draft_id")
    ):
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.response_lineage_mismatch",
            detail="Generated response does not match the artifact lineage.",
            status_code=409,
        )
    return {
        "response_binding_schema_version": (
            AE_ASYNC_ARTIFACT_RESPONSE_BINDING_SCHEMA_VERSION
        ),
        "response_id": lineage["response_id"],
        "interaction_id": lineage["interaction_id"],
        "chat_document_id": lineage["chat_document_id"],
        "cx_generation_id": lineage["cx_generation_id"],
        "structured_draft_id": lineage["structured_draft_id"],
        "lineage_type": lineage["lineage_type"],
        "citation_workflow_status": lineage["citation_workflow_status"],
        "owner_scope_enforced": True,
        "content_included": False,
    }


def deterministic_async_render_job_id(
    artifact_id: str,
    render_request_id: str,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-render-job:{_required_text(artifact_id, 'artifact_id')}:"
            f"{_required_text(render_request_id, 'render_request_id')}",
        )
    )


def build_async_artifact_render_request(
    *,
    artifact_record: Mapping[str, Any],
    render_request_id: str,
    target_formats: list[str],
    request_id: str,
    trace_id: str,
    response_id: str | None = None,
    max_attempts: int = 3,
    requested_at: str | None = None,
) -> dict[str, Any]:
    artifact = _required_mapping(artifact_record, "artifact_record")
    artifact_id = _required_text(artifact.get("artifact_id"), "artifact_id")
    owner_ref = _required_mapping(artifact.get("owner_actor_ref"), "owner_actor_ref")
    workspace_ref = _required_mapping(artifact.get("workspace_ref"), "workspace_ref")
    source_refs = artifact.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        raise _invalid("Artifact source_refs must contain a source reference.")
    source_ref = _required_mapping(source_refs[0], "source_ref")
    observed_at = requested_at or _utc_now()
    request = {
        "render_request_schema_version": (
            AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION
        ),
        "render_job_id": deterministic_async_render_job_id(
            artifact_id, render_request_id
        ),
        "artifact_id": artifact_id,
        "render_request_id": _required_text(
            render_request_id, "render_request_id"
        ),
        "target_formats": list(target_formats),
        "owner_scope": {
            "tenant_id": _required_text(owner_ref.get("tenant_id"), "tenant_id"),
            "owner_user_id": _required_text(
                owner_ref.get("actor_id"), "owner_user_id"
            ),
        },
        "workspace_id": _required_text(
            workspace_ref.get("workspace_id"), "workspace_id"
        ),
        "interaction_id": _required_text(
            artifact.get("interaction_id"), "interaction_id"
        ),
        "response_id": _nullable_text(response_id, "response_id"),
        "source_ref": {
            "cx_generation_id": _required_text(
                source_ref.get("cx_generation_id"), "cx_generation_id"
            ),
            "structured_draft_id": _required_text(
                source_ref.get("structured_draft_id"), "structured_draft_id"
            ),
            "structured_draft_content_hash": _required_sha256(
                source_ref.get("structured_draft_content_hash"),
                "structured_draft_content_hash",
            ),
            "citation_claims_hash": _required_sha256(
                source_ref.get("citation_claims_hash"), "citation_claims_hash"
            ),
        },
        "request_id": _required_text(request_id, "request_id"),
        "trace_id": _required_text(trace_id, "trace_id"),
        "max_attempts": max_attempts,
        "requested_at": _required_text(observed_at, "requested_at"),
        "links": {
            "artifact": f"/api/v1/artifacts/{artifact_id}",
            "render_job": (
                "/api/v1/artifact-render-jobs/"
                f"{deterministic_async_render_job_id(artifact_id, render_request_id)}"
            ),
        },
        "content_included": False,
    }
    return validate_async_artifact_render_request(request)


def validate_async_artifact_render_request(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
        raise _invalid("Async artifact render request has an invalid shape.")
    request = deepcopy(dict(value))
    if request["render_request_schema_version"] != (
        AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION
    ):
        raise _invalid("Async artifact render request schema version is invalid.")
    for field in (
        "render_job_id",
        "artifact_id",
        "render_request_id",
        "workspace_id",
        "interaction_id",
        "request_id",
        "trace_id",
        "requested_at",
    ):
        request[field] = _required_text(request[field], field)
    expected_job_id = deterministic_async_render_job_id(
        request["artifact_id"], request["render_request_id"]
    )
    if request["render_job_id"] != expected_job_id:
        raise _invalid("Async artifact render job identity is inconsistent.")
    request["response_id"] = _nullable_text(request["response_id"], "response_id")
    request["target_formats"] = _validate_target_formats(request["target_formats"])
    request["owner_scope"] = _validate_owner_scope(request["owner_scope"])
    request["source_ref"] = _validate_source_ref(request["source_ref"])
    request["max_attempts"] = _validate_max_attempts(request["max_attempts"])
    request["links"] = _validate_links(
        request["links"], request["artifact_id"], request["render_job_id"]
    )
    if request["content_included"] is not False:
        raise _invalid("Async artifact render request must not include content.")
    return request


def build_initial_render_job(request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_async_artifact_render_request(request)
    return {
        "render_job_id": normalized["render_job_id"],
        "artifact_id": normalized["artifact_id"],
        "artifact_version_id": None,
        "job_status": "QUEUED",
        "current_stage": "QUEUED",
        "progress_mode": "DETERMINATE",
        "progress_percent": 0,
        "retryable": True,
        "failure_code": None,
        "started_at": None,
        "completed_at": None,
        "created_at": normalized["requested_at"],
        "updated_at": normalized["requested_at"],
    }


def build_async_artifact_render_queue_job(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_async_artifact_render_request(request)
    job = build_common_job(
        job_id=normalized["render_job_id"],
        job_type=ASYNC_ARTIFACT_RENDER_JOB_TYPE,
        trace_id=normalized["trace_id"],
        request_id=normalized["request_id"],
        subject_ref=build_subject_ref("artifact", normalized["artifact_id"]),
        idempotency_key=normalized["render_job_id"],
        created_at=normalized["requested_at"],
        max_attempts=normalized["max_attempts"],
        retryable=True,
        links=deepcopy(normalized["links"]),
    )
    job["payload"] = {"render_request": normalized}
    return validate_async_artifact_render_queue_job(job, normalized)


def validate_async_artifact_render_queue_job(
    value: object,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("Async artifact render queue job must be an object.")
    try:
        job = validate_common_job(deepcopy(dict(value)))
    except JobQueueError as exc:
        raise _invalid("Async artifact render queue job is invalid.") from exc
    if job["job_type"] != ASYNC_ARTIFACT_RENDER_JOB_TYPE:
        raise _invalid("Async artifact render queue job type is invalid.")
    payload = job.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"render_request"}:
        raise _invalid("Async artifact render queue payload is invalid.")
    render_request = validate_async_artifact_render_request(
        payload["render_request"]
    )
    supplied_request = (
        validate_async_artifact_render_request(request)
        if request is not None
        else render_request
    )
    if not _requests_share_idempotent_identity(render_request, supplied_request):
        raise _invalid("Async artifact render queue request binding is inconsistent.")
    if (
        job["job_id"] != render_request["render_job_id"]
        or job["idempotency_key"] != render_request["render_job_id"]
        or job["subject_ref"]
        != {"type": "artifact", "id": render_request["artifact_id"]}
        or job["trace_id"] != render_request["trace_id"]
        or job["request_id"] != render_request["request_id"]
        or job["max_attempts"] != render_request["max_attempts"]
        or job["links"] != render_request["links"]
    ):
        raise _invalid("Async artifact render queue lineage is inconsistent.")
    return job


def admit_async_artifact_render(
    *,
    request: Mapping[str, Any],
    artifact_store: ArtifactRenderAdmissionStore,
    job_queue: JobQueue,
) -> dict[str, Any]:
    normalized = validate_async_artifact_render_request(request)
    artifact = artifact_store.get(normalized["artifact_id"])
    if artifact is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.artifact_not_found",
            detail="Artifact was not found for asynchronous rendering.",
            status_code=404,
        )
    validate_async_artifact_render_artifact_binding(normalized, artifact)
    render_job = artifact_store.get_render_job(normalized["render_job_id"])
    render_job_existed = render_job is not None
    if render_job is None:
        render_job = artifact_store.save_initial_render_job(
            build_initial_render_job(normalized)
        )
    queue_job = job_queue.get_job(normalized["render_job_id"])
    queue_job_existed = queue_job is not None
    if queue_job is None:
        try:
            queue_job = job_queue.enqueue(
                build_async_artifact_render_queue_job(normalized)
            )
        except JobQueueError as exc:
            raise AeAsyncArtifactRenderError(
                error_code="ae.async_artifact_render.queue_unavailable",
                detail="Artifact render queue is unavailable.",
                status_code=503 if exc.status_code >= 500 else exc.status_code,
                retryable=True,
            ) from exc
    queue_job = validate_async_artifact_render_queue_job(queue_job, normalized)
    admission_status = (
        "JOINED"
        if queue_job_existed
        else "RECOVERED"
        if render_job_existed
        else "ENQUEUED"
    )
    return validate_async_artifact_render_admission(
        {
            "render_admission_schema_version": (
                AE_ASYNC_ARTIFACT_RENDER_ADMISSION_SCHEMA_VERSION
            ),
            "admission_status": admission_status,
            "render": build_async_artifact_render_projection(
                render_job=render_job,
                queue_job=queue_job,
            ),
            "owner_scope_enforced": True,
            "content_included": False,
        }
    )


def validate_async_artifact_render_admission(value: object) -> dict[str, Any]:
    fields = {
        "render_admission_schema_version",
        "admission_status",
        "render",
        "owner_scope_enforced",
        "content_included",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Async artifact render admission has an invalid shape.")
    admission = deepcopy(dict(value))
    if admission["render_admission_schema_version"] != (
        AE_ASYNC_ARTIFACT_RENDER_ADMISSION_SCHEMA_VERSION
    ):
        raise _invalid("Async artifact render admission schema version is invalid.")
    if admission["admission_status"] not in ASYNC_RENDER_ADMISSION_STATUSES:
        raise _invalid("Async artifact render admission status is invalid.")
    admission["render"] = validate_async_artifact_render_projection(
        admission["render"]
    )
    if admission["owner_scope_enforced"] is not True:
        raise _invalid("Async artifact render admission must enforce owner scope.")
    if admission["content_included"] is not False:
        raise _invalid("Async artifact render admission must not include content.")
    return admission


def get_async_artifact_render_projection(
    *,
    render_job_id: str,
    artifact_store: ArtifactRenderAdmissionStore,
    job_queue: JobQueue,
) -> dict[str, Any]:
    normalized_id = _required_text(render_job_id, "render_job_id")
    render_job = artifact_store.get_render_job(normalized_id)
    if render_job is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.not_found",
            detail="Asynchronous artifact render job was not found.",
            status_code=404,
        )
    queue_job = job_queue.get_job(normalized_id)
    if queue_job is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.queue_state_missing",
            detail="Artifact render queue state is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )
    return build_async_artifact_render_projection(
        render_job=render_job,
        queue_job=queue_job,
    )


def cancel_async_artifact_render(
    *,
    render_job_id: str,
    artifact_store: ArtifactRenderAdmissionStore,
    job_queue: JobQueue,
    cancelled_at: str | None = None,
) -> dict[str, Any]:
    normalized_id = _required_text(render_job_id, "render_job_id")
    render_job = artifact_store.get_render_job(normalized_id)
    if render_job is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.not_found",
            detail="Asynchronous artifact render job was not found.",
            status_code=404,
        )
    queue_job = job_queue.get_job(normalized_id)
    if queue_job is None:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.queue_state_missing",
            detail="Artifact render queue state is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )
    queue_job = validate_async_artifact_render_queue_job(queue_job)
    if queue_job["status"] in {"SUCCEEDED", "FAILED"}:
        raise AeAsyncArtifactRenderError(
            error_code="ae.async_artifact_render.terminal",
            detail="Terminal artifact render jobs cannot be cancelled.",
            status_code=409,
        )
    observed_at = cancelled_at or _utc_now()
    if queue_job["status"] != "CANCELLED":
        try:
            queue_job = job_queue.cancel_job(normalized_id, updated_at=observed_at)
        except JobQueueError as exc:
            raise AeAsyncArtifactRenderError(
                error_code="ae.async_artifact_render.cancel_failed",
                detail="Artifact render cancellation could not be persisted.",
                status_code=exc.status_code,
                retryable=exc.status_code >= 500,
            ) from exc
    if render_job.get("job_status") != "CANCELLED":
        render_job = artifact_store.save_render_job_state(
            {
                **dict(render_job),
                "job_status": "CANCELLED",
                "current_stage": "CANCELLED",
                "retryable": False,
                "failure_code": None,
                "completed_at": observed_at,
                "updated_at": observed_at,
            }
        )
    return build_async_artifact_render_projection(
        render_job=render_job,
        queue_job=queue_job,
    )


def build_async_artifact_render_projection(
    *,
    render_job: Mapping[str, Any],
    queue_job: Mapping[str, Any],
) -> dict[str, Any]:
    render = _required_mapping(render_job, "render_job")
    queue = _required_mapping(queue_job, "queue_job")
    render_status = render.get("job_status")
    queue_status = queue.get("status")
    if render_status not in RENDER_JOB_STATUSES:
        raise _invalid("Artifact render job status is invalid.")
    if queue_status not in QUEUE_JOB_STATUSES:
        raise _invalid("Artifact render queue job status is invalid.")
    render_job_id = _required_text(render.get("render_job_id"), "render_job_id")
    if queue.get("job_id") != render_job_id:
        raise _invalid("Artifact render queue lineage is inconsistent.")
    expected_render_status, lifecycle_status = _states_for_queue_status(queue_status)
    if render_status != expected_render_status:
        raise _invalid("Artifact render and queue statuses are inconsistent.")
    attempt_count, max_attempts = _validate_attempts(queue)
    progress_percent = _validate_progress(render.get("progress_percent"))
    _validate_progress_for_status(render_status, progress_percent)
    retryable = render.get("retryable")
    if not isinstance(retryable, bool):
        raise _invalid("Artifact render retryable flag is invalid.")
    queue_error = queue.get("error")
    validated_failure = _safe_failure(
        queue_error,
        render.get("failure_code") if render_status == "FAILED" else None,
    )
    if (
        render_status != "FAILED"
        and queue_error is not None
        and (not isinstance(queue_error, Mapping) or "detail" not in queue_error)
    ):
        raise _invalid("Non-terminal artifact render queue failure is invalid.")
    failure = validated_failure if render_status == "FAILED" else None
    if render_status != "FAILED" and render.get("failure_code") is not None:
        raise _invalid("Only failed artifact render jobs may expose a failure.")
    return validate_async_artifact_render_projection(
        {
            "render_projection_schema_version": (
                AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION
            ),
            "render_job_id": render_job_id,
            "artifact_id": _required_text(render.get("artifact_id"), "artifact_id"),
            "lifecycle_status": lifecycle_status,
            "render_job_status": render_status,
            "queue_job_status": queue_status,
            "current_stage": _required_text(
                render.get("current_stage"), "current_stage"
            ),
            "progress_percent": progress_percent,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "retryable": retryable,
            "failure": failure,
            "links": {
                "artifact": f"/api/v1/artifacts/{render['artifact_id']}",
                "render_job": f"/api/v1/artifact-render-jobs/{render_job_id}",
            },
            "owner_scope_enforced": True,
            "rendered_content_included": False,
        }
    )


def validate_async_artifact_render_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROJECTION_FIELDS:
        raise _invalid("Async artifact render projection has an invalid shape.")
    projection = deepcopy(dict(value))
    if projection["render_projection_schema_version"] != (
        AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION
    ):
        raise _invalid("Async artifact render projection schema version is invalid.")
    for field in ("render_job_id", "artifact_id", "current_stage"):
        projection[field] = _required_text(projection[field], field)
    if projection["render_job_status"] not in RENDER_JOB_STATUSES:
        raise _invalid("Async artifact render status is invalid.")
    if projection["queue_job_status"] not in QUEUE_JOB_STATUSES:
        raise _invalid("Async artifact render queue status is invalid.")
    expected_render_status, expected_lifecycle = _states_for_queue_status(
        projection["queue_job_status"]
    )
    if projection["render_job_status"] != expected_render_status:
        raise _invalid("Async artifact render statuses are inconsistent.")
    if projection["lifecycle_status"] != expected_lifecycle:
        raise _invalid("Async artifact render lifecycle is inconsistent.")
    projection["progress_percent"] = _validate_progress(
        projection["progress_percent"]
    )
    _validate_progress_for_status(
        projection["render_job_status"], projection["progress_percent"]
    )
    projection["attempt_count"], projection["max_attempts"] = _validate_attempts(
        projection
    )
    if not isinstance(projection["retryable"], bool):
        raise _invalid("Async artifact render retryable flag is invalid.")
    projection["failure"] = _safe_failure(
        projection["failure"],
        projection["failure"].get("error_code")
        if isinstance(projection["failure"], Mapping)
        else None,
    )
    if projection["render_job_status"] != "FAILED" and projection["failure"]:
        raise _invalid("Only failed artifact renders may expose a failure.")
    projection["links"] = _validate_links(
        projection["links"], projection["artifact_id"], projection["render_job_id"]
    )
    if projection["owner_scope_enforced"] is not True:
        raise _invalid("Async artifact render owner scope must be enforced.")
    if projection["rendered_content_included"] is not False:
        raise _invalid("Async artifact render projection must not include content.")
    return projection


def _states_for_queue_status(queue_status: str) -> tuple[str, str]:
    return {
        "QUEUED": ("QUEUED", "PENDING"),
        "RUNNING": ("RUNNING", "RUNNING"),
        "SUCCEEDED": ("COMPLETED", "READY"),
        "FAILED": ("FAILED", "BLOCKED"),
        "CANCELLED": ("CANCELLED", "CANCELLED"),
    }[queue_status]


def validate_async_artifact_render_artifact_binding(
    request: Mapping[str, Any],
    artifact_record: Mapping[str, Any],
) -> None:
    rebuilt = build_async_artifact_render_request(
        artifact_record=artifact_record,
        render_request_id=str(request["render_request_id"]),
        target_formats=list(request["target_formats"]),
        request_id=str(request["request_id"]),
        trace_id=str(request["trace_id"]),
        response_id=request["response_id"],
        max_attempts=int(request["max_attempts"]),
        requested_at=str(request["requested_at"]),
    )
    if rebuilt != request:
        raise _invalid("Async artifact render request no longer matches the artifact.")


def _requests_share_idempotent_identity(
    stored: Mapping[str, Any],
    supplied: Mapping[str, Any],
) -> bool:
    immutable_fields = (
        "render_job_id",
        "artifact_id",
        "render_request_id",
        "target_formats",
        "owner_scope",
        "workspace_id",
        "interaction_id",
        "response_id",
        "source_ref",
        "max_attempts",
        "links",
        "content_included",
    )
    return all(stored[field] == supplied[field] for field in immutable_fields)


def _validate_target_formats(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _invalid("Async artifact render target_formats must be a non-empty list.")
    formats: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in RENDER_FORMATS:
            raise _invalid("Async artifact render target format is invalid.")
        if item not in formats:
            formats.append(item)
    return formats


def _validate_owner_scope(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"tenant_id", "owner_user_id"}:
        raise _invalid("Async artifact render owner scope is invalid.")
    return {
        "tenant_id": _required_text(value["tenant_id"], "tenant_id"),
        "owner_user_id": _required_text(value["owner_user_id"], "owner_user_id"),
    }


def _validate_source_ref(value: object) -> dict[str, str]:
    fields = {
        "cx_generation_id",
        "structured_draft_id",
        "structured_draft_content_hash",
        "citation_claims_hash",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Async artifact render source reference is invalid.")
    return {
        "cx_generation_id": _required_text(
            value["cx_generation_id"], "cx_generation_id"
        ),
        "structured_draft_id": _required_text(
            value["structured_draft_id"], "structured_draft_id"
        ),
        "structured_draft_content_hash": _required_sha256(
            value["structured_draft_content_hash"], "structured_draft_content_hash"
        ),
        "citation_claims_hash": _required_sha256(
            value["citation_claims_hash"], "citation_claims_hash"
        ),
    }


def _validate_links(
    value: object,
    artifact_id: str,
    render_job_id: str,
) -> dict[str, str]:
    expected = {
        "artifact": f"/api/v1/artifacts/{artifact_id}",
        "render_job": f"/api/v1/artifact-render-jobs/{render_job_id}",
    }
    if value != expected:
        raise _invalid("Async artifact render links are invalid.")
    return expected


def _validate_max_attempts(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_RENDER_ATTEMPTS
    ):
        raise _invalid("Async artifact render max_attempts is invalid.")
    return value


def _validate_attempts(value: Mapping[str, Any]) -> tuple[int, int]:
    attempt_count = value.get("attempt_count")
    max_attempts = value.get("max_attempts")
    validated_max = _validate_max_attempts(max_attempts)
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count < 0
        or attempt_count > validated_max
    ):
        raise _invalid("Async artifact render attempt_count is invalid.")
    return attempt_count, validated_max


def _validate_progress(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise _invalid("Async artifact render progress_percent is invalid.")
    return value


def _validate_progress_for_status(status: str, progress: int) -> None:
    if status == "QUEUED" and progress != 0:
        raise _invalid("Queued artifact render progress must be zero.")
    if status == "COMPLETED" and progress != 100:
        raise _invalid("Completed artifact render progress must be 100.")


def _safe_failure(value: object, failure_code: object) -> dict[str, Any] | None:
    if value is None and failure_code is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid("Async artifact render failure is invalid.")
    required = {"error_code", "retryable", "dead_lettered"}
    if not required.issubset(value) or set(value) - required not in (set(), {"detail"}):
        raise _invalid("Async artifact render failure has an invalid shape.")
    error_code = _required_text(value.get("error_code"), "failure.error_code")
    if failure_code is not None and failure_code != error_code:
        raise _invalid("Async artifact render failure code is inconsistent.")
    if not isinstance(value.get("retryable"), bool) or not isinstance(
        value.get("dead_lettered"), bool
    ):
        raise _invalid("Async artifact render failure flags are invalid.")
    return {
        "error_code": error_code,
        "retryable": value["retryable"],
        "dead_lettered": value["dead_lettered"],
    }


def _required_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object.")
    return dict(value)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.")
    return value.strip()


def _nullable_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _required_sha256(value: object, field: str) -> str:
    text = _required_text(value, field)
    if _SHA256_PATTERN.fullmatch(text) is None:
        raise _invalid(f"{field} must be a lowercase SHA-256 digest.")
    return text


def _invalid(detail: str) -> AeAsyncArtifactRenderError:
    return AeAsyncArtifactRenderError(
        error_code="ae.async_artifact_render.contract_invalid",
        detail=detail,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
