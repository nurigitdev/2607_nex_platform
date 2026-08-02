from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


ALLOWED_EVENT_TYPES = {
    "generation.request.accepted",
    "generation.intent.selected",
    "generation.retrieval.requested",
    "generation.retrieval.ready",
    "generation.retrieval.no_answer",
    "generation.template.selected",
    "generation.prompt.packaged",
    "generation.provider.admitted",
    "generation.provider.streaming_delta",
    "generation.provider.completed",
    "generation.draft.validating",
    "generation.citation.validating",
    "generation.artifact.rendering",
    "generation.artifact.ready",
    "generation.completed",
    "generation.failed",
    "generation.cancelled",
}
ALLOWED_JOB_STATUSES = {
    "PENDING",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "TIMEOUT",
    "CANCELLED",
}
ALLOWED_PROGRESS_MODES = {"DETERMINATE", "INDETERMINATE", "STREAMING"}
EVENT_STAGE_BY_TYPE = {
    "generation.request.accepted": "INTAKE",
    "generation.intent.selected": "INTENT_DETECTED",
    "generation.retrieval.requested": "RETRIEVAL_REQUESTED",
    "generation.retrieval.ready": "CONTEXT_PACKAGED",
    "generation.retrieval.no_answer": "CONTEXT_PACKAGED",
    "generation.template.selected": "TEMPLATE_SELECTED",
    "generation.prompt.packaged": "PROMPT_ASSEMBLING",
    "generation.provider.admitted": "MO_ADMISSION_WAITING",
    "generation.provider.streaming_delta": "GENERATING",
    "generation.provider.completed": "GENERATING",
    "generation.draft.validating": "DRAFT_VALIDATING",
    "generation.citation.validating": "CITATION_VALIDATING",
    "generation.artifact.rendering": "ARTIFACT_RENDERING",
    "generation.artifact.ready": "FINALIZING",
    "generation.completed": "COMPLETED",
}
MESSAGE_KEY_BY_EVENT = {
    "generation.request.accepted": "generation.progress.request_accepted",
    "generation.retrieval.ready": "generation.progress.retrieval_ready",
    "generation.prompt.packaged": "generation.progress.prompt_packaged",
    "generation.provider.completed": "generation.progress.provider_completed",
    "generation.draft.validating": "generation.progress.draft_validating",
    "generation.citation.validating": "generation.progress.citation_validating",
    "generation.completed": "generation.progress.completed",
}
SAFE_MESSAGE_BY_EVENT = {
    "generation.request.accepted": "Generation request accepted.",
    "generation.retrieval.ready": "Retrieval package validated.",
    "generation.prompt.packaged": "Prompt package assembled.",
    "generation.provider.completed": "Provider generation completed.",
    "generation.draft.validating": "Structured draft validated.",
    "generation.citation.validating": "Citation claims validated.",
    "generation.completed": "Generation completed.",
}
FORBIDDEN_DETAIL_KEYS = {
    "prompt",
    "messages",
    "content",
    "content_text",
    "source_text",
    "output_text",
    "raw_prompt",
    "raw_output",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "authorization",
    "cookie",
}
FORBIDDEN_DETAIL_KEY_FRAGMENTS = {
    "api_key",
    "bearer",
    "password",
    "secret",
}


def build_generation_progress_event(
    *,
    event_type: str,
    event_source_service: str,
    trace_id: str,
    request_id: str,
    sequence_no: int,
    job_status: str,
    progress_mode: str = "INDETERMINATE",
    retryable: bool = False,
    current_stage: str | None = None,
    job_id: str | None = None,
    cx_generation_id: str | None = None,
    mo_generation_id: str | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
    progress_percent: int | None = None,
    message_key: str | None = None,
    safe_message: str | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported generation progress event type: {event_type}")
    if job_status not in ALLOWED_JOB_STATUSES:
        raise ValueError(f"unsupported generation progress job status: {job_status}")
    if progress_mode not in ALLOWED_PROGRESS_MODES:
        raise ValueError(f"unsupported generation progress mode: {progress_mode}")
    if sequence_no < 1:
        raise ValueError("sequence_no must be positive")
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        raise ValueError("progress_percent must be between 0 and 100")

    stage = current_stage or EVENT_STAGE_BY_TYPE.get(event_type)
    if stage is None:
        raise ValueError(f"current_stage is required for {event_type}")
    expected_stage = EVENT_STAGE_BY_TYPE.get(event_type)
    if expected_stage is not None and stage != expected_stage:
        raise ValueError(f"{event_type} must use current_stage {expected_stage}")

    event = {
        "event_schema_version": "generation_progress_event.v1",
        "event_id": deterministic_event_id(
            event_source_service=event_source_service,
            cx_generation_id=cx_generation_id,
            job_id=job_id,
            event_type=event_type,
            sequence_no=sequence_no,
        ),
        "event_type": event_type,
        "event_source_service": event_source_service,
        "trace_id": trace_id,
        "request_id": request_id,
        "occurred_at": occurred_at or _utc_now(),
        "sequence_no": sequence_no,
        "job_status": job_status,
        "current_stage": stage,
        "progress_mode": progress_mode,
        "message_key": message_key or MESSAGE_KEY_BY_EVENT.get(event_type, event_type),
        "retryable": retryable,
    }
    optional_values = {
        "job_id": job_id,
        "cx_generation_id": cx_generation_id,
        "mo_generation_id": mo_generation_id,
        "artifact_id": artifact_id,
        "artifact_version_id": artifact_version_id,
        "progress_percent": progress_percent,
        "safe_message": safe_message or SAFE_MESSAGE_BY_EVENT.get(event_type),
        "details": safe_progress_details(details or {}),
    }
    event.update(
        {
            key: value
            for key, value in optional_values.items()
            if value is not None and value != {}
        }
    )
    return event


def build_cx_generation_progress_events(
    *,
    source_payload: dict[str, Any],
    mo_payload: dict[str, Any],
    mo_response: dict[str, Any],
    compatibility_rule: dict[str, Any],
    retrieval_package: dict[str, Any] | None,
    structured_draft: dict[str, Any],
    request_id: str,
    trace_id: str,
) -> list[dict[str, Any]]:
    cx_generation_id = mo_payload["cx_generation_id"]
    events: list[dict[str, Any]] = []

    def add(
        event_type: str,
        *,
        job_status: str = "RUNNING",
        details: dict[str, Any] | None = None,
        mo_generation_id: str | None = None,
    ) -> None:
        events.append(
            build_generation_progress_event(
                event_type=event_type,
                event_source_service="nex-cx",
                trace_id=trace_id,
                request_id=request_id,
                sequence_no=len(events) + 1,
                job_status=job_status,
                cx_generation_id=cx_generation_id,
                mo_generation_id=mo_generation_id,
                details=details,
            )
        )

    add(
        "generation.request.accepted",
        details={
            "execution_mode": compatibility_rule["execution_mode"],
            "generation_profile": compatibility_rule["generation_profile"],
            "compatibility_rule_id": compatibility_rule["compatibility_rule_id"],
            "grounding_required": compatibility_rule["grounding_required"],
        },
    )
    if retrieval_package is not None:
        add(
            "generation.retrieval.ready",
            details={
                "retrieval_package_id": retrieval_package["retrieval_package_id"],
                "retrieval_package_hash": retrieval_package["package_hash"],
                "evidence_item_count": len(retrieval_package.get("evidence_items", [])),
                "selected_evidence_count": selected_evidence_count(source_payload),
            },
        )
    add(
        "generation.prompt.packaged",
        details={
            "provider_prompt_package_hash": mo_payload["provider_prompt_package_hash"],
            "generation_request_hash": mo_payload["metadata"]["generation_request_hash"],
            "response_format_type": mo_payload["response_format"]["type"],
        },
    )
    add(
        "generation.provider.completed",
        mo_generation_id=mo_response["mo_generation_id"],
        details={
            "alias": mo_response["alias"],
            "finish_reason": mo_response.get("finish_reason"),
            "usage": safe_usage_summary(mo_response.get("usage", {})),
        },
    )
    add(
        "generation.draft.validating",
        details={
            "structured_draft_id": structured_draft["structured_draft_id"],
            "draft_status": structured_draft["status"],
        },
    )
    add(
        "generation.citation.validating",
        details={
            "citation_status": structured_draft["validation"]["citation_status"],
            "citation_count": len(structured_draft["citations"]),
            "validation_error_count": len(structured_draft["validation"]["errors"]),
        },
    )
    add(
        "generation.completed",
        job_status="COMPLETED",
        details={
            "structured_draft_id": structured_draft["structured_draft_id"],
            "draft_validation_status": structured_draft["validation"]["citation_status"],
        },
    )
    return events


def safe_usage_summary(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    return {
        key: usage[key]
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance(usage.get(key), int) and usage[key] >= 0
    }


def selected_evidence_count(source_payload: dict[str, Any]) -> int:
    selected = source_payload.get("selected_evidence_ids") or []
    if not isinstance(selected, list):
        return 0
    return len([item for item in selected if isinstance(item, str) and item.strip()])


def safe_progress_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_detail_value(value)
        for key, value in details.items()
        if _is_safe_detail_key(key)
    }


def deterministic_event_id(
    *,
    event_source_service: str,
    cx_generation_id: str | None,
    job_id: str | None,
    event_type: str,
    sequence_no: int,
) -> str:
    subject_id = cx_generation_id or job_id or "unscoped"
    return str(
        uuid5(
            NAMESPACE_URL,
            f"generation-progress:{event_source_service}:{subject_id}:{sequence_no}:{event_type}",
        )
    )


def _is_safe_detail_key(key: str) -> bool:
    lowered = key.lower()
    return lowered not in FORBIDDEN_DETAIL_KEYS and not any(
        fragment in lowered for fragment in FORBIDDEN_DETAIL_KEY_FRAGMENTS
    )


def _safe_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        return safe_progress_details(value)
    if isinstance(value, list):
        return [_safe_detail_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
