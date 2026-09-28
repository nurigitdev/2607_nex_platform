from __future__ import annotations

from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.citation_quality_workflow import (
    validate_citation_quality_workflow,
)
from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


AE_CITATION_QUALITY_OBSERVABILITY_SCHEMA_VERSION = (
    "ae_citation_quality_observability.v1"
)
AE_CITATION_QUALITY_WORKFLOW_EVENT = "ae.citation_quality.workflow_observed"
_OUTCOMES = {
    "NOT_REQUIRED": "CITATION_NOT_REQUIRED",
    "VALIDATED": "CITATION_VALIDATED",
    "REPAIRED": "BOUNDED_REPAIR_SUCCEEDED",
    "ATTENTION_REQUIRED": "ATTENTION_REQUIRED",
}


def observe_citation_quality_workflow(
    emitter: OperationalEventEmitter,
    workflow: Mapping[str, Any],
    *,
    request_id: str | None,
    trace_id: str | None,
) -> OperationalEventEmitResult:
    projection = validate_citation_quality_workflow(workflow)
    interaction_id = projection["interaction_id"]
    workflow_status = projection["workflow_status"]
    quality = projection["quality"]
    repair = projection["repair"]
    remediation = projection["operator_remediation"]
    return emitter.safe_emit(
        event_type=AE_CITATION_QUALITY_WORKFLOW_EVENT,
        severity=(
            "WARNING" if workflow_status == "ATTENTION_REQUIRED" else "INFO"
        ),
        message="AE citation quality workflow observed.",
        trace_id=_optional_text(trace_id),
        request_id=_optional_text(request_id),
        subject_ref=build_subject_ref("ae.chat_interaction", interaction_id),
        details={
            "observability_schema_version": (
                AE_CITATION_QUALITY_OBSERVABILITY_SCHEMA_VERSION
            ),
            "outcome": _OUTCOMES[workflow_status],
            "workflow_status": workflow_status,
            "next_action": projection["next_action"],
            "boundary_status": quality["boundary_status"],
            "citation_status": quality["citation_status"],
            "issue_count": quality["issue_count"],
            "recommended_action": quality["recommended_action"],
            "grounding_required": quality["grounding_required"],
            "repair_mode": repair["mode"],
            "repair_status": repair["status"],
            "repair_attempted": repair["attempted"],
            "repair_attempt_count": repair["attempt_count"],
            "repair_max_attempts": repair["max_attempts"],
            "same_retrieval_package": repair["same_retrieval_package"],
            "operator_remediation_required": remediation["required"],
            "prompt_content_included": False,
            "response_content_included": False,
            "evidence_text_included": False,
            "owner_identity_included": False,
            "provider_detail_included": False,
            "raw_invalid_output_included": False,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "ae-citation-quality:"
                f"{interaction_id}:{projection['cx_generation_id']}:"
                f"{workflow_status}:{repair['attempt_count']}:"
                f"{quality['issue_count']}",
            )
        ),
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
