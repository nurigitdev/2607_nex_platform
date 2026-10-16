from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nex_runtime.semantic_hashes import canonical_json, sha256_text


INTENT_DECISION_SCHEMA_VERSION = "ae_intent_decision.v1"
CANONICAL_EXECUTION_MODES = (
    "GENERAL_ANSWER",
    "GROUNDED_ANSWER",
    "DOCUMENT_SUMMARY",
    "DOCUMENT_GENERATION",
)

_INTENT_RULES = (
    (
        "document_generation",
        "create_document",
        ("report", "proposal", "memo", "보고서", "제안서", "문서 작성"),
        "DOCUMENT_GENERATION",
        0.88,
    ),
    (
        "document_summary",
        "summarize_document",
        ("summarize", "summary", "brief", "요약", "정리"),
        "DOCUMENT_SUMMARY",
        0.86,
    ),
)


@dataclass(frozen=True)
class IntentPolicyError(Exception):
    status_code: int
    error_code: str
    detail: str


def resolve_intent_decision(payload: Mapping[str, Any]) -> dict[str, Any]:
    user_message = _required_text(payload.get("user_message"), "user_message")
    generation = payload.get("generation", {})
    if not isinstance(generation, Mapping):
        raise IntentPolicyError(
            400,
            "ae.intent_generation_invalid",
            "generation must be an object when supplied.",
        )
    explicit_mode = generation.get("execution_mode")
    if explicit_mode is not None:
        mode = _canonical_mode(explicit_mode)
        intent_label = _intent_label_for_mode(mode)
        task_category = _task_category_for_mode(mode)
        source = "EXPLICIT"
        confidence = 1.0
        matched_rule = None
    else:
        classified = classify_runtime_intent(user_message)
        requested_retrieval = _retrieval_requested(payload)
        mode = classified["execution_mode"]
        if mode == "GENERAL_ANSWER" and requested_retrieval:
            mode = "GROUNDED_ANSWER"
        intent_label = classified["intent_label"]
        task_category = classified["task_category"]
        source = "DETERMINISTIC_FALLBACK"
        confidence = classified["confidence"]
        matched_rule = classified["matched_rule"]

    retrieval_required = mode != "GENERAL_ANSWER"
    template_required = mode == "DOCUMENT_GENERATION"
    decision = {
        "intent_decision_schema_version": INTENT_DECISION_SCHEMA_VERSION,
        "intent_label": intent_label,
        "task_category": task_category,
        "execution_mode": mode,
        "decision_source": source,
        "confidence": confidence,
        "retrieval_required": retrieval_required,
        "template_required": template_required,
        "matched_rule": matched_rule,
        "raw_prompt_included": False,
    }
    decision["decision_hash"] = _decision_hash(decision)
    return decision


def resolve_validated_intent_candidate(
    candidate: Mapping[str, Any],
    *,
    trusted_execution_mode: str | None = None,
    retrieval_enabled: bool = False,
) -> dict[str, Any]:
    candidate_mode = _canonical_mode(candidate.get("suggested_execution_mode"))
    if trusted_execution_mode is not None:
        resolved_mode = _canonical_mode(trusted_execution_mode)
        if candidate_mode != resolved_mode:
            raise IntentPolicyError(
                422,
                "ae.intent_candidate_mode_conflict",
                "IntentCandidate cannot override the trusted execution mode.",
            )
    else:
        resolved_mode = candidate_mode
        if resolved_mode == "GENERAL_ANSWER" and retrieval_enabled:
            resolved_mode = "GROUNDED_ANSWER"

    confidence = candidate.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise IntentPolicyError(
            422,
            "ae.intent_candidate_confidence_invalid",
            "IntentCandidate confidence must be numeric.",
        )
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise IntentPolicyError(
            422,
            "ae.intent_candidate_confidence_invalid",
            "IntentCandidate confidence must be between zero and one.",
        )

    decision = {
        "intent_decision_schema_version": INTENT_DECISION_SCHEMA_VERSION,
        "intent_label": _required_text(candidate.get("intent_label"), "intent_label"),
        "task_category": _task_category_for_mode(resolved_mode),
        "execution_mode": resolved_mode,
        "decision_source": "LLM_CANDIDATE_VALIDATED",
        "confidence": confidence,
        "retrieval_required": resolved_mode != "GENERAL_ANSWER",
        "template_required": resolved_mode == "DOCUMENT_GENERATION",
        "matched_rule": None,
        "raw_prompt_included": False,
    }
    decision["decision_hash"] = _decision_hash(decision)
    return decision


def classify_runtime_intent(user_message: str) -> dict[str, Any]:
    normalized = _required_text(user_message, "user_message").casefold()
    for task_category, intent_label, terms, mode, confidence in _INTENT_RULES:
        if any(term.casefold() in normalized for term in terms):
            return {
                "intent_label": intent_label,
                "task_category": task_category,
                "execution_mode": mode,
                "confidence": confidence,
                "matched_rule": task_category,
            }
    return {
        "intent_label": "general_question",
        "task_category": "knowledge_work",
        "execution_mode": "GENERAL_ANSWER",
        "confidence": 0.55,
        "matched_rule": None,
    }


def _canonical_mode(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntentPolicyError(
            422,
            "ae.execution_mode_invalid",
            "execution_mode must be a non-empty string.",
        )
    mode = value.strip().upper()
    if mode not in CANONICAL_EXECUTION_MODES:
        raise IntentPolicyError(
            422,
            "ae.execution_mode_unsupported",
            f"Unsupported execution_mode: {mode}",
        )
    return mode


def _retrieval_requested(payload: Mapping[str, Any]) -> bool:
    retrieval = payload.get("retrieval")
    if retrieval is None:
        return False
    if not isinstance(retrieval, Mapping):
        raise IntentPolicyError(
            400,
            "ae.intent_retrieval_invalid",
            "retrieval must be an object when supplied.",
        )
    return bool(retrieval.get("enabled", True))


def _intent_label_for_mode(mode: str) -> str:
    return {
        "GENERAL_ANSWER": "general_question",
        "GROUNDED_ANSWER": "grounded_question",
        "DOCUMENT_SUMMARY": "summarize_document",
        "DOCUMENT_GENERATION": "create_document",
    }[mode]


def _task_category_for_mode(mode: str) -> str:
    return {
        "GENERAL_ANSWER": "knowledge_work",
        "GROUNDED_ANSWER": "grounded_knowledge_work",
        "DOCUMENT_SUMMARY": "document_summary",
        "DOCUMENT_GENERATION": "document_generation",
    }[mode]


def _decision_hash(decision: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json(dict(decision)))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntentPolicyError(
            400,
            "ae.intent_request_invalid",
            f"{field_name} must be a non-empty string.",
        )
    return value.strip()
