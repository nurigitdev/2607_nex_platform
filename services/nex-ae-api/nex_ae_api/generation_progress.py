from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from nex_ae_api.async_generation import validate_async_generation_projection


AE_GENERATION_PROGRESS_SCHEMA_VERSION = "ae_generation_progress.v1"
AE_GENERATION_RECOVERY_PLAN_SCHEMA_VERSION = "ae_generation_recovery_plan.v1"

_PROGRESS_FIELDS = frozenset(
    {
        "progress_schema_version",
        "interaction_id",
        "job_id",
        "cx_generation_id",
        "cx_job_status",
        "lifecycle_status",
        "event_type",
        "job_status",
        "current_stage",
        "progress_mode",
        "progress_percent",
        "message_key",
        "attempt_count",
        "max_attempts",
        "retryable",
        "cancellable",
        "terminal",
        "next_action",
        "next_poll_after_seconds",
        "handoff_status",
        "error",
        "links",
        "recovery",
        "owner_scope_enforced",
        "content_included",
        "raw_failure_detail_included",
    }
)
_RECOVERY_FIELDS = frozenset(
    {
        "recovery_plan_schema_version",
        "action",
        "eligible",
        "reason_code",
        "new_interaction_required",
        "parent_lineage_required",
        "input_hash_required",
    }
)
_STATUS_PRESENTATION = {
    "QUEUED": {
        "event_type": "generation.request.accepted",
        "job_status": "QUEUED",
        "current_stage": "MO_ADMISSION_WAITING",
        "message_key": "generation.progress.queued",
    },
    "RUNNING": {
        "event_type": "generation.provider.admitted",
        "job_status": "RUNNING",
        "current_stage": "GENERATING",
        "message_key": "generation.progress.generating",
    },
    "SUCCEEDED": {
        "event_type": "generation.provider.completed",
        "job_status": "COMPLETED",
        "current_stage": "FINALIZING",
        "message_key": "generation.progress.finalizing",
    },
    "FAILED": {
        "event_type": "generation.failed",
        "job_status": "FAILED",
        "current_stage": "GENERATION_FAILED",
        "message_key": "generation.progress.failed",
    },
    "CANCELLED": {
        "event_type": "generation.cancelled",
        "job_status": "CANCELLED",
        "current_stage": "CANCELLED",
        "message_key": "generation.progress.cancelled",
    },
}
_FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "messages",
        "content",
        "output_text",
        "raw_prompt",
        "raw_output",
        "raw_error_detail",
        "provider_endpoint",
        "provider_url",
        "api_key",
        "authorization",
        "cookie",
        "evidence_text",
    }
)


@dataclass(frozen=True)
class AeGenerationProgressError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_generation_progress_projection(
    *,
    interaction_id: str,
    async_generation: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_interaction_id = _required_text(interaction_id, "interaction_id")
    projection = validate_async_generation_projection(async_generation)
    presentation = dict(_STATUS_PRESENTATION[projection["cx_job_status"]])
    completed = projection["lifecycle_status"] == "COMPLETED"
    if completed:
        presentation.update(
            event_type="generation.completed",
            current_stage="COMPLETED",
            message_key="generation.progress.completed",
        )
    terminal = projection["lifecycle_status"] in {"COMPLETED", "BLOCKED"}
    result = {
        "progress_schema_version": AE_GENERATION_PROGRESS_SCHEMA_VERSION,
        "interaction_id": normalized_interaction_id,
        "job_id": projection["job_id"],
        "cx_generation_id": projection["cx_generation_id"],
        "cx_job_status": projection["cx_job_status"],
        "lifecycle_status": projection["lifecycle_status"],
        **presentation,
        "progress_mode": "DETERMINATE" if completed else "INDETERMINATE",
        "progress_percent": 100 if completed else None,
        "attempt_count": projection["attempt_count"],
        "max_attempts": projection["max_attempts"],
        "retryable": projection["retryable"],
        "cancellable": (
            projection["lifecycle_status"] == "PENDING"
            and projection["cx_job_status"] in {"QUEUED", "RUNNING"}
        ),
        "terminal": terminal,
        "next_action": projection["next_action"],
        "next_poll_after_seconds": None if terminal else 2,
        "handoff_status": projection["handoff_status"],
        "error": deepcopy(projection["error"]),
        "links": deepcopy(projection["links"]),
        "recovery": build_generation_recovery_plan(projection),
        "owner_scope_enforced": True,
        "content_included": False,
        "raw_failure_detail_included": False,
    }
    return validate_generation_progress_projection(result)


def build_generation_recovery_plan(
    async_generation: Mapping[str, Any],
) -> dict[str, Any]:
    projection = validate_async_generation_projection(async_generation)
    lifecycle = projection["lifecycle_status"]
    if lifecycle == "PENDING":
        action, eligible, reason = "WAIT", False, "GENERATION_IN_PROGRESS"
    elif lifecycle == "COMPLETED":
        action, eligible, reason = "NONE", False, "GENERATION_COMPLETED"
    elif projection["retryable"]:
        action, eligible, reason = (
            "RETRY_AS_CHILD",
            True,
            "RETRYABLE_TERMINAL_STATE",
        )
    else:
        action, eligible, reason = (
            "REVIEW_REQUIRED",
            False,
            "NON_RETRYABLE_TERMINAL_STATE",
        )
    return {
        "recovery_plan_schema_version": AE_GENERATION_RECOVERY_PLAN_SCHEMA_VERSION,
        "action": action,
        "eligible": eligible,
        "reason_code": reason,
        "new_interaction_required": eligible,
        "parent_lineage_required": eligible,
        "input_hash_required": eligible,
    }


def validate_generation_progress_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROGRESS_FIELDS:
        raise _invalid("AE generation progress projection has an invalid shape.")
    result = deepcopy(dict(value))
    if result["progress_schema_version"] != AE_GENERATION_PROGRESS_SCHEMA_VERSION:
        raise _invalid("AE generation progress schema version is invalid.")
    for field in ("interaction_id", "job_id", "cx_generation_id"):
        result[field] = _required_text(result[field], field)
    status = result["cx_job_status"]
    if status not in _STATUS_PRESENTATION:
        raise _invalid("AE generation progress CX job status is invalid.")
    expected = dict(_STATUS_PRESENTATION[status])
    completed = result["lifecycle_status"] == "COMPLETED"
    if completed:
        expected.update(
            event_type="generation.completed",
            current_stage="COMPLETED",
            message_key="generation.progress.completed",
        )
    for field, expected_value in expected.items():
        if result[field] != expected_value:
            raise _invalid(f"AE generation progress {field} is inconsistent.")
    terminal = result["lifecycle_status"] in {"COMPLETED", "BLOCKED"}
    if result["terminal"] is not terminal:
        raise _invalid("AE generation progress terminal flag is inconsistent.")
    if completed:
        if (
            result["progress_mode"] != "DETERMINATE"
            or result["progress_percent"] != 100
        ):
            raise _invalid("Completed generation progress must be determinate.")
    elif (
        result["progress_mode"] != "INDETERMINATE"
        or result["progress_percent"] is not None
    ):
        raise _invalid("Non-completed generation progress must be indeterminate.")
    expected_cancellable = (
        result["lifecycle_status"] == "PENDING"
        and status in {"QUEUED", "RUNNING"}
    )
    if result["cancellable"] is not expected_cancellable:
        raise _invalid("AE generation progress cancellable flag is inconsistent.")
    expected_poll = None if terminal else 2
    if result["next_poll_after_seconds"] != expected_poll:
        raise _invalid("AE generation progress polling interval is inconsistent.")
    if (
        result["owner_scope_enforced"] is not True
        or result["content_included"] is not False
        or result["raw_failure_detail_included"] is not False
    ):
        raise _invalid("AE generation progress privacy flags are invalid.")
    _validate_attempts(result)
    if _contains_private_material(result):
        raise _invalid("AE generation progress contains private material.")
    _validate_recovery(result["recovery"], result)
    return result


def _validate_recovery(value: object, progress: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != _RECOVERY_FIELDS:
        raise _invalid("AE generation recovery plan has an invalid shape.")
    if value["recovery_plan_schema_version"] != (
        AE_GENERATION_RECOVERY_PLAN_SCHEMA_VERSION
    ):
        raise _invalid("AE generation recovery schema version is invalid.")
    try:
        expected = build_generation_recovery_plan(
            {
                "async_generation_schema_version": "ae_async_generation.v1",
                "execution_strategy": "ASYNCHRONOUS",
                "lifecycle_status": progress["lifecycle_status"],
                "admission_status": "ENQUEUED",
                "job_id": progress["job_id"],
                "cx_generation_id": progress["cx_generation_id"],
                "cx_job_status": progress["cx_job_status"],
                "attempt_count": progress["attempt_count"],
                "max_attempts": progress["max_attempts"],
                "retryable": progress["retryable"],
                "handoff_status": progress["handoff_status"],
                "next_action": progress["next_action"],
                "error": progress["error"],
                "links": progress["links"],
                "owner_scope_enforced": True,
                "content_included": False,
            }
        )
    except ValueError as exc:
        raise _invalid("AE generation recovery source state is invalid.") from exc
    if dict(value) != expected:
        raise _invalid("AE generation recovery plan is inconsistent.")


def _validate_attempts(value: Mapping[str, Any]) -> None:
    attempt_count = value.get("attempt_count")
    max_attempts = value.get("max_attempts")
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count < 0
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
        or attempt_count > max_attempts
    ):
        raise _invalid("AE generation progress attempt counts are invalid.")


def _contains_private_material(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).strip().lower() in _FORBIDDEN_KEYS
            or _contains_private_material(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_private_material(item) for item in value)
    return False


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _invalid(detail: str) -> AeGenerationProgressError:
    return AeGenerationProgressError(
        error_code="ae.generation_progress.contract_invalid",
        detail=detail,
    )
