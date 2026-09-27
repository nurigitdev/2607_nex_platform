from __future__ import annotations

import pytest

from nex_ae_api.runtime_policy import (
    DEFAULT_AE_RUNTIME_POLICY_RULES,
    RuntimePolicyError,
    resolve_runtime_policy,
)


@pytest.mark.parametrize(
    ("payload", "rule_id", "binding"),
    [
        (
            {"user_message": "hello"},
            "ae.general_answer.v1",
            "ae.general_answer.default",
        ),
        (
            {"user_message": "hello", "retrieval": {"enabled": True}},
            "ae.grounded_answer.v1",
            "ae.grounded_chat.default",
        ),
        (
            {"user_message": "이 문서를 요약해줘"},
            "ae.document_summary.v1",
            "ae.document_summary.default",
        ),
        (
            {
                "user_message": "보고서를 작성해줘",
                "generation": {
                    "template_ref": {
                        "template_id": "report",
                        "template_version": "v1",
                    }
                },
            },
            "ae.document_generation.report.v1",
            "ae.document_generation.default",
        ),
    ],
)
def test_resolver_selects_exact_active_policy(
    payload: dict,
    rule_id: str,
    binding: str,
) -> None:
    result = resolve_runtime_policy(payload)

    assert result["compatibility_rule"]["rule_id"] == rule_id
    assert result["prompt_contract_ref"]["prompt_binding_key"] == binding
    assert len(result["compatibility_rule"]["rule_hash"]) == 64
    assert len(result["policy_snapshot_hash"]) == 64
    assert result["raw_prompt_included"] is False
    assert result["provider_runtime_included"] is False
    assert payload["user_message"] not in str(result)


def test_explicit_refs_and_bounded_parameters_are_honored() -> None:
    result = resolve_runtime_policy(
        {
            "user_message": "hello",
            "generation": {
                "execution_mode": "GENERAL_ANSWER",
                "prompt_contract_ref": {
                    "prompt_binding_key": "ae.general_answer.default",
                    "prompt_version": "v1",
                },
                "output_contract": {
                    "output_contract_id": "text_answer_v1",
                    "artifact_intent": "none",
                },
                "parameters": {
                    "max_output_tokens": 768,
                    "temperature": 0.2,
                    "streaming": True,
                    "timeout_ms": 30000,
                },
            },
        }
    )

    assert result["generation_parameters"] == {
        "max_output_tokens": 768,
        "temperature": 0.2,
        "streaming": True,
        "timeout_ms": 30000,
    }


@pytest.mark.parametrize("template_id", ["report", "proposal", "memo"])
def test_document_templates_have_distinct_exact_rules(template_id: str) -> None:
    result = resolve_runtime_policy(
        {
            "user_message": "create document",
            "generation": {
                "execution_mode": "DOCUMENT_GENERATION",
                "template_id": template_id,
                "template_version": "v1",
            },
        }
    )

    assert result["template_ref"]["template_id"] == template_id
    assert result["output_contract"]["artifact_intent"] == "create_artifact"


@pytest.mark.parametrize(
    ("generation", "error_code"),
    [
        ({"provider_url": "http://private"}, "ae.provider_runtime_field_forbidden"),
        (
            {"execution_mode": "DOCUMENT_GENERATION"},
            "ae.template_required",
        ),
        (
            {"template_ref": []},
            "ae.template_ref_invalid",
        ),
        (
            {"prompt_contract_ref": []},
            "ae.runtime_policy_ref_invalid",
        ),
        (
            {"prompt_version": "latest"},
            "ae.runtime_policy_implicit_latest_forbidden",
        ),
        (
            {"prompt_version": 3},
            "ae.runtime_policy_value_invalid",
        ),
        (
            {"parameters": []},
            "ae.generation_parameters_invalid",
        ),
        (
            {"parameters": {"top_p": 0.9}},
            "ae.generation_parameter_unknown",
        ),
        (
            {"parameters": {"max_output_tokens": 1}},
            "ae.generation_parameter_out_of_bounds",
        ),
        (
            {"parameters": {"temperature": True}},
            "ae.generation_parameter_out_of_bounds",
        ),
        (
            {"parameters": {"streaming": "yes"}},
            "ae.generation_parameter_out_of_bounds",
        ),
        (
            {"parameters": {"timeout_ms": 10}},
            "ae.generation_parameter_out_of_bounds",
        ),
    ],
)
def test_policy_rejects_unsafe_or_invalid_generation(
    generation: dict,
    error_code: str,
) -> None:
    with pytest.raises(RuntimePolicyError) as raised:
        resolve_runtime_policy(
            {
                "user_message": "hello",
                "generation": generation,
            }
        )

    assert raised.value.error_code == error_code


def test_policy_rejects_missing_inactive_and_ambiguous_rules() -> None:
    with pytest.raises(RuntimePolicyError) as missing:
        resolve_runtime_policy(
            {"user_message": "hello"},
            rules=(),
        )
    assert missing.value.error_code == "ae.runtime_policy_not_found"

    inactive = {**DEFAULT_AE_RUNTIME_POLICY_RULES[0], "status": "INACTIVE"}
    with pytest.raises(RuntimePolicyError) as inactive_result:
        resolve_runtime_policy({"user_message": "hello"}, rules=(inactive,))
    assert inactive_result.value.error_code == "ae.runtime_policy_not_found"

    duplicate = dict(DEFAULT_AE_RUNTIME_POLICY_RULES[0])
    with pytest.raises(RuntimePolicyError) as ambiguous:
        resolve_runtime_policy(
            {"user_message": "hello"},
            rules=(DEFAULT_AE_RUNTIME_POLICY_RULES[0], duplicate),
        )
    assert ambiguous.value.error_code == "ae.runtime_policy_ambiguous"


def test_generation_must_be_an_object() -> None:
    with pytest.raises(RuntimePolicyError) as raised:
        resolve_runtime_policy({"user_message": "hello", "generation": []})
    assert raised.value.error_code == "ae.runtime_policy_generation_invalid"
