from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


AE_REPAIRED_RESPONSE_RUNTIME_BOUNDARY_DECISION_VERSION = (
    "ae_repaired_response_runtime_boundary_decision.v1"
)
AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION = "ae_repaired_response_handoff.v1"
CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION = "cx_remediation_execution_detail.v1"
CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION = "cx_repaired_generation_lineage.v1"
CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION = "cx_generation_execution_record.v1"

AE_HANDOFF_OWNER_SERVICE = "nex-ae-api"
AE_WEB_RESULT_SURFACE_OWNER_SERVICE = "nex-ae-web"
CX_REMEDIATION_LINEAGE_OWNER_SERVICE = "nex-cx"
AG_REMEDIATION_ORCHESTRATION_OWNER_SERVICE = "nex-ag"

REPAIRED_RESPONSE_HANDOFF_ROUTES = {
    "create": "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs",
    "read": (
        "/api/v1/chat/interactions/{interaction_id}/repaired-response-handoffs/"
        "{repaired_response_handoff_id}"
    ),
}

SAFE_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS = (
    "repaired_response_handoff_id",
    "handoff_request_id",
    "tenant_id",
    "workspace_id",
    "owner_user_id",
    "chat_document_id",
    "interaction_id",
    "actor_claims_ref",
    "original_cx_generation_id",
    "parent_cx_generation_id",
    "root_cx_generation_id",
    "repair_cx_generation_id",
    "remediation_action_id",
    "lineage_type",
    "result_ref",
    "output_hash",
    "output_preview",
    "usage",
    "quality_summary",
    "user_surface",
    "links",
    "redaction_summary",
    "trace_id",
    "request_id",
    "created_at",
    "updated_at",
)

FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS = (
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "messages",
    "model_path",
    "password",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
    "raw_output",
    "raw_prompt",
    "raw_source_text",
    "raw_text",
    "source_text",
    "storage_path",
)

RAW_CONTENT_POLICY = {
    "raw_prompt_stored": False,
    "raw_generation_output_stored": False,
    "raw_source_document_text_stored": False,
    "raw_evidence_stored": False,
    "provider_endpoint_stored": False,
    "credential_material_stored": False,
    "local_storage_path_stored": False,
    "free_text_storage": "hash_and_short_preview_only",
}

ALLOWED_FALSE_REDACTION_FLAG_KEYS = {
    key for key in RAW_CONTENT_POLICY if key.endswith("_stored")
}

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "messages",
    "model_path",
    "password",
    "passwd",
    "provider_endpoint",
    "provider_url",
    "raw_evidence",
    "raw_generation_output",
    "raw_output",
    "raw_prompt",
    "raw_source",
    "raw_text",
    "secret",
    "source_text",
    "storage_path",
    "token",
)


@dataclass(frozen=True)
class RepairedResponseRuntimeBoundaryError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_repaired_response_runtime_boundary_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": (
            AE_REPAIRED_RESPONSE_RUNTIME_BOUNDARY_DECISION_VERSION
        ),
        "decision_id": "s39.ae_repaired_response_runtime_boundary.v1",
        "slice_id": "0381",
        "status": "accepted",
        "owner_services": {
            "repaired_response_handoff": AE_HANDOFF_OWNER_SERVICE,
            "user_visible_result_surface": AE_WEB_RESULT_SURFACE_OWNER_SERVICE,
            "remediation_lineage_source": CX_REMEDIATION_LINEAGE_OWNER_SERVICE,
            "remediation_task_orchestration": (
                AG_REMEDIATION_ORCHESTRATION_OWNER_SERVICE
            ),
        },
        "route_scope": {
            "routes": dict(REPAIRED_RESPONSE_HANDOFF_ROUTES),
            "runtime_route_wiring_status": "deferred_to_0384",
            "client_adapter_status": "deferred_to_0382",
            "persistence_status": "deferred_to_0383",
        },
        "source_contract": {
            "required_cx_detail_schema_version": (
                CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION
            ),
            "required_lineage_schema_version": (
                CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION
            ),
            "required_generation_record_schema_version": (
                CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION
            ),
            "required_execution_status": "SUCCEEDED",
            "required_lineage_status": "LINKED",
            "required_repaired_generation_status": "COMPLETED",
            "parent_generation_mutated": False,
            "lineage_consistent": True,
        },
        "storage_contract": {
            "handoff_contract_version": AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION,
            "system_of_record": AE_HANDOFF_OWNER_SERVICE,
            "table_candidate": "ae_repaired_response_handoffs",
            "safe_fields": list(SAFE_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS),
            "forbidden_fields": list(FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS),
            "raw_content_policy": dict(RAW_CONTENT_POLICY),
        },
        "mutation_policy": {
            "original_chat_interaction_mutated": False,
            "original_cx_generation_record_mutated": False,
            "repair_acceptance_decision_status": "deferred_after_user_review",
        },
        "refactoring_checkpoint": {
            "external_api_changed": False,
            "database_schema_changed": False,
            "remote_provider_required": False,
            "postgres_smoke_required": False,
            "runtime_route_changed": False,
            "next_slice": "0382_ae_to_cx_repaired_lineage_client_adapter",
        },
        "next_slices": {
            "0382": "AE-to-CX repaired lineage client adapter",
            "0383": "AE repaired handoff persistence foundation",
            "0384": "AE repaired handoff service API wiring",
            "0385": "AE repaired handoff PostgreSQL smoke evidence",
        },
    }


def validate_repaired_response_runtime_boundary_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        decision.get("decision_schema_version")
        != AE_REPAIRED_RESPONSE_RUNTIME_BOUNDARY_DECISION_VERSION
    ):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.schema_version_invalid",
            detail="AE repaired response runtime boundary schema version is invalid.",
        )

    expected_owners = {
        "repaired_response_handoff": AE_HANDOFF_OWNER_SERVICE,
        "user_visible_result_surface": AE_WEB_RESULT_SURFACE_OWNER_SERVICE,
        "remediation_lineage_source": CX_REMEDIATION_LINEAGE_OWNER_SERVICE,
        "remediation_task_orchestration": AG_REMEDIATION_ORCHESTRATION_OWNER_SERVICE,
    }
    if _mapping(decision.get("owner_services")) != expected_owners:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.owner_services_invalid",
            detail="AE repaired response runtime boundary owner services are invalid.",
        )

    route_scope = _mapping(decision.get("route_scope"))
    if _mapping(route_scope.get("routes")) != REPAIRED_RESPONSE_HANDOFF_ROUTES:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.route_scope_invalid",
            detail="AE repaired response handoff route scope is invalid.",
        )
    if route_scope.get("runtime_route_wiring_status") != "deferred_to_0384":
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.route_scope_invalid",
            detail="AE repaired response handoff route wiring status is invalid.",
        )

    source_contract = _mapping(decision.get("source_contract"))
    expected_source = {
        "required_cx_detail_schema_version": CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
        "required_lineage_schema_version": CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
        "required_generation_record_schema_version": CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
        "required_execution_status": "SUCCEEDED",
        "required_lineage_status": "LINKED",
        "required_repaired_generation_status": "COMPLETED",
        "parent_generation_mutated": False,
        "lineage_consistent": True,
    }
    if source_contract != expected_source:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.source_contract_invalid",
            detail="AE repaired response source contract is not canonical.",
        )

    storage_contract = _mapping(decision.get("storage_contract"))
    if storage_contract.get("system_of_record") != AE_HANDOFF_OWNER_SERVICE:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.storage_contract_invalid",
            detail="AE repaired response handoff storage owner is invalid.",
        )
    if storage_contract.get("handoff_contract_version") != (
        AE_REPAIRED_RESPONSE_HANDOFF_SCHEMA_VERSION
    ):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.storage_contract_invalid",
            detail="AE repaired response handoff contract version is invalid.",
        )

    raw_policy = _mapping(storage_contract.get("raw_content_policy"))
    if any(
        raw_policy.get(key) is not False
        for key in RAW_CONTENT_POLICY
        if key.endswith("_stored")
    ):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.raw_content_policy_invalid",
            detail="AE repaired response handoff must not store raw content.",
        )
    if raw_policy.get("free_text_storage") != "hash_and_short_preview_only":
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.raw_content_policy_invalid",
            detail="AE repaired response free text storage policy is invalid.",
        )

    sensitive_safe_fields = find_sensitive_repaired_response_runtime_boundary_keys(
        {field: True for field in storage_contract.get("safe_fields", [])}
    )
    if sensitive_safe_fields:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.safe_field_sensitive",
            detail=(
                "AE repaired response safe fields contain sensitive keys: "
                f"{', '.join(sensitive_safe_fields)}"
            ),
        )

    forbidden_fields = tuple(storage_contract.get("forbidden_fields", ()))
    missing_forbidden = [
        field
        for field in FORBIDDEN_REPAIRED_RESPONSE_HANDOFF_STORAGE_FIELDS
        if field not in forbidden_fields
    ]
    if missing_forbidden:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.forbidden_fields_incomplete",
            detail=(
                "AE repaired response forbidden storage fields are incomplete: "
                f"{', '.join(missing_forbidden)}"
            ),
        )

    mutation_policy = _mapping(decision.get("mutation_policy"))
    if (
        mutation_policy.get("original_chat_interaction_mutated") is not False
        or mutation_policy.get("original_cx_generation_record_mutated") is not False
    ):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.mutation_policy_invalid",
            detail="AE repaired response handoff must not mutate original records.",
        )

    checkpoint = _mapping(decision.get("refactoring_checkpoint"))
    if any(
        checkpoint.get(key) is not False
        for key in (
            "external_api_changed",
            "database_schema_changed",
            "remote_provider_required",
            "postgres_smoke_required",
            "runtime_route_changed",
        )
    ):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.refactoring_checkpoint_invalid",
            detail="AE repaired response boundary checkpoint changed runtime scope.",
        )

    next_slices = _mapping(decision.get("next_slices"))
    if tuple(next_slices) != ("0382", "0383", "0384", "0385"):
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_boundary.next_slices_invalid",
            detail="AE repaired response boundary next slices are not canonical.",
        )

    return dict(decision)


def find_sensitive_repaired_response_runtime_boundary_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def assert_repaired_response_runtime_boundary_redaction_safe(payload: Any) -> None:
    sensitive_keys = find_sensitive_repaired_response_runtime_boundary_keys(payload)
    if sensitive_keys:
        raise RepairedResponseRuntimeBoundaryError(
            error_code="ae.repaired_response_runtime_boundary_payload.sensitive_key",
            detail=(
                "AE repaired response runtime boundary payload contains sensitive keys: "
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
