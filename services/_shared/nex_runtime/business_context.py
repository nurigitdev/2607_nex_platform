from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

BUSINESS_REQUEST_CONTEXT_SCHEMA_VERSION = "ae.business_request_context.v1"
BUSINESS_REQUEST_KIND = "FINANCE_VOUCHER_POSTING"
BUSINESS_CONTEXT_MAX_BYTES = 16_384
BUSINESS_ALLOCATION_MAX_ITEMS = 12

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SOURCE_PROMPT_REF = re.compile(
    r"^AE:INTERACTION:[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"
)
_CONTEXT_KEYS = frozenset(
    {
        "schema_version",
        "request_kind",
        "source_prompt_ref",
        "company_selector",
        "document",
        "transaction",
        "requested_allocation",
        "candidate_provenance",
        "context_hash",
    }
)


@dataclass(frozen=True)
class BusinessContextValidationError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def validate_business_request_context(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("BusinessRequestContext must be an object.")
    try:
        record = json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid("BusinessRequestContext must be canonical JSON.") from exc
    if set(record) != _CONTEXT_KEYS:
        raise _invalid("BusinessRequestContext fields are invalid.")
    if (
        record.get("schema_version") != BUSINESS_REQUEST_CONTEXT_SCHEMA_VERSION
        or record.get("request_kind") != BUSINESS_REQUEST_KIND
    ):
        raise _invalid("BusinessRequestContext version or request kind is invalid.")
    _source_prompt_ref(record.get("source_prompt_ref"))
    _validate_company(record.get("company_selector"))
    _validate_document(record.get("document"))
    _validate_transaction(record.get("transaction"))
    _validate_allocation_records(record.get("requested_allocation"))
    _validate_candidate_provenance(record.get("candidate_provenance"))
    _hash_ref("context_hash", record.get("context_hash"))
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "context_hash"}
    )
    if record["context_hash"] != expected_hash:
        raise _error(
            "business_context_hash_mismatch",
            "BusinessRequestContext hash does not match its semantic content."
        )
    if len(canonical_json(record).encode("utf-8")) > BUSINESS_CONTEXT_MAX_BYTES:
        raise _error(
            "business_context_bounds_exceeded",
            "BusinessRequestContext exceeds 16384 bytes.",
        )
    return record


def _validate_company(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"kind", "value"}:
        raise _invalid("Business company selector is invalid.")
    if value.get("kind") not in {"CODE", "NAME", "CODE_OR_NAME"}:
        raise _invalid("Business company selector kind is invalid.")
    _text("company_selector.value", value.get("value"), 160)


def _validate_document(value: object) -> None:
    fields = {
        "document_type",
        "subject_ref",
        "subject_revision",
        "content_hash",
        "attachment_manifest_hash",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Business document fields are invalid.")
    if value.get("document_type") != "BUSINESS_PROPOSAL":
        raise _invalid("Business document type is invalid.")
    _text("document.subject_ref", value.get("subject_ref"), 256)
    revision = value.get("subject_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise _invalid("Business document subject revision is invalid.")
    _hash_ref("document.content_hash", value.get("content_hash"))
    if value.get("attachment_manifest_hash") is not None:
        _hash_ref(
            "document.attachment_manifest_hash",
            value.get("attachment_manifest_hash"),
        )


def _validate_transaction(value: object) -> None:
    fields = {
        "counterparty_selector",
        "amount",
        "currency",
        "recognition_date",
        "description",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Business transaction fields are invalid.")
    _text("transaction.counterparty_selector", value.get("counterparty_selector"), 160)
    if _amount(value.get("amount")) != value.get("amount"):
        raise _invalid("Business transaction amount is not canonical.")
    if _currency(value.get("currency")) != value.get("currency"):
        raise _invalid("Business transaction currency is not canonical.")
    if _calendar_date(value.get("recognition_date")) != value.get(
        "recognition_date"
    ):
        raise _invalid("Business transaction recognition date is not canonical.")
    _text("transaction.description", value.get("description"), 1000)


def _validate_allocation_records(value: object) -> None:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > BUSINESS_ALLOCATION_MAX_ITEMS
    ):
        raise _invalid("Business requested allocation is invalid.")
    seen: set[str] = set()
    total = Decimal(0)
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"project_code", "ratio"}:
            raise _invalid("Business allocation fields are invalid.")
        project_code = _project_code(item.get("project_code"))
        if project_code in seen:
            raise _invalid("Business allocation Project Codes must be unique.")
        seen.add(project_code)
        ratio = _ratio(item.get("ratio"))
        if ratio != item.get("ratio"):
            raise _invalid("Business allocation ratio is not canonical.")
        total += Decimal(ratio)
    if total != Decimal("1.000000"):
        raise _invalid("Business allocation ratios must total exactly 1.000000.")


def _validate_candidate_provenance(value: object) -> None:
    fields = {
        "intent_candidate_hash",
        "input_context_hash",
        "model_profile",
        "model_ref",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("Business candidate provenance fields are invalid.")
    _hash_ref(
        "candidate_provenance.intent_candidate_hash",
        value.get("intent_candidate_hash"),
    )
    _hash_ref(
        "candidate_provenance.input_context_hash", value.get("input_context_hash")
    )
    _optional_text("model_profile", value.get("model_profile"), 128)
    _optional_text("model_ref", value.get("model_ref"), 256)


def _text(field_name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field_name} is invalid.")
    return value.strip()


def _optional_text(field_name: str, value: object, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(field_name, value, maximum)


def _source_prompt_ref(value: object) -> str:
    selected = _text("source_prompt_ref", value, 175)
    if _SOURCE_PROMPT_REF.fullmatch(selected) is None:
        raise _invalid("source_prompt_ref must identify one AE interaction.")
    return selected


def _project_code(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("Allocation Project Code is invalid.")
    selected = value.strip().upper()
    if _PROJECT_CODE.fullmatch(selected) is None:
        raise _invalid("Allocation Project Code is invalid.")
    return selected


def _amount(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise _invalid("Business amount is invalid.")
    try:
        selected = Decimal(str(value).strip())
        quantized = selected.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise _invalid("Business amount is invalid.") from None
    if not selected.is_finite() or selected <= 0 or selected != quantized:
        raise _invalid("Business amount must be a positive value with two decimals.")
    if len(str(quantized.copy_abs()).split(".", maxsplit=1)[0]) > 16:
        raise _invalid("Business amount exceeds its bound.")
    return format(quantized, ".2f")


def _currency(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("Business currency is invalid.")
    selected = value.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", selected) is None:
        raise _invalid("Business currency must be an ISO 4217 code candidate.")
    return selected


def _calendar_date(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("Business recognition date is invalid.")
    selected = value.strip()
    try:
        parsed = date.fromisoformat(selected)
    except ValueError:
        raise _invalid("Business recognition date must be an ISO calendar date.") from None
    if parsed.isoformat() != selected:
        raise _invalid("Business recognition date must be canonical.")
    return selected


def _ratio(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise _invalid("Business allocation ratio is invalid.")
    try:
        selected = Decimal(str(value).strip())
        quantized = selected.quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        raise _invalid("Business allocation ratio is invalid.") from None
    if (
        not selected.is_finite()
        or selected <= 0
        or selected > 1
        or selected != quantized
    ):
        raise _invalid("Business allocation ratio must be within (0, 1].")
    return format(quantized, ".6f")


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError):
        raise _invalid(f"{field_name} is invalid.") from None


def _invalid(detail: str) -> BusinessContextValidationError:
    return _error("business_context_invalid", detail)


def _error(error_code: str, detail: str) -> BusinessContextValidationError:
    return BusinessContextValidationError(error_code, detail)
