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
    return {
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
