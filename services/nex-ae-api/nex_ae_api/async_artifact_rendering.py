from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION = (
    "ae_async_artifact_render_request.v1"
)
AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION = (
    "ae_async_artifact_render_projection.v1"
)
ASYNC_ARTIFACT_RENDER_JOB_TYPE = "ae.artifact.render"
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
    failure = _safe_failure(queue.get("error"), render.get("failure_code"))
    if render_status != "FAILED" and failure is not None:
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
    allowed = {"error_code", "retryable", "dead_lettered"}
    if set(value) != allowed:
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
