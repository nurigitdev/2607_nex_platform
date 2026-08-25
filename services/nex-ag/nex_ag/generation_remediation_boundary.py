from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


GENERATION_REMEDIATION_BOUNDARY_DECISION_VERSION = (
    "ag_generation_remediation_boundary_decision.v1"
)

AG_REMEDIATION_OWNER_SERVICE = "nex-ag"
CX_REPAIR_EXECUTION_OWNER_SERVICE = "nex-cx"
AE_FEEDBACK_OWNER_SERVICE = "nex-ae-api"
MO_MODEL_EXECUTION_OWNER_SERVICE = "nex-mo"

ALLOWED_REMEDIATION_INTENTS = (
    "retry_generation",
    "retrieval_repair",
    "citation_repair",
    "prompt_policy_review",
    "operator_followup",
    "mark_accepted",
)

SAFE_REMEDIATION_STORAGE_FIELDS = (
    "remediation_id",
    "tenant_id",
    "cx_generation_id",
    "trace_id",
    "request_id",
    "remediation_intent",
    "remediation_status",
    "priority",
    "owner_ref",
    "operator_ref",
    "feedback_refs",
    "disposition_refs",
    "quality_issue_refs",
    "evidence_hashes",
    "evidence_previews",
    "result_ref",
    "metadata",
    "created_at",
    "updated_at",
)

RAW_CONTENT_POLICY = {
    "raw_prompt_stored": False,
    "raw_generation_output_stored": False,
    "raw_source_document_text_stored": False,
    "raw_feedback_comment_stored": False,
    "raw_operator_note_stored": False,
    "credential_material_stored": False,
    "free_text_storage": "hash_and_short_preview_only",
}

REMEDIATION_STATUS_TRANSITIONS = {
    "PROPOSED": ("ASSIGNED", "IN_PROGRESS", "CANCELLED"),
    "ASSIGNED": ("IN_PROGRESS", "CANCELLED"),
    "IN_PROGRESS": ("WAITING_ON_CX", "COMPLETED", "FAILED", "CANCELLED"),
    "WAITING_ON_CX": ("IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"),
    "COMPLETED": (),
    "FAILED": (),
    "CANCELLED": (),
}

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "raw_feedback_comment",
    "raw_generation_output",
    "raw_note",
    "raw_operator_note",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "raw_user_message",
    "secret",
    "source_text",
    "token",
)


@dataclass(frozen=True)
class GenerationRemediationBoundaryError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_generation_remediation_boundary_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": GENERATION_REMEDIATION_BOUNDARY_DECISION_VERSION,
        "decision_id": "s35.generation_quality_repair_loop_boundary.v1",
        "slice_id": "0341",
        "status": "accepted",
        "owner_services": {
            "remediation_orchestration": AG_REMEDIATION_OWNER_SERVICE,
            "generation_lineage_and_repair_execution": CX_REPAIR_EXECUTION_OWNER_SERVICE,
            "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
            "model_provider_execution": MO_MODEL_EXECUTION_OWNER_SERVICE,
        },
        "storage_contract": {
            "safe_fields": list(SAFE_REMEDIATION_STORAGE_FIELDS),
            "raw_content_policy": dict(RAW_CONTENT_POLICY),
            "allowed_remediation_intents": list(ALLOWED_REMEDIATION_INTENTS),
            "status_transitions": {
                key: list(values)
                for key, values in REMEDIATION_STATUS_TRANSITIONS.items()
            },
        },
        "cross_service_refs": {
            "required": [
                "tenant_id",
                "cx_generation_id",
                "trace_id",
                "request_id",
            ],
            "optional": [
                "feedback_refs",
                "disposition_refs",
                "quality_issue_refs",
                "result_ref",
            ],
        },
        "next_slices": {
            "0342": "freeze remediation action contract/schema",
            "0343": "derive AG remediation candidates from quality signals",
            "0344": "wire remediation task repository and API",
            "0345": "prove remediation task persistence with nex_ag_test PostgreSQL smoke",
        },
    }


def validate_generation_remediation_boundary_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        decision.get("decision_schema_version")
        != GENERATION_REMEDIATION_BOUNDARY_DECISION_VERSION
    ):
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_boundary.schema_version_invalid",
            detail="Generation remediation boundary decision schema version is invalid.",
        )

    owners = _mapping(decision.get("owner_services"))
    expected_owners = {
        "remediation_orchestration": AG_REMEDIATION_OWNER_SERVICE,
        "generation_lineage_and_repair_execution": CX_REPAIR_EXECUTION_OWNER_SERVICE,
        "user_feedback_intake": AE_FEEDBACK_OWNER_SERVICE,
        "model_provider_execution": MO_MODEL_EXECUTION_OWNER_SERVICE,
    }
    if owners != expected_owners:
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_boundary.owner_services_invalid",
            detail="Generation remediation boundary owner services are not canonical.",
        )

    storage_contract = _mapping(decision.get("storage_contract"))
    raw_policy = _mapping(storage_contract.get("raw_content_policy"))
    if any(
        raw_policy.get(key) is not False
        for key in RAW_CONTENT_POLICY
        if key.endswith("_stored")
    ):
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_boundary.raw_content_policy_invalid",
            detail="Generation remediation must not store raw prompt/output/source content.",
        )

    sensitive_fields = find_sensitive_generation_remediation_keys(
        {field: True for field in storage_contract.get("safe_fields", [])}
    )
    if sensitive_fields:
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_boundary.safe_field_sensitive",
            detail=(
                "Generation remediation safe fields contain sensitive keys: "
                f"{', '.join(sensitive_fields)}"
            ),
        )

    transitions = _mapping(storage_contract.get("status_transitions"))
    if set(transitions) != set(REMEDIATION_STATUS_TRANSITIONS):
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_boundary.status_transitions_invalid",
            detail="Generation remediation status transitions are incomplete.",
        )
    for status, next_statuses in transitions.items():
        if tuple(next_statuses) != REMEDIATION_STATUS_TRANSITIONS[status]:
            raise GenerationRemediationBoundaryError(
                error_code="ag.remediation_boundary.status_transitions_invalid",
                detail=f"Generation remediation status transition is invalid: {status}.",
            )

    return dict(decision)


def remediation_transition_allowed(current_status: str, next_status: str) -> bool:
    return next_status in REMEDIATION_STATUS_TRANSITIONS.get(current_status, ())


def find_sensitive_generation_remediation_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_generation_remediation_payload_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_generation_remediation_keys(payload)
    if sensitive_keys:
        raise GenerationRemediationBoundaryError(
            error_code="ag.remediation_payload.sensitive_key",
            detail=(
                "Generation remediation payload contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def _collect_sensitive_keys(
    value: Any,
    *,
    path: str,
    matches: list[str],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
