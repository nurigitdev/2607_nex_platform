from __future__ import annotations

import pytest

from nex_ag.mvp_acceptance import (
    AgMvpAcceptancePolicyError,
    acceptance_gate_by_id,
    build_ag_mvp_acceptance_policy,
)


def test_default_policy_freezes_strict_blocking_acceptance() -> None:
    policy = build_ag_mvp_acceptance_policy({})

    assert policy["policy_id"] == "ag-mvp-acceptance-v1"
    assert policy["acceptance_scope"] == "nex_ag_service_mvp"
    assert policy["transition_target"] == "nex-cx"
    assert policy["coverage"] == {
        "statement_min_percent": 98.0,
        "branch_min_percent": 96.0,
        "project_floor_statement_percent": 95.0,
        "project_floor_branch_percent": 85.0,
    }
    assert policy["regression"]["minimum_passed_tests"] == 6000
    assert policy["database"]["required_database"] == "nex_ag_test"
    assert policy["database"]["skipped_when_required_is_pass"] is False
    assert len(policy["gates"]) == 8
    assert all(gate["severity"] == "BLOCKING" for gate in policy["gates"])
    assert all(gate["skipped_allowed"] is False for gate in policy["gates"])


def test_policy_accepts_bounded_configuration() -> None:
    policy = build_ag_mvp_acceptance_policy(
        {
            "NEX_AG_MVP_MIN_STATEMENT_COVERAGE": "99.25",
            "NEX_AG_MVP_MIN_BRANCH_COVERAGE": "97.5",
            "NEX_AG_MVP_EVIDENCE_MAX_AGE_HOURS": "48",
            "NEX_AG_MVP_REQUIRED_REGRESSION_TESTS": "6100",
        }
    )

    assert policy["coverage"]["statement_min_percent"] == 99.25
    assert policy["coverage"]["branch_min_percent"] == 97.5
    assert policy["evidence"]["max_age_hours"] == 48
    assert policy["regression"]["minimum_passed_tests"] == 6100


@pytest.mark.parametrize(
    ("key", "value", "error_code"),
    [
        (
            "NEX_AG_MVP_MIN_STATEMENT_COVERAGE",
            "not-a-number",
            "ag.mvp_acceptance.config_invalid",
        ),
        (
            "NEX_AG_MVP_MIN_STATEMENT_COVERAGE",
            "94.99",
            "ag.mvp_acceptance.config_out_of_range",
        ),
        (
            "NEX_AG_MVP_MIN_BRANCH_COVERAGE",
            "nan",
            "ag.mvp_acceptance.config_out_of_range",
        ),
        (
            "NEX_AG_MVP_EVIDENCE_MAX_AGE_HOURS",
            "0",
            "ag.mvp_acceptance.config_out_of_range",
        ),
        (
            "NEX_AG_MVP_EVIDENCE_MAX_AGE_HOURS",
            "bad",
            "ag.mvp_acceptance.config_invalid",
        ),
        (
            "NEX_AG_MVP_REQUIRED_REGRESSION_TESTS",
            "1000001",
            "ag.mvp_acceptance.config_out_of_range",
        ),
    ],
)
def test_policy_rejects_invalid_configuration(
    key: str, value: str, error_code: str
) -> None:
    with pytest.raises(AgMvpAcceptancePolicyError) as exc_info:
        build_ag_mvp_acceptance_policy({key: value})

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_policy_rejects_branch_threshold_above_statement() -> None:
    with pytest.raises(AgMvpAcceptancePolicyError) as exc_info:
        build_ag_mvp_acceptance_policy(
            {
                "NEX_AG_MVP_MIN_STATEMENT_COVERAGE": "96",
                "NEX_AG_MVP_MIN_BRANCH_COVERAGE": "97",
            }
        )

    assert exc_info.value.error_code == (
        "ag.mvp_acceptance.branch_exceeds_statement_threshold"
    )


def test_gate_lookup_returns_registered_gate() -> None:
    policy = build_ag_mvp_acceptance_policy({})

    gate = acceptance_gate_by_id(policy, " postgres_smoke ")

    assert gate == {
        "gate_id": "postgres_smoke",
        "severity": "BLOCKING",
        "required_status": "PASS",
        "skipped_allowed": False,
        "evidence_source": "nex_ag_test",
    }


@pytest.mark.parametrize("gate_id", ["", "   ", None])
def test_gate_lookup_requires_non_empty_id(gate_id: str | None) -> None:
    with pytest.raises(AgMvpAcceptancePolicyError) as exc_info:
        acceptance_gate_by_id(build_ag_mvp_acceptance_policy({}), gate_id)  # type: ignore[arg-type]

    assert exc_info.value.error_code == "ag.mvp_acceptance.gate_id_required"


def test_gate_lookup_rejects_invalid_policy_and_unknown_gate() -> None:
    with pytest.raises(AgMvpAcceptancePolicyError) as invalid:
        acceptance_gate_by_id({}, "postgres_smoke")
    with pytest.raises(AgMvpAcceptancePolicyError) as unknown:
        acceptance_gate_by_id(build_ag_mvp_acceptance_policy({}), "unknown")

    assert invalid.value.error_code == "ag.mvp_acceptance.policy_gates_invalid"
    assert unknown.value.error_code == "ag.mvp_acceptance.gate_unknown"
