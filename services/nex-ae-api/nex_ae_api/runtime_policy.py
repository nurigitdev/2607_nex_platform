from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from nex_ae_api.intent_policy import resolve_intent_decision
from nex_ae_api.prompts import (
    AE_DOCUMENT_GENERATION_BINDING,
    AE_DOCUMENT_SUMMARY_BINDING,
    AE_GENERAL_ANSWER_BINDING,
    AE_GROUNDED_CHAT_BINDING,
)


RUNTIME_POLICY_SCHEMA_VERSION = "ae_runtime_policy.v1"
FORBIDDEN_PROVIDER_FIELDS = {
    "provider_url",
    "base_url",
    "port",
    "api_key",
    "model_path",
    "vllm_options",
}


@dataclass(frozen=True)
class RuntimePolicyError(Exception):
    status_code: int
    error_code: str
    detail: str


def _stable_hash(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rule(
    rule_id: str,
    mode: str,
    template_id: str,
    binding_key: str,
    output_contract_id: str,
    artifact_intent: str,
    generation_profile: str,
    *,
    grounding_required: bool,
    citation_required: bool,
    max_output_tokens: int,
) -> dict[str, Any]:
    rule = {
        "rule_schema_version": "ae_runtime_policy_rule.v1",
        "rule_id": rule_id,
        "rule_version": "v1",
        "status": "ACTIVE",
        "execution_mode": mode,
        "template_id": template_id,
        "template_version": "v1" if template_id != "none" else "none",
        "prompt_binding_key": binding_key,
        "prompt_version": "v1",
        "output_contract_id": output_contract_id,
        "output_contract_version": "v1",
        "artifact_intent": artifact_intent,
        "preferred_export_format": "MD" if artifact_intent != "none" else "none",
        "generation_profile": generation_profile,
        "provider_capability": "generation",
        "generation_parameters": {
            "max_output_tokens": max_output_tokens,
            "temperature": 0.0,
            "streaming": False,
            "timeout_ms": 120000,
        },
        "quality_policy": {
            "policy_id": f"quality.{generation_profile}.v1",
            "grounding_required": grounding_required,
            "citation_required": citation_required,
            "low_confidence_behavior": "block" if grounding_required else "warn",
            "no_answer_behavior": (
                "block_grounded_generation" if grounding_required else "allow"
            ),
            "untrusted_context_boundary": True,
        },
    }
    rule["rule_hash"] = _stable_hash(rule)
    return rule


DEFAULT_AE_RUNTIME_POLICY_RULES: tuple[dict[str, Any], ...] = (
    _rule(
        "ae.general_answer.v1",
        "GENERAL_ANSWER",
        "none",
        AE_GENERAL_ANSWER_BINDING,
        "text_answer_v1",
        "none",
        "general-answer",
        grounding_required=False,
        citation_required=False,
        max_output_tokens=512,
    ),
    _rule(
        "ae.grounded_answer.v1",
        "GROUNDED_ANSWER",
        "none",
        AE_GROUNDED_CHAT_BINDING,
        "grounded_answer_v1",
        "none",
        "grounded-answer",
        grounding_required=True,
        citation_required=True,
        max_output_tokens=1024,
    ),
    _rule(
        "ae.document_summary.v1",
        "DOCUMENT_SUMMARY",
        "summary",
        AE_DOCUMENT_SUMMARY_BINDING,
        "document_summary_v1",
        "preview_only",
        "summary",
        grounding_required=True,
        citation_required=True,
        max_output_tokens=1024,
    ),
    *(
        _rule(
            f"ae.document_generation.{template_id}.v1",
            "DOCUMENT_GENERATION",
            template_id,
            AE_DOCUMENT_GENERATION_BINDING,
            "structured_document_v1",
            "create_artifact",
            "general-document",
            grounding_required=True,
            citation_required=True,
            max_output_tokens=4096,
        )
        for template_id in ("report", "proposal", "memo")
    ),
)


def resolve_runtime_policy(
    payload: Mapping[str, Any],
    *,
    rules: Sequence[Mapping[str, Any]] = DEFAULT_AE_RUNTIME_POLICY_RULES,
) -> dict[str, Any]:
    generation = payload.get("generation", {})
    if not isinstance(generation, Mapping):
        raise RuntimePolicyError(
            400,
            "ae.runtime_policy_generation_invalid",
            "generation must be an object when supplied.",
        )
    forbidden = sorted(FORBIDDEN_PROVIDER_FIELDS.intersection(generation))
    if forbidden:
        raise RuntimePolicyError(
            422,
            "ae.provider_runtime_field_forbidden",
            f"Provider runtime field is forbidden: {forbidden[0]}",
        )

    intent = resolve_intent_decision(payload)
    template_id, template_version = _template_ref(generation, intent)
    requested = {
        "execution_mode": intent["execution_mode"],
        "template_id": template_id,
        "template_version": template_version,
        "prompt_binding_key": _nested_or_flat(
            generation,
            "prompt_contract_ref",
            "prompt_binding_key",
        ),
        "prompt_version": _nested_or_flat(
            generation,
            "prompt_contract_ref",
            "prompt_version",
        ),
        "output_contract_id": _nested_or_flat(
            generation,
            "output_contract",
            "output_contract_id",
        ),
        "artifact_intent": _nested_or_flat(
            generation,
            "output_contract",
            "artifact_intent",
        ),
    }
    matches = [
        dict(rule)
        for rule in rules
        if rule.get("status") == "ACTIVE"
        and _rule_matches(rule, requested)
    ]
    if not matches:
        raise RuntimePolicyError(
            422,
            "ae.runtime_policy_not_found",
            "No active AE runtime policy matches the requested combination.",
        )
    if len(matches) != 1:
        raise RuntimePolicyError(
            409,
            "ae.runtime_policy_ambiguous",
            "More than one active AE runtime policy matches the request.",
        )
    rule = matches[0]
    parameters = _resolve_generation_parameters(
        generation.get("parameters"),
        rule["generation_parameters"],
    )
    resolved = {
        "runtime_policy_schema_version": RUNTIME_POLICY_SCHEMA_VERSION,
        "intent_decision": intent,
        "compatibility_rule": {
            "rule_id": rule["rule_id"],
            "rule_version": rule["rule_version"],
            "rule_hash": rule["rule_hash"],
        },
        "template_ref": {
            "template_id": rule["template_id"],
            "template_version": rule["template_version"],
        },
        "prompt_contract_ref": {
            "prompt_binding_key": rule["prompt_binding_key"],
            "prompt_version": rule["prompt_version"],
        },
        "output_contract": {
            "output_contract_id": rule["output_contract_id"],
            "output_contract_version": rule["output_contract_version"],
            "artifact_intent": rule["artifact_intent"],
            "preferred_export_format": rule["preferred_export_format"],
        },
        "generation_profile": rule["generation_profile"],
        "provider_capability": rule["provider_capability"],
        "generation_parameters": parameters,
        "quality_policy": dict(rule["quality_policy"]),
        "raw_prompt_included": False,
        "provider_runtime_included": False,
    }
    resolved["policy_snapshot_hash"] = _stable_hash(resolved)
    return resolved


def _rule_matches(rule: Mapping[str, Any], requested: Mapping[str, Any]) -> bool:
    for field in (
        "execution_mode",
        "template_id",
        "template_version",
        "prompt_binding_key",
        "prompt_version",
        "output_contract_id",
        "artifact_intent",
    ):
        requested_value = requested.get(field)
        if requested_value is not None and requested_value != rule.get(field):
            return False
    return True


def _template_ref(
    generation: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> tuple[str, str]:
    nested = generation.get("template_ref", {})
    if nested is not None and not isinstance(nested, Mapping):
        raise RuntimePolicyError(
            400,
            "ae.template_ref_invalid",
            "template_ref must be an object when supplied.",
        )
    nested = nested or {}
    template_id = generation.get("template_id", nested.get("template_id"))
    template_version = generation.get(
        "template_version", nested.get("template_version")
    )
    if intent["template_required"] and template_id is None:
        raise RuntimePolicyError(
            422,
            "ae.template_required",
            "DOCUMENT_GENERATION requires an explicit template_id.",
        )
    if template_id is None:
        template_id = "summary" if intent["execution_mode"] == "DOCUMENT_SUMMARY" else "none"
    if template_version is None:
        template_version = "v1" if template_id != "none" else "none"
    template_id = _versioned_text(template_id, "template_id")
    template_version = _versioned_text(template_version, "template_version")
    return template_id, template_version


def _nested_or_flat(
    generation: Mapping[str, Any],
    container_name: str,
    field_name: str,
) -> str | None:
    container = generation.get(container_name, {})
    if container is not None and not isinstance(container, Mapping):
        raise RuntimePolicyError(
            400,
            "ae.runtime_policy_ref_invalid",
            f"{container_name} must be an object when supplied.",
        )
    value = generation.get(field_name, (container or {}).get(field_name))
    return None if value is None else _versioned_text(value, field_name)


def _versioned_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimePolicyError(
            422,
            "ae.runtime_policy_value_invalid",
            f"{field_name} must be a non-empty string.",
        )
    normalized = value.strip()
    if normalized.casefold() == "latest":
        raise RuntimePolicyError(
            422,
            "ae.runtime_policy_implicit_latest_forbidden",
            f"{field_name} must use an explicit version.",
        )
    return normalized


def _resolve_generation_parameters(
    requested: Any,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    if requested is None:
        return dict(defaults)
    if not isinstance(requested, Mapping):
        raise RuntimePolicyError(
            400,
            "ae.generation_parameters_invalid",
            "generation parameters must be an object.",
        )
    unknown = sorted(set(requested).difference(defaults))
    if unknown:
        raise RuntimePolicyError(
            422,
            "ae.generation_parameter_unknown",
            f"Unsupported generation parameter: {unknown[0]}",
        )
    merged = {**defaults, **requested}
    if not isinstance(merged["max_output_tokens"], int) or not (
        128 <= merged["max_output_tokens"] <= 8192
    ):
        raise _parameter_out_of_bounds("max_output_tokens")
    if not isinstance(merged["temperature"], (int, float)) or isinstance(
        merged["temperature"], bool
    ) or not (0 <= merged["temperature"] <= 1):
        raise _parameter_out_of_bounds("temperature")
    if not isinstance(merged["streaming"], bool):
        raise _parameter_out_of_bounds("streaming")
    if not isinstance(merged["timeout_ms"], int) or not (
        1000 <= merged["timeout_ms"] <= 180000
    ):
        raise _parameter_out_of_bounds("timeout_ms")
    return merged


def _parameter_out_of_bounds(field_name: str) -> RuntimePolicyError:
    return RuntimePolicyError(
        422,
        "ae.generation_parameter_out_of_bounds",
        f"Generation parameter is outside policy: {field_name}",
    )

