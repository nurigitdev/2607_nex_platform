"""MyBee consumer contract for immutable EOS approved document envelopes."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref

GET_APPROVED_DOCUMENT_OPERATION = "BUSINESS.DOCUMENT_APPROVED.GET"
GET_APPROVED_DOCUMENT_PATH = "/internal/v2/finance/approved-documents/{envelope_id}"
APPROVED_DOCUMENT_STATES = frozenset({"ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"})
APPROVED_DOCUMENT_SCOPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "envelope_id",
        "company_id",
        "approved_document_id",
        "document_revision",
        "document_type",
        "work_code",
        "document_content_hash",
        "attachment_manifest_hash",
        "business_approval_proof_id",
        "business_proof_hash",
        "approval_policy_id",
        "approval_policy_version",
        "approval_policy_hash",
        "scope_type",
        "project_set_hash",
        "allowed_project_ids",
        "approved_amount",
        "approved_currency",
        "remaining_amount",
        "tolerance_policy_hash",
        "valid_from",
        "valid_until",
        "state",
        "usable",
        "approved_at",
        "approved_by_principal_ref",
        "source_work_item_ref",
        "payload_hash",
        "created_business_operation_id",
        "created_at",
    }
)


class ApprovedDocumentContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class EosApprovedDocumentRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str


def build_approved_document_request(
    *, tenant_id: str, envelope_id: str, requester_subject_id: str
) -> EosApprovedDocumentRequest:
    return EosApprovedDocumentRequest(
        method="GET",
        path=GET_APPROVED_DOCUMENT_PATH.format(
            envelope_id=_uuid("envelope_id", envelope_id)
        ),
        operation_id=GET_APPROVED_DOCUMENT_OPERATION,
        tenant_id=_scoped_id("tenant_id", tenant_id, 128),
        subject_id=_scoped_id("requester_subject_id", requester_subject_id, 128),
    )


def admit_approved_document_envelope(
    value: object, *, tenant_id: str, envelope_id: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise _error("EOS_APPROVED_DOCUMENT_FIELDS_INVALID", "fields drifted")
    item = dict(value)
    if item["schema_version"] != "eos_approved_document_envelope.v1":
        raise _error("EOS_APPROVED_DOCUMENT_SCHEMA_INVALID", "version drifted")
    if item["tenant_id"] != _scoped_id("tenant_id", tenant_id, 128):
        raise _error("EOS_APPROVED_DOCUMENT_SCOPE_MISMATCH", "tenant drifted")
    if item["envelope_id"] != _uuid("envelope_id", envelope_id):
        raise _error("EOS_APPROVED_DOCUMENT_SCOPE_MISMATCH", "envelope drifted")
    for field in (
        "company_id",
        "business_approval_proof_id",
        "approval_policy_id",
        "created_business_operation_id",
    ):
        _uuid(field, item[field])
    _scoped_id("approved_document_id", item["approved_document_id"], 128)
    _positive_int("document_revision", item["document_revision"])
    _scoped_id("document_type", item["document_type"], 64)
    if not isinstance(item["work_code"], str) or not _WORK_CODE.fullmatch(
        item["work_code"]
    ):
        raise _error("EOS_APPROVED_DOCUMENT_WORK_CODE_INVALID", "work code drifted")
    for field in (
        "document_content_hash",
        "attachment_manifest_hash",
        "business_proof_hash",
        "approval_policy_hash",
        "project_set_hash",
        "payload_hash",
    ):
        _hash_ref(field, item[field])
    if item["tolerance_policy_hash"] is not None:
        _hash_ref("tolerance_policy_hash", item["tolerance_policy_hash"])
    _positive_int("approval_policy_version", item["approval_policy_version"])
    scope_type = _choice("scope_type", item["scope_type"], APPROVED_DOCUMENT_SCOPES)
    project_ids = item["allowed_project_ids"]
    if not isinstance(project_ids, list) or project_ids != sorted(set(project_ids)):
        raise _error(
            "EOS_APPROVED_DOCUMENT_PROJECT_SET_INVALID",
            "Project IDs must be sorted and unique",
        )
    for project_id in project_ids:
        _uuid("allowed_project_ids", project_id)
    if (
        (scope_type == "COMPANY" and project_ids)
        or (scope_type == "PROJECT" and len(project_ids) != 1)
        or (scope_type == "PROJECT_SET" and len(project_ids) < 2)
    ):
        raise _error("EOS_APPROVED_DOCUMENT_PROJECT_SET_INVALID", "scope shape drifted")
    approved = _decimal("approved_amount", item["approved_amount"])
    remaining = _decimal("remaining_amount", item["remaining_amount"])
    if remaining < 0 or remaining > approved:
        raise _error(
            "EOS_APPROVED_DOCUMENT_ALLOWANCE_INVALID", "remaining amount drifted"
        )
    if not isinstance(item["approved_currency"], str) or not _CURRENCY.fullmatch(
        item["approved_currency"]
    ):
        raise _error("EOS_APPROVED_DOCUMENT_CURRENCY_INVALID", "currency drifted")
    state = _choice("state", item["state"], APPROVED_DOCUMENT_STATES)
    if not isinstance(item["usable"], bool) or (item["usable"] and state != "ACTIVE"):
        raise _error("EOS_APPROVED_DOCUMENT_USABILITY_INVALID", "usability drifted")
    valid_from = _timestamp("valid_from", item["valid_from"])
    valid_until = (
        _timestamp("valid_until", item["valid_until"])
        if item["valid_until"] is not None
        else None
    )
    if valid_until is not None and valid_until <= valid_from:
        raise _error("EOS_APPROVED_DOCUMENT_PERIOD_INVALID", "period reversed")
    _timestamp("approved_at", item["approved_at"])
    _timestamp("created_at", item["created_at"])
    principal = item["approved_by_principal_ref"]
    if not isinstance(principal, Mapping) or set(principal) != {"type", "id"}:
        raise _error("EOS_APPROVED_DOCUMENT_PRINCIPAL_INVALID", "principal drifted")
    _scoped_id("approved_by_principal_ref.type", principal["type"], 32)
    _scoped_id("approved_by_principal_ref.id", principal["id"], 128)
    _scoped_id("source_work_item_ref", item["source_work_item_ref"], 256)
    return MappingProxyType(item)


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _SCOPED_ID.fullmatch(value)
    ):
        raise _error("EOS_APPROVED_DOCUMENT_ID_INVALID", f"{field} invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _error("EOS_APPROVED_DOCUMENT_ID_INVALID", f"{field} invalid") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error("EOS_APPROVED_DOCUMENT_NUMBER_INVALID", f"{field} invalid")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _error("EOS_APPROVED_DOCUMENT_HASH_INVALID", f"{field} invalid") from exc


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _error("EOS_APPROVED_DOCUMENT_ENUM_INVALID", f"{field} invalid")
    return value


def _decimal(field: str, value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _error(
            "EOS_APPROVED_DOCUMENT_AMOUNT_INVALID", f"{field} invalid"
        ) from exc
    if not result.is_finite() or result < 0 or result.as_tuple().exponent < -4:
        raise _error("EOS_APPROVED_DOCUMENT_AMOUNT_INVALID", f"{field} invalid")
    return result


def _timestamp(field: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid") from exc
    if parsed.tzinfo is None:
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid")
    return parsed


def _error(code: str, detail: str) -> ApprovedDocumentContractError:
    return ApprovedDocumentContractError(code, detail)
