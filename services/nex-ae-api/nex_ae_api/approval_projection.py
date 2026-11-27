from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


APPROVAL_PROJECTION_SCHEMA_VERSION = "ae_user_approval_projection.v1"
_SOURCE_SCHEMA_VERSION = "wc_approval_gate_detail.v1"
_APPROVAL_DOMAINS = {"NSL_WRITE", "AGENT_FORMAL", "BUSINESS_FORMAL"}
_APPROVAL_STATES = {"PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"}
_PROTECTED_DISPLAY_MARKERS = {
    "access_token",
    "api_key",
    "authorization_header",
    "credential",
    "database_url",
    "password",
    "protected_request",
    "raw_payload",
    "raw_prompt",
    "service_token",
    "storage_path",
}


@dataclass(frozen=True)
class ApprovalProjectionError(ValueError):
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_user_approval_projection(
    *,
    tenant_id: str,
    detail: Mapping[str, Any],
    accounting_document: Mapping[str, Any] | None = None,
    accounting_diagnostic_code: str | None = None,
) -> dict[str, Any]:
    """Build a display-safe projection without inferring absent business data."""

    admitted_tenant_id = _required_text(tenant_id, "tenant_id")
    if detail.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        raise ApprovalProjectionError("Approval detail schema is invalid.")
    gate = detail.get("gate")
    if not isinstance(gate, Mapping):
        raise ApprovalProjectionError("Approval gate is invalid.")

    approval_domain = _required_text(gate.get("approval_domain"), "approval_domain")
    state = _required_text(gate.get("state"), "state")
    if approval_domain not in _APPROVAL_DOMAINS or state not in _APPROVAL_STATES:
        raise ApprovalProjectionError("Approval gate state is invalid.")

    project_id = _formal_project_id(gate, approval_domain)
    requested_at = _required_datetime(detail.get("created_at"), "created_at")
    projection = {
        "schema_version": APPROVAL_PROJECTION_SCHEMA_VERSION,
        "tenant_id": admitted_tenant_id,
        "gate_id": _required_uuid(gate.get("gate_id"), "gate_id"),
        "approval_domain": approval_domain,
        "state": state,
        "title": _safe_display_text(gate.get("title"), "title"),
        "summary": _safe_display_text(gate.get("summary"), "summary"),
        "expires_at": _optional_datetime(gate.get("expires_at"), "expires_at"),
        "approval_provider_type": _optional_text(
            gate.get("approval_provider_type")
        ),
        "approval_target_ref": _optional_text(gate.get("approval_target_ref")),
        "business_operation_id": _optional_text(
            gate.get("business_operation_id")
        ),
        "requester": {
            "status": "OPEN",
            "display_name": None,
        },
        "requested_at": {
            "status": "AVAILABLE",
            "value": requested_at,
        },
        "project": {
            "id_status": "AVAILABLE" if project_id else "OPEN",
            "project_id": project_id,
            "display_status": "OPEN",
            "display_name": None,
        },
        "amount": {
            "status": "OPEN",
            "value": None,
            "currency": None,
        },
        "business_date": {
            "status": "OPEN",
            "value": None,
        },
        "accounts": {
            "status": "OPEN",
            "items": [],
        },
        "risk": {
            "status": "OPEN",
            "level": None,
            "explanation": None,
        },
        "line_items": {
            "status": "OPEN",
            "items": [],
        },
        "metadata": {
            "source_contract": _SOURCE_SCHEMA_VERSION,
            "browser_join_required": False,
            "protected_fields_included": False,
        },
    }
    if accounting_document is not None:
        projection["accounting_document"] = _accounting_document_projection(
            accounting_document
        )
    elif accounting_diagnostic_code is not None:
        projection["accounting_document"] = {
            "schema_version": "ae_accounting_document_projection.v1",
            "status": "UNAVAILABLE",
            "diagnostic_code": _required_text(
                accounting_diagnostic_code,
                "accounting_diagnostic_code",
            ),
            "header": None,
            "lines": [],
            "totals": None,
            "lineage": None,
        }
    return projection


def _accounting_document_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != "eos_accounting_document_projection.v1":
        raise ApprovalProjectionError("Accounting document schema is invalid.")
    lines = value.get("lines")
    totals = value.get("totals")
    if not isinstance(lines, list) or not lines or not isinstance(totals, Mapping):
        raise ApprovalProjectionError("Accounting document content is invalid.")
    admitted_lines = []
    for line in lines:
        if not isinstance(line, Mapping):
            raise ApprovalProjectionError("Accounting document line is invalid.")
        line_no = line.get("line_no")
        if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no < 1:
            raise ApprovalProjectionError("Accounting document line number is invalid.")
        admitted_lines.append(
            {
                "line_no": line_no,
                "account_code": _required_text(
                    line.get("account_code"), "account_code"
                ),
                "account_name": _safe_display_text(
                    line.get("account_name"), "account_name"
                ),
                "description": (
                    None
                    if line.get("description") is None
                    else _safe_display_text(line.get("description"), "description")
                ),
                "debit": _required_text(line.get("debit"), "debit"),
                "credit": _required_text(line.get("credit"), "credit"),
                "currency": _required_text(line.get("currency"), "currency"),
            }
        )
    balanced = totals.get("balanced")
    if not isinstance(balanced, bool):
        raise ApprovalProjectionError("Accounting document balance is invalid.")
    return {
        "schema_version": "ae_accounting_document_projection.v1",
        "status": "AVAILABLE",
        "diagnostic_code": None,
        "header": {
            "project_code": _required_text(value.get("project_code"), "project_code"),
            "company_id": _required_text(value.get("company_id"), "company_id"),
            "approved_document_ref": _required_text(
                value.get("approved_document_ref"), "approved_document_ref"
            ),
            "recognition_date": _required_text(
                value.get("recognition_date"), "recognition_date"
            ),
            "currency": _required_text(value.get("currency"), "currency"),
            "requester_subject_id": _required_text(
                value.get("requester_subject_id"), "requester_subject_id"
            ),
        },
        "lines": admitted_lines,
        "totals": {
            "debit": _required_text(totals.get("debit"), "debit_total"),
            "credit": _required_text(totals.get("credit"), "credit_total"),
            "difference": _required_text(totals.get("difference"), "difference"),
            "balanced": balanced,
        },
        "lineage": {
            "candidate_id": _required_uuid(value.get("candidate_id"), "candidate_id"),
            "candidate_revision": _positive_int(
                value.get("candidate_revision"), "candidate_revision"
            ),
            "candidate_hash": _required_text(
                value.get("candidate_hash"), "candidate_hash"
            ),
            "approval_case_id": _optional_text(value.get("approval_case_id")),
        },
    }


def _formal_project_id(gate: Mapping[str, Any], approval_domain: str) -> str | None:
    if approval_domain != "BUSINESS_FORMAL":
        return None
    formal = gate.get("formal_approval")
    if not isinstance(formal, Mapping):
        raise ApprovalProjectionError("Business formal approval is invalid.")
    return _optional_text(formal.get("project_id"))


def _required_text(value: object, field: str) -> str:
    admitted = _optional_text(value)
    if admitted is None:
        raise ApprovalProjectionError(f"Approval {field} is invalid.")
    return admitted


def _safe_display_text(value: object, field: str) -> str:
    admitted = _required_text(value, field)
    normalized = admitted.lower()
    if any(marker in normalized for marker in _PROTECTED_DISPLAY_MARKERS):
        raise ApprovalProjectionError(f"Approval {field} is not display-safe.")
    return admitted


def _required_uuid(value: object, field: str) -> str:
    admitted = _required_text(value, field)
    try:
        parsed = UUID(admitted)
    except ValueError as exc:
        raise ApprovalProjectionError(f"Approval {field} is invalid.") from exc
    if str(parsed) != admitted.lower():
        raise ApprovalProjectionError(f"Approval {field} is invalid.")
    return admitted


def _required_datetime(value: object, field: str) -> str:
    admitted = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(admitted.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovalProjectionError(f"Approval {field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise ApprovalProjectionError(f"Approval {field} is invalid.")
    return admitted


def _optional_datetime(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_datetime(value, field)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ApprovalProjectionError(f"Approval {field} is invalid.")
    return value
