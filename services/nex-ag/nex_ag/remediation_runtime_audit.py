from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


AG_REMEDIATION_RUNTIME_OPERATIONS_GAP_AUDIT_VERSION = (
    "ag_remediation_runtime_operations_gap_audit.v1"
)

AG_OWNER_SERVICE = "nex-ag"
CX_OWNER_SERVICE = "nex-cx"
AE_OWNER_SERVICE = "nex-ae-api"
MO_OWNER_SERVICE = "nex-mo"

_CLOSED_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "capability_id": "cx_remediation_execution_contract",
        "owner_service": CX_OWNER_SERVICE,
        "evidence_slice": "0352",
        "runtime_surface": "cx_remediation_execution_request.v1",
    },
    {
        "capability_id": "cx_remediation_execution_api",
        "owner_service": CX_OWNER_SERVICE,
        "evidence_slice": "0354",
        "runtime_surface": "POST /api/v1/generations/{cx_generation_id}/remediation-executions",
    },
    {
        "capability_id": "cx_remediation_execution_worker_runtime",
        "owner_service": CX_OWNER_SERVICE,
        "evidence_slice": "0359",
        "runtime_surface": "run_cx_remediation_execution_worker_batch",
    },
    {
        "capability_id": "ag_remediation_execution_dispatch_api",
        "owner_service": AG_OWNER_SERVICE,
        "evidence_slice": "0364",
        "runtime_surface": (
            "POST /admin/v1/generation-audit/generations/{cx_generation_id}"
            "/remediation-tasks/{remediation_action_id}/execute"
        ),
    },
    {
        "capability_id": "ag_remediation_execution_dispatch_postgres_smoke",
        "owner_service": AG_OWNER_SERVICE,
        "evidence_slice": "0365",
        "runtime_surface": "run_ag_remediation_execution_dispatch_postgres_smoke",
    },
    {
        "capability_id": "cx_remediation_execution_read_model_api",
        "owner_service": CX_OWNER_SERVICE,
        "evidence_slice": "0366",
        "runtime_surface": (
            "GET /api/v1/generations/{cx_generation_id}/remediation-executions"
        ),
    },
    {
        "capability_id": "cx_remediation_execution_read_model_postgres_smoke",
        "owner_service": CX_OWNER_SERVICE,
        "evidence_slice": "0367",
        "runtime_surface": "run_cx_remediation_execution_read_model_postgres_smoke",
    },
    {
        "capability_id": "ag_remediation_execution_status_sync_api",
        "owner_service": AG_OWNER_SERVICE,
        "evidence_slice": "0369",
        "runtime_surface": (
            "POST /admin/v1/generation-audit/generations/{cx_generation_id}"
            "/remediation-tasks/{remediation_action_id}/sync-execution-status"
        ),
    },
    {
        "capability_id": "s37_remediation_runtime_integration_closure",
        "owner_service": AG_OWNER_SERVICE,
        "evidence_slice": "0370",
        "runtime_surface": "run_s37_remediation_runtime_integration_closure",
    },
)

_OPERATIONS_GAPS: tuple[dict[str, Any], ...] = (
    {
        "gap_id": "ag_remediation_execution_operations_projection",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0372",
        "decision": "required_before_operations_api",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    },
    {
        "gap_id": "ag_remediation_execution_operations_api",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0373",
        "decision": "required_for_operator_read_model",
        "external_api_changed": True,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    },
    {
        "gap_id": "ag_remediation_execution_dashboard_issue_candidate_integration",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0374",
        "decision": "required_for_unified_operations_visibility",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    },
    {
        "gap_id": "ag_remediation_execution_status_sync_job_plan",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0375",
        "decision": "required_before_background_sync",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    },
    {
        "gap_id": "ag_remediation_execution_status_sync_worker",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0376",
        "decision": "required_for_service_local_reconciliation",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": False,
    },
    {
        "gap_id": "ag_remediation_execution_status_sync_postgres_smoke",
        "owner_service": AG_OWNER_SERVICE,
        "target_slice": "0377",
        "decision": "required_to_prove_test_db_reconciliation",
        "external_api_changed": False,
        "database_schema_changed": False,
        "postgres_smoke_required": True,
    },
)

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "password",
    "passwd",
    "provider_api_key",
    "raw_evidence",
    "raw_generation_output",
    "raw_prompt",
    "raw_source_document_text",
    "secret",
    "service_token",
    "token",
)


@dataclass(frozen=True)
class RemediationRuntimeAuditError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_remediation_runtime_operations_gap_audit(
    *,
    closed_capabilities: Sequence[Mapping[str, Any]] | None = None,
    operations_gaps: Sequence[Mapping[str, Any]] | None = None,
    include_deferred_scope: bool = True,
) -> dict[str, Any]:
    closed = _copy_records(closed_capabilities or _CLOSED_CAPABILITIES)
    gaps = _copy_records(operations_gaps or _OPERATIONS_GAPS)
    audit: dict[str, Any] = {
        "audit_schema_version": AG_REMEDIATION_RUNTIME_OPERATIONS_GAP_AUDIT_VERSION,
        "audit_id": "s38.remediation_runtime_operations_gap_audit.v1",
        "slice_id": "0371",
        "status": "accepted",
        "closed_capabilities": closed,
        "operations_gaps": gaps,
        "boundary_policy": {
            "ag_runtime_role": "owns_operator_state_operations_and_status_sync",
            "cx_runtime_role": "owns_execution_attempts_and_repair_lineage",
            "ae_runtime_role": "owns_user_visible_repaired_response_surface",
            "mo_runtime_role": "owns_model_provider_execution",
            "ag_may_update_task_state": True,
            "ag_may_mutate_cx_execution_records": False,
            "cx_may_mutate_ag_task_records": False,
            "ag_operations_projection_is_read_only": True,
            "remote_provider_required_for_slices_0371_0377": False,
        },
        "safe_debug_contract": {
            "raw_content_included": False,
            "credential_material_included": False,
            "allowed_debug_fields": [
                "service_id",
                "trace_id",
                "request_id",
                "cx_generation_id",
                "remediation_action_id",
                "execution_status",
                "task_status",
                "result_ref",
                "status_reason",
                "created_at",
                "updated_at",
            ],
        },
        "recommended_slices": _recommended_slices_from_gaps(gaps),
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
        },
    }
    if include_deferred_scope:
        audit["deferred_scope"] = [
            {
                "scope_id": "ae_repaired_response_surface",
                "owner_service": AE_OWNER_SERVICE,
                "reason": "requires_operator_operations_runtime_visibility_first",
            },
            {
                "scope_id": "live_provider_repair_generation_execution",
                "owner_service": MO_OWNER_SERVICE,
                "reason": "mock_repair_worker_runtime_remains_sufficient_until_execution_provider_slice",
            },
            {
                "scope_id": "new_database_schema",
                "owner_service": "none",
                "reason": "S38 operations can read existing AG task and CX execution stores",
            },
        ]
    return validate_remediation_runtime_operations_gap_audit(audit)


def validate_remediation_runtime_operations_gap_audit(
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        audit.get("audit_schema_version")
        != AG_REMEDIATION_RUNTIME_OPERATIONS_GAP_AUDIT_VERSION
    ):
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.schema_version_invalid",
            detail="AG remediation runtime operations gap audit schema version is invalid.",
        )
    if audit.get("status") != "accepted":
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.status_invalid",
            detail="AG remediation runtime operations gap audit status is invalid.",
        )

    gaps = _records(audit.get("operations_gaps"))
    if not _slice_ids_are_contiguous(
        [str(gap.get("target_slice", "")) for gap in gaps],
        start="0372",
        end="0377",
    ):
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.next_slices_invalid",
            detail="AG remediation runtime operations gap audit next slices are invalid.",
        )
    if any(gap.get("owner_service") != AG_OWNER_SERVICE for gap in gaps):
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.gap_owner_invalid",
            detail="AG remediation runtime operations gaps must be owned by nex-ag.",
        )

    recommended_slices = _records(audit.get("recommended_slices"))
    if [item.get("slice_id") for item in recommended_slices] != [
        gap.get("target_slice") for gap in gaps
    ]:
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.recommended_slices_invalid",
            detail="AG remediation runtime recommended slices must mirror gap order.",
        )

    boundary_policy = _mapping(audit.get("boundary_policy"))
    if boundary_policy != _expected_boundary_policy():
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.boundary_policy_invalid",
            detail="AG remediation runtime operations boundary policy is invalid.",
        )

    safe_debug_contract = _mapping(audit.get("safe_debug_contract"))
    if safe_debug_contract.get("raw_content_included") is not False:
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.raw_content_policy_invalid",
            detail="AG remediation runtime operations audit must not include raw content.",
        )
    if safe_debug_contract.get("credential_material_included") is not False:
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.credential_policy_invalid",
            detail="AG remediation runtime operations audit must not include credentials.",
        )

    closed = _records(audit.get("closed_capabilities"))
    closed_slices = {str(item.get("evidence_slice", "")) for item in closed}
    if not {"0352", "0354", "0359", "0364", "0365", "0366", "0367", "0369", "0370"}.issubset(
        closed_slices
    ):
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.closed_capabilities_invalid",
            detail="AG remediation runtime operations audit is missing S37 prerequisites.",
        )

    redaction_summary = _mapping(audit.get("redaction_summary"))
    if any(value is not False for value in redaction_summary.values()):
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.redaction_summary_invalid",
            detail="AG remediation runtime operations redaction summary is invalid.",
        )

    sensitive_keys = find_sensitive_remediation_runtime_audit_keys(audit)
    if sensitive_keys:
        raise RemediationRuntimeAuditError(
            error_code="ag.remediation_runtime_audit.sensitive_payload",
            detail=(
                "AG remediation runtime operations gap audit contains sensitive keys: "
                f"{', '.join(sensitive_keys)}"
            ),
        )

    return dict(audit)


def find_sensitive_remediation_runtime_audit_keys(payload: Any) -> list[str]:
    matches: list[str] = []
    _collect_sensitive_keys(payload, path="", matches=matches)
    return matches


def _expected_boundary_policy() -> dict[str, Any]:
    return {
        "ag_runtime_role": "owns_operator_state_operations_and_status_sync",
        "cx_runtime_role": "owns_execution_attempts_and_repair_lineage",
        "ae_runtime_role": "owns_user_visible_repaired_response_surface",
        "mo_runtime_role": "owns_model_provider_execution",
        "ag_may_update_task_state": True,
        "ag_may_mutate_cx_execution_records": False,
        "cx_may_mutate_ag_task_records": False,
        "ag_operations_projection_is_read_only": True,
        "remote_provider_required_for_slices_0371_0377": False,
    }


def _recommended_slices_from_gaps(
    gaps: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "slice_id": str(gap["target_slice"]),
            "gap_id": str(gap["gap_id"]),
            "decision": str(gap["decision"]),
        }
        for gap in gaps
    ]


def _copy_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(record) for record in records]


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _slice_ids_are_contiguous(
    slice_ids: Sequence[str],
    *,
    start: str,
    end: str,
) -> bool:
    if len(slice_ids) != int(end) - int(start) + 1:
        return False
    expected = [f"{number:04d}" for number in range(int(start), int(end) + 1)]
    return list(slice_ids) == expected


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
            if _is_sensitive_key(key_text) and child is not False:
                matches.append(child_path)
            _collect_sensitive_keys(child, path=child_path, matches=matches)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_sensitive_keys(child, path=f"{path}[{index}]", matches=matches)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
