from __future__ import annotations

import pytest

from nex_ag.mvp_acceptance import (
    AgMvpEvidenceSpec,
    AgMvpAcceptancePolicyError,
    acceptance_gate_by_id,
    ag_mvp_evidence_specs,
    build_ag_mvp_evidence_inventory,
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


def test_repository_evidence_inventory_is_complete_and_unique() -> None:
    inventory = build_ag_mvp_evidence_inventory()

    assert inventory["status"] == "PASS"
    assert all(inventory["checks"].values())
    assert inventory["issues"] == []
    assert inventory["scope"] == {
        "first_requirement": "S34",
        "last_requirement": "S89",
        "included_requirement_count": 33,
        "ae_only_s39_s62_included": False,
    }
    assert len(inventory["entries"]) == 33
    assert all(item["status"] == "READY" for item in inventory["entries"])


def test_evidence_specs_keep_intended_capability_groups() -> None:
    specs = ag_mvp_evidence_specs()
    by_requirement = {spec.requirement: spec for spec in specs}

    assert len(specs) == 33
    assert by_requirement["S34"].capability_group == "shared_generation_quality"
    assert by_requirement["S53"].capability_group == "ag_operations_foundation"
    assert by_requirement["S63"].capability_group == "ag_operator_governance"
    assert by_requirement["S71"].closure_slice == "0711"
    assert by_requirement["S82"].capability_group == "ag_mvp_hardening"
    assert by_requirement["S89"].closure_slice == "0890"
    assert "S39" not in by_requirement


def test_inventory_reports_missing_runner_and_document(tmp_path) -> None:
    inventory = build_ag_mvp_evidence_inventory(tmp_path)

    assert inventory["status"] == "FAIL"
    assert inventory["checks"]["closure_runners_present"] is False
    assert inventory["checks"]["closure_docs_present"] is False
    assert inventory["entries"][0]["closure_runner"] is None
    assert inventory["entries"][0]["closure_document"] is None
    assert {issue["category"] for issue in inventory["issues"]} == {
        "closure_runner_count_invalid",
        "closure_document_count_invalid",
    }


def test_inventory_reports_ambiguous_paths(tmp_path, monkeypatch) -> None:
    runner_dir = tmp_path / "scripts/smoke"
    document_dir = tmp_path / "docs/slices"
    runner_dir.mkdir(parents=True)
    document_dir.mkdir(parents=True)
    (runner_dir / "run_s34_one_closure.py").write_text("one", encoding="utf-8")
    (runner_dir / "run_s34_two_closure.py").write_text("two", encoding="utf-8")
    (document_dir / "0340_one_closure.md").write_text("one", encoding="utf-8")
    (document_dir / "0340_two_closure.md").write_text("two", encoding="utf-8")
    monkeypatch.setattr(
        "nex_ag.mvp_acceptance.ag_mvp_evidence_specs",
        lambda: (AgMvpEvidenceSpec("S34", "test", "0340"),) * 33,
    )

    inventory = build_ag_mvp_evidence_inventory(tmp_path)

    assert inventory["status"] == "FAIL"
    assert inventory["checks"]["requirements_unique"] is False
    assert inventory["entries"][0]["closure_runner_count"] == 2
    assert inventory["entries"][0]["closure_document_count"] == 2


def test_inventory_reports_identity_token_failure(tmp_path, monkeypatch) -> None:
    runner_dir = tmp_path / "scripts/smoke"
    document_dir = tmp_path / "docs/slices"
    runner_dir.mkdir(parents=True)
    document_dir.mkdir(parents=True)
    (runner_dir / "run_s34_test_closure.py").write_text(
        "SCHEMA_VERSION = 'wrong'\n", encoding="utf-8"
    )
    (document_dir / "0340_test_closure.md").write_text(
        "# Slice 0340\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "nex_ag.mvp_acceptance.ag_mvp_evidence_specs",
        lambda: tuple(
            AgMvpEvidenceSpec(f"S{number}", "test", f"{number * 10:04d}")
            for number in range(34, 67)
        ),
    )

    inventory = build_ag_mvp_evidence_inventory(tmp_path)

    assert inventory["status"] == "FAIL"
    first = inventory["entries"][0]
    assert first["closure_runner"].endswith("run_s34_test_closure.py")
    assert first["closure_document"].endswith("0340_test_closure.md")
    assert first["identity_tokens_present"] is False
    assert first["issues"] == [
        {
            "category": "closure_identity_token_missing",
            "requirement": "S34",
        }
    ]
