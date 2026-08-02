from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime.auth import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from nex_runtime.problem import problem_response


@dataclass(frozen=True)
class GenerationCompatibilityError(Exception):
    status_code: int
    error_code: str
    detail: str


DEFAULT_GENERATION_COMPATIBILITY_RULES: tuple[dict[str, Any], ...] = (
    {
        "compatibility_rule_schema_version": "generation_compatibility_rule.v1",
        "compatibility_rule_id": "compat-grounded-answer-v1",
        "status": "ACTIVE",
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "grounding_required": True,
        "allowed_artifact_intents": ["preview_only", "answer_export"],
        "citation_policy": {
            "citations_required": True,
            "source_trace_required": True,
        },
        "metadata": {
            "slice": "0034",
            "owner": "ae-cx-contract",
        },
    },
    {
        "compatibility_rule_schema_version": "generation_compatibility_rule.v1",
        "compatibility_rule_id": "compat-general-answer-v1",
        "status": "ACTIVE",
        "execution_mode": "GENERAL_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "general-answer",
        "grounding_required": False,
        "allowed_artifact_intents": ["preview_only", "answer_export"],
        "citation_policy": {
            "citations_required": False,
            "source_trace_required": False,
        },
        "metadata": {
            "slice": "0034",
            "owner": "ae-cx-contract",
        },
    },
    {
        "compatibility_rule_schema_version": "generation_compatibility_rule.v1",
        "compatibility_rule_id": "compat-document-summary-v1",
        "status": "ACTIVE",
        "execution_mode": "DOCUMENT_SUMMARY",
        "template_id": "summary",
        "prompt_binding_id": "cx.document_summary.default",
        "output_contract_id": "document_summary_v1",
        "provider_capability": "generation",
        "generation_profile": "summary",
        "grounding_required": True,
        "allowed_artifact_intents": ["preview_only", "create_artifact"],
        "citation_policy": {
            "citations_required": False,
            "source_trace_required": True,
        },
        "metadata": {
            "slice": "0034",
            "owner": "ae-cx-contract",
        },
    },
    {
        "compatibility_rule_schema_version": "generation_compatibility_rule.v1",
        "compatibility_rule_id": "compat-report-generation-v1",
        "status": "ACTIVE",
        "execution_mode": "REPORT_GENERATION",
        "template_id": "report",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "report_generation_v1",
        "provider_capability": "generation",
        "generation_profile": "general-document",
        "grounding_required": True,
        "allowed_artifact_intents": ["preview_only", "create_artifact"],
        "citation_policy": {
            "citations_required": True,
            "source_trace_required": True,
        },
        "metadata": {
            "slice": "0034",
            "owner": "ae-cx-contract",
        },
    },
)


COMPATIBILITY_FIELDS = (
    "execution_mode",
    "template_id",
    "prompt_binding_id",
    "output_contract_id",
    "provider_capability",
    "generation_profile",
)


def register_generation_compatibility_routes(
    app: FastAPI,
    *,
    expected_audience: str,
    rules: tuple[dict[str, Any], ...] = DEFAULT_GENERATION_COMPATIBILITY_RULES,
) -> None:
    @app.get("/api/v1/compatibility/generation-rules", response_model=None)
    def list_generation_compatibility_rules(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_request(
            request,
            authorization,
            expected_audience=expected_audience,
        )
        if auth_problem is not None:
            return auth_problem
        return {"rules": list(rules)}


def compatibility_key_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    metadata = _optional_mapping(payload.get("metadata"))
    template_ref = _optional_mapping(payload.get("template_ref"))
    prompt_ref = _optional_mapping(payload.get("prompt_contract_ref"))
    output_contract = _optional_mapping(payload.get("output_contract"))

    return {
        "execution_mode": _string_value(
            payload,
            metadata,
            "execution_mode",
            default="GROUNDED_ANSWER",
        ),
        "template_id": _string_value(
            payload,
            template_ref,
            "template_id",
            default="none",
        ),
        "prompt_binding_id": _string_value(
            payload,
            prompt_ref,
            "prompt_binding_id",
            default="ae.grounded_chat.default",
        ),
        "output_contract_id": _string_value(
            payload,
            output_contract,
            "output_contract_id",
            default="text_answer_v1",
        ),
        "provider_capability": _string_value(
            payload,
            metadata,
            "provider_capability",
            default="generation",
        ),
        "generation_profile": _string_value(
            payload,
            metadata,
            "generation_profile",
            default="grounded-answer",
        ),
    }


def select_generation_compatibility_rule(
    payload: dict[str, Any],
    *,
    rules: tuple[dict[str, Any], ...] = DEFAULT_GENERATION_COMPATIBILITY_RULES,
) -> dict[str, Any]:
    key = compatibility_key_from_payload(payload)
    for rule in rules:
        if rule.get("status") != "ACTIVE":
            continue
        if all(rule[field] == key[field] for field in COMPATIBILITY_FIELDS):
            return rule

    raise GenerationCompatibilityError(
        status_code=422,
        error_code="generation.compatibility_rule_not_found",
        detail=(
            "No active generation compatibility rule matched "
            f"{compatibility_key_label(key)}."
        ),
    )


def compatibility_key_label(key: dict[str, str]) -> str:
    return ", ".join(f"{field}={key[field]}" for field in COMPATIBILITY_FIELDS)


def _optional_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _string_value(
    primary: dict[str, Any],
    secondary: dict[str, Any],
    field_name: str,
    *,
    default: str,
) -> str:
    value = primary.get(field_name, secondary.get(field_name, default))
    if not isinstance(value, str) or not value.strip():
        raise GenerationCompatibilityError(
            status_code=400,
            error_code="generation.compatibility_key_invalid",
            detail=f"{field_name} must be a non-empty string.",
        )
    return value.strip()


def _authorize_request(
    request: Request,
    authorization: str | None,
    *,
    expected_audience: str,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience=expected_audience,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or f"{expected_audience} requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )
