from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from nex_ae_api.intent_policy import (
    IntentPolicyError,
    resolve_validated_intent_candidate,
)
from nex_ae_api.mo_generation_client import (
    AeMoGenerationClient,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.prompts import AE_INTENT_RESOLUTION_BINDING
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
    SemanticCandidateStageError,
)
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.prompts import PromptRegistryError, render_prompt_from_binding
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_sha256_digest,
)


INTENT_CANDIDATE_SCHEMA_VERSION = "p65.intent_candidate.v1"
INTENT_GENERATION_INPUT_SCHEMA_VERSION = "p65.intent_generation_input.v1"

_EXECUTION_MODES = {
    "GENERAL_ANSWER",
    "GROUNDED_ANSWER",
    "DOCUMENT_SUMMARY",
    "DOCUMENT_GENERATION",
}
_SELECTOR_TYPES = {
    "ENTITY_ID",
    "ENTITY_NAME",
    "DOCUMENT_ID",
    "QUERY_TERM",
    "RESOURCE_HINT",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "intent_label",
    "suggested_execution_mode",
    "entity_selectors",
    "parameter_candidates",
    "clarification",
    "confidence",
}
_SELECTOR_KEYS = {"selector_id", "selector_type", "value", "confidence"}
_PARAMETER_KEYS = {"name", "value", "confidence"}
_CLARIFICATION_KEYS = {"required", "reasons", "questions"}
_AUTHORITY_KEYS = {
    "tenant",
    "tenant_id",
    "principal",
    "principal_id",
    "owner",
    "owner_id",
    "owner_subject_id",
    "project",
    "project_id",
    "project_ref",
    "role",
    "roles",
    "permission",
    "permissions",
    "capability_version",
    "executor_kind",
    "execution_authority",
    "approved",
    "provider_url",
    "provider_endpoint",
    "api_key",
    "model_path",
}
_INJECTION_MARKERS = (
    "ignore previous instruction",
    "ignore all previous",
    "ignore the system",
    "reveal system prompt",
    "developer message",
    "jailbreak",
    "이전 지시를 무시",
    "시스템 프롬프트를 공개",
    "개발자 메시지",
)
_SELECTOR_ID = re.compile(r"^E[0-9]{1,3}$")
_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
IntentCandidateStageError = SemanticCandidateStageError
IntentCalibrationPolicy = SemanticCalibrationPolicy
IntentCalibrationRegistry = SemanticCalibrationRegistry


@dataclass(frozen=True)
class IntentCandidateStageResult:
    directive: str
    failure_code: str | None
    candidate_hash: str
    provider_output_sha256: str
    input_context_hash: str
    prompt_provenance: Mapping[str, Any]
    model_provenance: Mapping[str, Any]
    admission_policy_ref: str | None
    selected_threshold: float | None
    candidate: Mapping[str, Any] = field(repr=False)
    intent_decision: Mapping[str, Any] | None = field(default=None, repr=False)
    work_intent: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LiveIntentCandidateService:
    client: AeMoGenerationClient = field(repr=False)
    prompt_store: Any = field(repr=False)
    calibration_registry: IntentCalibrationRegistry = field(
        default_factory=IntentCalibrationRegistry,
        repr=False,
    )

    def generate_and_resolve(
        self,
        *,
        user_prompt: str,
        execution_id: str,
        source_ref: str,
        actor_ref: str,
        received_at: str,
        request_id: str,
        trace_id: str,
        planning_mode: str,
        trusted_execution_mode: str | None = None,
        retrieval_enabled: bool = False,
        authorized_resource_context_available: bool = False,
        work_intent_id: str | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> IntentCandidateStageResult:
        selected_mode = _planning_mode(planning_mode)
        selected_prompt = _bounded_text(user_prompt, "user_prompt", 65_536)
        selected_request_id = _bounded_text(request_id, "request_id", 200)
        selected_trace_id = _trace_id_value(trace_id)
        if not isinstance(retrieval_enabled, bool):
            raise _request_error("retrieval_enabled must be boolean.")
        if not isinstance(authorized_resource_context_available, bool):
            raise _request_error(
                "authorized_resource_context_available must be boolean."
            )

        prompt_snapshot = _resolve_prompt_snapshot(
            self.prompt_store,
            user_prompt=selected_prompt,
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        input_context = {
            "schema_version": INTENT_GENERATION_INPUT_SCHEMA_VERSION,
            "user_prompt": selected_prompt,
            "trusted_controls": {
                "execution_mode": trusted_execution_mode,
                "retrieval_enabled": retrieval_enabled,
                "authorized_resource_context_available": (
                    authorized_resource_context_available
                ),
            },
        }
        input_context_hash = semantic_sha256_hash_ref(input_context)

        readiness = self.client.check_required_mode_readiness(
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        policy = self.calibration_registry.select(
            semantic_stage="INTENT",
            model_profile=readiness.model_profile,
            model_ref=readiness.model_ref,
        )
        if selected_mode == "required" and policy is None:
            raise IntentCandidateStageError(
                503,
                "SEMANTIC_CALIBRATION_REQUIRED",
                "Required INTENT mode needs an exact active model calibration policy.",
                retryable=False,
            )

        generation = self.client.generate_candidate(
            semantic_stage="INTENT",
            messages=(
                {"role": "system", "content": prompt_snapshot["rendered_prompt"]},
                {"role": "user", "content": canonical_json(input_context)},
            ),
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        _require_matching_model(readiness, generation)
        candidate = parse_intent_candidate(generation.output_text)
        candidate_hash = semantic_sha256_hash_ref(candidate)
        decision = resolve_intent_candidate(
            candidate,
            trusted_execution_mode=trusted_execution_mode,
            retrieval_enabled=retrieval_enabled,
        )
        prompt_provenance = {
            **prompt_snapshot["provenance"],
            "input_context_hash": input_context_hash,
        }
        model_provenance = {
            "model_profile": generation.model_profile,
            "model_ref": generation.model_ref,
            "deployment_id": generation.deployment_id,
            "mo_generation_id": generation.mo_generation_id,
            "route_id": generation.route_id,
        }

        threshold = policy.minimum_confidence if policy is not None else None
        if threshold is not None and float(candidate["confidence"]) < threshold:
            return _result(
                directive="CLARIFICATION_REQUIRED",
                failure_code="CANDIDATE_LOW_CONFIDENCE",
                candidate=candidate,
                candidate_hash=candidate_hash,
                generation=generation,
                input_context_hash=input_context_hash,
                prompt_provenance=prompt_provenance,
                model_provenance=model_provenance,
                policy=policy,
            )
        if candidate["clarification"]["required"] is True:
            return _result(
                directive="CLARIFICATION_REQUIRED",
                failure_code=None,
                candidate=candidate,
                candidate_hash=candidate_hash,
                generation=generation,
                input_context_hash=input_context_hash,
                prompt_provenance=prompt_provenance,
                model_provenance=model_provenance,
                policy=policy,
            )
        if selected_mode == "shadow":
            return _result(
                directive="SHADOW_ONLY",
                failure_code=None,
                candidate=candidate,
                candidate_hash=candidate_hash,
                generation=generation,
                input_context_hash=input_context_hash,
                prompt_provenance=prompt_provenance,
                model_provenance=model_provenance,
                policy=policy,
                intent_decision=decision,
            )

        work_intent = build_work_intent_from_decision(
            execution_id=execution_id,
            source_ref=source_ref,
            actor_ref=actor_ref,
            received_at=received_at,
            intent_decision=decision,
            input_context_hash=input_context_hash,
            work_intent_id=work_intent_id,
            prompt_provenance={
                "prompt_binding_key": prompt_snapshot["provenance"][
                    "prompt_binding_key"
                ],
                "prompt_template_version_id": prompt_snapshot["provenance"][
                    "prompt_template_version_id"
                ],
                "prompt_content_sha256": prompt_snapshot["provenance"][
                    "prompt_content_sha256"
                ],
                "rendered_prompt_hash": prompt_snapshot["provenance"][
                    "rendered_prompt_hash"
                ],
                "model_profile": generation.model_profile,
                "model_ref": generation.model_ref,
            },
            id_factory=id_factory,
        )
        return _result(
            directive="CONTINUE",
            failure_code=None,
            candidate=candidate,
            candidate_hash=candidate_hash,
            generation=generation,
            input_context_hash=input_context_hash,
            prompt_provenance=prompt_provenance,
            model_provenance=model_provenance,
            policy=policy,
            intent_decision=decision,
            work_intent=work_intent,
        )


def parse_intent_candidate(output_text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            output_text,
            parse_constant=lambda constant: (_raise_json_constant(constant)),
        )
    except (TypeError, ValueError) as exc:
        raise IntentCandidateStageError(
            422,
            "CANDIDATE_JSON_INVALID",
            "INTENT provider output is not strict JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise _schema_error("INTENT candidate must be a JSON object.")
    _reject_authority_fields(value)
    if set(value) != _TOP_LEVEL_KEYS:
        raise _schema_error("INTENT candidate fields do not match the contract.")
    if value.get("schema_version") != INTENT_CANDIDATE_SCHEMA_VERSION:
        raise _schema_error("INTENT candidate schema version is unsupported.")

    intent_label = _candidate_text(value.get("intent_label"), "intent_label", 160)
    execution_mode = value.get("suggested_execution_mode")
    if execution_mode not in _EXECUTION_MODES:
        raise _schema_error("INTENT candidate execution mode is unsupported.")
    selectors = _selectors(value.get("entity_selectors"))
    parameters = _parameters(value.get("parameter_candidates"))
    clarification = _clarification(value.get("clarification"))
    confidence = _confidence(value.get("confidence"), "confidence")
    normalized = {
        "schema_version": INTENT_CANDIDATE_SCHEMA_VERSION,
        "intent_label": intent_label,
        "suggested_execution_mode": execution_mode,
        "entity_selectors": selectors,
        "parameter_candidates": parameters,
        "clarification": clarification,
        "confidence": confidence,
    }
    _reject_prompt_injection(normalized)
    return normalized


def _resolve_prompt_snapshot(
    store: Any,
    *,
    user_prompt: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    try:
        rendered = render_prompt_from_binding(
            store,
            binding_key=AE_INTENT_RESOLUTION_BINDING,
            variables={},
            request_id=request_id,
            trace_id=trace_id,
            user_prompt=user_prompt,
        )
        event = rendered["render_event"]
        version = store.get_template_version(event["prompt_template_version_id"])
    except (AttributeError, KeyError, PromptRegistryError) as exc:
        raise IntentCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The exact INTENT prompt binding is not ready.",
        ) from exc
    if not isinstance(version, dict) or version.get("status") != "ACTIVE":
        raise IntentCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The captured INTENT prompt version is not active.",
        )
    if (
        event.get("binding_key") != AE_INTENT_RESOLUTION_BINDING
        or event.get("purpose") != "intent_resolution"
        or version.get("purpose") != "intent_resolution"
        or version.get("role") != "system"
        or version.get("model_capability") != "generation"
    ):
        raise _schema_error("The captured INTENT prompt binding is incompatible.")
    try:
        content_sha256 = validate_sha256_digest(version.get("content_sha256"))
        rendered_hash = validate_sha256_digest(event.get("rendered_prompt_hash"))
    except ValueError as exc:
        raise _schema_error(
            "The captured INTENT prompt provenance digest is invalid."
        ) from exc
    return {
        "rendered_prompt": _bounded_text(
            rendered.get("rendered_prompt"), "rendered_prompt", 16_384
        ),
        "provenance": {
            "prompt_binding_id": _bounded_text(
                event.get("prompt_binding_id"), "prompt_binding_id", 64
            ),
            "prompt_binding_key": AE_INTENT_RESOLUTION_BINDING,
            "prompt_template_version_id": _bounded_text(
                event.get("prompt_template_version_id"),
                "prompt_template_version_id",
                64,
            ),
            "prompt_template_version": _bounded_text(
                version.get("version"), "prompt_template_version", 64
            ),
            "prompt_content_sha256": content_sha256,
            "rendered_prompt_hash": rendered_hash,
        },
    }


def _result(
    *,
    directive: str,
    failure_code: str | None,
    candidate: Mapping[str, Any],
    candidate_hash: str,
    generation: AeMoGenerationResult,
    input_context_hash: str,
    prompt_provenance: Mapping[str, Any],
    model_provenance: Mapping[str, Any],
    policy: SemanticCalibrationPolicy | None,
    intent_decision: Mapping[str, Any] | None = None,
    work_intent: Mapping[str, Any] | None = None,
) -> IntentCandidateStageResult:
    return IntentCandidateStageResult(
        directive=directive,
        failure_code=failure_code,
        candidate_hash=candidate_hash,
        provider_output_sha256=generation.provider_output_sha256,
        input_context_hash=input_context_hash,
        prompt_provenance=dict(prompt_provenance),
        model_provenance=dict(model_provenance),
        admission_policy_ref=policy.policy_ref if policy is not None else None,
        selected_threshold=(
            policy.minimum_confidence if policy is not None else None
        ),
        candidate=dict(candidate),
        intent_decision=(dict(intent_decision) if intent_decision else None),
        work_intent=(dict(work_intent) if work_intent else None),
    )


def resolve_intent_candidate(
    candidate: Mapping[str, Any],
    *,
    trusted_execution_mode: str | None,
    retrieval_enabled: bool,
) -> dict[str, Any]:
    try:
        return resolve_validated_intent_candidate(
            candidate,
            trusted_execution_mode=trusted_execution_mode,
            retrieval_enabled=retrieval_enabled,
        )
    except IntentPolicyError as exc:
        code = (
            "CANDIDATE_AUTHORITY_VIOLATION"
            if exc.error_code == "ae.intent_candidate_mode_conflict"
            else "CANDIDATE_SCHEMA_INVALID"
        )
        raise IntentCandidateStageError(422, code, exc.detail) from exc


def _require_matching_model(
    readiness: AeMoGenerationReadiness,
    generation: AeMoGenerationResult,
) -> None:
    if (
        generation.model_profile != readiness.model_profile
        or generation.model_ref != readiness.model_ref
        or generation.deployment_id != readiness.deployment_id
        or generation.route_id != readiness.route_id
    ):
        raise IntentCandidateStageError(
            502,
            "PROVIDER_RESPONSE_INVALID",
            "MO generation lineage changed after INTENT readiness selection.",
        )


def _selectors(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "entity_selectors", 32)
    normalized: list[dict[str, Any]] = []
    selector_ids: set[str] = set()
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _SELECTOR_KEYS:
            raise _schema_error("INTENT entity selector fields are invalid.")
        selector_id = record.get("selector_id")
        if not isinstance(selector_id, str) or _SELECTOR_ID.fullmatch(selector_id) is None:
            raise _schema_error("INTENT entity selector ID is invalid.")
        selector_type = record.get("selector_type")
        if selector_type not in _SELECTOR_TYPES:
            raise _schema_error("INTENT entity selector type is invalid.")
        item = {
            "selector_id": selector_id,
            "selector_type": selector_type,
            "value": _candidate_text(record.get("value"), "selector value", 256),
            "confidence": _confidence(
                record.get("confidence"), "selector confidence"
            ),
        }
        identity = canonical_json(item)
        if selector_id in selector_ids or identity in seen:
            raise _schema_error("INTENT entity selectors must be unique.")
        selector_ids.add(selector_id)
        seen.add(identity)
        normalized.append(item)
    return normalized


def _parameters(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "parameter_candidates", 32)
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _PARAMETER_KEYS:
            raise _schema_error("INTENT parameter candidate fields are invalid.")
        name = record.get("name")
        if not isinstance(name, str) or _PARAMETER_NAME.fullmatch(name) is None:
            raise _schema_error("INTENT parameter candidate name is invalid.")
        candidate_value = record.get("value")
        if isinstance(candidate_value, str):
            if len(candidate_value) > 500:
                raise _bounds_error("INTENT parameter value exceeds its bound.")
        elif isinstance(candidate_value, bool) or candidate_value is None:
            pass
        elif isinstance(candidate_value, (int, float)):
            if not math.isfinite(float(candidate_value)):
                raise _schema_error("INTENT parameter value must be finite.")
        else:
            raise _schema_error("INTENT parameter value type is invalid.")
        item = {
            "name": name,
            "value": candidate_value,
            "confidence": _confidence(
                record.get("confidence"), "parameter confidence"
            ),
        }
        identity = canonical_json(item)
        if name in names or identity in seen:
            raise _schema_error("INTENT parameter candidates must be unique.")
        names.add(name)
        seen.add(identity)
        normalized.append(item)
    return normalized


def _clarification(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CLARIFICATION_KEYS:
        raise _schema_error("INTENT clarification fields are invalid.")
    required = value.get("required")
    if not isinstance(required, bool):
        raise _schema_error("INTENT clarification required flag is invalid.")
    reasons = _text_list(value.get("reasons"), "clarification reasons", 8, 240)
    questions = _text_list(
        value.get("questions"), "clarification questions", 4, 500
    )
    return {"required": required, "reasons": reasons, "questions": questions}


def _text_list(value: object, field_name: str, maximum: int, text_max: int) -> list[str]:
    records = _bounded_list(value, field_name, maximum)
    normalized = [_candidate_text(item, field_name, text_max) for item in records]
    if len(set(normalized)) != len(normalized):
        raise _schema_error(f"INTENT {field_name} must be unique.")
    return normalized


def _bounded_list(value: object, field_name: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise _schema_error(f"INTENT {field_name} must be an array.")
    if len(value) > maximum:
        raise _bounds_error(f"INTENT {field_name} exceeds its bound.")
    return value


def _confidence(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise _schema_error(f"INTENT {field_name} must be between zero and one.")
    return float(value)


def _reject_authority_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _AUTHORITY_KEYS:
                raise IntentCandidateStageError(
                    422,
                    "CANDIDATE_AUTHORITY_VIOLATION",
                    "INTENT candidate contains an authority-bearing field.",
                )
            _reject_authority_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_authority_fields(item)


def _reject_prompt_injection(value: object) -> None:
    if isinstance(value, Mapping):
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        values = ()
        if isinstance(value, str):
            normalized = value.casefold()
            if any(marker in normalized for marker in _INJECTION_MARKERS):
                raise IntentCandidateStageError(
                    422,
                    "PROMPT_INJECTION_OR_POLICY_BLOCK",
                    "INTENT candidate contains prompt-control language.",
                )
    for item in values:
        _reject_prompt_injection(item)


def _planning_mode(value: object) -> str:
    if not isinstance(value, str) or value.casefold() not in {"shadow", "required"}:
        raise _request_error("INTENT candidate stage requires shadow or required mode.")
    return value.casefold()


def _trace_id_value(value: object) -> str:
    if not isinstance(value, str) or _TRACE_ID.fullmatch(value) is None:
        raise _request_error("trace_id must be 32 lowercase hexadecimal characters.")
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _request_error(f"{field_name} must be a bounded non-empty string.")
    return value.strip()


def _candidate_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _schema_error(f"INTENT {field_name} must be non-empty text.")
    if len(value) > maximum:
        raise _bounds_error(f"INTENT {field_name} exceeds its bound.")
    return value.strip()


def _raise_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _schema_error(detail: str) -> IntentCandidateStageError:
    return IntentCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", detail)


def _bounds_error(detail: str) -> IntentCandidateStageError:
    return IntentCandidateStageError(422, "CANDIDATE_BOUNDS_EXCEEDED", detail)


def _request_error(detail: str) -> IntentCandidateStageError:
    return IntentCandidateStageError(400, "INTENT_STAGE_REQUEST_INVALID", detail)
