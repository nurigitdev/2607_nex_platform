"""Grade-based Project workforce planning without private payroll data."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref, validate_hash_ref

ASSIGN_OPERATION = "PROJECT.WORK_ASSIGNMENT.ASSIGN"
LIST_OPERATION = "PROJECT.WORK_ASSIGNMENT.LIST"
ASSIGN_PATH = "/internal/v2/projects/{project_id}/work-assignments:assign"
LIST_PATH = "/internal/v2/projects/{project_id}/work-assignments"

PERFORMER_KINDS = frozenset({"HUMAN", "AGENT"})
ASSIGNMENT_SCOPES = frozenset({"EXECUTE", "REVIEW", "REPORT"})
PRIVATE_PAYROLL_FIELDS = frozenset(
    {
        "actual_day_rate",
        "actual_payroll_cost",
        "actual_salary",
        "compensation",
        "employee_salary",
        "payroll_amount",
        "salary",
    }
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_PROJECTION_FIELDS = frozenset(
    {
        "tenant_id",
        "assignment_id",
        "project_id",
        "work_set_id",
        "work_set_revision",
        "work_code_id",
        "performer_kind",
        "subject_ref",
        "performer_authority_hash",
        "assignment_scope",
        "planned_man_days",
        "planned_grade_id",
        "grade_policy_ref",
        "grade_policy_hash",
        "valid_from",
        "valid_until",
        "approved_proof_hash",
        "approved_by_subject_id",
        "assignment_hash",
        "created_at",
    }
)


class WorkforcePlanningError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class WorkAssignmentPlanLine:
    assignment_id: str
    work_set_id: str
    work_set_revision: int
    work_code_id: str
    performer_kind: str
    subject_ref: str
    assignment_scope: str
    planned_man_days: Decimal
    planned_grade_id: str
    grade_policy_ref: str
    grade_policy_hash: str
    valid_from: date
    valid_until: date | None
    approved_proof_hash: str


@dataclass(frozen=True)
class EosWorkAssignmentRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str
    payload: Mapping[str, Any] | None = None
    query: Mapping[str, str] | None = None


def build_work_assignment_request(
    *,
    tenant_id: str,
    project_id: str,
    requester_subject_id: str,
    business_operation_id: str,
    idempotency_key: str,
    line: WorkAssignmentPlanLine,
) -> EosWorkAssignmentRequest:
    tenant_id = _scoped_id("tenant_id", tenant_id)
    project_id = _uuid("project_id", project_id)
    requester = _scoped_id("requester_subject_id", requester_subject_id)
    assignment = _line_payload(line)
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "business_operation_id": _uuid("business_operation_id", business_operation_id),
        "idempotency_key": _text("idempotency_key", idempotency_key, 256),
        "requester_subject_id": requester,
        "requested_operation": ASSIGN_OPERATION,
        "assignment": assignment,
    }
    payload["payload_hash"] = work_assignment_payload_hash(
        {**payload, "project_id": project_id}
    )
    return EosWorkAssignmentRequest(
        method="POST",
        path=ASSIGN_PATH.format(project_id=project_id),
        operation_id=ASSIGN_OPERATION,
        tenant_id=tenant_id,
        subject_id=requester,
        payload=MappingProxyType(payload),
    )


def build_work_assignment_list_request(
    *,
    tenant_id: str,
    project_id: str,
    requester_subject_id: str,
    effective_on: date | None = None,
    work_code_id: str | None = None,
) -> EosWorkAssignmentRequest:
    query: dict[str, str] = {}
    if effective_on is not None:
        query["effective_on"] = _date("effective_on", effective_on).isoformat()
    if work_code_id is not None:
        query["work_code_id"] = _work_code("work_code_id", work_code_id)
    return EosWorkAssignmentRequest(
        method="GET",
        path=LIST_PATH.format(project_id=_uuid("project_id", project_id)),
        operation_id=LIST_OPERATION,
        tenant_id=_scoped_id("tenant_id", tenant_id),
        subject_id=_scoped_id("requester_subject_id", requester_subject_id),
        query=MappingProxyType(query) if query else None,
    )


def admit_work_assignment_projection(
    value: object, *, tenant_id: str, project_id: str
) -> Mapping[str, Any]:
    item = _object(value, "EOS_WORK_ASSIGNMENT_INVALID")
    if PRIVATE_PAYROLL_FIELDS.intersection(item):
        raise WorkforcePlanningError(
            "PRIVATE_PAYROLL_EXPOSED", "standard projection contains private payroll"
        )
    if set(item) != _PROJECTION_FIELDS:
        raise WorkforcePlanningError(
            "EOS_WORK_ASSIGNMENT_FIELDS_INVALID", "projection fields drifted"
        )
    if item.get("tenant_id") != _scoped_id("tenant_id", tenant_id) or item.get(
        "project_id"
    ) != _uuid("project_id", project_id):
        raise WorkforcePlanningError(
            "EOS_WORK_ASSIGNMENT_SCOPE_MISMATCH", "tenant or Project identity drifted"
        )
    _uuid("assignment_id", item.get("assignment_id"))
    _uuid("work_set_id", item.get("work_set_id"))
    _positive_int("work_set_revision", item.get("work_set_revision"))
    _work_code("work_code_id", item.get("work_code_id"))
    _choice("performer_kind", item.get("performer_kind"), PERFORMER_KINDS)
    _scoped_id("subject_ref", item.get("subject_ref"))
    _hash_ref("performer_authority_hash", item.get("performer_authority_hash"))
    _choice("assignment_scope", item.get("assignment_scope"), ASSIGNMENT_SCOPES)
    _positive_decimal("planned_man_days", item.get("planned_man_days"))
    _text("planned_grade_id", item.get("planned_grade_id"), 64)
    _text("grade_policy_ref", item.get("grade_policy_ref"), 256)
    _hash_ref("grade_policy_hash", item.get("grade_policy_hash"))
    valid_from = _date_text("valid_from", item.get("valid_from"))
    valid_until = (
        _date_text("valid_until", item.get("valid_until"))
        if item.get("valid_until") is not None
        else None
    )
    if valid_until is not None and valid_until < valid_from:
        raise WorkforcePlanningError(
            "EOS_WORK_ASSIGNMENT_PERIOD_INVALID", "valid period is reversed"
        )
    _hash_ref("approved_proof_hash", item.get("approved_proof_hash"))
    _scoped_id("approved_by_subject_id", item.get("approved_by_subject_id"))
    _hash_ref("assignment_hash", item.get("assignment_hash"))
    if not isinstance(item.get("created_at"), str):
        raise WorkforcePlanningError(
            "EOS_WORK_ASSIGNMENT_CREATED_AT_INVALID", "date-time text required"
        )
    return MappingProxyType(dict(item))


def admit_work_assignment_collection(
    value: object, *, tenant_id: str, project_id: str
) -> tuple[Mapping[str, Any], ...]:
    payload = _object(value, "EOS_WORK_ASSIGNMENT_COLLECTION_INVALID")
    if (
        payload.get("private_payroll_excluded") is not True
        or payload.get("data_classification") != "INTERNAL_PLANNING"
    ):
        raise WorkforcePlanningError(
            "PRIVATE_PAYROLL_BOUNDARY_INVALID", "privacy contract drifted"
        )
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("count") != len(items):
        raise WorkforcePlanningError(
            "EOS_WORK_ASSIGNMENT_COLLECTION_INVALID", "items/count drifted"
        )
    return tuple(
        admit_work_assignment_projection(
            item, tenant_id=tenant_id, project_id=project_id
        )
        for item in items
    )


def work_assignment_payload_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise WorkforcePlanningError("PAYLOAD_INVALID", "object required")
    projected = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "requested_operation",
            "trace",
        }
    }
    return nsl_write_payload_hash_ref({"operation": ASSIGN_OPERATION, **projected})


def _line_payload(line: WorkAssignmentPlanLine) -> dict[str, Any]:
    if not isinstance(line, WorkAssignmentPlanLine):
        raise WorkforcePlanningError("PLAN_LINE_INVALID", "typed plan line required")
    valid_from = _date("valid_from", line.valid_from)
    valid_until = (
        _date("valid_until", line.valid_until) if line.valid_until is not None else None
    )
    if valid_until is not None and valid_until < valid_from:
        raise WorkforcePlanningError("PLAN_PERIOD_INVALID", "period is reversed")
    return {
        "assignment_id": _uuid("assignment_id", line.assignment_id),
        "work_set_id": _uuid("work_set_id", line.work_set_id),
        "work_set_revision": _positive_int("work_set_revision", line.work_set_revision),
        "work_code_id": _work_code("work_code_id", line.work_code_id),
        "performer_kind": _choice(
            "performer_kind", line.performer_kind, PERFORMER_KINDS
        ),
        "subject_ref": _scoped_id("subject_ref", line.subject_ref),
        "assignment_scope": _choice(
            "assignment_scope", line.assignment_scope, ASSIGNMENT_SCOPES
        ),
        "planned_man_days": format(
            _positive_decimal("planned_man_days", line.planned_man_days), "f"
        ),
        "planned_grade_id": _text("planned_grade_id", line.planned_grade_id, 64),
        "grade_policy_ref": _text("grade_policy_ref", line.grade_policy_ref, 256),
        "grade_policy_hash": _hash_ref("grade_policy_hash", line.grade_policy_hash),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
        "approved_proof_hash": _hash_ref(
            "approved_proof_hash", line.approved_proof_hash
        ),
    }


def _object(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkforcePlanningError(code, "object required")
    return value


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise WorkforcePlanningError(f"{field.upper()}_INVALID", "stable ID required")
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "UUID required"
        ) from error


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "positive integer required"
        )
    return value


def _positive_decimal(field: str, value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "exact positive decimal required"
        )
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "exact positive decimal required"
        ) from error
    if not normalized.is_finite() or normalized <= 0 or normalized > Decimal(99999999):
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "positive range required"
        )
    if normalized.as_tuple().exponent < -4:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "at most four decimal places"
        )
    return normalized.quantize(Decimal("0.0001"))


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", f"1..{maximum} characters required"
        )
    return normalized


def _choice(field: str, value: object, allowed: frozenset[str]) -> str:
    normalized = _text(field, value, 64)
    if normalized not in allowed:
        raise WorkforcePlanningError(f"{field.upper()}_INVALID", "value not admitted")
    return normalized


def _work_code(field: str, value: object) -> str:
    normalized = _text(field, value, 16)
    if _WORK_CODE.fullmatch(normalized) is None:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "canonical FL code required"
        )
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as error:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "SHA-256 hash reference required"
        ) from error


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise WorkforcePlanningError(f"{field.upper()}_INVALID", "date required")
    return value


def _date_text(field: str, value: object) -> date:
    if not isinstance(value, str):
        raise WorkforcePlanningError(f"{field.upper()}_INVALID", "ISO date required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise WorkforcePlanningError(
            f"{field.upper()}_INVALID", "ISO date required"
        ) from error
