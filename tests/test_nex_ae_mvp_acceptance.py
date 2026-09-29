from __future__ import annotations

import pytest

from nex_ae_api.mvp_acceptance import (
    AE_MVP_ACCEPTANCE_POLICY_ID,
    AeMvpAcceptancePolicyError,
    acceptance_gate_by_id,
    build_ae_mvp_acceptance_policy,
)


def test_default_policy_freezes_all_blocking_acceptance_gates() -> None:
    policy = build_ae_mvp_acceptance_policy({})

    assert policy["policy_id"] == AE_MVP_ACCEPTANCE_POLICY_ID
    assert policy["acceptance_scope"] == "nex_ae_service_mvp"
    assert policy["coverage"]["statement_min_percent"] == 98.0
    assert policy["coverage"]["branch_min_percent"] == 96.0
    assert policy["regression"]["minimum_passed_tests"] == 8500
    assert policy["evidence"]["max_age_hours"] == 24
    assert policy["databases"]["required_databases"] == [
        "nex_ae_test",
        "nex_cx_test",
    ]
    assert policy["live_providers"]["required_models"] == {
        "embedding": "Qwen3-Embedding-4B",
        "reranking": "Qwen3-Reranker-4B",
        "generation": "Qwen3.5-4B",
    }
    assert policy["browser"]["required_display_state"] == "VERIFIED_RESPONSE"
    assert len(policy["gates"]) == 9
    assert all(gate["severity"] == "BLOCKING" for gate in policy["gates"])
    assert all(gate["skipped_allowed"] is False for gate in policy["gates"])
    assert policy["operations"]["ready_status"] == "READY_FOR_OPERATIONS"


def test_policy_accepts_bounded_environment_overrides() -> None:
    policy = build_ae_mvp_acceptance_policy(
        {
            "NEX_AE_MVP_MIN_STATEMENT_COVERAGE": "99.25",
            "NEX_AE_MVP_MIN_BRANCH_COVERAGE": "97.5",
            "NEX_AE_MVP_EVIDENCE_MAX_AGE_HOURS": "48",
            "NEX_AE_MVP_REQUIRED_REGRESSION_TESTS": "9000",
        }
    )

    assert policy["coverage"]["statement_min_percent"] == 99.25
    assert policy["coverage"]["branch_min_percent"] == 97.5
    assert policy["evidence"]["max_age_hours"] == 48
    assert policy["regression"]["minimum_passed_tests"] == 9000


@pytest.mark.parametrize(
    ("key", "value", "error_code"),
    [
        ("NEX_AE_MVP_MIN_STATEMENT_COVERAGE", "nope", "config_invalid"),
        ("NEX_AE_MVP_MIN_STATEMENT_COVERAGE", "nan", "config_out_of_range"),
        ("NEX_AE_MVP_MIN_STATEMENT_COVERAGE", "94.9", "config_out_of_range"),
        ("NEX_AE_MVP_MIN_BRANCH_COVERAGE", "101", "config_out_of_range"),
        ("NEX_AE_MVP_EVIDENCE_MAX_AGE_HOURS", "0", "config_out_of_range"),
        ("NEX_AE_MVP_EVIDENCE_MAX_AGE_HOURS", "bad", "config_invalid"),
        ("NEX_AE_MVP_REQUIRED_REGRESSION_TESTS", "0", "config_out_of_range"),
        ("NEX_AE_MVP_REQUIRED_REGRESSION_TESTS", "8.5", "config_invalid"),
    ],
)
def test_policy_rejects_invalid_environment_values(
    key: str, value: str, error_code: str
) -> None:
    with pytest.raises(AeMvpAcceptancePolicyError) as exc_info:
        build_ae_mvp_acceptance_policy({key: value})

    assert exc_info.value.error_code.endswith(error_code)
    assert key in str(exc_info.value)


def test_policy_rejects_branch_threshold_above_statement() -> None:
    with pytest.raises(AeMvpAcceptancePolicyError) as exc_info:
        build_ae_mvp_acceptance_policy(
            {
                "NEX_AE_MVP_MIN_STATEMENT_COVERAGE": "96",
                "NEX_AE_MVP_MIN_BRANCH_COVERAGE": "97",
            }
        )

    assert exc_info.value.error_code == (
        "ae.mvp_acceptance.branch_exceeds_statement_threshold"
    )


def test_acceptance_gate_lookup_is_strict() -> None:
    policy = build_ae_mvp_acceptance_policy({})

    gate = acceptance_gate_by_id(policy, " postgres_smoke ")
    assert gate["evidence_source"] == "nex_ae_test+nex_cx_test"

    with pytest.raises(AeMvpAcceptancePolicyError) as missing:
        acceptance_gate_by_id(policy, " ")
    assert missing.value.error_code == "ae.mvp_acceptance.gate_id_required"

    with pytest.raises(AeMvpAcceptancePolicyError) as unknown:
        acceptance_gate_by_id(policy, "not-registered")
    assert unknown.value.error_code == "ae.mvp_acceptance.gate_unknown"

    with pytest.raises(AeMvpAcceptancePolicyError) as malformed:
        acceptance_gate_by_id({"gates": "wrong"}, "postgres_smoke")
    assert malformed.value.error_code == "ae.mvp_acceptance.policy_gates_invalid"


def test_non_mapping_gate_entries_are_ignored() -> None:
    policy = {"gates": [None, {"gate_id": "one", "severity": "BLOCKING"}]}

    assert acceptance_gate_by_id(policy, "one")["severity"] == "BLOCKING"
