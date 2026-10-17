from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from nex_ae_api.agent_context import (
    AgentContextError,
    ContextCandidateHints,
    TrustedContextResolver,
    build_agent_context,
)
from nex_ae_api.mo_generation_client import (
    AeMoGenerationClient,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.prompts import AE_CONTEXT_CANDIDATE_BINDING
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
    SemanticCandidateStageError,
)
from nex_runtime.prompts import PromptRegistryError, render_prompt_from_binding
from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
    validate_sha256_digest,
)


CONTEXT_CANDIDATE_SCHEMA_VERSION = "p65.context_candidate_set.v1"
CONTEXT_GENERATION_INPUT_SCHEMA_VERSION = "p65.context_generation_input.v1"

_TOP_LEVEL_KEYS = {
    "schema_version",
    "entity_candidates",
    "retrieval_hints",
    "resource_selectors",
    "parameter_candidates",
    "confidence",
}
_ENTITY_KEYS = {
    "candidate_key",
    "entity_type",
    "selector_kind",
    "selector_value",
    "confidence",
}
_RETRIEVAL_KEYS = {"query_terms", "resource_types", "confidence"}
_RESOURCE_SELECTOR_KEYS = {
    "resource_type",
    "selector_kind",
    "selector_value",
    "confidence",
}
_PARAMETER_KEYS = {"name", "value", "confidence"}
_BASE_CONTEXT_KEYS = {
    "interaction_text",
    "conversation_summary",
    "resource_label_hints",
}
_ENTITY_SELECTOR_KINDS = {"ID", "NAME", "QUERY"}
_RESOURCE_TYPES = {"DOCUMENT", "CONVERSATION", "WORKSPACE"}
_RESOURCE_SELECTOR_KINDS = {"ID", "OWNER_VISIBLE_LABEL"}
_EXECUTION_MODES = {
    "GENERAL_ANSWER",
    "GROUNDED_ANSWER",
    "DOCUMENT_SUMMARY",
    "DOCUMENT_GENERATION",
}
_AUTHORITY_KEYS = {
    "approval_authority",
    "authority",
    "authority_ref",
    "capability_version",
    "classification",
    "classification_authority",
    "data_classification",
    "data_classification_authority",
    "exact_capability_version",
    "owner",
    "owner_id",
    "owner_subject_id",
    "permission",
    "permission_grants",
    "permissions",
    "principal",
    "principal_authority",
    "principal_id",
    "project",
    "project_authority",
    "project_id",
    "project_ref",
    "role",
    "role_bindings",
    "roles",
    "tenant",
    "tenant_authority",
    "tenant_id",
}
_PRIVATE_KEYS = {
    "api_key",
    "credential",
    "hidden_reasoning",
    "model_path",
    "provider_endpoint",
    "provider_url",
    "raw_prompt",
    "secret",
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
_CANDIDATE_KEY = re.compile(r"^E[0-9]{1,3}$")
_ENTITY_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")

ContextCandidateStageError = SemanticCandidateStageError
ContextCalibrationPolicy = SemanticCalibrationPolicy
ContextCalibrationRegistry = SemanticCalibrationRegistry


@dataclass(frozen=True)
class ContextCandidateStageResult:
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
    agent_context: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class LiveContextCandidateService:
    client: AeMoGenerationClient = field(repr=False)
    prompt_store: Any = field(repr=False)
    calibration_registry: ContextCalibrationRegistry = field(
        default_factory=ContextCalibrationRegistry,
        repr=False,
    )

    def generate_and_resolve(
        self,
        *,
        work_intent: Mapping[str, Any],
        base_context: Mapping[str, Any],
        tenant_id: str,
        principal_id: str,
        agent_id: str,
        execution_id: str,
        workspace_id: str,
        conversation_id: str,
        interaction_id: str,
        runtime_policy_ref: Mapping[str, Any],
        resolver: TrustedContextResolver,
        request_id: str,
        trace_id: str,
        planning_mode: str,
        context_id: str | None = None,
        context_generation: int = 1,
        built_at: str | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> ContextCandidateStageResult:
        selected_mode = _planning_mode(planning_mode)
        selected_request_id = _bounded_text(request_id, "request_id", 200)
        selected_trace_id = _trace_id_value(trace_id)
        work_intent_projection = _work_intent_projection(
            work_intent,
            execution_id=execution_id,
        )
        normalized_base_context = _base_context(base_context)
        generation_input = {
            "schema_version": CONTEXT_GENERATION_INPUT_SCHEMA_VERSION,
            "work_intent": work_intent_projection,
            "base_context": normalized_base_context,
        }
        input_context_hash = semantic_sha256_hash_ref(generation_input)
        prompt_snapshot = _resolve_prompt_snapshot(
            self.prompt_store,
            user_prompt=canonical_json(generation_input),
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )

        readiness = self.client.check_required_mode_readiness(
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        policy = self.calibration_registry.select(
            semantic_stage="CONTEXT",
            model_profile=readiness.model_profile,
            model_ref=readiness.model_ref,
        )
        if selected_mode == "required" and policy is None:
            raise ContextCandidateStageError(
                503,
                "SEMANTIC_CALIBRATION_REQUIRED",
                "Required CONTEXT mode needs an exact active model calibration policy.",
                retryable=False,
            )

        generation = self.client.generate_candidate(
            semantic_stage="CONTEXT",
            messages=(
                {"role": "system", "content": prompt_snapshot["rendered_prompt"]},
                {"role": "user", "content": canonical_json(generation_input)},
            ),
            request_id=selected_request_id,
            trace_id=selected_trace_id,
        )
        _require_matching_model(readiness, generation)
        candidate = parse_context_candidate_set(generation.output_text)
        candidate_hash = semantic_sha256_hash_ref(candidate)
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
                directive="CONTEXT_REFRESH_REQUIRED",
                failure_code="CANDIDATE_LOW_CONFIDENCE",
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
            )

        hints = context_candidate_hints(candidate, candidate_hash=candidate_hash)
        try:
            agent_context = build_agent_context(
                tenant_id=tenant_id,
                principal_id=principal_id,
                agent_id=agent_id,
                execution_id=execution_id,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                interaction_id=interaction_id,
                work_intent=work_intent,
                runtime_policy_ref=runtime_policy_ref,
                resolver=resolver,
                candidate_hints=hints,
                context_id=context_id,
                context_generation=context_generation,
                built_at=built_at,
                id_factory=id_factory,
            )
        except AgentContextError as exc:
            raise ContextCandidateStageError(
                422,
                "TRUSTED_CONTEXT_RESOLUTION_FAILED",
                exc.detail,
                retryable=exc.retryable,
            ) from exc
        except Exception as exc:
            raise ContextCandidateStageError(
                503,
                "TRUSTED_CONTEXT_RESOLVER_UNAVAILABLE",
                "The trusted context resolver is unavailable.",
                retryable=True,
            ) from exc
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
            agent_context=agent_context,
        )


def parse_context_candidate_set(output_text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            output_text,
            parse_constant=lambda constant: (_raise_json_constant(constant)),
        )
    except (TypeError, ValueError) as exc:
        raise ContextCandidateStageError(
            422,
            "CANDIDATE_JSON_INVALID",
            "CONTEXT provider output is not strict JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise _schema_error("CONTEXT candidate must be a JSON object.")
    _reject_authority_and_private_fields(value)
    if set(value) != _TOP_LEVEL_KEYS:
        raise _schema_error("CONTEXT candidate fields do not match the contract.")
    if value.get("schema_version") != CONTEXT_CANDIDATE_SCHEMA_VERSION:
        raise _schema_error("CONTEXT candidate schema version is unsupported.")
    normalized = {
        "schema_version": CONTEXT_CANDIDATE_SCHEMA_VERSION,
        "entity_candidates": _entity_candidates(value.get("entity_candidates")),
        "retrieval_hints": _retrieval_hints(value.get("retrieval_hints")),
        "resource_selectors": _resource_selectors(value.get("resource_selectors")),
        "parameter_candidates": _parameter_candidates(
            value.get("parameter_candidates")
        ),
        "confidence": _confidence(value.get("confidence"), "confidence"),
    }
    _reject_prompt_injection(normalized)
    return normalized


def context_candidate_hints(
    candidate: Mapping[str, Any], *, candidate_hash: str
) -> ContextCandidateHints:
    normalized = parse_context_candidate_set(canonical_json(candidate))
    try:
        normalized_hash = validate_hash_ref(candidate_hash)
    except ValueError as exc:
        raise _request_error("CONTEXT candidate hash is invalid.") from exc
    if normalized_hash != semantic_sha256_hash_ref(normalized):
        raise _request_error("CONTEXT candidate hash does not match its content.")
    return ContextCandidateHints(
        candidate_hash=normalized_hash,
        entity_candidates=tuple(normalized["entity_candidates"]),
        retrieval_hints=tuple(normalized["retrieval_hints"]),
        resource_selectors=tuple(normalized["resource_selectors"]),
        parameter_candidates=tuple(normalized["parameter_candidates"]),
        confidence=float(normalized["confidence"]),
    )


def _entity_candidates(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "entity_candidates", 32)
    normalized: list[dict[str, Any]] = []
    candidate_keys: set[str] = set()
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _ENTITY_KEYS:
            raise _schema_error("CONTEXT entity candidate fields are invalid.")
        candidate_key = record.get("candidate_key")
        if (
            not isinstance(candidate_key, str)
            or _CANDIDATE_KEY.fullmatch(candidate_key) is None
        ):
            raise _schema_error("CONTEXT entity candidate key is invalid.")
        entity_type = record.get("entity_type")
        if not isinstance(entity_type, str) or _ENTITY_TYPE.fullmatch(entity_type) is None:
            raise _schema_error("CONTEXT entity type is invalid.")
        selector_kind = record.get("selector_kind")
        if selector_kind not in _ENTITY_SELECTOR_KINDS:
            raise _schema_error("CONTEXT entity selector kind is invalid.")
        item = {
            "candidate_key": candidate_key,
            "entity_type": entity_type,
            "selector_kind": selector_kind,
            "selector_value": _candidate_text(
                record.get("selector_value"), "entity selector value", 256
            ),
            "confidence": _confidence(
                record.get("confidence"), "entity confidence"
            ),
        }
        identity = canonical_json(item)
        if candidate_key in candidate_keys or identity in identities:
            raise _schema_error("CONTEXT entity candidates must be unique.")
        candidate_keys.add(candidate_key)
        identities.add(identity)
        normalized.append(item)
    return normalized


def _retrieval_hints(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "retrieval_hints", 16)
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _RETRIEVAL_KEYS:
            raise _schema_error("CONTEXT retrieval hint fields are invalid.")
        query_terms = _text_list(
            record.get("query_terms"),
            "retrieval query terms",
            maximum=16,
            text_maximum=120,
            require_one=True,
        )
        resource_types = _enum_list(
            record.get("resource_types"),
            "retrieval resource types",
            allowed=_RESOURCE_TYPES,
            maximum=8,
            require_one=True,
        )
        item = {
            "query_terms": query_terms,
            "resource_types": resource_types,
            "confidence": _confidence(
                record.get("confidence"), "retrieval confidence"
            ),
        }
        identity = canonical_json(item)
        if identity in identities:
            raise _schema_error("CONTEXT retrieval hints must be unique.")
        identities.add(identity)
        normalized.append(item)
    return normalized


def _resource_selectors(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "resource_selectors", 32)
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _RESOURCE_SELECTOR_KEYS:
            raise _schema_error("CONTEXT resource selector fields are invalid.")
        resource_type = record.get("resource_type")
        if resource_type not in _RESOURCE_TYPES:
            raise _schema_error("CONTEXT resource type is invalid.")
        selector_kind = record.get("selector_kind")
        if selector_kind not in _RESOURCE_SELECTOR_KINDS:
            raise _schema_error("CONTEXT resource selector kind is invalid.")
        item = {
            "resource_type": resource_type,
            "selector_kind": selector_kind,
            "selector_value": _candidate_text(
                record.get("selector_value"), "resource selector value", 256
            ),
            "confidence": _confidence(
                record.get("confidence"), "resource selector confidence"
            ),
        }
        identity = canonical_json(item)
        if identity in identities:
            raise _schema_error("CONTEXT resource selectors must be unique.")
        identities.add(identity)
        normalized.append(item)
    return normalized


def _parameter_candidates(value: object) -> list[dict[str, Any]]:
    records = _bounded_list(value, "parameter_candidates", 32)
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _PARAMETER_KEYS:
            raise _schema_error("CONTEXT parameter candidate fields are invalid.")
        name = record.get("name")
        if not isinstance(name, str) or _PARAMETER_NAME.fullmatch(name) is None:
            raise _schema_error("CONTEXT parameter candidate name is invalid.")
        candidate_value = record.get("value")
        if isinstance(candidate_value, str):
            if len(candidate_value) > 500:
                raise _bounds_error("CONTEXT parameter value exceeds its bound.")
        elif isinstance(candidate_value, bool) or candidate_value is None:
            pass
        elif isinstance(candidate_value, (int, float)):
            if not math.isfinite(float(candidate_value)):
                raise _schema_error("CONTEXT parameter value must be finite.")
        else:
            raise _schema_error("CONTEXT parameter value type is invalid.")
        item = {
            "name": name,
            "value": candidate_value,
            "confidence": _confidence(
                record.get("confidence"), "parameter confidence"
            ),
        }
        identity = canonical_json(item)
        if name in names or identity in identities:
            raise _schema_error("CONTEXT parameter candidates must be unique.")
        names.add(name)
        identities.add(identity)
        normalized.append(item)
    return normalized


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
    agent_context: Mapping[str, Any] | None = None,
) -> ContextCandidateStageResult:
    return ContextCandidateStageResult(
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
        agent_context=(dict(agent_context) if agent_context is not None else None),
    )


def _work_intent_projection(
    value: Mapping[str, Any],
    *,
    execution_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.1":
        raise _request_error("work_intent must use schema version 1.1.")
    if value.get("execution_id") != execution_id:
        raise _request_error("work_intent execution does not match the CONTEXT stage.")
    try:
        intent_hash = validate_hash_ref(value.get("intent_hash"))
    except ValueError as exc:
        raise _request_error("work_intent hash is invalid.") from exc
    mode = value.get("compatibility_execution_mode")
    if mode not in _EXECUTION_MODES:
        raise _request_error("work_intent execution mode is unsupported.")
    return {
        "intent_hash": intent_hash,
        "intent_label": _bounded_text(value.get("intent_label"), "intent_label", 160),
        "execution_mode": mode,
        "goal": _bounded_text(value.get("goal"), "goal", 500),
        "work_class": _bounded_text(value.get("work_class"), "work_class", 64),
        "retrieval_required": mode != "GENERAL_ANSWER",
    }


def _base_context(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _BASE_CONTEXT_KEYS:
        raise _request_error("base_context fields do not match the CONTEXT contract.")
    summary = value.get("conversation_summary")
    if summary is not None:
        summary = _bounded_text(summary, "conversation_summary", 16_384)
    labels = _text_list(
        value.get("resource_label_hints"),
        "resource label hints",
        maximum=32,
        text_maximum=256,
        require_one=False,
        request_scope=True,
    )
    return {
        "interaction_text": _bounded_text(
            value.get("interaction_text"), "interaction_text", 65_536
        ),
        "conversation_summary": summary,
        "resource_label_hints": labels,
    }


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
            binding_key=AE_CONTEXT_CANDIDATE_BINDING,
            variables={},
            request_id=request_id,
            trace_id=trace_id,
            user_prompt=user_prompt,
        )
        event = rendered["render_event"]
        version = store.get_template_version(event["prompt_template_version_id"])
    except (AttributeError, KeyError, PromptRegistryError) as exc:
        raise ContextCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The exact CONTEXT prompt binding is not ready.",
        ) from exc
    if not isinstance(version, dict) or version.get("status") != "ACTIVE":
        raise ContextCandidateStageError(
            503,
            "PROVIDER_NOT_READY",
            "The captured CONTEXT prompt version is not active.",
        )
    if (
        event.get("binding_key") != AE_CONTEXT_CANDIDATE_BINDING
        or event.get("purpose") != "context_candidate_extraction"
        or version.get("purpose") != "context_candidate_extraction"
        or version.get("role") != "system"
        or version.get("model_capability") != "generation"
    ):
        raise _schema_error("The captured CONTEXT prompt binding is incompatible.")
    try:
        content_sha256 = validate_sha256_digest(version.get("content_sha256"))
        rendered_hash = validate_sha256_digest(event.get("rendered_prompt_hash"))
    except ValueError as exc:
        raise _schema_error(
            "The captured CONTEXT prompt provenance digest is invalid."
        ) from exc
    return {
        "rendered_prompt": _bounded_text(
            rendered.get("rendered_prompt"), "rendered_prompt", 16_384
        ),
        "provenance": {
            "prompt_binding_id": _bounded_text(
                event.get("prompt_binding_id"), "prompt_binding_id", 64
            ),
            "prompt_binding_key": AE_CONTEXT_CANDIDATE_BINDING,
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
        raise ContextCandidateStageError(
            502,
            "PROVIDER_RESPONSE_INVALID",
            "MO generation lineage changed after CONTEXT readiness selection.",
        )


def _text_list(
    value: object,
    field_name: str,
    *,
    maximum: int,
    text_maximum: int,
    require_one: bool,
    request_scope: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        error = _request_error if request_scope else _schema_error
        raise error(f"{field_name} must be an array.")
    if (require_one and not value) or len(value) > maximum:
        error = _request_error if request_scope else _bounds_error
        raise error(f"{field_name} item count is invalid.")
    normalized: list[str] = []
    for item in value:
        try:
            normalized.append(_candidate_text(item, field_name, text_maximum))
        except ContextCandidateStageError as exc:
            if request_scope:
                raise _request_error(exc.detail) from exc
            raise
    if len(set(normalized)) != len(normalized):
        error = _request_error if request_scope else _schema_error
        raise error(f"{field_name} must be unique.")
    return normalized


def _enum_list(
    value: object,
    field_name: str,
    *,
    allowed: set[str],
    maximum: int,
    require_one: bool,
) -> list[str]:
    records = _bounded_list(value, field_name, maximum)
    if require_one and not records:
        raise _schema_error(f"CONTEXT {field_name} must not be empty.")
    if any(item not in allowed for item in records) or len(set(records)) != len(records):
        raise _schema_error(f"CONTEXT {field_name} is invalid.")
    return list(records)


def _bounded_list(value: object, field_name: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise _schema_error(f"CONTEXT {field_name} must be an array.")
    if len(value) > maximum:
        raise _bounds_error(f"CONTEXT {field_name} exceeds its bound.")
    return value


def _confidence(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise _schema_error(f"CONTEXT {field_name} must be between zero and one.")
    return float(value)


def _reject_authority_and_private_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _AUTHORITY_KEYS:
                raise ContextCandidateStageError(
                    422,
                    "CANDIDATE_AUTHORITY_VIOLATION",
                    "CONTEXT candidate contains an authority-bearing field.",
                )
            if normalized in _PRIVATE_KEYS:
                raise ContextCandidateStageError(
                    422,
                    "CANDIDATE_PRIVATE_DATA_VIOLATION",
                    "CONTEXT candidate contains a private configuration field.",
                )
            _reject_authority_and_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_authority_and_private_fields(item)


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
                raise ContextCandidateStageError(
                    422,
                    "PROMPT_INJECTION_OR_POLICY_BLOCK",
                    "CONTEXT candidate contains prompt-control language.",
                )
    for item in values:
        _reject_prompt_injection(item)


def _planning_mode(value: object) -> str:
    if not isinstance(value, str) or value.casefold() not in {"shadow", "required"}:
        raise _request_error("CONTEXT candidate stage requires shadow or required mode.")
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
        raise _schema_error(f"CONTEXT {field_name} must be non-empty text.")
    if len(value) > maximum:
        raise _bounds_error(f"CONTEXT {field_name} exceeds its bound.")
    return value.strip()


def _raise_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _schema_error(detail: str) -> ContextCandidateStageError:
    return ContextCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", detail)


def _bounds_error(detail: str) -> ContextCandidateStageError:
    return ContextCandidateStageError(422, "CANDIDATE_BOUNDS_EXCEEDED", detail)


def _request_error(detail: str) -> ContextCandidateStageError:
    return ContextCandidateStageError(400, "CONTEXT_STAGE_REQUEST_INVALID", detail)
