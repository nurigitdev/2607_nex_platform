from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_ag.generation_remediation import (
    GenerationRemediationError,
    REMEDIATION_ACTION_SCHEMA_VERSION,
    REMEDIATION_STATUS_TRANSITIONS,
    update_generation_remediation_action_status,
)
from nex_ag.generation_remediation_handoff import (
    CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
    CX_EXECUTABLE_ACTION_TYPES,
    CxRemediationExecutionClient,
    CxRemediationExecutionClientError,
    assert_remediation_action_handoff_safe,
    optional_text,
    required_text,
)


AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION = (
    "ag_generation_remediation_execution_handoff_plan.v1"
)
AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION = (
    "ag_generation_remediation_execution_dispatch.v1"
)
AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION = (
    "ag_generation_remediation_execution_result_ref.v1"
)
TARGET_STATUS_BY_CX_EXECUTION_STATUS = {
    "ACCEPTED": "WAITING_ON_CX",
    "RUNNING": "WAITING_ON_CX",
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
}
TERMINAL_AG_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


@dataclass(frozen=True)
class GenerationRemediationExecutionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class GenerationRemediationTaskExecutionStore(Protocol):
    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        ...


def dispatch_generation_remediation_execution(
    *,
    store: GenerationRemediationTaskExecutionStore,
    cx_client: CxRemediationExecutionClient,
    remediation_action_id: str,
    cx_generation_id: str | None = None,
    request_id: str,
    trace_id: str,
    requested_at: str | None = None,
    idempotency_key: str | None = None,
    planned_at: str | None = None,
) -> dict[str, Any]:
    action_id = required_text(
        {"remediation_action_id": remediation_action_id},
        "remediation_action_id",
    )
    requested_generation_id = optional_text(cx_generation_id)
    request_id_value = required_text({"request_id": request_id}, "request_id")
    trace_id_value = required_text({"trace_id": trace_id}, "trace_id")
    try:
        record = store.get(action_id)
    except GenerationRemediationError as exc:
        raise _execution_error_from_exception(exc) from exc
    if record is None:
        raise GenerationRemediationExecutionError(
            status_code=404,
            error_code="ag.remediation_execution_task_not_found",
            detail=f"Generation remediation task was not found: {action_id}",
            retryable=False,
        )
    if (
        requested_generation_id is not None
        and optional_text(record.get("cx_generation_id")) != requested_generation_id
    ):
        raise GenerationRemediationExecutionError(
            status_code=404,
            error_code="ag.remediation_execution_task_not_found",
            detail=f"Generation remediation task was not found: {action_id}",
            retryable=False,
        )

    try:
        cx_result = cx_client.submit_remediation_action(
            record,
            request_id=request_id_value,
            trace_id=trace_id_value,
            requested_at=requested_at,
            idempotency_key=idempotency_key,
        )
    except CxRemediationExecutionClientError as exc:
        raise GenerationRemediationExecutionError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.retryable,
        ) from exc

    plan = build_generation_remediation_execution_handoff_plan(
        record,
        cx_result,
        request_id=request_id_value,
        trace_id=trace_id_value,
        planned_at=planned_at,
    )
    planned_records = apply_generation_remediation_execution_handoff_plan(
        record,
        plan,
        request_id=request_id_value,
        trace_id=trace_id_value,
        updated_at=planned_at,
    )
    saved_records: list[dict[str, Any]] = []
    try:
        for planned_record in planned_records:
            saved_records.append(store.save(planned_record))
    except GenerationRemediationError as exc:
        raise _execution_error_from_exception(exc) from exc

    final_record = saved_records[-1]
    return {
        "dispatch_schema_version": AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION,
        "dispatch_status": "DISPATCHED",
        "remediation_action_id": action_id,
        "cx_generation_id": final_record["cx_generation_id"],
        "trace_id": trace_id_value,
        "request_id": request_id_value,
        "cx_execution_status": plan["cx_execution_status"],
        "final_action_status": final_record["action_status"],
        "status_update_count": len(saved_records),
        "result_ref": deepcopy(plan["result_ref"]),
        "plan": clone_plan(plan),
        "task": deepcopy(final_record),
        "redaction_summary": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "provider_detail_included": False,
        },
    }


def build_generation_remediation_execution_handoff_plan(
    record: Mapping[str, Any],
    cx_execution_result: Mapping[str, Any],
    *,
    request_id: str,
    trace_id: str,
    planned_at: str | None = None,
) -> dict[str, Any]:
    normalized_record = _validate_remediation_record(record)
    normalized_result = _validate_cx_execution_result(
        cx_execution_result,
        record=normalized_record,
    )
    current_status = str(normalized_record["action_status"])
    if current_status in TERMINAL_AG_STATUSES:
        raise GenerationRemediationExecutionError(
            status_code=409,
            error_code="ag.remediation_execution_terminal_task",
            detail=(
                "Terminal generation remediation tasks cannot be handed off to CX: "
                f"{current_status}"
            ),
            retryable=False,
        )

    target_status = TARGET_STATUS_BY_CX_EXECUTION_STATUS[
        normalized_result["execution_status"]
    ]
    transitions = _status_path(current_status, target_status)
    result_ref = build_generation_remediation_execution_result_ref(
        normalized_result,
        record=normalized_record,
    )
    status_updates = [
        _status_update_payload(
            status,
            include_result_ref=(index == len(transitions) - 1),
            result_ref=result_ref,
        )
        for index, status in enumerate(transitions)
    ]
    observed_at = planned_at or _utc_now()
    return {
        "plan_schema_version": AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION,
        "remediation_action_id": normalized_record["remediation_action_id"],
        "cx_generation_id": normalized_record["cx_generation_id"],
        "trace_id": required_text({"trace_id": trace_id}, "trace_id"),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "current_action_status": current_status,
        "target_action_status": target_status,
        "cx_execution_status": normalized_result["execution_status"],
        "status_updates": status_updates,
        "result_ref": result_ref,
        "debug_paths": {
            "ag_remediation_task_path": (
                "/admin/v1/generation-audit/generations/"
                f"{normalized_record['cx_generation_id']}/remediation-tasks/"
                f"{normalized_record['remediation_action_id']}"
            ),
            "cx_remediation_execution_path": (
                "/api/v1/generations/"
                f"{normalized_record['cx_generation_id']}/remediation-executions"
            ),
        },
        "redaction_summary": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "raw_evidence_included": False,
            "provider_detail_included": False,
        },
        "planned_at": observed_at,
    }


def build_generation_remediation_execution_result_ref(
    cx_execution_result: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    action_id = required_text(record, "remediation_action_id")
    cx_generation_id = required_text(record, "cx_generation_id")
    supplied = (
        dict(cx_execution_result["result_ref"])
        if isinstance(cx_execution_result.get("result_ref"), Mapping)
        else {}
    )
    return {
        "result_ref_schema_version": AG_REMEDIATION_EXECUTION_RESULT_REF_SCHEMA_VERSION,
        "source_service": optional_text(supplied.get("source_service")) or "nex-cx",
        "ref_type": optional_text(supplied.get("ref_type")) or "repair_execution",
        "ref_id": optional_text(supplied.get("ref_id")) or action_id,
        "relation": optional_text(supplied.get("relation")) or "result_of",
        "cx_generation_id": cx_generation_id,
        "remediation_action_id": action_id,
        "repair_cx_generation_id": optional_text(
            cx_execution_result.get("repair_cx_generation_id")
        ),
        "cx_execution_status": required_text(
            cx_execution_result,
            "execution_status",
        ),
    }


def apply_generation_remediation_execution_handoff_plan(
    record: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    request_id: str,
    trace_id: str,
    updated_at: str | None = None,
) -> list[dict[str, Any]]:
    if (
        plan.get("plan_schema_version")
        != AG_REMEDIATION_EXECUTION_HANDOFF_PLAN_SCHEMA_VERSION
    ):
        raise GenerationRemediationExecutionError(
            status_code=422,
            error_code="ag.remediation_execution_plan_schema_invalid",
            detail="AG remediation execution handoff plan schema version is invalid.",
            retryable=False,
        )
    updates = plan.get("status_updates")
    if not isinstance(updates, list) or not updates:
        raise GenerationRemediationExecutionError(
            status_code=422,
            error_code="ag.remediation_execution_plan_updates_invalid",
            detail="AG remediation execution handoff plan requires status updates.",
            retryable=False,
        )
    current = dict(record)
    applied: list[dict[str, Any]] = []
    for update in updates:
        if not isinstance(update, Mapping):
            raise GenerationRemediationExecutionError(
                status_code=422,
                error_code="ag.remediation_execution_plan_update_invalid",
                detail="AG remediation execution handoff update must be an object.",
                retryable=False,
            )
        try:
            current = update_generation_remediation_action_status(
                current,
                dict(update),
                request_id=request_id,
                trace_id=trace_id,
                updated_at=updated_at,
            )
        except Exception as exc:
            raise GenerationRemediationExecutionError(
                status_code=int(getattr(exc, "status_code", 409)),
                error_code=str(
                    getattr(
                        exc,
                        "error_code",
                        "ag.remediation_execution_plan_apply_failed",
                    )
                ),
                detail=str(getattr(exc, "detail", str(exc))),
                retryable=False,
            ) from exc
        applied.append(current)
    return applied


def _validate_remediation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("action_schema_version") != REMEDIATION_ACTION_SCHEMA_VERSION:
        raise GenerationRemediationExecutionError(
            status_code=422,
            error_code="ag.remediation_execution_record_schema_invalid",
            detail="AG remediation task schema version is invalid.",
            retryable=False,
        )
    normalized = dict(record)
    try:
        assert_remediation_action_handoff_safe(normalized)
    except Exception as exc:
        raise GenerationRemediationExecutionError(
            status_code=int(getattr(exc, "status_code", 422)),
            error_code=str(
                getattr(exc, "error_code", "ag.remediation_execution_record_sensitive")
            ),
            detail=str(getattr(exc, "detail", str(exc))),
            retryable=False,
        ) from exc
    action_type = required_text(normalized, "action_type")
    if action_type not in CX_EXECUTABLE_ACTION_TYPES:
        raise GenerationRemediationExecutionError(
            status_code=422,
            error_code="ag.remediation_execution_action_not_executable",
            detail=f"Remediation action is not executable by CX: {action_type}",
            retryable=False,
        )
    required_text(normalized, "remediation_action_id")
    required_text(normalized, "cx_generation_id")
    status = required_text(normalized, "action_status")
    if status not in REMEDIATION_STATUS_TRANSITIONS:
        raise GenerationRemediationExecutionError(
            status_code=422,
            error_code="ag.remediation_execution_status_invalid",
            detail=f"AG remediation task status is invalid: {status}",
            retryable=False,
        )
    return normalized


def _validate_cx_execution_result(
    result: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(result)
    if (
        normalized.get("result_schema_version")
        != CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION
    ):
        raise GenerationRemediationExecutionError(
            status_code=502,
            error_code="ag.remediation_execution_cx_result_schema_invalid",
            detail="CX remediation execution result schema version is invalid.",
            retryable=True,
        )
    action_id = required_text(normalized, "remediation_action_id")
    if action_id != record["remediation_action_id"]:
        raise GenerationRemediationExecutionError(
            status_code=409,
            error_code="ag.remediation_execution_action_mismatch",
            detail="CX remediation execution result action id does not match AG task.",
            retryable=False,
        )
    parent_id = required_text(normalized, "parent_cx_generation_id")
    if parent_id != record["cx_generation_id"]:
        raise GenerationRemediationExecutionError(
            status_code=409,
            error_code="ag.remediation_execution_generation_mismatch",
            detail="CX remediation execution result generation id does not match AG task.",
            retryable=False,
        )
    execution_status = required_text(normalized, "execution_status")
    if execution_status not in TARGET_STATUS_BY_CX_EXECUTION_STATUS:
        raise GenerationRemediationExecutionError(
            status_code=502,
            error_code="ag.remediation_execution_cx_status_invalid",
            detail=f"CX remediation execution status is invalid: {execution_status}",
            retryable=True,
        )
    return normalized


def _status_path(current_status: str, target_status: str) -> list[str]:
    if current_status == target_status:
        return [target_status]
    if target_status in REMEDIATION_STATUS_TRANSITIONS.get(current_status, ()):
        return [target_status]
    if (
        current_status in {"PROPOSED", "ASSIGNED"}
        and "IN_PROGRESS" in REMEDIATION_STATUS_TRANSITIONS[current_status]
        and target_status in REMEDIATION_STATUS_TRANSITIONS["IN_PROGRESS"]
    ):
        return ["IN_PROGRESS", target_status]
    raise GenerationRemediationExecutionError(
        status_code=409,
        error_code="ag.remediation_execution_status_transition_invalid",
        detail=f"Cannot move remediation task from {current_status} to {target_status}.",
        retryable=False,
    )


def _status_update_payload(
    status: str,
    *,
    include_result_ref: bool,
    result_ref: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {"action_status": status}
    if include_result_ref:
        payload["result_ref"] = _ag_task_result_ref(result_ref)
    return payload


def _ag_task_result_ref(result_ref: Mapping[str, Any]) -> dict[str, str]:
    return {
        "source_service": str(result_ref.get("source_service") or "nex-cx"),
        "ref_type": str(result_ref.get("ref_type") or "repair_execution"),
        "ref_id": str(result_ref.get("ref_id") or result_ref["remediation_action_id"]),
        "relation": str(result_ref.get("relation") or "result_of"),
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def clone_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(plan))


def _execution_error_from_exception(exc: Exception) -> GenerationRemediationExecutionError:
    return GenerationRemediationExecutionError(
        status_code=int(getattr(exc, "status_code", 500)),
        error_code=str(
            getattr(exc, "error_code", "ag.remediation_execution_store_unavailable")
        ),
        detail=str(getattr(exc, "detail", str(exc))),
        retryable=int(getattr(exc, "status_code", 500)) >= 500,
    )
