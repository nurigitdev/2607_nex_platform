from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ae_api.async_artifact_rendering import (
    AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION,
    AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION,
    AeAsyncArtifactRenderError,
    build_async_artifact_render_projection,
    build_async_artifact_render_request,
    build_initial_render_job,
    deterministic_async_render_job_id,
    validate_async_artifact_render_projection,
    validate_async_artifact_render_request,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
NOW = "2026-09-29T00:00:00Z"


def _artifact() -> dict:
    return {
        "artifact_id": "artifact-1",
        "interaction_id": "interaction-1",
        "owner_actor_ref": {
            "tenant_id": "tenant-1",
            "actor_id": "owner-1",
        },
        "workspace_ref": {"workspace_id": "workspace-1"},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": DIGEST_A,
                "citation_claims_hash": DIGEST_B,
            }
        ],
    }


def _request() -> dict:
    return build_async_artifact_render_request(
        artifact_record=_artifact(),
        render_request_id="render-request-1",
        target_formats=["MD", "HTML_PREVIEW", "MD"],
        request_id="request-1",
        trace_id="trace-1",
        response_id="response-1",
        requested_at=NOW,
    )


def _queue_job(status: str = "QUEUED") -> dict:
    return {
        "job_id": _request()["render_job_id"],
        "status": status,
        "attempt_count": 0 if status == "QUEUED" else 1,
        "max_attempts": 3,
        "error": None,
    }


def _render_job(status: str = "QUEUED") -> dict:
    job = build_initial_render_job(_request())
    job["job_status"] = status
    if status == "RUNNING":
        job.update(current_stage="MARKDOWN_RENDERING", progress_percent=40)
    elif status == "COMPLETED":
        job.update(current_stage="FINALIZING", progress_percent=100, retryable=False)
    elif status == "FAILED":
        job.update(current_stage="DOCX_RENDERING", progress_percent=70, failure_code="ae.render_failed")
    elif status == "CANCELLED":
        job.update(current_stage="CANCELLED", retryable=False)
    return job


def test_build_request_is_deterministic_owner_scoped_and_content_free() -> None:
    result = _request()

    assert result["render_request_schema_version"] == (
        AE_ASYNC_ARTIFACT_RENDER_REQUEST_SCHEMA_VERSION
    )
    assert result["render_job_id"] == deterministic_async_render_job_id(
        "artifact-1", "render-request-1"
    )
    assert result["target_formats"] == ["MD", "HTML_PREVIEW"]
    assert result["owner_scope"] == {
        "tenant_id": "tenant-1",
        "owner_user_id": "owner-1",
    }
    assert result["response_id"] == "response-1"
    assert result["content_included"] is False
    assert "content" not in result


def test_build_request_accepts_no_response_lineage_and_generates_time() -> None:
    result = build_async_artifact_render_request(
        artifact_record=_artifact(),
        render_request_id="render-request-2",
        target_formats=["PDF"],
        request_id="request-2",
        trace_id="trace-2",
    )

    assert result["response_id"] is None
    assert result["target_formats"] == ["PDF"]
    assert result["requested_at"].endswith("Z")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("artifact_id"),
        lambda value: value.update(render_request_schema_version="v2"),
        lambda value: value.update(render_job_id="other"),
        lambda value: value.update(response_id=" "),
        lambda value: value.update(target_formats=[]),
        lambda value: value.update(target_formats=["TXT"]),
        lambda value: value.update(owner_scope={"tenant_id": "tenant-1"}),
        lambda value: value["owner_scope"].update(tenant_id=""),
        lambda value: value.update(source_ref=[]),
        lambda value: value["source_ref"].update(structured_draft_content_hash="bad"),
        lambda value: value.update(max_attempts=True),
        lambda value: value.update(max_attempts=0),
        lambda value: value.update(max_attempts=6),
        lambda value: value.update(links={}),
        lambda value: value.update(content_included=True),
    ],
)
def test_validate_request_fails_closed(mutation) -> None:
    request = _request()
    mutation(request)

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        validate_async_artifact_render_request(request)

    assert exc_info.value.error_code == "ae.async_artifact_render.contract_invalid"


@pytest.mark.parametrize(
    "artifact",
    [
        [],
        {**_artifact(), "owner_actor_ref": []},
        {**_artifact(), "workspace_ref": []},
        {**_artifact(), "source_refs": []},
        {**_artifact(), "source_refs": [None]},
        {**_artifact(), "artifact_id": ""},
    ],
)
def test_build_request_rejects_invalid_artifact_boundary(artifact: object) -> None:
    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_request(
            artifact_record=artifact,  # type: ignore[arg-type]
            render_request_id="render-request-1",
            target_formats=["MD"],
            request_id="request-1",
            trace_id="trace-1",
        )


def test_initial_render_job_is_queue_ready() -> None:
    result = build_initial_render_job(_request())

    assert result == {
        "render_job_id": _request()["render_job_id"],
        "artifact_id": "artifact-1",
        "artifact_version_id": None,
        "job_status": "QUEUED",
        "current_stage": "QUEUED",
        "progress_mode": "DETERMINATE",
        "progress_percent": 0,
        "retryable": True,
        "failure_code": None,
        "started_at": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.parametrize(
    ("queue_status", "render_status", "lifecycle", "progress"),
    [
        ("QUEUED", "QUEUED", "PENDING", 0),
        ("RUNNING", "RUNNING", "RUNNING", 40),
        ("SUCCEEDED", "COMPLETED", "READY", 100),
        ("FAILED", "FAILED", "BLOCKED", 70),
        ("CANCELLED", "CANCELLED", "CANCELLED", 0),
    ],
)
def test_projection_maps_consistent_dual_state(
    queue_status: str,
    render_status: str,
    lifecycle: str,
    progress: int,
) -> None:
    render_job = _render_job(render_status)
    queue_job = _queue_job(queue_status)
    if queue_status == "FAILED":
        queue_job["error"] = {
            "error_code": "ae.render_failed",
            "retryable": True,
            "dead_lettered": False,
        }

    result = build_async_artifact_render_projection(
        render_job=render_job,
        queue_job=queue_job,
    )

    assert result["render_projection_schema_version"] == (
        AE_ASYNC_ARTIFACT_RENDER_PROJECTION_SCHEMA_VERSION
    )
    assert result["lifecycle_status"] == lifecycle
    assert result["progress_percent"] == progress
    assert result["owner_scope_enforced"] is True
    assert result["rendered_content_included"] is False


@pytest.mark.parametrize(
    "mutator",
    [
        lambda render, queue: render.update(job_status="UNKNOWN"),
        lambda render, queue: queue.update(status="UNKNOWN"),
        lambda render, queue: queue.update(job_id="other"),
        lambda render, queue: render.update(job_status="RUNNING"),
        lambda render, queue: queue.update(attempt_count=True),
        lambda render, queue: queue.update(attempt_count=4),
        lambda render, queue: render.update(progress_percent=True),
        lambda render, queue: render.update(progress_percent=101),
        lambda render, queue: render.update(progress_percent=1),
        lambda render, queue: render.update(retryable="yes"),
        lambda render, queue: queue.update(error={"error_code": "secret"}),
        lambda render, queue: queue.update(
            error={"error_code": "x", "retryable": False, "dead_lettered": False}
        ),
    ],
)
def test_build_projection_rejects_inconsistent_or_unsafe_state(mutator) -> None:
    render_job = _render_job()
    queue_job = _queue_job()
    mutator(render_job, queue_job)

    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_projection(
            render_job=render_job,
            queue_job=queue_job,
        )


def test_failed_projection_requires_matching_failure_code() -> None:
    render_job = _render_job("FAILED")
    queue_job = _queue_job("FAILED")
    queue_job["error"] = {
        "error_code": "other",
        "retryable": True,
        "dead_lettered": False,
    }

    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_projection(render_job=render_job, queue_job=queue_job)


def test_completed_projection_requires_full_progress() -> None:
    render_job = _render_job("COMPLETED")
    render_job["progress_percent"] = 99

    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_projection(
            render_job=render_job,
            queue_job=_queue_job("SUCCEEDED"),
        )


@pytest.mark.parametrize(
    "failure",
    [
        "failure",
        {"error_code": "ae.render_failed", "retryable": 1, "dead_lettered": False},
        {"error_code": "ae.render_failed", "retryable": True, "dead_lettered": 0},
    ],
)
def test_failed_projection_rejects_invalid_failure_shape(failure: object) -> None:
    render_job = _render_job("FAILED")
    queue_job = _queue_job("FAILED")
    queue_job["error"] = failure

    with pytest.raises(AeAsyncArtifactRenderError):
        build_async_artifact_render_projection(render_job=render_job, queue_job=queue_job)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("artifact_id"),
        lambda value: value.update(render_projection_schema_version="v2"),
        lambda value: value.update(render_job_id=""),
        lambda value: value.update(render_job_status="UNKNOWN"),
        lambda value: value.update(queue_job_status="UNKNOWN"),
        lambda value: value.update(render_job_status="RUNNING"),
        lambda value: value.update(lifecycle_status="READY"),
        lambda value: value.update(progress_percent=-1),
        lambda value: value.update(progress_percent=1),
        lambda value: value.update(attempt_count=-1),
        lambda value: value.update(retryable=1),
        lambda value: value.update(failure={"error_code": "x", "retryable": False, "dead_lettered": False}),
        lambda value: value.update(links={}),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(rendered_content_included=True),
    ],
)
def test_validate_projection_fails_closed(mutation) -> None:
    projection = build_async_artifact_render_projection(
        render_job=_render_job(),
        queue_job=_queue_job(),
    )
    mutation(projection)

    with pytest.raises(AeAsyncArtifactRenderError):
        validate_async_artifact_render_projection(projection)


def test_projection_validation_returns_detached_copy() -> None:
    projection = build_async_artifact_render_projection(
        render_job=_render_job(),
        queue_job=_queue_job(),
    )
    normalized = validate_async_artifact_render_projection(projection)
    normalized["links"]["artifact"] = "/changed"

    assert projection["links"]["artifact"] != normalized["links"]["artifact"]


def test_error_string_uses_safe_detail() -> None:
    error = AeAsyncArtifactRenderError("code", "safe detail")
    assert str(error) == "safe detail"


def test_validation_does_not_mutate_request() -> None:
    request = _request()
    original = deepcopy(request)
    validate_async_artifact_render_request(request)
    assert request == original
