from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


CX_REMEDIATION_EXECUTION_BOUNDARY_DECISION_VERSION = (
    "cx_remediation_execution_boundary_decision.v1"
)

AG_REMEDIATION_OWNER_SERVICE = "nex-ag"
CX_REMEDIATION_EXECUTION_OWNER_SERVICE = "nex-cx"
CX_GENERATION_LINEAGE_OWNER_SERVICE = "nex-cx"
AE_RESULT_SURFACE_OWNER_SERVICE = "nex-ae-api"
MO_PROVIDER_EXECUTION_OWNER_SERVICE = "nex-mo"

CX_EXECUTABLE_REMEDIATION_ACTION_TYPES = (
    "retry_generation",
    "retrieval_repair",
    "citation_repair",
)
AG_ONLY_REMEDIATION_ACTION_TYPES = (
    "prompt_policy_review",
    "operator_followup",
    "mark_accepted",
)
KNOWN_REMEDIATION_ACTION_TYPES = (
    *CX_EXECUTABLE_REMEDIATION_ACTION_TYPES,
    *AG_ONLY_REMEDIATION_ACTION_TYPES,
)

REMEDIATION_EXECUTION_STAGES = (
    "task_intake",
    "parent_generation_lookup",
    "repair_plan_selection",
    "retrieval_package_policy",
    "prompt_package_rebuild",
    "mo_provider_execution",
    "cx_lineage_persistence",
    "ag_status_callback",
    "ae_result_projection",
)

SAFE_REMEDIATION_EXECUTION_STORAGE_FIELDS = (
    "remediation_action_id",
    "parent_cx_generation_id",
    "root_cx_generation_id",
    "repair_cx_generation_id",
    "tenant_id",
    "trace_id",
    "request_id",
    "action_type",
    "execution_status",
    "lineage_type",
    "attempt_no",
    "reason_codes",
    "source_refs",
    "evidence_hashes",
    "evidence_previews",
    "retrieval_package_ref",
    "generation_request_hash",
    "provider_prompt_package_hash",
    "result_ref",
    "failure_code",
    "safe_message",
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
    "raw_evidence_stored": False,
    "credential_material_stored": False,
    "provider_endpoint_stored": False,
    "free_text_storage": "hash_and_short_preview_only",
}

ALLOWED_FALSE_REDACTION_FLAG_KEYS = {
    key for key in RAW_CONTENT_POLICY if key.endswith("_stored")
}
ALLOWED_FALSE_REDACTION_FLAG_KEYS.add("raw_evidence_stored")

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "model_path",
    "password",
    "passwd",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
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
    "storage_path",
    "token",
)


@dataclass(frozen=True)
class RemediationExecutionBoundaryError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_cx_remediation_execution_boundary_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": (
            CX_REMEDIATION_EXECUTION_BOUNDARY_DECISION_VERSION
        ),
        "decision_id": "s36.cx_remediation_execution_boundary.v1",
        "slice_id": "0351",
        "status": "accepted",
        "owner_services": {
            "remediation_task_orchestration": AG_REMEDIATION_OWNER_SERVICE,
            "remediation_execution": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
            "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
            "provider_execution": MO_PROVIDER_EXECUTION_OWNER_SERVICE,
            "user_visible_result_surface": AE_RESULT_SURFACE_OWNER_SERVICE,
        },
        "action_execution_policy": {
            "executable_by_cx": {
                "retry_generation": {
                    "lineage_type": "retry",
                    "retrieval_package_policy": "reuse_parent_package_if_allowed",
                    "prompt_package_policy": "rebuild_from_parent_request_and_policy_refs",
                    "result_ref_type": "repair_execution",
                },
                "retrieval_repair": {
                    "lineage_type": "fresh_retrieval_regenerate",
                    "retrieval_package_policy": "create_or_select_fresh_package",
                    "prompt_package_policy": "rebuild_after_retrieval_refresh",
                    "result_ref_type": "repair_execution",
                },
                "citation_repair": {
                    "lineage_type": "repair",
                    "retrieval_package_policy": "reuse_or_expand_cited_evidence",
                    "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
                    "result_ref_type": "repair_execution",
                },
            },
            "ag_only": {
                "prompt_policy_review": "operator_review_no_cx_execution",
                "operator_followup": "operator_followup_no_cx_execution",
                "mark_accepted": "terminal_operator_acceptance_no_cx_execution",
            },
        },
        "lineage_contract": {
            "parent_generation_id_required": True,
            "parent_generation_id_source": "ag_action.cx_generation_id",
            "root_generation_id_policy": "inherit_from_parent_or_parent_id",
            "attempt_no_policy": "cx_increments_from_parent_attempt",
            "original_generation_record_mutated": False,
            "child_generation_record_schema_version": "cx_generation_execution_record.v1",
            "result_ref": {
                "source_service": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
                "ref_type": "repair_execution",
                "relation": "result_of",
            },
        },
        "handoff_contract": {
            "ag_to_cx_required_fields": [
                "remediation_action_id",
                "cx_generation_id",
                "tenant_id",
                "trace_id",
                "request_id",
                "action_type",
                "reason_codes",
                "evidence.evidence_hashes",
            ],
            "cx_to_ag_result_fields": [
                "remediation_action_id",
                "repair_cx_generation_id",
                "execution_status",
                "result_ref",
                "failure_code",
                "safe_message",
            ],
            "status_flow": [
                "AG marks task WAITING_ON_CX",
                "CX records repair attempt ACCEPTED/RUNNING/SUCCEEDED/FAILED",
                "AG records result_ref and moves task COMPLETED or FAILED",
                "AE reads original and repaired generation refs through CX/AE API",
            ],
        },
        "storage_contract": {
            "safe_fields": list(SAFE_REMEDIATION_EXECUTION_STORAGE_FIELDS),
            "raw_content_policy": dict(RAW_CONTENT_POLICY),
        },
        "execution_stages": list(REMEDIATION_EXECUTION_STAGES),
        "refactoring_checkpoint": {
            "external_api_changed": False,
            "database_schema_changed": False,
            "remote_provider_required": False,
            "next_slice": "0352_cx_remediation_execution_contract_schema_foundation",
        },
    }


def validate_cx_remediation_execution_boundary_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        decision.get("decision_schema_version")
        != CX_REMEDIATION_EXECUTION_BOUNDARY_DECISION_VERSION
    ):
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.schema_version_invalid",
            detail="CX remediation execution boundary schema version is invalid.",
        )

    expected_owners = {
        "remediation_task_orchestration": AG_REMEDIATION_OWNER_SERVICE,
        "remediation_execution": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
        "generation_lineage": CX_GENERATION_LINEAGE_OWNER_SERVICE,
        "provider_execution": MO_PROVIDER_EXECUTION_OWNER_SERVICE,
        "user_visible_result_surface": AE_RESULT_SURFACE_OWNER_SERVICE,
    }
    if _mapping(decision.get("owner_services")) != expected_owners:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.owner_services_invalid",
            detail="CX remediation execution owner services are not canonical.",
        )

    action_policy = _mapping(decision.get("action_execution_policy"))
    executable = _mapping(action_policy.get("executable_by_cx"))
    ag_only = _mapping(action_policy.get("ag_only"))
    if set(executable) != set(CX_EXECUTABLE_REMEDIATION_ACTION_TYPES) or set(
        ag_only
    ) != set(AG_ONLY_REMEDIATION_ACTION_TYPES):
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.action_policy_invalid",
            detail="CX remediation execution action policy is incomplete.",
        )
    for action_type, policy in executable.items():
        if _mapping(policy).get("result_ref_type") != "repair_execution":
            raise RemediationExecutionBoundaryError(
                error_code="cx.remediation_execution_boundary.action_policy_invalid",
                detail=(
                    "Executable CX remediation actions must produce repair_execution "
                    f"refs: {action_type}."
                ),
            )

    lineage_contract = _mapping(decision.get("lineage_contract"))
    if lineage_contract.get("parent_generation_id_required") is not True:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.lineage_contract_invalid",
            detail="CX remediation execution requires a parent generation id.",
        )
    if lineage_contract.get("original_generation_record_mutated") is not False:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.lineage_contract_invalid",
            detail="CX remediation execution must not mutate the original generation.",
        )
    result_ref = _mapping(lineage_contract.get("result_ref"))
    if result_ref != {
        "source_service": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
        "ref_type": "repair_execution",
        "relation": "result_of",
    }:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.lineage_contract_invalid",
            detail="CX remediation execution result_ref contract is invalid.",
        )

    storage_contract = _mapping(decision.get("storage_contract"))
    raw_policy = _mapping(storage_contract.get("raw_content_policy"))
    if any(
        raw_policy.get(key) is not False
        for key in RAW_CONTENT_POLICY
        if key.endswith("_stored")
    ):
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.raw_content_policy_invalid",
            detail="CX remediation execution must not store raw prompt/output/source content.",
        )
    sensitive_safe_fields = find_sensitive_cx_remediation_execution_keys(
        {field: True for field in storage_contract.get("safe_fields", [])}
    )
    if sensitive_safe_fields:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.safe_field_sensitive",
            detail=(
                "CX remediation execution safe fields contain sensitive keys: "
                f"{', '.join(sensitive_safe_fields)}"
            ),
        )

    if tuple(decision.get("execution_stages", ())) != REMEDIATION_EXECUTION_STAGES:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_boundary.execution_stages_invalid",
            detail="CX remediation execution stages are not canonical.",
        )

    return dict(decision)


def remediation_action_executable_by_cx(action_type: str) -> bool:
    return action_type in CX_EXECUTABLE_REMEDIATION_ACTION_TYPES


def build_remediation_action_intake_summary(action: Mapping[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("action_type") or "")
    executable = remediation_action_executable_by_cx(action_type)
    assert_cx_remediation_execution_payload_redaction_safe(action)
    evidence = _mapping(action.get("evidence"))
    source_refs = action.get("source_refs", [])
    source_ref_count = len(source_refs) if isinstance(source_refs, list) else 0
    evidence_hashes = evidence.get("evidence_hashes", [])
    evidence_previews = evidence.get("evidence_previews", [])
    return {
        "summary_schema_version": "cx_remediation_execution_intake_summary.v1",
        "remediation_action_id": _optional_text(action.get("remediation_action_id")),
        "parent_cx_generation_id": _optional_text(action.get("cx_generation_id")),
        "tenant_id": _optional_text(action.get("tenant_id")),
        "trace_id": _optional_text(action.get("trace_id")),
        "request_id": _optional_text(action.get("request_id")),
        "action_type": action_type,
        "executable_by_cx": executable,
        "non_executable_reason": None
        if executable
        else _non_executable_reason(action_type),
        "lineage_type": remediation_lineage_type_for_action(action_type)
        if executable
        else None,
        "result_ref": {
            "source_service": CX_REMEDIATION_EXECUTION_OWNER_SERVICE,
            "ref_type": "repair_execution",
            "relation": "result_of",
        }
        if executable
        else None,
        "source_ref_count": source_ref_count,
        "evidence_hash_count": len(evidence_hashes)
        if isinstance(evidence_hashes, list)
        else 0,
        "evidence_preview_count": len(evidence_previews)
        if isinstance(evidence_previews, list)
        else 0,
        "redaction": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_feedback_comment_included": False,
            "raw_operator_note_included": False,
            "raw_evidence_included": False,
            "provider_detail_included": False,
        },
    }


def find_sensitive_cx_remediation_execution_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_cx_remediation_execution_payload_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_cx_remediation_execution_keys(payload)
    if sensitive_keys:
        raise RemediationExecutionBoundaryError(
            error_code="cx.remediation_execution_payload.sensitive_key",
            detail=(
                "CX remediation execution payload contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )


def remediation_lineage_type_for_action(action_type: str) -> str | None:
    decision = build_cx_remediation_execution_boundary_decision()
    policy = (
        decision["action_execution_policy"]["executable_by_cx"].get(action_type)
    )
    if not isinstance(policy, Mapping):
        return None
    lineage_type = policy.get("lineage_type")
    return str(lineage_type) if lineage_type else None


def _non_executable_reason(action_type: str) -> str:
    if action_type in AG_ONLY_REMEDIATION_ACTION_TYPES:
        return "ag_owned_operator_state"
    if action_type:
        return "unknown_action_type"
    return "missing_action_type"


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
            if _is_sensitive_key(key_text, child):
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str, value: Any) -> bool:
    normalized = key.strip().lower()
    if normalized in ALLOWED_FALSE_REDACTION_FLAG_KEYS:
        return value is not False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
