from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

BUSINESS_RESULT_SUMMARY_SCHEMA_VERSION = "ae_business_result_summary.v1"
VOUCHER_DRAFT_RESULT_TYPE = "FINANCE.VOUCHER_DRAFT"
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
    if value.get("result_type") != VOUCHER_DRAFT_RESULT_TYPE:
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
