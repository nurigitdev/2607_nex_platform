from __future__ import annotations

from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from nex_ae_api.generated_response_lineage import (
    validate_generated_response_lineage,
)
from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)


AE_GENERATED_RESPONSE_OBSERVABILITY_SCHEMA_VERSION = (
    "ae_generated_response_observability.v1"
)
AE_GENERATED_RESPONSE_PERSISTED_EVENT = "ae.generated_response.persisted"


def observe_generated_response_persisted(
    emitter: OperationalEventEmitter,
    lineage: Mapping[str, Any],
    *,
    request_id: str | None,
    trace_id: str | None,
) -> OperationalEventEmitResult:
    projection = validate_generated_response_lineage(lineage)
    return emitter.safe_emit(
        event_type=AE_GENERATED_RESPONSE_PERSISTED_EVENT,
        severity="INFO",
        message="AE generated response persisted.",
        trace_id=_optional_text(trace_id),
        request_id=_optional_text(request_id),
        subject_ref=build_subject_ref(
            "ae.chat_interaction", projection["interaction_id"]
        ),
        details={
            "observability_schema_version": (
                AE_GENERATED_RESPONSE_OBSERVABILITY_SCHEMA_VERSION
            ),
            "outcome": "PERSISTED",
            "lineage_type": projection["lineage_type"],
            "content_type": projection["content_type"],
            "content_size_bytes": projection["size_bytes"],
            "content_available": projection["content_available"],
            "retrieval_package_linked": (
                projection["retrieval_package_id"] is not None
            ),
            "structured_draft_linked": (
                projection["structured_draft_id"] is not None
            ),
            "citation_workflow_status": projection[
                "citation_workflow_status"
            ],
            "bounded_repair_applied": projection["bounded_repair_applied"],
            "parent_response_linked": (
                projection["parent_response_id"] is not None
            ),
            "prompt_content_included": False,
            "response_content_included": False,
            "storage_ref_included": False,
            "owner_identity_included": False,
            "provider_detail_included": False,
            "lineage_identifiers_included": False,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "ae-generated-response-persisted:"
                f"{projection['response_id']}:{projection['content_sha256']}",
            )
        ),
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
