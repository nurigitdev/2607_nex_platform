from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION = "ae_business_result_summary.v1"
VOUCHER_DRAFT_RESULT_TYPE = "FINANCE.VOUCHER_DRAFT"
PROJECT_ALLOCATION_RESULT_TYPE = "FINANCE.PROJECT_ALLOCATION"
_VOUCHER_OUTCOMES = frozenset(
    {"COMMITTED", "NOT_COMMITTED", "UNKNOWN_COMMIT_STATE"}
)
_APPROVAL_STATES = frozenset({"APPROVED", "DENIED", "NOT_REQUIRED", "UNKNOWN"})


class BusinessResultSummaryError(ValueError):
    pass


def build_voucher_draft_summary(
    *,
    commit_state: str,
    verification_status: str | None,
    approval_state: str,
    business_operation_id: str,
    voucher_number: str | None,
    amount: object,
    currency: str,
    account_codes: Sequence[str],
    project_code: str,
) -> dict[str, Any]:
    summary = {
        "result_type": VOUCHER_DRAFT_RESULT_TYPE,
        "summary_schema_version": BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION,
        "summary": {
            "outcome": _enum("commit_state", commit_state, _VOUCHER_OUTCOMES),
            "verification_status": _optional_text(
                "verification_status", verification_status, 64
            ),
            "approval_state": _enum(
                "approval_state", approval_state, _APPROVAL_STATES
            ),
            "business_operation_id": _required_text(
                "business_operation_id", business_operation_id, 128
            ),
            "voucher_number": _optional_text(
                "voucher_number", voucher_number, 128
            ),
            "amount": _amount(amount),
            "currency": _required_text("currency", currency, 16).upper(),
            "account_codes": _bounded_text_list(
                "account_codes", account_codes, maximum_items=8, maximum_length=64
            ),
            "project_code": _required_text("project_code", project_code, 128),
            # A link requires an admitted owner-facing EOS facade. None exists yet.
            "business_object_link": None,
        },
    }
    admitted = admit_business_result_summary(summary, strict=True)
    assert admitted is not None
    return admitted


def admit_business_result_summary(
    value: object, *, strict: bool = False
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        if strict:
            raise BusinessResultSummaryError("Business result summary must be an object.")
        return None
    result_type = value.get("result_type")
    if result_type == PROJECT_ALLOCATION_RESULT_TYPE:
        return _admit_project_allocation_summary(value)
    if result_type != VOUCHER_DRAFT_RESULT_TYPE:
        return None
    if set(value) != {"result_type", "summary_schema_version", "summary"}:
        raise BusinessResultSummaryError("Business result summary fields are invalid.")
    if value.get("summary_schema_version") != BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION:
        raise BusinessResultSummaryError(
            "Business result summary schema version is invalid."
        )
    summary = value.get("summary")
    if not isinstance(summary, Mapping):
        raise BusinessResultSummaryError("Business result summary payload is invalid.")
    expected = {
        "outcome",
        "verification_status",
        "approval_state",
        "business_operation_id",
        "voucher_number",
        "amount",
        "currency",
        "account_codes",
        "project_code",
        "business_object_link",
    }
    if set(summary) != expected:
        raise BusinessResultSummaryError("Voucher result summary fields are invalid.")
    if summary.get("business_object_link") is not None:
        raise BusinessResultSummaryError(
            "Voucher result link requires an admitted owner-facing facade."
        )
    return {
        "result_type": VOUCHER_DRAFT_RESULT_TYPE,
        "summary_schema_version": BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION,
        "summary": {
            "outcome": _enum("outcome", summary.get("outcome"), _VOUCHER_OUTCOMES),
            "verification_status": _optional_text(
                "verification_status", summary.get("verification_status"), 64
            ),
            "approval_state": _enum(
                "approval_state", summary.get("approval_state"), _APPROVAL_STATES
            ),
            "business_operation_id": _required_text(
                "business_operation_id", summary.get("business_operation_id"), 128
            ),
            "voucher_number": _optional_text(
                "voucher_number", summary.get("voucher_number"), 128
            ),
            "amount": _amount(summary.get("amount")),
            "currency": _required_text(
                "currency", summary.get("currency"), 16
            ).upper(),
            "account_codes": _bounded_text_list(
                "account_codes",
                summary.get("account_codes"),
                maximum_items=8,
                maximum_length=64,
            ),
            "project_code": _required_text(
                "project_code", summary.get("project_code"), 128
            ),
            "business_object_link": None,
        },
    }


def build_project_allocation_summary(
    financial_result: Mapping[str, Any],
) -> dict[str, Any]:
    projects = financial_result.get("project_results")
    if not isinstance(projects, (list, tuple)) or not projects:
        raise BusinessResultSummaryError(
            "Project allocation result requires Project projections."
        )
    summary = {
        "result_type": PROJECT_ALLOCATION_RESULT_TYPE,
        "summary_schema_version": BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION,
        "summary": {
            "outcome": "ALLOCATED_AND_VERIFIED",
            "journal_ref": financial_result.get("journal_ref"),
            "source_pool_ref": financial_result.get("source_pool_ref"),
            "source_pool_hash": financial_result.get("source_pool_hash"),
            "allocation_batch_ref": financial_result.get("allocation_batch_ref"),
            "allocation_reconciliation_hash": financial_result.get(
                "allocation_reconciliation_hash"
            ),
            "pnl_refresh_hash": financial_result.get("pnl_refresh_hash"),
            "project_projections": [
                {
                    "project_code": item.get("project_code"),
                    "projection_id": item.get("projection_id"),
                    "projection_version": item.get("projection_version"),
                    "projection_hash": item.get("projection_hash"),
                    "reconciliation_status": item.get("reconciliation_status"),
                    "freshness_status": item.get("freshness_status"),
                    "data_classification": item.get("data_classification"),
                }
                for item in projects
                if isinstance(item, Mapping)
            ],
        },
    }
    admitted = admit_business_result_summary(summary, strict=True)
    assert admitted is not None
    return admitted


def _admit_project_allocation_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"result_type", "summary_schema_version", "summary"}:
        raise BusinessResultSummaryError(
            "Project allocation result summary fields are invalid."
        )
    if value.get("summary_schema_version") != BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION:
        raise BusinessResultSummaryError(
            "Project allocation result schema version is invalid."
        )
    summary = value.get("summary")
    expected = {
        "outcome",
        "journal_ref",
        "source_pool_ref",
        "source_pool_hash",
        "allocation_batch_ref",
        "allocation_reconciliation_hash",
        "pnl_refresh_hash",
        "project_projections",
    }
    if not isinstance(summary, Mapping) or set(summary) != expected:
        raise BusinessResultSummaryError(
            "Project allocation result payload is invalid."
        )
    if summary.get("outcome") != "ALLOCATED_AND_VERIFIED":
        raise BusinessResultSummaryError("Project allocation outcome is invalid.")
    projections = summary.get("project_projections")
    if (
        not isinstance(projections, Sequence)
        or isinstance(projections, (str, bytes))
        or not projections
    ):
        raise BusinessResultSummaryError(
            "Project allocation projections must be a non-empty list."
        )
    admitted_projects = [_project_projection(item) for item in projections]
    codes = [item["project_code"] for item in admitted_projects]
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise BusinessResultSummaryError(
            "Project allocation projections must be unique and ordered."
        )
    return {
        "result_type": PROJECT_ALLOCATION_RESULT_TYPE,
        "summary_schema_version": BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION,
        "summary": {
            "outcome": "ALLOCATED_AND_VERIFIED",
            "journal_ref": _required_text(
                "journal_ref", summary.get("journal_ref"), 256
            ),
            "source_pool_ref": _required_text(
                "source_pool_ref", summary.get("source_pool_ref"), 256
            ),
            "source_pool_hash": _hash_ref(
                "source_pool_hash", summary.get("source_pool_hash")
            ),
            "allocation_batch_ref": _required_text(
                "allocation_batch_ref", summary.get("allocation_batch_ref"), 256
            ),
            "allocation_reconciliation_hash": _hash_ref(
                "allocation_reconciliation_hash",
                summary.get("allocation_reconciliation_hash"),
            ),
            "pnl_refresh_hash": _hash_ref(
                "pnl_refresh_hash", summary.get("pnl_refresh_hash")
            ),
            "project_projections": admitted_projects,
        },
    }


def _project_projection(value: object) -> dict[str, Any]:
    expected = {
        "project_code",
        "projection_id",
        "projection_version",
        "projection_hash",
        "reconciliation_status",
        "freshness_status",
        "data_classification",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise BusinessResultSummaryError("Project projection fields are invalid.")
    version = value.get("projection_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise BusinessResultSummaryError("projection_version must be positive.")
    return {
        "project_code": _required_text(
            "project_code", value.get("project_code"), 128
        ),
        "projection_id": _required_text(
            "projection_id", value.get("projection_id"), 64
        ),
        "projection_version": version,
        "projection_hash": _hash_ref(
            "projection_hash", value.get("projection_hash")
        ),
        "reconciliation_status": _required_text(
            "reconciliation_status", value.get("reconciliation_status"), 32
        ),
        "freshness_status": _required_text(
            "freshness_status", value.get("freshness_status"), 32
        ),
        "data_classification": _required_text(
            "data_classification", value.get("data_classification"), 64
        ),
    }


def _hash_ref(name: str, value: object) -> str:
    text = _required_text(name, value, 71)
    if not text.startswith("sha256:") or len(text) != 71:
        raise BusinessResultSummaryError(f"{name} must be a SHA-256 reference.")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise BusinessResultSummaryError(
            f"{name} must be a SHA-256 reference."
        ) from exc
    return text


def summary_from_step_results(
    step_results: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    admitted: list[dict[str, Any]] = []
    for result in step_results:
        payload = result.get("result_payload")
        if not isinstance(payload, Mapping) or "business_summary" not in payload:
            continue
        summary = admit_business_result_summary(payload["business_summary"], strict=True)
        if summary is not None:
            admitted.append(summary)
    if not admitted:
        return None
    if any(item != admitted[0] for item in admitted[1:]):
        raise BusinessResultSummaryError(
            "Step results contain conflicting business summaries."
        )
    return admitted[0]


def _amount(value: object) -> str:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise BusinessResultSummaryError("amount must be a decimal value.") from exc
    if amount <= 0:
        raise BusinessResultSummaryError("amount must be positive.")
    return f"{amount:.2f}"


def _enum(name: str, value: object, allowed: frozenset[str]) -> str:
    normalized = _required_text(name, value, 64).upper()
    if normalized not in allowed:
        raise BusinessResultSummaryError(f"{name} is invalid.")
    return normalized


def _required_text(name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise BusinessResultSummaryError(
            f"{name} must be a bounded non-empty string."
        )
    return value.strip()


def _optional_text(name: str, value: object, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, maximum)


def _bounded_text_list(
    name: str,
    value: object,
    *,
    maximum_items: int,
    maximum_length: int,
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= maximum_items
    ):
        raise BusinessResultSummaryError(f"{name} must be a bounded list.")
    normalized = [_required_text(name, item, maximum_length) for item in value]
    if len(set(normalized)) != len(normalized):
        raise BusinessResultSummaryError(f"{name} must not contain duplicates.")
    return normalized
