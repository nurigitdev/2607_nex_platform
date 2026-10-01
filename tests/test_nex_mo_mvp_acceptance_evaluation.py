from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nex_mo.mvp_acceptance import build_mo_mvp_acceptance_policy
from nex_mo.mvp_acceptance_evaluation import (
    _gate_specific_reasons,
    _normalize_now,
    _number_at_least,
    _parse_timestamp,
    _positive_number,
    evaluate_mo_mvp_acceptance,
)
from run_mo_mvp_acceptance_evaluator import build_passing_evidence


NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_passing_evidence_is_accepted_and_deterministic() -> None:
    first = evaluate_mo_mvp_acceptance(build_passing_evidence(), now=NOW)
    second = evaluate_mo_mvp_acceptance(build_passing_evidence(), now=NOW)

    assert first == second
    assert first["status"] == "ACCEPTED"
    assert first["transition_status"] == "READY_FOR_OA"
    assert first["summary"] == {
        "gate_count": 9,
        "passed_gate_count": 9,
        "blocked_gate_count": 0,
    }
    assert len(first["acceptance_id"]) == 64
    assert first["raw_evidence_included"] is False
    assert "passed_tests" not in str(first)


@pytest.mark.parametrize(
    ("gate_id", "updates", "reason"),
    [
        ("mo_requirement_closures", {"requirement_count": 8}, "requirement_count_incomplete"),
        ("mo_requirement_closures", {"issue_count": 1}, "closure_inventory_has_issues"),
        ("contract_validation", {"schema_count": 0}, "schema_count_empty"),
        ("contract_validation", {"example_count": False}, "example_count_empty"),
        ("unit_regression", {"passed_tests": 8999}, "regression_pass_count_below_minimum"),
        ("unit_regression", {"failed_tests": 1}, "regression_failures_present"),
        ("statement_coverage", {"percent": 97.99}, "coverage_below_threshold"),
        ("branch_coverage", {"percent": 95.99}, "coverage_below_threshold"),
        ("postgres_smoke", {"backend": "sqlite"}, "postgres_backend_not_proven"),
        ("postgres_smoke", {"database": "nex_mo_dev"}, "test_database_not_proven"),
        ("postgres_smoke", {"zero_residue": False}, "postgres_cleanup_not_proven"),
        ("live_provider_acceptance", {"provider_models": {}}, "live_provider_models_not_proven"),
        ("live_provider_acceptance", {"ready_capabilities": 2}, "live_capabilities_not_ready"),
        ("live_provider_acceptance", {"failed_calls": 1}, "live_provider_failures_present"),
        ("live_provider_acceptance", {"explicit_bfloat16": False}, "live_bfloat16_not_proven"),
        ("privacy_failure_runbooks", {"runbook_count": 3}, "runbook_inventory_incomplete"),
        ("oa_transition_handoff", {"target_service": "nex-ag"}, "transition_target_invalid"),
        ("oa_transition_handoff", {"manifest_status": "DRAFT"}, "transition_manifest_not_sealed"),
    ],
)
def test_gate_specific_failures_block_acceptance(
    gate_id: str, updates: dict, reason: str
) -> None:
    evidence = build_passing_evidence()
    evidence[gate_id].update(updates)

    report = evaluate_mo_mvp_acceptance(evidence, now=NOW)

    blocker = next(item for item in report["blockers"] if item["gate_id"] == gate_id)
    assert report["status"] == "BLOCKED"
    assert reason in blocker["reason_codes"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda evidence: evidence.pop("postgres_smoke"), "evidence_missing"),
        (lambda evidence: evidence["postgres_smoke"].update(status="SKIPPED"), "status_not_pass"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="bad"), "observed_at_invalid"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="2026-10-02T09:00:00Z"), "evidence_from_future"),
        (lambda evidence: evidence["postgres_smoke"].update(observed_at="2026-09-29T09:00:00Z"), "evidence_stale"),
    ],
)
def test_missing_skipped_and_unfresh_evidence_blocks(mutation, reason: str) -> None:
    evidence = build_passing_evidence()
    mutation(evidence)

    report = evaluate_mo_mvp_acceptance(evidence, now=NOW)

    blocker = next(
        item for item in report["blockers"] if item["gate_id"] == "postgres_smoke"
    )
    assert reason in blocker["reason_codes"]


def test_invalid_policy_and_naive_clock_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_mo_mvp_acceptance(
            build_passing_evidence(), now=datetime(2026, 10, 1)
        )
    with pytest.raises(ValueError, match="policy is invalid"):
        evaluate_mo_mvp_acceptance(
            build_passing_evidence(), policy={"gates": [], "evidence": {}}, now=NOW
        )
    with pytest.raises(ValueError, match="policy is invalid"):
        evaluate_mo_mvp_acceptance(
            build_passing_evidence(),
            policy={"gates": "bad", "evidence": {"max_age_hours": 1}},
            now=NOW,
        )


def test_helpers_cover_unknown_gate_and_value_types() -> None:
    assert _gate_specific_reasons("unknown", {}, {}) == ["gate_evaluator_missing"]
    assert _normalize_now(None).tzinfo is UTC
    assert _normalize_now(NOW) == NOW
    assert _parse_timestamp(None) is None
    assert _parse_timestamp("bad") is None
    assert _parse_timestamp("2026-10-01T08:30:00") is None
    assert _parse_timestamp("2026-10-01T08:30:00Z") == datetime(
        2026, 10, 1, 8, 30, tzinfo=UTC
    )
    assert _positive_number(1) is True
    assert _positive_number(True) is False
    assert _number_at_least(2, 1) is True
    assert _number_at_least(True, 1) is False
    assert _number_at_least(2, "1") is False


def test_custom_policy_threshold_is_honored() -> None:
    policy = build_mo_mvp_acceptance_policy(
        {"NEX_MO_MVP_REQUIRED_REGRESSION_TESTS": "9700"}
    )
    report = evaluate_mo_mvp_acceptance(
        build_passing_evidence(), policy=policy, now=NOW
    )

    assert report["status"] == "BLOCKED"
    assert report["summary"]["blocked_gate_count"] == 1
