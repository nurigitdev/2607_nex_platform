from __future__ import annotations

import math

import pytest

from nex_mo.mvp_acceptance import (
    MO_MVP_ACCEPTANCE_POLICY_ID,
    MoMvpAcceptancePolicyError,
    acceptance_gate_by_id,
    build_mo_mvp_acceptance_policy,
)


def test_default_policy_freezes_nine_blocking_gates() -> None:
    policy = build_mo_mvp_acceptance_policy({})

    assert policy["policy_id"] == MO_MVP_ACCEPTANCE_POLICY_ID
    assert policy["service_id"] == "nex-mo"
    assert policy["transition_target"] == "nex-oa"
    assert len(policy["gates"]) == 9
    assert {gate["severity"] for gate in policy["gates"]} == {"BLOCKING"}
    assert all(not gate["skipped_allowed"] for gate in policy["gates"])
    assert policy["coverage"]["statement_min_percent"] == 98.0
    assert policy["coverage"]["branch_min_percent"] == 96.0
    assert policy["regression"]["minimum_passed_tests"] == 9000
    assert policy["database"]["required_database"] == "nex_mo_test"


def test_policy_accepts_bounded_operator_overrides() -> None:
    policy = build_mo_mvp_acceptance_policy(
        {
            "NEX_MO_MVP_MIN_STATEMENT_COVERAGE": "99.5",
            "NEX_MO_MVP_MIN_BRANCH_COVERAGE": "97.5",
            "NEX_MO_MVP_EVIDENCE_MAX_AGE_HOURS": "12",
            "NEX_MO_MVP_REQUIRED_REGRESSION_TESTS": "9500",
        }
    )

    assert policy["coverage"]["statement_min_percent"] == 99.5
    assert policy["coverage"]["branch_min_percent"] == 97.5
    assert policy["evidence"]["max_age_hours"] == 12
    assert policy["regression"]["minimum_passed_tests"] == 9500


@pytest.mark.parametrize(
    ("key", "value", "error_code"),
    [
        (
            "NEX_MO_MVP_MIN_STATEMENT_COVERAGE",
            "94.9",
            "mo.mvp_acceptance.config_out_of_range",
        ),
        (
            "NEX_MO_MVP_MIN_BRANCH_COVERAGE",
            "not-a-number",
            "mo.mvp_acceptance.config_invalid",
        ),
        (
            "NEX_MO_MVP_EVIDENCE_MAX_AGE_HOURS",
            "0",
            "mo.mvp_acceptance.config_out_of_range",
        ),
        (
            "NEX_MO_MVP_REQUIRED_REGRESSION_TESTS",
            "many",
            "mo.mvp_acceptance.config_invalid",
        ),
    ],
)
def test_policy_rejects_invalid_or_weakened_overrides(
    key: str, value: str, error_code: str
) -> None:
    with pytest.raises(MoMvpAcceptancePolicyError) as exc_info:
        build_mo_mvp_acceptance_policy({key: value})

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_policy_rejects_non_finite_and_inverted_coverage() -> None:
    with pytest.raises(MoMvpAcceptancePolicyError):
        build_mo_mvp_acceptance_policy(
            {"NEX_MO_MVP_MIN_STATEMENT_COVERAGE": str(math.inf)}
        )
    with pytest.raises(MoMvpAcceptancePolicyError) as exc_info:
        build_mo_mvp_acceptance_policy(
            {
                "NEX_MO_MVP_MIN_STATEMENT_COVERAGE": "96",
                "NEX_MO_MVP_MIN_BRANCH_COVERAGE": "97",
            }
        )
    assert exc_info.value.error_code == (
        "mo.mvp_acceptance.branch_exceeds_statement_threshold"
    )


def test_gate_lookup_returns_registered_gate() -> None:
    policy = build_mo_mvp_acceptance_policy({})

    gate = acceptance_gate_by_id(policy, " postgres_smoke ")

    assert gate["gate_id"] == "postgres_smoke"
    assert gate["evidence_source"] == "nex_mo_test"


def test_gate_lookup_fails_closed_for_invalid_inputs() -> None:
    with pytest.raises(MoMvpAcceptancePolicyError) as required:
        acceptance_gate_by_id({}, "")
    assert required.value.error_code == "mo.mvp_acceptance.gate_id_required"

    with pytest.raises(MoMvpAcceptancePolicyError) as invalid:
        acceptance_gate_by_id({}, "postgres_smoke")
    assert invalid.value.error_code == "mo.mvp_acceptance.policy_gates_invalid"

    with pytest.raises(MoMvpAcceptancePolicyError) as unknown:
        acceptance_gate_by_id(build_mo_mvp_acceptance_policy({}), "unknown")
    assert unknown.value.error_code == "mo.mvp_acceptance.gate_unknown"
