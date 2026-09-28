from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.generation_progress import (
    AE_GENERATION_PROGRESS_SCHEMA_VERSION,
    AeGenerationProgressError,
    build_generation_progress_projection,
    build_generation_recovery_plan,
    validate_generation_progress_projection,
)


def _job(status: str = "QUEUED", *, retryable: bool = True) -> dict:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": "cx.generation.failed",
            "retryable": retryable,
            "dead_lettered": not retryable,
        }
    return {
        "job_id": "job-1043",
        "cx_generation_id": "generation-1043",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-1043",
            "async_job": "/api/v1/generation-jobs/job-1043",
        },
        "error": error,
    }


def _projection(status: str = "QUEUED", *, retryable: bool = True) -> dict:
    return build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )


@pytest.mark.parametrize(
    (
        "status",
        "event_type",
        "stage",
        "job_status",
        "cancellable",
        "terminal",
    ),
    [
        (
            "QUEUED",
            "generation.request.accepted",
            "MO_ADMISSION_WAITING",
            "QUEUED",
            True,
            False,
        ),
        (
            "RUNNING",
            "generation.provider.admitted",
            "GENERATING",
            "RUNNING",
            True,
            False,
        ),
        (
            "SUCCEEDED",
            "generation.provider.completed",
            "FINALIZING",
            "COMPLETED",
            False,
            False,
        ),
        (
            "FAILED",
            "generation.failed",
            "GENERATION_FAILED",
            "FAILED",
            False,
            True,
        ),
        (
            "CANCELLED",
            "generation.cancelled",
            "CANCELLED",
            "CANCELLED",
            False,
            True,
        ),
    ],
)
def test_progress_projection_maps_cx_job_states(
    status: str,
    event_type: str,
    stage: str,
    job_status: str,
    cancellable: bool,
    terminal: bool,
) -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(status),
    )

    assert result["progress_schema_version"] == AE_GENERATION_PROGRESS_SCHEMA_VERSION
    assert result["event_type"] == event_type
    assert result["current_stage"] == stage
    assert result["job_status"] == job_status
    assert result["cancellable"] is cancellable
    assert result["terminal"] is terminal
    assert result["progress_mode"] == "INDETERMINATE"
    assert result["progress_percent"] is None
    assert result["next_poll_after_seconds"] == (None if terminal else 2)
    assert result["owner_scope_enforced"] is True
    assert result["content_included"] is False


def test_completed_handoff_uses_determinate_terminal_progress() -> None:
    projection = _projection("SUCCEEDED")
    projection.update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )

    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=projection,
    )

    assert result["event_type"] == "generation.completed"
    assert result["current_stage"] == "COMPLETED"
    assert result["progress_mode"] == "DETERMINATE"
    assert result["progress_percent"] == 100
    assert result["terminal"] is True
    assert result["recovery"]["action"] == "NONE"


@pytest.mark.parametrize(
    ("status", "retryable", "action", "eligible", "reason"),
    [
        ("QUEUED", True, "WAIT", False, "GENERATION_IN_PROGRESS"),
        ("FAILED", True, "RETRY_AS_CHILD", True, "RETRYABLE_TERMINAL_STATE"),
        (
            "FAILED",
            False,
            "REVIEW_REQUIRED",
            False,
            "NON_RETRYABLE_TERMINAL_STATE",
        ),
    ],
)
def test_recovery_plan_is_deterministic(
    status: str,
    retryable: bool,
    action: str,
    eligible: bool,
    reason: str,
) -> None:
    result = build_generation_recovery_plan(
        _projection(status, retryable=retryable)
    )

    assert result["action"] == action
    assert result["eligible"] is eligible
    assert result["reason_code"] == reason
    assert result["new_interaction_required"] is eligible
    assert result["parent_lineage_required"] is eligible
    assert result["input_hash_required"] is eligible


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("interaction_id"),
        lambda value: value.update(progress_schema_version="v2"),
        lambda value: value.update(interaction_id=""),
        lambda value: value.update(cx_job_status="UNKNOWN"),
        lambda value: value.update(event_type="generation.completed"),
        lambda value: value.update(current_stage="COMPLETED"),
        lambda value: value.update(terminal=True),
        lambda value: value.update(progress_mode="DETERMINATE"),
        lambda value: value.update(cancellable=False),
        lambda value: value.update(next_poll_after_seconds=None),
        lambda value: value.update(owner_scope_enforced=False),
        lambda value: value.update(content_included=True),
        lambda value: value.update(raw_failure_detail_included=True),
        lambda value: value.update(attempt_count=True),
        lambda value: value.update(max_attempts=0),
        lambda value: value.update(recovery={}),
    ],
)
def test_progress_validation_rejects_invalid_shape_and_invariants(mutation) -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(),
    )
    mutation(result)

    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(result)


def test_progress_validation_rejects_private_material_recursively() -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(),
    )
    result["links"]["content"] = "private output"

    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(result)


def test_progress_validation_returns_detached_copy() -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(),
    )
    normalized = validate_generation_progress_projection(result)

    normalized["links"]["generation"] = "/api/v1/changed"
    assert normalized != result


def test_progress_builder_rejects_invalid_interaction_and_projection() -> None:
    with pytest.raises(AeGenerationProgressError):
        build_generation_progress_projection(
            interaction_id=" ",
            async_generation=_projection(),
        )
    with pytest.raises(Exception):
        build_generation_progress_projection(
            interaction_id="interaction-1043",
            async_generation={},
        )


def test_error_string_uses_safe_detail() -> None:
    error = AeGenerationProgressError("code", "safe detail")
    assert str(error) == "safe detail"


def test_recovery_validation_rejects_tampered_plan() -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection("FAILED"),
    )
    tampered = deepcopy(result)
    tampered["recovery"]["eligible"] = False

    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(tampered)


def test_completed_progress_rejects_invalid_determinate_value() -> None:
    projection = _projection("SUCCEEDED")
    projection.update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=projection,
    )
    result["progress_percent"] = 99

    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(result)


def test_recovery_validation_rejects_schema_and_invalid_source_state() -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(),
    )
    wrong_schema = deepcopy(result)
    wrong_schema["recovery"]["recovery_plan_schema_version"] = "v2"
    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(wrong_schema)

    invalid_state = deepcopy(result)
    invalid_state["lifecycle_status"] = "UNKNOWN"
    invalid_state["cancellable"] = False
    with pytest.raises(AeGenerationProgressError) as exc_info:
        validate_generation_progress_projection(invalid_state)
    assert "source state" in exc_info.value.detail


def test_private_scanner_handles_safe_list_before_contract_rejection() -> None:
    result = build_generation_progress_projection(
        interaction_id="interaction-1043",
        async_generation=_projection(),
    )
    result["links"]["generation"] = ["safe-but-invalid-link"]

    with pytest.raises(AeGenerationProgressError):
        validate_generation_progress_projection(result)
