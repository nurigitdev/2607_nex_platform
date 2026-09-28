from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from nex_ae_api.async_generation import (
    AE_ASYNC_GENERATION_SCHEMA_VERSION,
    ASYNCHRONOUS,
    SYNCHRONOUS,
    AeAsyncGenerationError,
    build_async_generation_projection,
    refresh_async_generation_projection,
    resolve_execution_strategy,
    validate_async_generation_projection,
)


def _job(status: str = "QUEUED") -> dict:
    return {
        "async_generation_schema_version": "cx_async_generation_job.v1",
        "job_id": "job-1",
        "cx_generation_id": "generation-1",
        "status": status,
        "attempt_count": 0,
        "max_attempts": 3,
        "retryable": True,
        "available_at": None,
        "created_at": "2026-09-28T00:00:00Z",
        "updated_at": "2026-09-28T00:00:00Z",
        "links": {
            "generation": "/api/v1/generations/generation-1",
            "async_job": "/api/v1/generation-jobs/job-1",
        },
        "error": None,
    }


def _admission(status: str = "QUEUED") -> dict:
    return {"admission_status": "ENQUEUED", "job": _job(status), "generation": None}


def _handoff(status: str = "PENDING") -> dict:
    job_status = {"PENDING": "RUNNING", "READY": "SUCCEEDED", "BLOCKED": "FAILED"}[
        status
    ]
    job = _job(job_status)
    job["attempt_count"] = 1
    if status == "BLOCKED":
        job["error"] = {
            "error_code": "cx.failed",
            "retryable": True,
            "dead_lettered": False,
        }
    generation = None
    content = None
    if status == "READY":
        text = "Owner answer."
        encoded = text.encode()
        generation = {"cx_generation_id": "generation-1", "status": "COMPLETED"}
        content = {
            "cx_generation_id": "generation-1",
            "content_type": "text/plain",
            "content": text,
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "owner_scope_enforced": True,
        }
    return {
        "handoff_schema_version": "cx_generation_handoff.v1",
        "handoff_status": status,
        "next_action": {
            "PENDING": "POLL_GENERATION_JOB",
            "READY": "PRESENT_GENERATION_TO_OWNER",
            "BLOCKED": "RETRY_OR_REPAIR_GENERATION",
        }[status],
        "job": job,
        "generation": generation,
        "content": content,
        "owner_scope_enforced": True,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, SYNCHRONOUS),
        ({"generation": None}, SYNCHRONOUS),
        ({"generation": {}}, SYNCHRONOUS),
        ({"generation": {"execution_strategy": " asynchronous "}}, ASYNCHRONOUS),
        ({"generation": {"execution_strategy": "SYNCHRONOUS"}}, SYNCHRONOUS),
    ],
)
def test_resolve_execution_strategy(payload: dict, expected: str) -> None:
    assert resolve_execution_strategy(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"generation": []},
        {"generation": {"execution_strategy": None}},
        {"generation": {"execution_strategy": " "}},
        {"generation": {"execution_strategy": "DEFERRED"}},
    ],
)
def test_resolve_execution_strategy_rejects_invalid_values(payload: object) -> None:
    with pytest.raises(AeAsyncGenerationError) as exc_info:
        resolve_execution_strategy(payload)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code.endswith("execution_strategy_invalid")


@pytest.mark.parametrize(
    ("job_status", "lifecycle", "action"),
    [
        ("QUEUED", "PENDING", "POLL_GENERATION_HANDOFF"),
        ("RUNNING", "PENDING", "POLL_GENERATION_HANDOFF"),
        ("SUCCEEDED", "PENDING", "POLL_GENERATION_HANDOFF"),
        ("FAILED", "BLOCKED", "RETRY_OR_REVIEW_GENERATION"),
        ("CANCELLED", "BLOCKED", "RETRY_OR_REVIEW_GENERATION"),
    ],
)
def test_build_projection_maps_cx_job_state(
    job_status: str, lifecycle: str, action: str
) -> None:
    admission = _admission(job_status)
    if job_status in {"FAILED", "CANCELLED"}:
        admission["job"]["error"] = {
            "error_code": "cx.cancelled",
            "retryable": False,
            "dead_lettered": False,
        }

    result = build_async_generation_projection(admission)

    assert result["async_generation_schema_version"] == (
        AE_ASYNC_GENERATION_SCHEMA_VERSION
    )
    assert result["execution_strategy"] == ASYNCHRONOUS
    assert result["lifecycle_status"] == lifecycle
    assert result["next_action"] == action
    assert result["owner_scope_enforced"] is True
    assert result["content_included"] is False
    assert "generation" not in result


def test_build_projection_accepts_join_and_replay_with_durable_job() -> None:
    for admission_status in ("JOINED", "REPLAYED"):
        admission = _admission("RUNNING")
        admission["admission_status"] = admission_status
        assert build_async_generation_projection(admission)["admission_status"] == (
            admission_status
        )


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda value: value.update(admission_status="UNKNOWN"), "contract_invalid"),
        (lambda value: value.update(job=None), "durable_job_missing"),
        (lambda value: value["job"].pop("job_id"), "contract_invalid"),
        (lambda value: value["job"].update(job_id=""), "contract_invalid"),
        (lambda value: value["job"].update(status="UNKNOWN"), "contract_invalid"),
        (lambda value: value["job"].update(attempt_count=True), "contract_invalid"),
        (lambda value: value["job"].update(attempt_count=4), "contract_invalid"),
        (lambda value: value["job"].update(retryable="yes"), "contract_invalid"),
        (
            lambda value: value["job"].update(links={"content": "/api/v1/private"}),
            "contract_invalid",
        ),
        (
            lambda value: value["job"].update(
                links={"generation": "https://outside.example/generation"}
            ),
            "contract_invalid",
        ),
        (lambda value: value["job"].update(error={"detail": "secret"}), "contract_invalid"),
    ],
)
def test_build_projection_fails_closed_for_invalid_cx_admission(
    mutation, error_code: str
) -> None:
    admission = _admission()
    mutation(admission)

    with pytest.raises(AeAsyncGenerationError) as exc_info:
        build_async_generation_projection(admission)

    assert exc_info.value.error_code.endswith(error_code)


def test_build_projection_requires_mapping() -> None:
    with pytest.raises(AeAsyncGenerationError):
        build_async_generation_projection([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("job_id"),
        lambda value: value.update(async_generation_schema_version="v2"),
        lambda value: value.update(execution_strategy=SYNCHRONOUS),
        lambda value: value.update(admission_status="UNKNOWN"),
        lambda value: value.update(job_id=""),
        lambda value: value.update(cx_job_status="UNKNOWN"),
        lambda value: value.update(max_attempts=0),
        lambda value: value.update(retryable=1),
        lambda value: value.update(handoff_status="READY"),
        lambda value: value.update(lifecycle_status="COMPLETED"),
        lambda value: value.update(next_action="PRESENT"),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(content_included=True),
        lambda value: value.update(error={"error_code": "", "retryable": False, "dead_lettered": False}),
        lambda value: value.update(error={"error_code": "x", "retryable": 1, "dead_lettered": False}),
        lambda value: value.update(links=[]),
    ],
)
def test_validate_projection_rejects_invalid_shape_or_invariant(mutation) -> None:
    projection = build_async_generation_projection(_admission())
    mutation(projection)

    with pytest.raises(AeAsyncGenerationError):
        validate_async_generation_projection(projection)


def test_validate_projection_returns_detached_copy() -> None:
    projection = build_async_generation_projection(_admission())
    normalized = validate_async_generation_projection(projection)

    normalized["links"]["generation"] = "/api/v1/changed"
    assert projection["links"]["generation"] != normalized["links"]["generation"]


@pytest.mark.parametrize(
    ("handoff_status", "lifecycle", "action", "has_content"),
    [
        ("PENDING", "PENDING", "POLL_GENERATION_HANDOFF", False),
        ("READY", "COMPLETED", "PRESENT_GENERATION_TO_OWNER", True),
        ("BLOCKED", "BLOCKED", "RETRY_OR_REVIEW_GENERATION", False),
    ],
)
def test_refresh_projection_maps_valid_handoff(
    handoff_status: str, lifecycle: str, action: str, has_content: bool
) -> None:
    current = build_async_generation_projection(_admission())

    projection, result = refresh_async_generation_projection(
        current, _handoff(handoff_status)
    )

    assert projection["lifecycle_status"] == lifecycle
    assert projection["next_action"] == action
    assert projection["handoff_status"] == handoff_status
    assert result["handoff_status"] == handoff_status
    assert (result["content"] is not None) is has_content
    assert "content" not in projection


def test_refresh_projection_rejects_lineage_mismatch() -> None:
    current = build_async_generation_projection(_admission())
    handoff = _handoff()
    handoff["job"]["job_id"] = "other-job"

    with pytest.raises(AeAsyncGenerationError):
        refresh_async_generation_projection(current, handoff)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(handoff_schema_version="old"),
        lambda value: value.update(handoff_status="UNKNOWN"),
        lambda value: value.update(next_action="UNKNOWN"),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(job=[]),
        lambda value: value.update(content={"content": "leak"}),
    ],
)
def test_refresh_projection_rejects_invalid_handoff_shape(mutation) -> None:
    current = build_async_generation_projection(_admission())
    handoff = _handoff()
    mutation(handoff)

    with pytest.raises(AeAsyncGenerationError):
        refresh_async_generation_projection(current, handoff)


def test_refresh_projection_rejects_non_mapping_handoff() -> None:
    current = build_async_generation_projection(_admission())
    with pytest.raises(AeAsyncGenerationError):
        refresh_async_generation_projection(current, [])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(generation=None),
        lambda value: value["generation"].update(cx_generation_id="other"),
        lambda value: value["generation"].update(status="RUNNING"),
        lambda value: value.update(content=None),
        lambda value: value["content"].update(cx_generation_id="other"),
        lambda value: value["content"].update(owner_scope_enforced=False),
        lambda value: value["content"].update(content=1),
        lambda value: value["content"].update(content_type=""),
        lambda value: value["content"].update(content_sha256="bad"),
        lambda value: value["content"].update(size_bytes=True),
        lambda value: value["content"].update(size_bytes=-1),
        lambda value: value["content"].update(size_bytes=999),
    ],
)
def test_refresh_projection_rejects_invalid_ready_payload(mutation) -> None:
    current = build_async_generation_projection(_admission())
    handoff = _handoff("READY")
    mutation(handoff)

    with pytest.raises(AeAsyncGenerationError):
        refresh_async_generation_projection(current, handoff)


def test_projection_rejects_unknown_handoff_status() -> None:
    projection = build_async_generation_projection(_admission())
    projection["handoff_status"] = "UNKNOWN"
    with pytest.raises(AeAsyncGenerationError):
        validate_async_generation_projection(projection)


def test_refresh_rejects_inconsistent_job_and_handoff_status() -> None:
    current = build_async_generation_projection(_admission())
    handoff = _handoff("PENDING")
    handoff["job"]["status"] = "FAILED"
    handoff["job"]["error"] = {
        "error_code": "cx.failed",
        "retryable": True,
        "dead_lettered": False,
    }
    with pytest.raises(AeAsyncGenerationError):
        refresh_async_generation_projection(current, handoff)


def test_error_string_is_detail() -> None:
    error = AeAsyncGenerationError("code", "detail")
    assert str(error) == "detail"
