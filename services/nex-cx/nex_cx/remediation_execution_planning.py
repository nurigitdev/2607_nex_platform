from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_cx.remediation_execution import (
    CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
    PROVIDER_BOUNDARY,
    optional_text,
    required_text,
)
from nex_cx.remediation_execution_boundary import (
    RemediationExecutionBoundaryError,
    assert_cx_remediation_execution_payload_redaction_safe,
    remediation_action_executable_by_cx,
    remediation_lineage_type_for_action,
)


CX_REMEDIATION_EXECUTION_WORKER_PLAN_SCHEMA_VERSION = (
    "cx_remediation_execution_worker_plan.v1"
)
CX_REMEDIATION_EXECUTION_TRANSITION_SCHEMA_VERSION = (
    "cx_remediation_execution_state_transition.v1"
)

ACCEPTED = "ACCEPTED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

CX_REMEDIATION_EXECUTION_STATUSES = (
    ACCEPTED,
    RUNNING,
    SUCCEEDED,
    FAILED,
    CANCELLED,
)
CX_REMEDIATION_EXECUTION_TERMINAL_STATUSES = (
    SUCCEEDED,
    FAILED,
    CANCELLED,
)
CX_REMEDIATION_EXECUTION_PLANNABLE_STATUSES = (
    ACCEPTED,
    RUNNING,
)
CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ACCEPTED: (RUNNING, CANCELLED),
    RUNNING: (SUCCEEDED, FAILED, CANCELLED),
    SUCCEEDED: (),
    FAILED: (),
    CANCELLED: (),
}

SAFE_REPAIR_FAILURE_CLASSES = (
    "validation",
    "retrieval",
    "generation",
    "citation_quality",
    "dependency",
)

ACTION_WORKER_POLICIES: dict[str, dict[str, Any]] = {
    "retry_generation": {
        "lineage_type": "retry",
        "retrieval_package_policy": "reuse_original_retrieval_package",
        "prompt_package_policy": "rebuild_with_retry_instruction_ref",
        "stages": (
            "load_parent_generation",
            "reuse_original_retrieval_package",
            "rebuild_retry_prompt_package",
            "submit_mo_generation_request",
            "persist_child_generation_lineage",
            "persist_remediation_result",
            "notify_ag_result_available",
        ),
    },
    "retrieval_repair": {
        "lineage_type": "fresh_retrieval_regenerate",
        "retrieval_package_policy": "fresh_retrieval_required",
        "prompt_package_policy": "rebuild_with_retrieval_repair_instruction_ref",
        "stages": (
            "load_parent_generation",
            "select_fresh_retrieval_package",
            "rebuild_retrieval_repair_prompt_package",
            "submit_mo_generation_request",
            "persist_child_generation_lineage",
            "persist_remediation_result",
            "notify_ag_result_available",
        ),
    },
    "citation_repair": {
        "lineage_type": "repair",
        "retrieval_package_policy": "reuse_or_expand_cited_evidence",
        "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
        "stages": (
            "load_parent_generation",
            "reuse_or_expand_cited_evidence",
            "rebuild_citation_repair_prompt_package",
            "submit_mo_generation_request",
            "validate_repaired_citations",
            "persist_child_generation_lineage",
            "persist_remediation_result",
            "notify_ag_result_available",
        ),
    },
}


@dataclass(frozen=True)
class RemediationExecutionPlanningError(ValueError):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def remediation_execution_transition_allowed(
    current_status: str,
    next_status: str,
) -> bool:
    return next_status in CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS.get(
        current_status,
        (),
    )


def build_remediation_execution_worker_plan(
    execution_record: Mapping[str, Any],
    *,
    planned_at: str | None = None,
) -> dict[str, Any]:
    normalized = validate_remediation_execution_record_for_worker(
        execution_record,
        require_plannable=True,
    )
    action_type = normalized["action_type"]
    policy = ACTION_WORKER_POLICIES[action_type]
    attempt_no = _positive_int(normalized.get("attempt_no"), default=1)
    parent_id = normalized["parent_cx_generation_id"]
    root_id = optional_text(normalized.get("root_cx_generation_id")) or parent_id

    plan = {
        "plan_schema_version": CX_REMEDIATION_EXECUTION_WORKER_PLAN_SCHEMA_VERSION,
        "plan_id": f"{normalized['remediation_action_id']}:attempt-{attempt_no}",
        "remediation_action_id": normalized["remediation_action_id"],
        "parent_cx_generation_id": parent_id,
        "root_cx_generation_id": root_id,
        "tenant_id": normalized.get("tenant_id"),
        "trace_id": normalized["trace_id"],
        "request_id": normalized["request_id"],
        "action_type": action_type,
        "lineage_type": normalized["lineage_type"],
        "start_status": normalized["execution_status"],
        "attempt_no": attempt_no,
        "planned_at": planned_at or _utc_now(),
        "state_machine": {
            status: list(next_statuses)
            for status, next_statuses in CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS.items()
        },
        "retrieval_package_policy": policy["retrieval_package_policy"],
        "prompt_package_policy": policy["prompt_package_policy"],
        "provider_boundary": PROVIDER_BOUNDARY,
        "parent_generation_mutation_allowed": False,
        "repair_generation_policy": {
            "creates_child_generation_record": True,
            "parent_generation_id": parent_id,
            "root_generation_id": root_id,
            "parent_generation_mutated": False,
            "repair_cx_generation_id_required_on_success": True,
        },
        "worker_stages": [
            _build_stage(stage_id, index=index)
            for index, stage_id in enumerate(policy["stages"], start=1)
        ],
        "redaction_policy": {
            "raw_content_storage": "forbidden",
            "prompt_text_storage": "forbidden",
            "evidence_text_storage": "forbidden",
            "provider_detail_storage": "forbidden",
            "stored_payload_shape": "ids_hashes_refs_and_short_previews_only",
        },
    }
    return validate_remediation_execution_worker_plan(plan)


def validate_remediation_execution_worker_plan(
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_redaction_safe(plan)
    if (
        plan.get("plan_schema_version")
        != CX_REMEDIATION_EXECUTION_WORKER_PLAN_SCHEMA_VERSION
    ):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.schema_version_invalid",
            detail="CX remediation execution worker plan schema version is invalid.",
        )
    action_type = _required_text(plan, "action_type")
    policy = _policy_for_action(action_type)
    if plan.get("lineage_type") != policy["lineage_type"]:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.lineage_invalid",
            detail="CX remediation execution worker plan lineage is invalid.",
        )
    if plan.get("provider_boundary") != PROVIDER_BOUNDARY:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.provider_boundary_invalid",
            detail="CX remediation execution worker plan must use MO service APIs.",
        )
    if plan.get("parent_generation_mutation_allowed") is not False:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.parent_mutation_forbidden",
            detail="CX remediation execution worker plan cannot mutate the parent.",
        )
    state_machine = _mapping(plan.get("state_machine"))
    if state_machine != {
        status: list(next_statuses)
        for status, next_statuses in CX_REMEDIATION_EXECUTION_STATUS_TRANSITIONS.items()
    }:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.state_machine_invalid",
            detail="CX remediation execution worker plan state machine is invalid.",
        )
    if plan.get("start_status") not in CX_REMEDIATION_EXECUTION_PLANNABLE_STATUSES:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.start_status_invalid",
            detail="CX remediation execution worker plan start status is not plannable.",
        )

    expected_stage_ids = tuple(policy["stages"])
    observed_stage_ids = tuple(
        stage.get("stage_id")
        for stage in _list_of_mappings(plan.get("worker_stages"))
    )
    if observed_stage_ids != expected_stage_ids:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.stages_invalid",
            detail="CX remediation execution worker plan stages are invalid.",
        )
    for stage in _list_of_mappings(plan.get("worker_stages")):
        if stage.get("raw_payload_storage") != "forbidden":
            raise RemediationExecutionPlanningError(
                error_code="cx.remediation_execution_plan.raw_storage_forbidden",
                detail="CX remediation execution worker stages cannot store raw payloads.",
            )
        if (
            stage.get("stage_id") == "submit_mo_generation_request"
            and stage.get("provider_boundary") != PROVIDER_BOUNDARY
        ):
            raise RemediationExecutionPlanningError(
                error_code="cx.remediation_execution_plan.provider_boundary_invalid",
                detail="MO generation stage must use the CX-to-MO service boundary.",
            )
    repair_policy = _mapping(plan.get("repair_generation_policy"))
    if repair_policy.get("parent_generation_mutated") is not False:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_plan.parent_mutation_forbidden",
            detail="Repair generation policy cannot mutate the parent generation.",
        )
    return dict(plan)


def validate_remediation_execution_record_for_worker(
    execution_record: Mapping[str, Any],
    *,
    require_plannable: bool = False,
) -> dict[str, Any]:
    _assert_redaction_safe(execution_record)
    if (
        execution_record.get("result_schema_version")
        != CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION
    ):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.record_schema_invalid",
            detail="CX remediation execution worker record schema version is invalid.",
        )
    action_type = _required_text(execution_record, "action_type")
    policy = _policy_for_action(action_type)
    lineage_type = _required_text(execution_record, "lineage_type")
    if lineage_type != policy["lineage_type"]:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.lineage_invalid",
            detail="CX remediation execution worker record lineage is invalid.",
        )
    execution_status = _required_text(execution_record, "execution_status")
    if execution_status not in CX_REMEDIATION_EXECUTION_STATUSES:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.status_invalid",
            detail="CX remediation execution worker record status is invalid.",
        )
    if (
        require_plannable
        and execution_status not in CX_REMEDIATION_EXECUTION_PLANNABLE_STATUSES
    ):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.status_not_plannable",
            detail="CX remediation execution worker can plan only active records.",
            status_code=409,
        )
    parent_id = _required_text(execution_record, "parent_cx_generation_id")
    repair_id = optional_text(execution_record.get("repair_cx_generation_id"))
    if repair_id is not None and repair_id == parent_id:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.parent_mutation_forbidden",
            detail="Repair generation id cannot equal the parent generation id.",
        )
    _required_text(execution_record, "remediation_action_id")
    _required_text(execution_record, "trace_id")
    _required_text(execution_record, "request_id")
    return dict(execution_record)


def build_remediation_execution_transition(
    execution_record: Mapping[str, Any],
    next_status: str,
    *,
    observed_at: str | None = None,
    repair_cx_generation_id: str | None = None,
    result_ref: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = validate_remediation_execution_record_for_worker(execution_record)
    current_status = normalized["execution_status"]
    if not remediation_execution_transition_allowed(current_status, next_status):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.invalid",
            detail=(
                "CX remediation execution cannot transition from "
                f"{current_status} to {next_status}."
            ),
            status_code=409,
        )
    observed = observed_at or _utc_now()
    update = _transition_update(
        normalized,
        next_status,
        repair_cx_generation_id=repair_cx_generation_id,
        result_ref=result_ref,
        failure=failure,
        observed_at=observed,
    )
    return {
        "transition_schema_version": CX_REMEDIATION_EXECUTION_TRANSITION_SCHEMA_VERSION,
        "remediation_action_id": normalized["remediation_action_id"],
        "parent_cx_generation_id": normalized["parent_cx_generation_id"],
        "from_status": current_status,
        "to_status": next_status,
        "terminal": next_status in CX_REMEDIATION_EXECUTION_TERMINAL_STATUSES,
        "parent_generation_mutated": False,
        "observed_at": observed,
        "record_update": update,
    }


def apply_remediation_execution_transition(
    execution_record: Mapping[str, Any],
    next_status: str,
    *,
    observed_at: str | None = None,
    repair_cx_generation_id: str | None = None,
    result_ref: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    transition = build_remediation_execution_transition(
        execution_record,
        next_status,
        observed_at=observed_at,
        repair_cx_generation_id=repair_cx_generation_id,
        result_ref=result_ref,
        failure=failure,
    )
    updated = deepcopy(dict(execution_record))
    updated.update(transition["record_update"])
    return updated


def _transition_update(
    execution_record: Mapping[str, Any],
    next_status: str,
    *,
    repair_cx_generation_id: str | None,
    result_ref: Mapping[str, Any] | None,
    failure: Mapping[str, Any] | None,
    observed_at: str,
) -> dict[str, Any]:
    if next_status == RUNNING:
        _assert_no_terminal_payload(execution_record)
        return {
            "execution_status": RUNNING,
            "repair_cx_generation_id": None,
            "result_ref": None,
            "failure": None,
            "updated_at": observed_at,
        }
    if next_status == SUCCEEDED:
        repair_id = _required_string(repair_cx_generation_id, "repair_cx_generation_id")
        if repair_id == execution_record["parent_cx_generation_id"]:
            raise RemediationExecutionPlanningError(
                error_code="cx.remediation_execution_transition.parent_mutation_forbidden",
                detail="Successful repair generation id cannot equal the parent id.",
            )
        return {
            "execution_status": SUCCEEDED,
            "repair_cx_generation_id": repair_id,
            "result_ref": _validate_result_ref(result_ref),
            "failure": None,
            "updated_at": observed_at,
        }
    if next_status == FAILED:
        return {
            "execution_status": FAILED,
            "repair_cx_generation_id": None,
            "result_ref": None,
            "failure": _validate_failure(failure),
            "updated_at": observed_at,
        }
    if next_status == CANCELLED:
        return {
            "execution_status": CANCELLED,
            "repair_cx_generation_id": None,
            "result_ref": None,
            "failure": _validate_optional_failure(failure),
            "updated_at": observed_at,
        }
    raise RemediationExecutionPlanningError(
        error_code="cx.remediation_execution_transition.status_invalid",
        detail=f"CX remediation execution target status is invalid: {next_status}.",
    )


def _build_stage(stage_id: str, *, index: int) -> dict[str, Any]:
    owner_service = "nex-mo" if stage_id == "submit_mo_generation_request" else "nex-cx"
    stage = {
        "stage_order": index,
        "stage_id": stage_id,
        "owner_service": owner_service,
        "raw_payload_storage": "forbidden",
        "safe_output_policy": "ids_hashes_refs_and_status_only",
    }
    if stage_id == "submit_mo_generation_request":
        stage["provider_boundary"] = PROVIDER_BOUNDARY
    return stage


def _policy_for_action(action_type: str) -> dict[str, Any]:
    if not remediation_action_executable_by_cx(action_type):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.action_not_executable",
            detail=f"Remediation action is not executable by CX: {action_type}",
        )
    policy = ACTION_WORKER_POLICIES.get(action_type)
    expected_lineage = remediation_lineage_type_for_action(action_type)
    if not isinstance(policy, Mapping) or policy.get("lineage_type") != expected_lineage:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.action_policy_invalid",
            detail=f"Remediation action worker policy is invalid: {action_type}",
        )
    return dict(policy)


def _assert_no_terminal_payload(execution_record: Mapping[str, Any]) -> None:
    if (
        execution_record.get("repair_cx_generation_id") is not None
        or execution_record.get("result_ref") is not None
        or execution_record.get("failure") is not None
    ):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.terminal_payload_invalid",
            detail="RUNNING transition requires an unfinalized execution record.",
        )


def _validate_result_ref(value: Mapping[str, Any] | None) -> dict[str, Any]:
    ref = _mapping(value)
    if ref != {
        "source_service": "nex-cx",
        "ref_type": "repair_execution",
        "ref_id": ref.get("ref_id"),
        "relation": "result_of",
    } or not optional_text(ref.get("ref_id")):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.result_ref_invalid",
            detail="Successful repair requires a canonical nex-cx repair_execution result_ref.",
        )
    return dict(ref)


def _validate_failure(value: Mapping[str, Any] | None) -> dict[str, Any]:
    failure = _mapping(value)
    _assert_redaction_safe(failure)
    _required_string(failure.get("failure_code"), "failure.failure_code")
    failure_class = _required_string(failure.get("failure_class"), "failure.failure_class")
    if failure_class not in SAFE_REPAIR_FAILURE_CLASSES:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.failure_class_invalid",
            detail="Repair failure class is not supported.",
        )
    if not isinstance(failure.get("retryable"), bool):
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.failure_retryable_invalid",
            detail="Repair failure retryable flag is required.",
        )
    _required_string(failure.get("safe_message"), "failure.safe_message")
    return dict(failure)


def _validate_optional_failure(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return _validate_failure(value)


def _assert_redaction_safe(value: Any) -> None:
    try:
        assert_cx_remediation_execution_payload_redaction_safe(value)
    except RemediationExecutionBoundaryError as exc:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_worker.sensitive_payload",
            detail=str(exc),
            status_code=422,
        ) from exc


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    try:
        return required_text(payload, key)
    except Exception as exc:
        raise RemediationExecutionPlanningError(
            error_code=f"cx.remediation_execution_worker.{key}_required",
            detail=f"CX remediation execution worker requires {key}.",
        ) from exc


def _required_string(value: Any, field_name: str) -> str:
    text = optional_text(value)
    if text is None:
        raise RemediationExecutionPlanningError(
            error_code="cx.remediation_execution_transition.field_required",
            detail=f"CX remediation execution transition requires {field_name}.",
        )
    return text


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
