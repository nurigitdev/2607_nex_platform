"""MyBee consumer contract for EOS company and Project-set approvals."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    validate_hash_ref,
)

ACCOUNTING_APPROVAL_REQUEST_OPERATION = "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
ACCOUNTING_APPROVAL_REQUEST_PATH = "/internal/v2/finance/accounting-approval-cases"
SCOPED_APPROVAL_PURPOSES = frozenset({"DOCUMENT_SIGNOFF", "ACCOUNTING_POSTING"})
SCOPED_APPROVAL_SCOPE_TYPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})
SCOPED_APPROVAL_STATES = frozenset(
    {"PENDING", "APPROVED", "REJECTED", "CANCELLED", "EXPIRED"}
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CASE_FIELDS = frozenset(
    {
        "tenant_id",
        "case_id",
        "company_id",
        "purpose",
        "scope_type",
        "project_ids",
        "subject_ref",
        "subject_revision",
        "subject_hash",
        "requester_subject_id",
        "approval_policy_id",
        "correlation_id",
        "causation_id",
        "expires_at",
    }
)
_CASE_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "case_id",
        "company_id",
        "purpose",
        "scope_type",
        "project_set_hash",
        "project_ids",
        "subject_ref",
        "subject_revision",
        "subject_hash",
        "requester_ref",
        "approval_policy_ref",
        "oa_decision_ref",
        "authorization_revision_hash",
        "authorization_checked_at",
        "state",
        "active_stage_order",
        "stage_count",
        "target_role_ref",
        "version",
        "case_hash",
        "created_business_operation_id",
        "correlation_id",
        "causation_id",
        "expires_at",
        "created_at",
        "updated_at",
        "decided_at",
        "project_bindings",
    }
)


class ScopedApprovalContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class EosScopedApprovalRequest:
    method: str
    path: str
    operation_id: str
    payload: Mapping[str, Any]


def build_scoped_approval_request(
    *,
    tenant_id: str,
    business_operation_id: str,
    idempotency_key: str,
    case_id: str,
    company_id: str,
    purpose: str,
    scope_type: str,
    project_ids: Sequence[str],
    subject_ref: str,
    subject_revision: int,
    subject_hash: str,
    requester_subject_id: str,
    approval_policy_id: str,
    correlation_id: str,
    causation_id: str,
    accounting_review: Mapping[str, Any] | None = None,
    document_signoff_context: Mapping[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> EosScopedApprovalRequest:
    normalized_scope = _choice("scope_type", scope_type, SCOPED_APPROVAL_SCOPE_TYPES)
    normalized_projects = _project_ids(project_ids)
    _require_scope_shape(normalized_scope, normalized_projects)
    case = {
        "tenant_id": _scoped_id("tenant_id", tenant_id, 128),
        "case_id": _uuid("case_id", case_id),
        "company_id": _uuid("company_id", company_id),
        "purpose": _choice("purpose", purpose, SCOPED_APPROVAL_PURPOSES),
        "scope_type": normalized_scope,
        "project_ids": normalized_projects,
        "subject_ref": _text("subject_ref", subject_ref, 256),
        "subject_revision": _positive_int("subject_revision", subject_revision),
        "subject_hash": _hash_ref("subject_hash", subject_hash),
        "requester_subject_id": _scoped_id(
            "requester_subject_id", requester_subject_id, 128
        ),
        "approval_policy_id": _uuid("approval_policy_id", approval_policy_id),
        "correlation_id": _scoped_id("correlation_id", correlation_id, 128),
        "causation_id": _scoped_id("causation_id", causation_id, 128),
        "expires_at": _timestamp(expires_at),
    }
    if accounting_review is not None:
        if not isinstance(accounting_review, Mapping):
            raise _error(
                "MYBEE_APPROVAL_REVIEW_INVALID",
                "accounting_review must be an object",
            )
        case["accounting_review"] = dict(accounting_review)
    if document_signoff_context is not None:
        if not isinstance(document_signoff_context, Mapping):
            raise _error(
                "MYBEE_DOCUMENT_SIGNOFF_CONTEXT_INVALID",
                "document_signoff_context must be an object",
            )
        case["document_signoff_context"] = dict(document_signoff_context)
    if case["purpose"] == "DOCUMENT_SIGNOFF":
        if document_signoff_context is None or accounting_review is not None:
            raise _error(
                "MYBEE_DOCUMENT_SIGNOFF_CONTEXT_INVALID",
                "DOCUMENT_SIGNOFF requires only document_signoff_context",
            )
    elif document_signoff_context is not None:
        raise _error(
            "MYBEE_DOCUMENT_SIGNOFF_CONTEXT_INVALID",
            "ACCOUNTING_POSTING cannot carry document_signoff_context",
        )
    payload: dict[str, Any] = {
        "tenant_id": case["tenant_id"],
        "business_operation_id": _uuid("business_operation_id", business_operation_id),
        "idempotency_key": _text("idempotency_key", idempotency_key, 256),
        "requested_operation": ACCOUNTING_APPROVAL_REQUEST_OPERATION,
        "case": case,
    }
    payload["payload_hash"] = scoped_approval_request_hash(payload)
    return EosScopedApprovalRequest(
        method="POST",
        path=ACCOUNTING_APPROVAL_REQUEST_PATH,
        operation_id=ACCOUNTING_APPROVAL_REQUEST_OPERATION,
        payload=MappingProxyType(payload),
    )


def scoped_approval_request_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise _error("MYBEE_APPROVAL_REQUEST_INVALID", "payload must be an object")
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
    return nsl_write_payload_hash_ref(
        {"operation": ACCOUNTING_APPROVAL_REQUEST_OPERATION, **projected}
    )


def admit_scoped_approval_receipt(
    value: object,
    *,
    tenant_id: str,
    business_operation_id: str,
    case_id: str,
) -> Mapping[str, Any]:
    fields = {
        "schema_version",
        "created",
        "tenant_id",
        "business_operation_id",
        "commit_state",
        "scoped_approval_case",
        "wc_publication",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("MYBEE_APPROVAL_RECEIPT_INVALID", "receipt fields drifted")
    receipt = dict(value)
    if receipt["schema_version"] != "eos_scoped_approval_request_receipt.v2":
        raise _error("MYBEE_APPROVAL_RECEIPT_INVALID", "schema version drifted")
    if (
        not isinstance(receipt["created"], bool)
        or receipt["commit_state"] != "COMMITTED"
    ):
        raise _error("MYBEE_APPROVAL_RECEIPT_INVALID", "commit receipt is invalid")
    if receipt["tenant_id"] != _scoped_id("tenant_id", tenant_id, 128):
        raise _error("MYBEE_APPROVAL_SCOPE_MISMATCH", "tenant drifted")
    if receipt["business_operation_id"] != _uuid(
        "business_operation_id", business_operation_id
    ):
        raise _error("MYBEE_APPROVAL_SCOPE_MISMATCH", "operation drifted")
    case = _admit_case(
        receipt["scoped_approval_case"],
        tenant_id=tenant_id,
        case_id=case_id,
    )
    publication = receipt["wc_publication"]
    if (
        not isinstance(publication, Mapping)
        or set(publication) != {"work_item", "created"}
        or not isinstance(publication["created"], bool)
        or not isinstance(publication["work_item"], Mapping)
    ):
        raise _error("MYBEE_APPROVAL_WC_INVALID", "WC publication drifted")
    work_item = publication["work_item"]
    if (
        work_item.get("tenant_id") != tenant_id
        or work_item.get("approval_domain") != "BUSINESS_FORMAL"
        or work_item.get("approval_provider_type") != "EOS"
        or work_item.get("approval_request_id") != case_id
        or work_item.get("business_operation_id") != business_operation_id
        or work_item.get("protected_request_ref") != case["subject_ref"]
    ):
        raise _error("MYBEE_APPROVAL_WC_INVALID", "WC lineage drifted")
    return MappingProxyType(receipt)


def _admit_case(value: object, *, tenant_id: str, case_id: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CASE_PROJECTION_FIELDS:
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "case fields drifted")
    case = dict(value)
    if case["schema_version"] != "eos_scoped_approval_case.v2":
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "case schema drifted")
    if case["tenant_id"] != tenant_id or case["case_id"] != _uuid("case_id", case_id):
        raise _error("MYBEE_APPROVAL_SCOPE_MISMATCH", "case identity drifted")
    _uuid("company_id", case["company_id"])
    _choice("purpose", case["purpose"], SCOPED_APPROVAL_PURPOSES)
    scope_type = _choice("scope_type", case["scope_type"], SCOPED_APPROVAL_SCOPE_TYPES)
    project_ids = _project_ids(case["project_ids"])
    if project_ids != case["project_ids"]:
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "Project order drifted")
    _require_scope_shape(scope_type, project_ids)
    for field in (
        "project_set_hash",
        "subject_hash",
        "authorization_revision_hash",
        "case_hash",
    ):
        _hash_ref(field, case[field])
    _scoped_id("subject_ref", case["subject_ref"], 256)
    _positive_int("subject_revision", case["subject_revision"])
    _choice("state", case["state"], SCOPED_APPROVAL_STATES)
    _positive_int("stage_count", case["stage_count"])
    _positive_int("version", case["version"])
    for field in ("authorization_checked_at", "created_at", "updated_at"):
        _timestamp(case[field])
    for field in ("expires_at", "decided_at"):
        if case[field] is not None:
            _timestamp(case[field])
    requester = case["requester_ref"]
    if not isinstance(requester, Mapping) or set(requester) != {"type", "id"}:
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "requester drifted")
    policy = case["approval_policy_ref"]
    if not isinstance(policy, Mapping) or set(policy) != {"id", "version", "hash"}:
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "policy drifted")
    _uuid("approval_policy_ref.id", policy["id"])
    _positive_int("approval_policy_ref.version", policy["version"])
    _hash_ref("approval_policy_ref.hash", policy["hash"])
    bindings = case["project_bindings"]
    if not isinstance(bindings, list) or len(bindings) != len(project_ids):
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "binding count drifted")
    if sorted(item.get("project_id") for item in bindings) != project_ids:
        raise _error("MYBEE_APPROVAL_CASE_INVALID", "binding Project drifted")
    for binding in bindings:
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"project_id", "company_id", "authorization_scope_hash"}
            or binding["company_id"] != case["company_id"]
        ):
            raise _error("MYBEE_APPROVAL_CASE_INVALID", "binding scope drifted")
        _hash_ref("authorization_scope_hash", binding["authorization_scope_hash"])
    return MappingProxyType(case)


def _project_ids(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _error("MYBEE_APPROVAL_PROJECT_SET_INVALID", "must be an array")
    projects = [_uuid("project_ids", item) for item in value]
    if len(projects) != len(set(projects)):
        raise _error("MYBEE_APPROVAL_PROJECT_SET_INVALID", "must be unique")
    return sorted(projects)


def _require_scope_shape(scope_type: str, project_ids: Sequence[str]) -> None:
    if (
        (scope_type == "COMPANY" and project_ids)
        or (scope_type == "PROJECT" and len(project_ids) != 1)
        or (scope_type == "PROJECT_SET" and len(project_ids) < 2)
    ):
        raise _error("MYBEE_APPROVAL_PROJECT_SET_INVALID", "scope shape drifted")


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _error("MYBEE_APPROVAL_ID_INVALID", f"{field} invalid") from exc


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SCOPED_ID.fullmatch(value) is None
    ):
        raise _error("MYBEE_APPROVAL_ID_INVALID", f"{field} invalid")
    return value


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _error("MYBEE_APPROVAL_FIELD_INVALID", f"{field} invalid")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error("MYBEE_APPROVAL_FIELD_INVALID", f"{field} invalid")
    return value


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _error("MYBEE_APPROVAL_FIELD_INVALID", f"{field} invalid")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _error("MYBEE_APPROVAL_HASH_INVALID", f"{field} invalid") from exc


def _timestamp(value: object) -> str | datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _error("MYBEE_APPROVAL_TIME_INVALID", "timestamp invalid") from exc
    else:
        raise _error("MYBEE_APPROVAL_TIME_INVALID", "timestamp invalid")
    if parsed.tzinfo is None:
        raise _error("MYBEE_APPROVAL_TIME_INVALID", "timestamp must be timezone-aware")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _error(code: str, detail: str) -> ScopedApprovalContractError:
    return ScopedApprovalContractError(code, detail)
