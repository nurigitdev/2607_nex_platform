from __future__ import annotations

from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.generation_progress import validate_generation_progress_projection
from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


AE_GENERATION_LIFECYCLE_OBSERVABILITY_SCHEMA_VERSION = (
    "ae_generation_lifecycle_observability.v1"
)
AE_GENERATION_LIFECYCLE_EVENT = "ae.generation_lifecycle.action_observed"
GENERATION_LIFECYCLE_ACTIONS = frozenset(
    {
        "PROGRESS_OBSERVED",
        "CANCELLATION_ACCEPTED",
        "CANCELLATION_RECONCILED",
        "RECOVERY_PLANNED",
        "RETRY_ADMITTED",
    }
)


def observe_generation_lifecycle_action(
    emitter: OperationalEventEmitter,
    *,
    action: str,
    progress: Mapping[str, Any],
    request_id: str | None,
    trace_id: str | None,
) -> OperationalEventEmitResult:
    if action not in GENERATION_LIFECYCLE_ACTIONS:
        raise ValueError(f"unsupported generation lifecycle action: {action}")
    projection = validate_generation_progress_projection(progress)
    interaction_id = projection["interaction_id"]
    recovery = projection["recovery"]
    severity = (
        "WARNING"
        if projection["cx_job_status"] in {"FAILED", "CANCELLED"}
        else "INFO"
    )
    return emitter.safe_emit(
        event_type=AE_GENERATION_LIFECYCLE_EVENT,
        severity=severity,
        message="AE generation lifecycle action observed.",
        trace_id=_optional_text(trace_id),
        request_id=_optional_text(request_id),
        subject_ref=build_subject_ref("ae.chat_interaction", interaction_id),
        details={
            "observability_schema_version": (
                AE_GENERATION_LIFECYCLE_OBSERVABILITY_SCHEMA_VERSION
            ),
            "action": action,
            "cx_job_status": projection["cx_job_status"],
            "lifecycle_status": projection["lifecycle_status"],
            "current_stage": projection["current_stage"],
            "terminal": projection["terminal"],
            "cancellable": projection["cancellable"],
            "retryable": projection["retryable"],
            "attempt_count": projection["attempt_count"],
            "max_attempts": projection["max_attempts"],
            "recovery_action": recovery["action"],
            "recovery_eligible": recovery["eligible"],
            "prompt_content_included": False,
            "response_content_included": False,
            "owner_identity_included": False,
            "provider_detail_included": False,
            "raw_failure_detail_included": False,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "ae-generation-lifecycle:"
                f"{interaction_id}:{action}:{projection['cx_job_status']}:"
                f"{projection['attempt_count']}:{recovery['action']}",
            )
        ),
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
