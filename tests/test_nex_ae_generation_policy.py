from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ae_api.generation_policy import (
    GenerationPolicyPackageError,
    build_generation_policy_package,
)
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE
from nex_ae_api.runtime_policy import resolve_runtime_policy
from nex_ae_api.runtime_policy_api import resolve_safe_prompt_binding


def resolved(payload: dict) -> tuple[dict, dict]:
    policy = resolve_runtime_policy(payload)
    binding = resolve_safe_prompt_binding(
        DEFAULT_AE_PROMPT_STORE,
        binding_key=policy["prompt_contract_ref"]["prompt_binding_key"],
        prompt_version=policy["prompt_contract_ref"]["prompt_version"],
    )
    return policy, binding


def retrieval_package(*, status: str = "READY") -> dict:
    return {
        "retrieval_package_id": "retrieval-1027",
        "package_hash": "b" * 64,
        "status": status,
        "evidence_items": [
            {"evidence_id": "evidence-1", "text": "private evidence one"},
            {"evidence_id": "evidence-2", "text": "private evidence two"},
        ],
    }


def test_general_policy_package_is_deterministic_and_private() -> None:
    source = {
        "user_message": "private user strategy",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
    }
    policy, binding = resolved(source)

    first = build_generation_policy_package(
        source,
        runtime_policy=policy,
        prompt_binding=binding,
    )
    second = build_generation_policy_package(
        source,
        runtime_policy=policy,
        prompt_binding=binding,
    )

    assert first == second
    assert first["execution_mode"] == "GENERAL_ANSWER"
    assert first["retrieval_package_ref"] is None
    assert first["selected_evidence_ids"] == []
    assert len(first["client_package_hash"]) == 64
    assert first["ownership_ref"]["tenant_ref"]["id"] == "tenant-a"
    assert first["privacy"] == {
        "raw_user_prompt_included": False,
        "raw_evidence_included": False,
        "provider_runtime_included": False,
        "raw_token_included": False,
    }
    assert "private user strategy" not in str(first)


def test_grounded_policy_references_selected_evidence_without_raw_text() -> None:
    source = {
        "user_message": "answer from sources",
        "retrieval": {"enabled": True},
        "selected_evidence_ids": ["evidence-2"],
    }
    policy, binding = resolved(source)

    package = build_generation_policy_package(
        source,
        runtime_policy=policy,
        prompt_binding=binding,
        retrieval_package=retrieval_package(),
    )

    assert package["execution_mode"] == "GROUNDED_ANSWER"
    assert package["retrieval_package_ref"] == {
        "retrieval_package_id": "retrieval-1027",
        "package_hash": "b" * 64,
        "status": "READY",
    }
    assert package["selected_evidence_ids"] == ["evidence-2"]
    assert "private evidence" not in str(package)
    assert "content" not in package["prompt_contract_ref"]


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (
            lambda policy, binding: policy.update(runtime_policy_schema_version="bad"),
            "ae.generation_policy_runtime_invalid",
        ),
        (
            lambda policy, binding: policy.update(raw_prompt_included=True),
            "ae.generation_policy_raw_prompt_forbidden",
        ),
        (
            lambda policy, binding: policy.update(provider_runtime_included=True),
            "ae.generation_policy_provider_runtime_forbidden",
        ),
        (
            lambda policy, binding: binding.update(content="private prompt"),
            "ae.generation_policy_prompt_content_forbidden",
        ),
        (
            lambda policy, binding: binding.update(binding_key="other"),
            "ae.generation_policy_prompt_mismatch",
        ),
        (
            lambda policy, binding: binding.update(prompt_binding_id=""),
            "ae.generation_policy_value_invalid",
        ),
        (
            lambda policy, binding: binding.update(content_sha256="bad"),
            "ae.generation_policy_hash_invalid",
        ),
    ],
)
def test_policy_package_rejects_unsafe_runtime_or_binding(
    mutate,
    error_code: str,
) -> None:
    source = {"user_message": "hello"}
    policy, binding = resolved(source)
    policy = deepcopy(policy)
    binding = deepcopy(binding)
    mutate(policy, binding)

    with pytest.raises(GenerationPolicyPackageError) as raised:
        build_generation_policy_package(
            source,
            runtime_policy=policy,
            prompt_binding=binding,
        )

    assert raised.value.error_code == error_code


@pytest.mark.parametrize(
    ("source_change", "retrieval", "error_code"),
    [
        ({}, None, "ae.generation_policy_retrieval_required"),
        ({}, [], "ae.generation_policy_retrieval_invalid"),
        ({}, retrieval_package(status="NO_ANSWER"), "ae.generation_policy_retrieval_not_admitted"),
        ({}, {**retrieval_package(), "evidence_items": "bad"}, "ae.generation_policy_evidence_invalid"),
        (
            {},
            {**retrieval_package(), "evidence_items": [{"evidence_id": "same"}, {"evidence_id": "same"}]},
            "ae.generation_policy_evidence_invalid",
        ),
        (
            {"selected_evidence_ids": "bad"},
            retrieval_package(),
            "ae.generation_policy_evidence_selection_invalid",
        ),
        (
            {"selected_evidence_ids": ["missing"]},
            retrieval_package(),
            "ae.generation_policy_evidence_selection_invalid",
        ),
        (
            {"selected_evidence_ids": ["evidence-1", "evidence-1"]},
            retrieval_package(),
            "ae.generation_policy_evidence_selection_invalid",
        ),
    ],
)
def test_grounded_retrieval_policy_fails_closed(
    source_change: dict,
    retrieval,
    error_code: str,
) -> None:
    source = {
        "user_message": "ground this",
        "retrieval": {"enabled": True},
        **source_change,
    }
    policy, binding = resolved(source)

    with pytest.raises(GenerationPolicyPackageError) as raised:
        build_generation_policy_package(
            source,
            runtime_policy=policy,
            prompt_binding=binding,
            retrieval_package=retrieval,
        )

    assert raised.value.error_code == error_code


def test_general_policy_rejects_retrieval_and_provider_runtime_fields() -> None:
    source = {"user_message": "hello"}
    policy, binding = resolved(source)
    with pytest.raises(GenerationPolicyPackageError) as retrieval_error:
        build_generation_policy_package(
            source,
            runtime_policy=policy,
            prompt_binding=binding,
            retrieval_package=retrieval_package(),
        )
    assert retrieval_error.value.error_code == "ae.generation_policy_retrieval_not_allowed"

    with pytest.raises(GenerationPolicyPackageError) as provider_error:
        build_generation_policy_package(
            {**source, "generation": {"api_key": "secret"}},
            runtime_policy=policy,
            prompt_binding=binding,
        )
    assert provider_error.value.error_code == (
        "ae.generation_policy_provider_runtime_forbidden"
    )


def test_generation_and_policy_shape_validation_is_fail_closed() -> None:
    source = {"user_message": "hello"}
    policy, binding = resolved(source)
    invalid_cases = [
        ({**source, "generation": []}, policy, "ae.generation_policy_generation_invalid"),
        (source, {**policy, "template_ref": []}, "ae.generation_policy_runtime_invalid"),
        (source, {**policy, "generation_profile": ""}, "ae.generation_policy_value_invalid"),
    ]
    for candidate_source, candidate_policy, error_code in invalid_cases:
        with pytest.raises(GenerationPolicyPackageError) as raised:
            build_generation_policy_package(
                candidate_source,
                runtime_policy=candidate_policy,
                prompt_binding=binding,
            )
        assert raised.value.error_code == error_code


def test_package_hash_changes_with_owner_and_defaults_to_all_evidence() -> None:
    source = {"user_message": "ground this", "retrieval": {"enabled": True}}
    policy, binding = resolved(source)
    first = build_generation_policy_package(
        source,
        runtime_policy=policy,
        prompt_binding=binding,
        retrieval_package=retrieval_package(),
    )
    second = build_generation_policy_package(
        {**source, "tenant_id": "other"},
        runtime_policy=policy,
        prompt_binding=binding,
        retrieval_package=retrieval_package(),
    )

    assert first["selected_evidence_ids"] == ["evidence-1", "evidence-2"]
    assert first["client_package_hash"] != second["client_package_hash"]
