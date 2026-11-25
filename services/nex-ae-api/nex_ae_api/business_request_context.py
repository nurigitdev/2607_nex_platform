from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from nex_runtime.business_context import (
    BusinessContextValidationError,
)
from nex_runtime.business_context import (
    validate_business_request_context as validate_shared_business_request_context,
)
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

BUSINESS_REQUEST_CONTEXT_SCHEMA_VERSION = "ae.business_request_context.v1"
BUSINESS_TRANSACTION_INTENT_LABEL = "FINANCE.VOUCHER.APPROVE_AND_POST"
BUSINESS_REQUEST_KIND = "FINANCE_VOUCHER_POSTING"
BUSINESS_CONTEXT_MAX_BYTES = 16_384
BUSINESS_ALLOCATION_MAX_ITEMS = 12

_CANDIDATE_SCHEMA_VERSION = "p65.intent_candidate.v1"
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_SOURCE_PROMPT_REF = re.compile(r"^AE:INTERACTION:[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_ALLOCATION_PROJECT = re.compile(r"^allocation_project_code_([1-9][0-9]?)$")
_ALLOCATION_RATIO = re.compile(r"^allocation_ratio_([1-9][0-9]?)$")
_STATIC_PARAMETER_NAMES = frozenset(
    {
        "company_selector",
        "primary_project_code",
        "document_subject",
        "counterparty_selector",
        "amount",
        "currency",
        "recognition_date",
        "description",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "intent_label",
        "suggested_execution_mode",
        "entity_selectors",
        "parameter_candidates",
        "clarification",
        "confidence",
    }
)


@dataclass(frozen=True)
class BusinessRequestContextError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AdmittedBusinessRequest:
    context: Mapping[str, Any] = field(repr=False)
    entity_selectors: tuple[Mapping[str, Any], ...] = field(repr=False)
    parameter_candidates: tuple[Mapping[str, Any], ...] = field(repr=False)


def admit_business_request_context(
    *,
    candidate: Mapping[str, Any],
    candidate_hash: str,
    source_prompt_ref: str,
    input_context_hash: str,
    model_profile: str | None,
    model_ref: str | None,
    attachment_manifest_hash: str | None = None,
) -> AdmittedBusinessRequest:
    record = _candidate_record(candidate)
    expected_candidate_hash = semantic_sha256_hash_ref(record)
    if candidate_hash != expected_candidate_hash:
        raise _error(
            "ae.business_context_candidate_hash_mismatch",
            "IntentCandidate hash does not match its semantic content.",
        )
    _hash_ref("input_context_hash", input_context_hash)
    prompt_ref = _source_prompt_ref(source_prompt_ref)
    profile = _optional_text("model_profile", model_profile, 128)
    selected_model = _optional_text("model_ref", model_ref, 256)
    attachment_hash = (
        None
        if attachment_manifest_hash is None
        else _hash_ref("attachment_manifest_hash", attachment_manifest_hash)
    )

    parameters = _parameter_map(record.get("parameter_candidates"))
    allocations = _allocations(parameters)
    primary_project_code = _project_code(
        parameters["primary_project_code"].get("value"),
        field_name="Primary Project Code",
    )
    project_selector = _primary_project_selector(
        record.get("entity_selectors"),
        primary_project_code=primary_project_code,
        allocation_project_codes={item["project_code"] for item in allocations},
    )

    company = _text_parameter(parameters, "company_selector", 160)
    subject = _text_parameter(parameters, "document_subject", 256)
    counterparty = _text_parameter(parameters, "counterparty_selector", 160)
    description = _text_parameter(parameters, "description", 1000)
    amount = _amount_parameter(parameters)
    currency = _currency_parameter(parameters)
    recognition_date = _date_parameter(parameters)

    context: dict[str, Any] = {
        "schema_version": BUSINESS_REQUEST_CONTEXT_SCHEMA_VERSION,
        "request_kind": BUSINESS_REQUEST_KIND,
        "source_prompt_ref": prompt_ref,
        "company_selector": {"kind": "CODE_OR_NAME", "value": company},
        "primary_project_code": primary_project_code,
        "document": {
            "document_type": "BUSINESS_PROPOSAL",
            "subject_ref": subject,
            "subject_revision": 1,
            "content_hash": semantic_sha256_hash_ref(
                {
                    "document_type": "BUSINESS_PROPOSAL",
                    "subject_ref": subject,
                    "description": description,
                    "source_prompt_ref": prompt_ref,
                    "input_context_hash": input_context_hash,
                }
            ),
            "attachment_manifest_hash": attachment_hash,
        },
        "transaction": {
            "counterparty_selector": counterparty,
            "amount": amount,
            "currency": currency,
            "recognition_date": recognition_date,
            "description": description,
        },
        "requested_allocation": allocations,
        "candidate_provenance": {
            "intent_candidate_hash": candidate_hash,
            "input_context_hash": input_context_hash,
            "model_profile": profile,
            "model_ref": selected_model,
        },
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    normalized_context = validate_business_request_context(context)

    selector_confidence = _confidence(
        project_selector.get("confidence"), "Project selector confidence"
    )
    entity_selectors = (
        {
            "selector_id": str(project_selector["selector_id"]),
            "entity_type": "PROJECT",
            "raw_text": str(project_selector["value"]),
            "attributes": {"authority": "MODEL_CANDIDATE_ONLY"},
            "required": True,
            "confidence": selector_confidence,
        },
    )
    work_parameters = _work_intent_parameters(parameters, normalized_context)
    return AdmittedBusinessRequest(
        context=normalized_context,
        entity_selectors=entity_selectors,
        parameter_candidates=work_parameters,
    )


def validate_business_request_context(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        record = validate_shared_business_request_context(value)
    except BusinessContextValidationError as exc:
        raise _error(f"ae.{exc.error_code}", exc.detail) from exc
    if len(canonical_json(record).encode("utf-8")) > BUSINESS_CONTEXT_MAX_BYTES:
        raise _error(
            "ae.business_context_bounds_exceeded",
            f"BusinessRequestContext exceeds {BUSINESS_CONTEXT_MAX_BYTES} bytes.",
        )
    return record


def _candidate_record(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise _invalid("IntentCandidate must be an object.")
    record = json.loads(canonical_json(dict(candidate)))
    if set(record) != _CANDIDATE_KEYS:
        raise _invalid("IntentCandidate fields are invalid for business admission.")
    if (
        record.get("schema_version") != _CANDIDATE_SCHEMA_VERSION
        or record.get("intent_label") != BUSINESS_TRANSACTION_INTENT_LABEL
    ):
        raise _invalid("IntentCandidate is not the admitted business transaction kind.")
    return record


def _parameter_map(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 32:
        raise _invalid("Business parameter candidates are invalid.")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "name",
            "value",
            "confidence",
        }:
            raise _invalid("Business parameter candidate fields are invalid.")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise _invalid("Business parameter candidate name is invalid.")
        if name in result:
            raise _invalid("Business parameter candidate names must be unique.")
        if not (
            name in _STATIC_PARAMETER_NAMES
            or _ALLOCATION_PROJECT.fullmatch(name)
            or _ALLOCATION_RATIO.fullmatch(name)
        ):
            raise _error(
                "ae.business_context_authority_forbidden",
                "Business parameter candidate is unknown or authority-bearing.",
            )
        _confidence(item.get("confidence"), f"{name} confidence")
        result[name] = dict(item)
    missing = _STATIC_PARAMETER_NAMES - set(result)
    if missing:
        raise _invalid(
            "Business parameter candidates are missing: " + ", ".join(sorted(missing))
        )
    return result


def _primary_project_selector(
    value: object,
    *,
    primary_project_code: str,
    allocation_project_codes: set[str],
) -> dict[str, Any]:
    if not isinstance(value, list):
        raise _invalid("Project selectors must be an array.")
    matches = [
        dict(item)
        for item in value
        if isinstance(item, Mapping)
        and item.get("selector_type") == "QUERY_TERM"
        and isinstance(item.get("value"), str)
        and _PROJECT_CODE.fullmatch(str(item["value"]).strip().upper())
    ]
    normalized: list[dict[str, Any]] = []
    for selected in matches:
        selected["value"] = str(selected["value"]).strip().upper()
        selector_id = selected.get("selector_id")
        if (
            not isinstance(selector_id, str)
            or re.fullmatch(r"E[0-9]{1,3}", selector_id) is None
        ):
            raise _invalid("Delegated Project selector ID is invalid.")
        normalized.append(selected)

    project_codes = [str(item["value"]) for item in normalized]
    primary_matches = [
        item for item in normalized if item["value"] == primary_project_code
    ]
    if (
        len(primary_matches) != 1
        or len(project_codes) != len(set(project_codes))
        or (
            allocation_project_codes
            and not set(project_codes).issubset(allocation_project_codes)
        )
    ):
        raise _error(
            "ae.business_context_project_ambiguous",
            "Primary Project identity must match exactly one delegated selector.",
        )
    return primary_matches[0]


def _allocations(parameters: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    project_records: dict[int, Mapping[str, Any]] = {}
    ratio_records: dict[int, Mapping[str, Any]] = {}
    for name, item in parameters.items():
        project_match = _ALLOCATION_PROJECT.fullmatch(name)
        ratio_match = _ALLOCATION_RATIO.fullmatch(name)
        if project_match:
            project_records[int(project_match.group(1))] = item
        elif ratio_match:
            ratio_records[int(ratio_match.group(1))] = item
    indexes = set(project_records) | set(ratio_records)
    if not indexes:
        return []
    if (
        indexes != set(project_records)
        or indexes != set(ratio_records)
        or indexes != set(range(1, len(indexes) + 1))
        or len(indexes) > BUSINESS_ALLOCATION_MAX_ITEMS
    ):
        raise _invalid("Allocation candidates must be complete contiguous pairs.")

    result: list[dict[str, str]] = []
    seen_projects: set[str] = set()
    total = Decimal(0)
    for index in sorted(indexes):
        project_code = _project_code(project_records[index].get("value"))
        if project_code in seen_projects:
            raise _invalid("Allocation Project Codes must be unique.")
        seen_projects.add(project_code)
        ratio = _ratio(ratio_records[index].get("value"))
        total += Decimal(ratio)
        result.append({"project_code": project_code, "ratio": ratio})
    if total != Decimal("1.000000"):
        raise _invalid("Allocation ratios must total exactly 1.000000.")
    return result


def _work_intent_parameters(
    parameters: Mapping[str, Mapping[str, Any]], context: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    normalized_values: dict[str, Any] = {
        "company_selector": context["company_selector"]["value"],
        "primary_project_code": _project_code(
            parameters["primary_project_code"].get("value"),
            field_name="Primary Project Code",
        ),
        "document_subject": context["document"]["subject_ref"],
        "counterparty_selector": context["transaction"]["counterparty_selector"],
        "amount": context["transaction"]["amount"],
        "currency": context["transaction"]["currency"],
        "recognition_date": context["transaction"]["recognition_date"],
        "description": context["transaction"]["description"],
    }
    for index, allocation in enumerate(context["requested_allocation"], start=1):
        normalized_values[f"allocation_project_code_{index}"] = allocation[
            "project_code"
        ]
        normalized_values[f"allocation_ratio_{index}"] = allocation["ratio"]

    value_types = {
        "amount": "DECIMAL",
        "currency": "ENUM",
        "recognition_date": "DATE",
    }
    result: list[Mapping[str, Any]] = []
    for name in sorted(normalized_values):
        if name.startswith("allocation_ratio_"):
            value_type = "DECIMAL"
        elif name.startswith("allocation_project_code_"):
            value_type = "STRING"
        else:
            value_type = value_types.get(name, "STRING")
        result.append(
            {
                "name": name,
                "value": normalized_values[name],
                "value_type": value_type,
                "source": "MODEL_CANDIDATE",
                "confidence": _confidence(
                    parameters[name].get("confidence"), f"{name} confidence"
                ),
            }
        )
    return tuple(result)


def _text_parameter(
    parameters: Mapping[str, Mapping[str, Any]], name: str, maximum: int
) -> str:
    return _text(name, parameters[name].get("value"), maximum)


def _amount_parameter(parameters: Mapping[str, Mapping[str, Any]]) -> str:
    return _amount(parameters["amount"].get("value"))


def _currency_parameter(parameters: Mapping[str, Mapping[str, Any]]) -> str:
    return _currency(parameters["currency"].get("value"))


def _date_parameter(parameters: Mapping[str, Mapping[str, Any]]) -> str:
    return _calendar_date(parameters["recognition_date"].get("value"))


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


def _project_code(value: object, *, field_name: str = "Allocation Project Code") -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} is invalid.")
    selected = value.strip().upper()
    if _PROJECT_CODE.fullmatch(selected) is None:
        raise _invalid(f"{field_name} is invalid.")
    return selected


def _amount(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise _invalid("Business amount is invalid.")
    try:
        selected = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise _invalid("Business amount is invalid.") from None
    if not selected.is_finite() or selected <= 0:
        raise _invalid("Business amount must be a positive value with two decimals.")
    try:
        quantized = selected.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise _invalid("Business amount is invalid.") from None
    if selected != quantized:
        raise _invalid("Business amount must be a positive value with two decimals.")
    integer_digits = len(str(quantized.copy_abs()).split(".", maxsplit=1)[0])
    if integer_digits > 16:
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
        raise _invalid(
            "Business recognition date must be an ISO calendar date."
        ) from None
    if parsed.isoformat() != selected:
        raise _invalid("Business recognition date must be canonical.")
    return selected


def _ratio(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise _invalid("Business allocation ratio is invalid.")
    try:
        selected = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise _invalid("Business allocation ratio is invalid.") from None
    if not selected.is_finite() or selected <= 0 or selected > 1:
        raise _invalid("Business allocation ratio must be within (0, 1].")
    try:
        quantized = selected.quantize(Decimal("0.000001"))
    except InvalidOperation:
        raise _invalid("Business allocation ratio is invalid.") from None
    if selected != quantized:
        raise _invalid("Business allocation ratio must be within (0, 1].")
    return format(quantized, ".6f")


def _confidence(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
    ):
        raise _invalid(f"{field_name} is invalid.")
    return float(value)


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError):
        raise _invalid(f"{field_name} is invalid.") from None


def _invalid(detail: str) -> BusinessRequestContextError:
    return _error("ae.business_context_invalid", detail)


def _error(error_code: str, detail: str) -> BusinessRequestContextError:
    return BusinessRequestContextError(error_code, detail)
