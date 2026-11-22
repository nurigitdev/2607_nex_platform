"""Deterministic accounting rules owned by the EOS accounting boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

_CURRENCY_MINOR_UNITS = {
    "CNY": 2,
    "EUR": 2,
    "JPY": 0,
    "KRW": 0,
    "USD": 2,
}


class AccountingRuleError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class FunctionalizedCandidate:
    lines: tuple[dict[str, Any], ...]
    debit_original: str
    credit_original: str
    debit_functional: str
    credit_functional: str
    functional_scale: int
    rule_profile_hash: str


def functionalize_candidate_lines(
    lines: Sequence[Mapping[str, Any]],
    *,
    transaction_currency: str,
    functional_currency: str,
    normalized_rate: object,
) -> FunctionalizedCandidate:
    transaction_currency = _currency("transaction_currency", transaction_currency)
    functional_currency = _currency("functional_currency", functional_currency)
    scale = currency_minor_units(functional_currency)
    rate = _positive_decimal("normalized_rate", normalized_rate)
    if transaction_currency == functional_currency and rate != Decimal(1):
        raise AccountingRuleError(
            "MYBEE_SAME_CURRENCY_RATE_INVALID",
            "Same-currency validation requires an exact rate of 1.",
        )

    quantum = Decimal(1).scaleb(-scale)
    debit_original = Decimal(0)
    credit_original = Decimal(0)
    debit_functional = Decimal(0)
    credit_functional = Decimal(0)
    projected: list[dict[str, Any]] = []
    if not lines:
        raise AccountingRuleError(
            "MYBEE_CANDIDATE_LINES_REQUIRED",
            "VoucherCandidate validation requires at least one line.",
        )
    for expected_line_no, line in enumerate(lines, start=1):
        line_no = _positive_integer("line_no", line.get("line_no"))
        if line_no != expected_line_no:
            raise AccountingRuleError(
                "MYBEE_CANDIDATE_LINE_ORDER_INVALID",
                "VoucherCandidate line numbers must be contiguous from 1.",
            )
        debit = _nonnegative_decimal("debit_original", line.get("debit_original"))
        credit = _nonnegative_decimal("credit_original", line.get("credit_original"))
        if (debit > 0) == (credit > 0):
            raise AccountingRuleError(
                "MYBEE_CANDIDATE_LINE_SIDE_INVALID",
                "Each line must contain exactly one positive debit or credit.",
            )
        debit_value = (debit * rate).quantize(quantum, rounding=ROUND_HALF_EVEN)
        credit_value = (credit * rate).quantize(quantum, rounding=ROUND_HALF_EVEN)
        debit_original += debit
        credit_original += credit
        debit_functional += debit_value
        credit_functional += credit_value
        projected.append(
            {
                "line_no": line_no,
                "account_id": str(line.get("account_id", "")),
                "debit_original": _amount(debit, 4),
                "credit_original": _amount(credit, 4),
                "debit_functional": _amount(debit_value, scale),
                "credit_functional": _amount(credit_value, scale),
                "functional_currency": functional_currency,
            }
        )

    if debit_original != credit_original:
        raise AccountingRuleError(
            "MYBEE_ORIGINAL_BALANCE_INVALID",
            "VoucherCandidate original-currency debits and credits are not balanced.",
        )
    if debit_functional != credit_functional:
        raise AccountingRuleError(
            "MYBEE_FUNCTIONAL_BALANCE_INVALID",
            "VoucherCandidate functional-currency debits and credits are not balanced.",
        )
    profile = {
        "domain": "MYBEE-CANDIDATE-ACCOUNTING-RULES-V1",
        "rounding": "ROUND_HALF_EVEN",
        "functional_currency": functional_currency,
        "functional_scale": scale,
        "rate_application": "LINE_LEVEL_ONCE",
    }
    return FunctionalizedCandidate(
        lines=tuple(projected),
        debit_original=_amount(debit_original, 4),
        credit_original=_amount(credit_original, 4),
        debit_functional=_amount(debit_functional, scale),
        credit_functional=_amount(credit_functional, scale),
        functional_scale=scale,
        rule_profile_hash=semantic_sha256_hash_ref(profile),
    )


def currency_minor_units(currency: object) -> int:
    code = _currency("currency", currency)
    try:
        return _CURRENCY_MINOR_UNITS[code]
    except KeyError as exc:
        raise AccountingRuleError(
            "MYBEE_CURRENCY_MINOR_UNIT_UNCONFIRMED",
            f"Currency minor-unit policy is not admitted for {code}.",
        ) from exc


def _currency(field: str, value: object) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if len(normalized) != 3 or not normalized.isalpha():
        raise AccountingRuleError(
            "MYBEE_CURRENCY_INVALID", f"{field} must be an ISO-style currency code."
        )
    return normalized


def _positive_integer(field: str, value: object) -> int:
    if isinstance(value, bool):
        value = 0
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingRuleError(
            "MYBEE_CANDIDATE_LINE_INVALID", f"{field} must be a positive integer."
        ) from exc
    if parsed <= 0:
        raise AccountingRuleError(
            "MYBEE_CANDIDATE_LINE_INVALID", f"{field} must be a positive integer."
        )
    return parsed


def _nonnegative_decimal(field: str, value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingRuleError(
            "MYBEE_AMOUNT_INVALID", f"{field} must be an exact decimal amount."
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise AccountingRuleError(
            "MYBEE_AMOUNT_INVALID", f"{field} must be a non-negative finite amount."
        )
    return parsed


def _positive_decimal(field: str, value: object) -> Decimal:
    parsed = _nonnegative_decimal(field, value)
    if parsed <= 0:
        raise AccountingRuleError(
            "MYBEE_FX_RATE_INVALID", f"{field} must be greater than zero."
        )
    return parsed


def _amount(value: Decimal, scale: int) -> str:
    return format(value, f".{scale}f")
