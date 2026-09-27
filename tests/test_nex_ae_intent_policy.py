from __future__ import annotations

import pytest

from nex_ae_api.intent_policy import (
    CANONICAL_EXECUTION_MODES,
    INTENT_DECISION_SCHEMA_VERSION,
    IntentPolicyError,
    classify_runtime_intent,
    resolve_intent_decision,
)


@pytest.mark.parametrize("mode", CANONICAL_EXECUTION_MODES)
def test_explicit_execution_mode_is_authoritative(mode: str) -> None:
    result = resolve_intent_decision(
        {
            "user_message": "Summarize this even though the explicit mode wins.",
            "generation": {"execution_mode": mode.lower()},
            "retrieval": {"enabled": mode == "GENERAL_ANSWER"},
        }
    )

    assert result["intent_decision_schema_version"] == INTENT_DECISION_SCHEMA_VERSION
    assert result["execution_mode"] == mode
    assert result["decision_source"] == "EXPLICIT"
    assert result["confidence"] == 1.0
    assert result["retrieval_required"] is (mode != "GENERAL_ANSWER")
    assert result["template_required"] is (mode == "DOCUMENT_GENERATION")
    assert len(result["decision_hash"]) == 64
    assert result["raw_prompt_included"] is False
    assert "Summarize this" not in str(result)


@pytest.mark.parametrize(
    ("message", "mode", "rule"),
    [
        ("분기 보고서를 작성해줘", "DOCUMENT_GENERATION", "document_generation"),
        ("Please draft a proposal", "DOCUMENT_GENERATION", "document_generation"),
        ("이 문서를 요약해줘", "DOCUMENT_SUMMARY", "document_summary"),
        ("Give me a brief summary", "DOCUMENT_SUMMARY", "document_summary"),
        ("How are you?", "GENERAL_ANSWER", None),
    ],
)
def test_deterministic_intent_rules(message: str, mode: str, rule: str | None) -> None:
    result = classify_runtime_intent(message)

    assert result["execution_mode"] == mode
    assert result["matched_rule"] == rule


def test_retrieval_request_promotes_general_question_to_grounded_answer() -> None:
    result = resolve_intent_decision(
        {"user_message": "What changed?", "retrieval": {"enabled": True}}
    )

    assert result["execution_mode"] == "GROUNDED_ANSWER"
    assert result["decision_source"] == "DETERMINISTIC_FALLBACK"
    assert result["intent_label"] == "general_question"
    assert result["retrieval_required"] is True


def test_disabled_retrieval_keeps_general_answer() -> None:
    result = resolve_intent_decision(
        {"user_message": "What changed?", "retrieval": {"enabled": False}}
    )

    assert result["execution_mode"] == "GENERAL_ANSWER"
    assert result["retrieval_required"] is False


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({}, "ae.intent_request_invalid"),
        ({"user_message": " "}, "ae.intent_request_invalid"),
        ({"user_message": "hello", "generation": []}, "ae.intent_generation_invalid"),
        (
            {"user_message": "hello", "generation": {"execution_mode": 1}},
            "ae.execution_mode_invalid",
        ),
        (
            {"user_message": "hello", "generation": {"execution_mode": "unsafe"}},
            "ae.execution_mode_unsupported",
        ),
        ({"user_message": "hello", "retrieval": []}, "ae.intent_retrieval_invalid"),
    ],
)
def test_invalid_requests_fail_closed(payload: dict, error_code: str) -> None:
    with pytest.raises(IntentPolicyError) as raised:
        resolve_intent_decision(payload)

    assert raised.value.error_code == error_code


def test_decision_hash_is_deterministic_and_changes_with_mode() -> None:
    payload = {"user_message": "What changed?"}
    first = resolve_intent_decision(payload)
    second = resolve_intent_decision(payload)
    explicit = resolve_intent_decision(
        {
            **payload,
            "generation": {"execution_mode": "GROUNDED_ANSWER"},
        }
    )

    assert first["decision_hash"] == second["decision_hash"]
    assert first["decision_hash"] != explicit["decision_hash"]
